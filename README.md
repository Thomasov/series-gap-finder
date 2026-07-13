# Series Gap Finder — a calibre plugin

Finds the books missing from the series you own: "you have books 1–3 and 5
of this series; book 4 exists and book 7 isn't out yet." Series data comes
from the free [Hardcover.app](https://hardcover.app) GraphQL API.

## Install

1. Get the plugin ZIP: `SeriesGapFinder-1.0.0.zip` (or rebuild it — see below).
2. In calibre: **Preferences → Plugins → Load plugin from file**, pick the ZIP,
   accept the warning, restart calibre.
   - Or from a terminal: `calibre-customize -a SeriesGapFinder-1.0.0.zip`
3. Create a free account at [hardcover.app](https://hardcover.app), copy your
   API token from <https://hardcover.app/account/api>, and paste it into
   **Preferences → Plugins → Series Gap Finder → Customize plugin** (the plugin
   will also prompt you on first run).
4. If the button doesn't appear on the toolbar automatically, add it via
   **Preferences → Toolbars & menus → The main toolbar**.

## Use

Click the **Series Gap Finder** toolbar button to scan the whole library, or
select some books first to scan just those (the dropdown menu has both options
explicitly). The scan runs as a background job (see the Jobs spinner, bottom
right). Exact name matches are resolved in batches of 25 per request, so a
~100-series library typically finishes in well under a minute; the remaining
time is the ~1 request/second rate-limit throttle on fuzzy searches for names
Hardcover spells differently. Results show, per series: which numbered entries you're
missing, their release years, unreleased upcoming books, and series calibre
couldn't match on Hardcover. You can copy the list or export CSV, and
double-click any row to open it on Hardcover.

## Ignoring books

Sometimes Hardcover lists a book in a series that doesn't really belong to it
(a sampler, a spin-off, a mis-filed entry). Right-click the book in the
results and choose **Ignore this book** — it disappears immediately and is
never reported as missing again. Ignored books are listed in the plugin
configuration (**Customize plugin**), where you can select entries and
**Remove selected** to start reporting them again.

## How matching works

- Books are grouped by calibre's `series` column; your `series_index` values
  are compared against Hardcover's canonical positions for that series.
- A book also counts as owned if its title matches, even when your
  `series_index` disagrees with Hardcover's numbering. Ownership is checked
  against the *whole library* (title + author), so a book filed under a
  different calibre series still counts.
- When several calibre series match the same Hardcover series (e.g. Discworld
  shelved as per-arc subseries), they are combined into one result row, and
  series numbering is ignored for it — ownership is decided purely by title,
  since a custom grouping's numbering cannot align with Hardcover's.
- Series names are matched exactly first, then by fuzzy full-text search with
  an author-name bonus ("Dresden Files" ↔ "The Dresden Files"). Hardcover's
  API does not permit case-insensitive (`_ilike`) queries.
- Compilations, partial editions, and merged duplicate records are excluded,
  following Hardcover's own documented query recipe.

## Options

- **Ignore unnumbered entries** (default on): skips novellas/companion volumes
  that have no position in the series.
- **Only whole-numbered books** (default on): skips entries at fractional
  positions like #4.5 — Hardcover numbers novellas, short stories, and split
  editions that way, which otherwise buries the real gaps.
- **Skip unreleased books** (default off): hides books with a future release
  date instead of listing them as "not yet released". Books with no release
  date at all (announced/planned books, shown as "Planned" on Hardcover) are
  also treated as unreleased.

## Rebuild the ZIP from source

```powershell
Compress-Archive -Path *.py, plugin-import-name-series_gap_finder.txt `
  -DestinationPath SeriesGapFinder-1.0.0.zip -Force
```

## Notes

- Hardcover tokens currently expire after a year; the plugin tells you when
  the token is rejected.
- Hardcover's rate limit is 60 requests/minute; the client throttles itself
  and retries once on HTTP 429.
