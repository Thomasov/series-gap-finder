# Contributing

## Development setup

There are no external dependencies — the plugin only uses the Python standard
library and the Qt/calibre APIs that calibre ships with.

1. Clone the repo.
2. Make your changes.
3. Build the plugin ZIP:

   ```powershell
   .\build.ps1
   ```

4. Install it into calibre and watch the console for errors:

   ```
   calibre-customize -a SeriesGapFinder-<version>.zip
   calibre-debug -g
   ```

Repeat steps 3–4 after each change; calibre must be restarted to pick up a
reinstalled plugin.

You'll need a free [Hardcover.app](https://hardcover.app) account and API
token (from <https://hardcover.app/account/api>) to test against the real API.

## Code layout

| File | Purpose |
| --- | --- |
| `__init__.py` | Plugin metadata (name, version) and entry point |
| `ui.py` | Toolbar button, menu, and job kickoff |
| `worker.py` | Background scan: grouping, matching, gap analysis |
| `hardcover.py` | Hardcover GraphQL client, throttling, retries |
| `results.py` | Results dialog, ignore list, copy/CSV export |
| `config.py` | Preferences dialog and stored settings |

## Guidelines

- Keep the plugin dependency-free — only the standard library and what
  calibre bundles.
- Be gentle with the Hardcover API: respect the existing throttle and prefer
  batched queries over per-item requests.
- Match the style of the surrounding code.
- Bump the version in `__init__.py` only in release commits; regular PRs
  should leave it alone.

## Pull requests

1. Fork and create a branch from `main`.
2. Make your change, rebuild the ZIP, and test it in calibre against a real
   library.
3. Describe in the PR what you changed and how you tested it.
