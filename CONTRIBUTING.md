# Contributing

## Setup

1. Create and activate a Python 3.10 or newer virtual environment.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and add a restricted YouTube Data API key only when live indexing is required.
4. Install Node.js 20 or newer and run `npm ci` when working on the hosted Worker site.

Never commit API keys, local databases, logs, or packaged executables.

## Repository layout

- Python application entry points are kept at the repository root because the portable build and command-line tools import them directly.
- Shared indexing belongs in `indexing.py`; CLI and Flask entry points call that service. New code must not import business logic from `main.py`.
- `worker/index.js` handles routing, `worker/search.js` handles reads, `worker/sync.js` handles authenticated writes, and `worker/http.js` holds HTTP helpers.
- `site/`, `worker/`, `db/`, `drizzle/`, and `dist/` contain the hosted site source, Worker, schema, migrations, and deployable Worker output.
- `packaging/` contains portable-build specs and launcher documentation. Generated executables belong under ignored `build/portable/`.
- `tests/` contains Python and Worker regression coverage; test fixtures must not contain API keys or personal databases.
- Setup interactions live in `static/setup.js`; templates supply route configuration through data attributes. Frontend request/state regressions run with the Node tests, without a browser or a live service.
- Module boundaries and transaction rules are documented in [docs/architecture.md](docs/architecture.md); supported behavior is in [docs/features.md](docs/features.md).

## Checks

Run these checks before opening a pull request:

```powershell
npm ci
npm run db:generate
python scripts/check.py
```

Use `--scope python` or `--scope site` for focused checks. `npm run check` also builds, validates, and tests the site. Worker integration tests need Python with `requirements.txt` installed; the unified checker selects its own Python interpreter, while direct npm commands honor the `PYTHON` environment variable.

The checker compiles maintained sources, imports the applications, runs regression tests, builds and verifies the Worker, and checks whitespace. Tests use temporary data and never index a real channel or synchronize a live site. CI runs the same commands and verifies migrations and generated `dist/` are current. `dist/` remains versioned for deployment; rebuild and include it when source changes, without editing it directly.

For bug fixes, first demonstrate a failing behavioral regression. Indexing tests should cross a batch or restart boundary. Sync tests must cover rollback as well as success. Worker database tests use the production migrations through `tests/helpers/worker_db.mjs`. Search changes must cover both runtimes using shared fixtures; artist integration tests feed real Python exports into Worker APIs.

Keep parser and database changes backward compatible with existing SQLite data when possible, and document migrations or re-indexing requirements.

## Pull requests

Use a focused branch and a descriptive commit or pull request title. Describe the user-visible behavior, migration impact, and verification commands. Do not include `.env`, SQLite files, logs, screenshots containing private data, or generated executables in a pull request.
