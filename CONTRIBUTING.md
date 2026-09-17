# Contributing

## Setup

1. Create and activate a Python 3.10 or newer virtual environment.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and add a restricted YouTube Data API key only when live indexing is required.
4. Install Node.js 20 or newer and run `npm ci` when working on the hosted Worker site.

Never commit API keys, local databases, logs, or packaged executables.

## Repository layout

- Python application entry points are kept at the repository root because the portable build and command-line tools import them directly.
- `site/`, `worker/`, `db/`, `drizzle/`, and `dist/` contain the hosted site source, Worker, schema, migrations, and deployable Worker output.
- `packaging/` contains portable-build specs and launcher documentation. Generated executables belong under ignored `build/portable/`.
- `tests/` contains Python and Worker regression coverage; test fixtures must not contain API keys or personal databases.

## Checks

Run these checks before opening a pull request:

```powershell
python -m pip check
python -m compileall -q .
python -c "import app, config, database, indexer_app, main, search, song_identity, timeline_parser, youtube_client"
python -m unittest discover -s tests -p "test_*.py" -v
npm ci
npm run db:generate
npm run build
npm run validate
npm test
git diff --check
```

Keep parser and database changes backward compatible with existing SQLite data when possible, and document migrations or re-indexing requirements.

## Pull requests

Use a focused branch and a descriptive commit or pull request title. Describe the user-visible behavior, migration impact, and verification commands. Do not include `.env`, SQLite files, logs, screenshots containing private data, or generated executables in a pull request.
