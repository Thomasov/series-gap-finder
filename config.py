__license__ = 'GPL v3'

from qt.core import (QAbstractItemView, QCheckBox, QHBoxLayout, QLabel,
                     QLineEdit, QListWidget, QListWidgetItem, QPushButton, Qt,
                     QVBoxLayout, QWidget)

from calibre.utils.config import JSONConfig

prefs = JSONConfig('plugins/series_gap_finder')
prefs.defaults['api_token'] = ''
prefs.defaults['ignore_unnumbered'] = True
prefs.defaults['integers_only'] = True
prefs.defaults['skip_future'] = False
prefs.defaults['ignored_books'] = {}


def shared_token():
    '''Token stored by the optional Hardcover Token plugin in the shared
    plugins/hardcover_shared config (read directly — no dependency on
    that plugin being installed).'''
    try:
        return (JSONConfig('plugins/hardcover_shared')
                .get('api_token', '') or '').strip()
    except Exception:
        return ''


def api_token():
    '''This plugin's own token (a deliberate local override) first,
    then the shared one.'''
    return prefs['api_token'] or shared_token()


class ConfigWidget(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        layout = QVBoxLayout(self)

        info = QLabel(
            'Series Gap Finder looks up series data on Hardcover, which '
            'requires a free API token.<br><br>'
            '1. Create a free account at '
            '<a href="https://hardcover.app">hardcover.app</a><br>'
            '2. Copy your API token from '
            '<a href="https://hardcover.app/account/api">'
            'hardcover.app/account/api</a><br>'
            '3. Paste it below (with or without the leading "Bearer")<br><br>'
            'Note: Hardcover tokens currently expire after a year, so if the '
            'plugin stops working, paste a fresh token here.')
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel('API token:'))
        self.token_edit = QLineEdit(self)
        self.token_edit.setText(prefs['api_token'])
        row.addWidget(self.token_edit)
        layout.addLayout(row)

        if shared_token():
            note = QLabel(
                '<i>A shared token from the Hardcover Token plugin is '
                'configured and is used while the field above is empty; '
                'a token entered above overrides it.</i>')
            note.setWordWrap(True)
            layout.addWidget(note)

        self.ignore_unnumbered = QCheckBox(
            'Ignore entries with no series number (novellas, companion books)')
        self.ignore_unnumbered.setChecked(prefs['ignore_unnumbered'])
        layout.addWidget(self.ignore_unnumbered)

        self.integers_only = QCheckBox(
            'Only report whole-numbered books (skip novellas and stories '
            'at positions like 4.5)')
        self.integers_only.setChecked(prefs['integers_only'])
        layout.addWidget(self.integers_only)

        self.skip_future = QCheckBox('Skip books that have not been released yet')
        self.skip_future.setChecked(prefs['skip_future'])
        layout.addWidget(self.skip_future)

        self.ignored = dict(prefs['ignored_books'])
        layout.addWidget(QLabel('Ignored books (never reported as missing):'))
        self.ignored_list = QListWidget(self)
        self.ignored_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        for slug, info in sorted(
                self.ignored.items(),
                key=lambda kv: ((kv[1].get('series') or '').lower(),
                                (kv[1].get('title') or '').lower())):
            item = QListWidgetItem('%s — %s' % (info.get('series') or '?',
                                                info.get('title') or slug))
            item.setData(Qt.ItemDataRole.UserRole, slug)
            self.ignored_list.addItem(item)
        layout.addWidget(self.ignored_list)

        row = QHBoxLayout()
        remove_btn = QPushButton('Remove selected')
        remove_btn.clicked.connect(self._remove_ignored)
        row.addWidget(remove_btn)
        row.addStretch()
        layout.addLayout(row)

        layout.addStretch()

    def _remove_ignored(self):
        for item in self.ignored_list.selectedItems():
            self.ignored.pop(item.data(Qt.ItemDataRole.UserRole), None)
            self.ignored_list.takeItem(self.ignored_list.row(item))

    def save_settings(self):
        prefs['api_token'] = self.token_edit.text().strip()
        prefs['ignore_unnumbered'] = self.ignore_unnumbered.isChecked()
        prefs['integers_only'] = self.integers_only.isChecked()
        prefs['skip_future'] = self.skip_future.isChecked()
        prefs['ignored_books'] = self.ignored
