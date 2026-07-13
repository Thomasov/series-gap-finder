__license__ = 'GPL v3'

'''
Background job that checks each owned series against Hardcover.
Runs in a calibre ThreadedJob, so it must not touch Qt or the GUI.

The scan is phased to minimize request count, because Hardcover's
rate limit (60 requests/minute) dominates runtime, not API latency:

  1. resolve exact name matches in batches of BATCH_NAMES per request
  2. full-text search, one request per name that had no exact match
  3. fetch all series found by search, batched by id
  4. gap analysis (local, no requests)
'''

from datetime import date

from calibre_plugins.series_gap_finder.hardcover import (HardcoverClient,
                                                         HardcoverError,
                                                         author_key,
                                                         normalize,
                                                         pick_best)

BATCH_NAMES = 25
BATCH_IDS = 25


class TitleIndex:
    '''Title -> author-keys lookup over the whole library, so a book
    counts as owned no matter which calibre series it is filed under.
    Prefix matching copes with retailer title junk like
    "The Blade Itself: The First Law Trilogy, Book 1".'''

    def __init__(self, library_titles):
        self.exact = library_titles or {}
        self.by_first = {}
        for title, keys in self.exact.items():
            self.by_first.setdefault(title.split(' ', 1)[0],
                                     []).append((title, keys))

    def owned(self, norm_title, allowed_author_keys):
        if not norm_title:
            return False
        keys = self.exact.get(norm_title)
        if keys is not None and (not allowed_author_keys or
                                 allowed_author_keys & keys):
            return True
        prefix = norm_title + ' '
        for title, keys in self.by_first.get(norm_title.split(' ', 1)[0], ()):
            if title.startswith(prefix) and allowed_author_keys & keys:
                return True
        return False


def scan_series(series_map, library_titles, token, opts, notifications=None,
                abort=None, log=None):
    '''
    series_map: {series_name: {'positions': set of float series_index,
                               'titles': set of normalized owned titles,
                               'authors': set of author names}}
    library_titles: {normalized title: set of author keys} for the whole
    library, used so books filed under a different calibre series still
    count as owned.
    Returns {'fatal': None or message, 'results': [per-series dicts]}.
    Never raises: a raised exception would make calibre log the job's
    arguments, which include the API token.
    '''
    results = []
    try:
        client = HardcoverClient(token)
    except HardcoverError as e:
        return {'fatal': str(e), 'results': results}
    today = date.today().isoformat()
    names = sorted(series_map, key=lambda s: s.lower())

    def notify(frac, msg):
        if notifications is not None:
            notifications.put((frac, msg))

    def aborted():
        return abort is not None and abort.is_set()

    # name -> ('cand', series) | ('not_found',) | ('error', msg).
    # Names that stay unresolved (abort/failure mid-flight) are omitted
    # from the results rather than misreported as not found.
    state = {}
    fatal = None

    # Phase 1: batched exact-name lookup
    by_name = {}
    phase1_done = set()
    for i in range(0, len(names), BATCH_NAMES):
        if aborted():
            break
        chunk = names[i:i + BATCH_NAMES]
        notify(0.2 * i / len(names),
               'Looking up series names on Hardcover (%d of %d)' %
               (min(i + len(chunk), len(names)), len(names)))
        try:
            for s in client.series_by_names(chunk):
                by_name.setdefault(s.get('name'), []).append(s)
        except HardcoverError as e:
            if e.fatal:
                return {'fatal': str(e), 'results': results}
            for name in chunk:
                state[name] = ('error', str(e))
        phase1_done.update(chunk)
    for name in phase1_done:
        if name in state:
            continue
        cand = pick_best(name, series_map[name]['authors'],
                         by_name.get(name) or [])
        if cand is not None:
            state[name] = ('cand', cand)

    # Phase 2: full-text search for names with no exact match
    to_search = [n for n in names if n in phase1_done and n not in state]
    ids_for = {}
    searched = []
    for j, name in enumerate(to_search):
        if aborted() or fatal:
            break
        notify(0.2 + 0.6 * j / (len(to_search) or 1),
               'Searching Hardcover: %s' % name)
        try:
            ids_for[name] = client.search_series_ids(name)
        except HardcoverError as e:
            if e.fatal:
                fatal = str(e)
                break
            state[name] = ('error', str(e))
            continue
        searched.append(name)

    # Phase 3: batched fetch of everything the searches found
    series_by_id = {}
    fetched_all_ids = not fatal
    uniq_ids = []
    seen = set()
    for name in searched:
        for sid in ids_for.get(name, ()):
            if sid not in seen:
                seen.add(sid)
                uniq_ids.append(sid)
    for i in range(0, len(uniq_ids), BATCH_IDS):
        if aborted() or fatal:
            fetched_all_ids = False
            break
        notify(0.8 + 0.15 * i / (len(uniq_ids) or 1),
               'Fetching search results (%d of %d)' %
               (min(i + BATCH_IDS, len(uniq_ids)), len(uniq_ids)))
        try:
            for s in client.series_by_ids(uniq_ids[i:i + BATCH_IDS]):
                series_by_id[s.get('id')] = s
        except HardcoverError as e:
            if e.fatal:
                fatal = str(e)
            fetched_all_ids = False
            break
    for name in searched:
        if name in state:
            continue
        cands = [series_by_id[sid] for sid in ids_for.get(name, ())
                 if sid in series_by_id]
        cand = pick_best(name, series_map[name]['authors'], cands)
        if cand is not None:
            state[name] = ('cand', cand)
        elif not ids_for.get(name) or fetched_all_ids:
            state[name] = ('not_found',)

    # Phase 4: gap analysis, no network
    notify(0.95, 'Analyzing series')
    title_index = TitleIndex(library_titles)
    groups = {}
    for n in names:
        st = state.get(n)
        if st is not None and st[0] == 'cand':
            groups.setdefault(st[1].get('id'), []).append(n)
    reported = set()
    for name in names:
        st = state.get(name)
        if st is None or name in reported:
            continue
        if st[0] == 'error':
            res = {'name': name, 'status': 'error', 'error': st[1]}
        elif st[0] == 'not_found':
            res = {'name': name, 'status': 'not_found',
                   'owned_count': len(series_map[name]['positions'])}
        else:
            cand = st[1]
            group = groups.get(cand.get('id')) or [name]
            reported.update(group)
            if len(group) == 1:
                owned = series_map[name]
                display = name
            else:
                # Several calibre series matched the same Hardcover
                # series (e.g. Discworld subseries). Merge them, and
                # ignore series_index numbering: the user's custom
                # grouping cannot align with Hardcover's positions,
                # so ownership is decided by title alone here.
                display = ' / '.join(group)
                owned = {
                    'positions': set(),
                    'titles': set().union(
                        *(series_map[n]['titles'] for n in group)),
                    'authors': set().union(
                        *(series_map[n]['authors'] for n in group)),
                }
            res = check_series(display, cand, owned, opts, today,
                               title_index)
            if len(group) > 1:
                res['owned_count'] = sum(
                    len(series_map[n]['positions']) for n in group)
        if log is not None:
            if res['status'] == 'ok':
                log('%s: %d missing of %d numbered' %
                    (name, len(res['missing']), res['numbered_total']))
            else:
                log('%s: %s' % (name, res['status']))
        results.append(res)
    return {'fatal': fatal, 'results': results}


