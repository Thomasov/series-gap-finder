__license__ = 'GPL v3'

'''
Minimal Hardcover.app GraphQL client. No external dependencies —
uses urllib from the standard library so it runs inside calibre's
bundled Python as-is.

The series query follows Hardcover's own documented recipe for listing
the books in a series: exclude merged duplicates (canonical_id is null),
partial editions and compilations, and dedupe on position keeping the
most popular edition.
'''

import difflib
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = 'https://api.hardcover.app/v1/graphql'

# Hardcover allows 60 requests/minute; stay safely under it.
MIN_REQUEST_INTERVAL = 1.1


class HardcoverError(Exception):
    # fatal=True aborts the whole scan (bad/expired token) instead of
    # being recorded against a single series and continuing.
    fatal = False


_SERIES_SELECTION = '''
      id
      name
      slug
      books_count
      author { name }
      book_series(
        distinct_on: position,
        order_by: [{position: asc}, {book: {users_count: desc}}],
        where: {
          book: {canonical_id: {_is_null: true}, is_partial_book: {_eq: false}},
          compilation: {_eq: false}
        }
      ) {
        position
        book { slug title release_date release_year }
      }
'''

# NB: Hardcover's API rejects _ilike ("not permitted on this server",
# HTTP 403), so the direct lookup is exact-match only; case and spelling
# differences are handled by the search fallback. Many names are resolved
# per request: the API rate limit (60/min) dominates runtime, so fewer,
# bigger requests is the main speed lever.
SERIES_BY_NAMES = '''
query ($names: [String!]!) {
  series(
    where: {name: {_in: $names}, books_count: {_gt: 0}, canonical_id: {_is_null: true}},
    order_by: {books_count: desc}
  ) { %s }
}
''' % _SERIES_SELECTION

SEARCH_SERIES = '''
query ($q: String!) {
  search(query: $q, query_type: "Series", per_page: 5, page: 1) { ids }
}
'''

SERIES_BY_IDS = '''
query ($ids: [Int!]!) {
  series(
    where: {id: {_in: $ids}, books_count: {_gt: 0}},
    order_by: {books_count: desc}
  ) { %s }
}
''' % _SERIES_SELECTION


_ARTICLES = re.compile(r'^(the|a|an)\s+')
_NONWORD = re.compile(r'[^a-z0-9]+')


def normalize(text):
    text = (text or '').lower().strip()
    text = _ARTICLES.sub('', text)
    return _NONWORD.sub(' ', text).strip()


def author_key(name):
    '''Order-insensitive author identity: "Butcher, Jim" and
    "Jim Butcher" get the same key.'''
    return ' '.join(sorted(normalize(name).split()))


def pick_best(name, authors, candidates):
    '''
    Choose the Hardcover series that best matches a calibre series name,
    using fuzzy name similarity plus a bonus when the series author matches
    one of the authors of the books we own in that series.
    '''
    if not candidates:
        return None
    want = normalize(name)
    owned_authors = {normalize(a) for a in (authors or ()) if a}
    best, best_score = None, 0.0
    for cand in candidates:
        have = normalize(cand.get('name') or '')
        if not have:
            continue
        score = difflib.SequenceMatcher(None, want, have).ratio()
        author = normalize(((cand.get('author') or {}).get('name')) or '')
        if author and any(author == a or author in a or a in author
                          for a in owned_authors):
            score += 0.2
        # Tiny tiebreak in favour of better-populated series entries
        score += min(cand.get('books_count') or 0, 30) / 3000.0
        if score > best_score:
            best, best_score = cand, score
    return best if best_score >= 0.5 else None


class HardcoverClient:

    def __init__(self, token):
        token = (token or '').strip()
        if token.lower().startswith('bearer'):
            token = token[6:].strip()
        if not token:
            err = HardcoverError(
                'No Hardcover API token configured. Open the plugin '
                'configuration and paste your token from '
                'hardcover.app/account/api')
            err.fatal = True
            raise err
        self.token = token
        self._last_request = 0.0

    def _throttle(self):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _post(self, query, variables=None):
        data = None
        for attempt in (1, 2):
            self._throttle()
            payload = json.dumps({'query': query,
                                  'variables': variables or {}}).encode('utf-8')
            req = Request(API_URL, data=payload, headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + self.token,
                'User-Agent': 'calibre-series-gap-finder/1.0',
            })
            try:
                with urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                break
            except HTTPError as e:
                if e.code == 429 and attempt == 1:
                    time.sleep(20)
                    continue
                try:
                    detail = json.loads(e.read().decode('utf-8', 'replace'))
                    detail = detail.get('error') or detail.get('message') or ''
                except Exception:
                    detail = ''
                if e.code == 401 or 'jwt' in detail.lower() or \
                        'token' in detail.lower():
                    err = HardcoverError(
                        'Hardcover rejected the API token (HTTP %d%s). '
                        'Tokens expire after a year — paste a fresh one from '
                        'hardcover.app/account/api into the plugin '
                        'configuration.' % (e.code,
                                            ': %s' % detail if detail else ''))
                    err.fatal = True
                    raise err
                raise HardcoverError(
                    'Hardcover API returned HTTP %d%s' %
                    (e.code, ': %s' % detail if detail else ''))
            except URLError as e:
                raise HardcoverError(
                    'Could not reach Hardcover: %s' % getattr(e, 'reason', e))
            finally:
                self._last_request = time.monotonic()
        errors = (data or {}).get('errors')
        if errors:
            msg = '; '.join(e.get('message', 'unknown error') for e in errors)
            err = HardcoverError('Hardcover GraphQL error: ' + msg)
            if 'jwt' in msg.lower() or 'unauthor' in msg.lower():
                err.fatal = True
            raise err
        return (data or {}).get('data') or {}

    def series_by_names(self, names):
        '''All series whose name exactly matches one of `names`, with
        their book lists — one request for the whole batch.'''
        return self._post(SERIES_BY_NAMES,
                          {'names': list(names)}).get('series') or []

    def search_series_ids(self, name, limit=5):
        '''Full-text search for a series name; returns candidate ids
        for names calibre and Hardcover spell differently, e.g.
        "Dresden Files" vs "The Dresden Files".'''
        found = self._post(SEARCH_SERIES, {'q': name}).get('search') or {}
        ids = []
        for x in (found.get('ids') or [])[:limit]:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                pass
        return ids

    def series_by_ids(self, ids):
        '''Series records (with book lists) for a batch of ids — one
        request for the whole batch.'''
        return self._post(SERIES_BY_IDS, {'ids': list(ids)}).get('series') or []
