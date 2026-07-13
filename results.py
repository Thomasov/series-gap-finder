__license__ = 'GPL v3'

import csv

from qt.core import (QApplication, QDialog, QDialogButtonBox, QFileDialog,
                     QLabel, QMenu, QPushButton, Qt, QTreeWidget,
                     QTreeWidgetItem, QUrl, QVBoxLayout)

from calibre.gui2 import open_url

from calibre_plugins.series_gap_finder.config import prefs

URL_ROLE = Qt.ItemDataRole.UserRole
DATA_ROLE = Qt.ItemDataRole.UserRole + 1  # (series_result, missing_dict)


def fmt_pos(pos):
    if pos is None:
        return '—'
    return '%g' % pos


class ResultsDialog(QDialog):

    def __init__(self, gui, results):
        QDialog.__init__(self, gui)
        self.results = results or []
        self.gaps = [r for r in self.results
                     if r['status'] == 'ok' and r['missing']]
        complete = [r for r in self.results
                    if r['status'] == 'ok' and not r['missing']]
        notfound = [r for r in self.results if r['status'] == 'not_found']
        errors = [r for r in self.results if r['status'] == 'error']
        n_missing = sum(len(r['missing']) for r in self.gaps)

        self.setWindowTitle('Series Gap Finder — results')
        self.resize(900, 620)
        layout = QVBoxLayout(self)

        bits = ['Checked %d series:' % len(self.results),
                '%d with gaps (%d missing books),' % (len(self.gaps), n_missing),
                '%d complete,' % len(complete),
                '%d not found on Hardcover.' % len(notfound)]
        if errors:
            bits.append('%d failed with errors.' % len(errors))
        summary = QLabel(' '.join(bits))
        summary.setWordWrap(True)
        layout.addWidget(summary)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(['Series / Title', 'No.', 'Year', 'Notes'])
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.tree)

        for r in self.gaps:
            top = QTreeWidgetItem([r['name'], '', '', self._series_note(r)])
            top.setData(0, URL_ROLE, r.get('hc_url'))
            self.tree.addTopLevelItem(top)
            for m in r['missing']:
                notes = ''
                if m['unreleased']:
                    notes = ('not yet released' if m['year']
                             else 'planned — no release date')
                child = QTreeWidgetItem([m['title'], fmt_pos(m['position']),
                                         str(m['year'] or ''), notes])
                child.setData(0, URL_ROLE, m.get('url'))
                child.setData(0, DATA_ROLE, (r, m))
                top.addChild(child)
            top.setExpanded(True)

        for r in notfound:
            top = QTreeWidgetItem(
                ['? ' + r['name'], '', '',
                 'not found on Hardcover — check the series name spelling'])
            self.tree.addTopLevelItem(top)
        for r in errors:
            top = QTreeWidgetItem(['! ' + r['name'], '', '', r.get('error', '')])
            self.tree.addTopLevelItem(top)
        for r in complete:
            top = QTreeWidgetItem(
                ['✓ ' + r['name'], '', '',
                 'complete (%d numbered books)' % r['numbered_total']])
            top.setData(0, URL_ROLE, r.get('hc_url'))
            self.tree.addTopLevelItem(top)

        for col, width in enumerate((420, 60, 70)):
            self.tree.setColumnWidth(col, width)

        hint = QLabel('Double-click a row to open it on Hardcover. '
                      'Right-click a missing book to ignore it.')
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_btn = QPushButton('Copy missing list')
        copy_btn.clicked.connect(self.copy_list)
        buttons.addButton(copy_btn, QDialogButtonBox.ButtonRole.ActionRole)
        csv_btn = QPushButton('Save CSV…')
        csv_btn.clicked.connect(self.save_csv)
        buttons.addButton(csv_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _series_note(self, r):
        matched = r.get('hc_name') or ''
        if r.get('hc_author'):
            matched += ' by ' + r['hc_author']
        return 'missing %d of %d numbered — matched "%s"' % (
            len(r['missing']), r['numbered_total'], matched)

    def open_item(self, item, column):
        url = item.data(0, URL_ROLE)
        if url:
            open_url(QUrl(url))

    def show_context_menu(self, point):
        item = self.tree.itemAt(point)
        if item is None:
            return
        data = item.data(0, DATA_ROLE)
        if data is None:
            return
        _r, m = data
        menu = QMenu(self)
        act = menu.addAction('Ignore this book (never report again)')
        if m.get('slug'):
            act.triggered.connect(lambda: self.ignore_book(item))
        else:
            act.setText('Ignore this book (unavailable: no Hardcover id)')
            act.setEnabled(False)
        if m.get('url'):
            menu.addAction('Open on Hardcover',
                           lambda: self.open_item(item, 0))
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def ignore_book(self, item):
        r, m = item.data(0, DATA_ROLE)
        slug = m.get('slug')
        if not slug:
            return
        ignored = dict(prefs['ignored_books'])
        ignored[slug] = {'title': m['title'], 'series': r['name']}
        prefs['ignored_books'] = ignored

        r['missing'].remove(m)
        if m['position'] is not None:
            r['numbered_total'] = max(0, r['numbered_total'] - 1)
        top = item.parent()
        top.removeChild(item)
        if r['missing']:
            top.setText(3, self._series_note(r))
        else:
            self.gaps.remove(r)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(top))

    def missing_rows(self):
        for r in self.gaps:
            for m in r['missing']:
                yield r, m

    def copy_list(self):
        lines = []
        for r in self.gaps:
            matched = r.get('hc_name') or ''
            if r.get('hc_author'):
                matched += ' — ' + r['hc_author']
            lines.append('%s (%s)' % (r['name'], matched))
            for m in r['missing']:
                extra = ''
                if m['unreleased']:
                    extra = (' [not yet released]' if m['year']
                             else ' [planned — no release date]')
                year = ' (%s)' % m['year'] if m['year'] else ''
                lines.append('  #%s  %s%s%s' % (fmt_pos(m['position']),
                                                m['title'], year, extra))
            lines.append('')
        QApplication.clipboard().setText('\n'.join(lines).strip() + '\n')

    def save_csv(self):
        path, _filter = QFileDialog.getSaveFileName(
            self, 'Save missing books', 'missing-books.csv',
            'CSV files (*.csv)')
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['series', 'hardcover_series', 'position', 'title',
                        'year', 'unreleased', 'url'])
            for r, m in self.missing_rows():
                w.writerow([r['name'], r.get('hc_name') or '',
                            fmt_pos(m['position']), m['title'],
                            m['year'] or '', 'yes' if m['unreleased'] else '',
                            m.get('url') or ''])
