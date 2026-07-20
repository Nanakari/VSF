# Contributing

## Setup

1. Create and activate a Python 3.10 or newer virtual environment.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and add a restricted YouTube Data API key only when live indexing is required.

Never commit API keys, local databases, logs, or packaged executables.

## Checks

Run these checks before opening a pull request:

```powershell
python -m pip check
python -m compileall -q .
python -c "import app, config, database, indexer_app, main, search, song_identity, timeline_parser, youtube_client"
```

Keep parser and database changes backward compatible with existing SQLite data when possible, and document migrations or re-indexing requirements.