def check_series(name, cand, owned, opts, today, title_index=None):
    '''Compare one owned series against its matched Hardcover record.'''
    owned_pos = owned['positions']
    owned_titles = owned['titles']
    allowed_authors = {author_key(a) for a in owned['authors'] if a}
    hc_author = (cand.get('author') or {}).get('name')
    if hc_author:
        allowed_authors.add(author_key(hc_author))
    missing = []
    numbered_total = 0

    for bs in cand.get('book_series') or ():
        book = bs.get('book') or {}
        title = book.get('title') or ''
        slug = book.get('slug')
        if slug and slug in (opts.get('ignored_slugs') or ()):
            continue
        pos = bs.get('position')
        if pos is not None:
            try:
                pos = float(pos)
            except (TypeError, ValueError):
                pos = None
        if pos is None:
            if opts.get('ignore_unnumbered', True):
                continue
        else:
            if opts.get('integers_only', True) and \
                    abs(pos - round(pos)) > 1e-6:
                continue
            numbered_total += 1
            if any(abs(pos - o) < 0.01 for o in owned_pos):
                continue
        norm_title = normalize(title)
        if norm_title and norm_title in owned_titles:
            # Owned, but with a wrong/missing series_index in calibre
            continue
        if title_index is not None and \
                title_index.owned(norm_title, allowed_authors):
            # Owned, filed under a different calibre series
            continue

        year = book.get('release_year')
        rdate = book.get('release_date') or ''
        # No release date and no year at all means an announced/planned
        # book (Hardcover shows these as "Planned") — treat as unreleased.
        unreleased = bool((rdate and rdate > today) or
                          (not rdate and year and year > int(today[:4])) or
                          (not rdate and not year))
        if unreleased and opts.get('skip_future'):
            continue
        missing.append({
            'position': pos,
            'title': title or '(untitled)',
            'slug': slug,
            'year': year or (rdate[:4] if rdate else None),
            'unreleased': unreleased,
            'url': ('https://hardcover.app/books/%s' % slug) if slug else None,
        })

    return {
        'name': name,
        'status': 'ok',
        'hc_name': cand.get('name'),
        'hc_author': (cand.get('author') or {}).get('name'),
        'hc_url': ('https://hardcover.app/series/%s' % cand['slug'])
                  if cand.get('slug') else None,
        'numbered_total': numbered_total,
        'owned_count': len(owned_pos),
        'missing': missing,
    }
