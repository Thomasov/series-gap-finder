__license__ = 'GPL v3'

from qt.core import QMenu, pyqtSignal

from calibre.gui2 import error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.threaded_jobs import ThreadedJob

from calibre_plugins.series_gap_finder.config import prefs
from calibre_plugins.series_gap_finder.hardcover import author_key, normalize
from calibre_plugins.series_gap_finder.worker import scan_series


class SeriesGapFinderAction(InterfaceAction):

    name = 'Series Gap Finder'
    action_spec = ('Series Gap Finder', 'search.png',
                   'Find missing books in the series you own '
                   '(series data from Hardcover.app)', None)

    # calibre invokes ThreadedJob callbacks in the worker thread; Qt GUI
    # objects may only be created in the GUI thread, so the callback
    # emits this signal to hop threads before showing any dialog.
    scan_finished = pyqtSignal(object)

    def genesis(self):
        self.scan_finished.connect(self._show_results)
        self.menu = QMenu(self.gui)
        self.menu.addAction('Check entire library', self.scan_library)
        self.menu.addAction('Check selected books', self.scan_selected)
        self.menu.addSeparator()
        self.menu.addAction('Configure…', self.show_config)
        self.qaction.setMenu(self.menu)
        self.qaction.triggered.connect(self.scan_smart)

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    # -- entry points ------------------------------------------------

    def scan_smart(self):
        # Toolbar click: scan the selection if the user selected several
        # books, otherwise the whole library.
        ids = self._selected_ids()
        if len(ids) > 1:
            self._start(ids, 'the selected books')
        else:
            self.scan_library()

    def scan_library(self):
        db = self.gui.current_db.new_api
        self._start(list(db.all_book_ids()), 'your library')

    def scan_selected(self):
        ids = self._selected_ids()
        if not ids:
            return error_dialog(self.gui, 'Series Gap Finder',
                                'No books selected.', show=True)
        self._start(ids, 'the selected books')

    # -- implementation ----------------------------------------------

    def _selected_ids(self):
        try:
            return list(self.gui.library_view.get_selected_ids())
        except Exception:
            return []

    def _ensure_token(self):
        if not prefs['api_token']:
            self.interface_action_base_plugin.do_user_config(self.gui)
        return prefs['api_token']

    def _gather(self, book_ids):
        db = self.gui.current_db.new_api
        series_map = {}
        for book_id in book_ids:
            series = db.field_for('series', book_id)
            if not series:
                continue
            entry = series_map.setdefault(
                series, {'positions': set(), 'titles': set(), 'authors': set()})
            idx = db.field_for('series_index', book_id)
            if idx is not None:
                entry['positions'].add(float(idx))
            title = normalize(db.field_for('title', book_id))
            if title:
                entry['titles'].add(title)
            for author in db.field_for('authors', book_id) or ():
                entry['authors'].add(author)
        return series_map

    def _library_titles(self):
        # Ownership is a property of the whole library, regardless of
        # which books were selected for the scan.
        db = self.gui.current_db.new_api
        titles = {}
        for book_id in db.all_book_ids():
            title = normalize(db.field_for('title', book_id))
            if not title:
                continue
            keys = {author_key(a)
                    for a in db.field_for('authors', book_id) or () if a}
            titles.setdefault(title, set()).update(keys)
        return titles

    def _start(self, book_ids, label):
        token = self._ensure_token()
        if not token:
            return error_dialog(
                self.gui, 'Series Gap Finder',
                'A Hardcover API token is required. Get one free at '
                'hardcover.app/account/api and enter it in the plugin '
                'configuration.', show=True)
        series_map = self._gather(book_ids)
        if not series_map:
            return info_dialog(
                self.gui, 'Series Gap Finder',
                'No books with series metadata found in %s.' % label,
                show=True)
        opts = {'ignore_unnumbered': prefs['ignore_unnumbered'],
                'integers_only': prefs['integers_only'],
                'skip_future': prefs['skip_future'],
                'ignored_slugs': frozenset(prefs['ignored_books'])}
        job = ThreadedJob(
            'series_gap_finder',
            'Series Gap Finder: checking %d series' % len(series_map),
            scan_series,
            (series_map, self._library_titles(), token, opts), {},
            self._scan_done)
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(
            'Series Gap Finder: checking %d series against Hardcover '
            '(about %d seconds)…' % (len(series_map), int(len(series_map) * 1.3)),
            5000)

    def _scan_done(self, job):
        # Worker thread — no GUI work here, just cross to the GUI thread.
        self.scan_finished.emit(job)

    def _show_results(self, job):
        if job.failed:
            return self.gui.job_exception(
                job, dialog_title='Series Gap Finder failed')
        result = job.result or {}
        if result.get('fatal'):
            return error_dialog(self.gui, 'Series Gap Finder',
                                result['fatal'], show=True)
        from calibre_plugins.series_gap_finder.results import ResultsDialog
        ResultsDialog(self.gui, result.get('results') or []).exec()
