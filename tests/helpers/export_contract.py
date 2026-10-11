"""Build disposable real exports for Python -> D1 integration tests."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR))

from database import SongDatabase
from site_sync import TABLE_ORDER, _write_baseline, export_d1_seed, snapshot_diff
from timeline_parser import TimelineEntry, normalize_song_title


def add_song(db: SongDatabase, channel: str, video: str, title: str, seconds: int = 1) -> None:
    db.upsert_channel(channel, channel)
    db.upsert_video(video, channel, "karaoke", "2026-01-01")
    db.insert_song_entries(video, [TimelineEntry(
        f"00:{seconds:02d}", seconds, title, normalize_song_title(title),
    )], "contract fixture")


def read_export(database: Path, target: Path) -> dict[str, object]:
    manifest = export_d1_seed(database, target)
    return {
        "manifest": manifest,
        "tables": {table: json.loads((target / f"{table}.json").read_text(encoding="utf-8"))
                   for table in TABLE_ORDER},
    }


def export_contract(kind: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "songs.sqlite3"
        db = SongDatabase(database)
        try:
            db.init_schema()
            if kind == "artists":
                fixture = json.loads((PROJECT_DIR / "tests/fixtures/artist_contract.json").read_text(encoding="utf-8"))
                for artist in fixture["artists"]:
                    title = artist["title"] + (f" / {artist['name']}" if artist["name"] else "")
                    add_song(db, "artists", "video", title, artist["id"])
                return read_export(database, root / "current")
            if kind not in {"promotion", "demotion"}:
                raise ValueError(f"Unknown contract: {kind}")

            add_song(db, "first", "first-video", "KING")
            if kind == "demotion":
                add_song(db, "second", "second-video", "KING / Kanaria")
            before = read_export(database, root / "before")
            _write_baseline(root / "before", root / "baseline")
            if kind == "demotion":
                db.delete_channel("second")
            else:
                add_song(db, "second", "second-video", "KING / Kanaria")
            after = read_export(database, root / "after")
            return {"before": before, "after": after,
                    "diff": snapshot_diff(root / "after", root / "baseline")}
        finally:
            db.close()


if __name__ == "__main__":
    print(json.dumps(export_contract(sys.argv[1]), ensure_ascii=False))
