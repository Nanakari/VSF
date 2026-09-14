from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_DIR / "vtuber_songs.sqlite3"
OUTPUT_DIR = PROJECT_DIR / "build" / "d1-seed"
sys.path.insert(0, str(PROJECT_DIR))

from database import SongDatabase
from song_identity import parse_song_identity


def row_value(row: object, key: str, default: object = None) -> object:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return default


def export_seed() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db = SongDatabase(DATABASE_PATH)
    db.init_schema()
    try:
        groups = db.search_grouped(limit=100_000, offset=0)
        channels = [dict(row) for row in db.list_channels()]
        videos = [
            dict(row)
            for row in db.conn.execute(
                "SELECT video_id, channel_id, title, published_at, url, indexed_at FROM videos ORDER BY video_id"
            ).fetchall()
        ]
        songs = [
            dict(row)
            for row in db.conn.execute(
                """
                SELECT id, channel_id, canonical_song_title, normalized_song_title,
                       created_at, updated_at
                FROM songs
                ORDER BY id
                """
            ).fetchall()
        ]
        entries = [
            dict(row)
            for row in db.conn.execute(
                """
                SELECT id, song_id, video_id, timestamp_text, seconds,
                       raw_song_title, normalized_song_title, source_comment,
                       jump_url, created_at
                FROM song_entries
                ORDER BY id
                """
            ).fetchall()
        ]
    finally:
        db.close()

    group_rows: list[dict[str, object]] = []
    song_to_group: dict[int, str] = {}
    entry_to_group: dict[int, str] = {}
    for index, group in enumerate(groups):
        song_key = str(group.get("song_key") or index)
        artist_key = str(group.get("artist_key") or "")
        group_key = f"{song_key}::{artist_key}"
        title_parts = [str(group.get("song_title") or "")]
        artist_parts = [str(group.get("artist") or "")]
        entry_count = 0
        channel_ids: set[str] = set()
        for channel in group.get("channels", []):
            channel_ids.add(str(channel.get("channel_id") or ""))
            for entry in channel.get("entries", []):
                entry_count += 1
                parsed = parse_song_identity(str(entry.get("raw_song_title") or ""))
                title_parts.append(parsed.song_title)
                artist_parts.extend(parsed.artist_keys)
                song_id = row_value(entry, "song_id")
                if song_id is not None:
                    song_to_group[int(song_id)] = group_key
                entry_id = row_value(entry, "entry_id")
                if entry_id is not None:
                    entry_to_group[int(entry_id)] = group_key
        group_rows.append(
            {
                "group_key": group_key,
                "song_title": str(group.get("song_title") or "未命名歌曲"),
                "artist": str(group.get("artist") or ""),
                "title_search": " ".join(title_parts).casefold(),
                "artist_search": " ".join(artist_parts).casefold(),
                "entry_count": entry_count,
                "channel_count": len(channel_ids),
            }
        )

    missing = [int(row["id"]) for row in songs if int(row["id"]) not in song_to_group]
    if missing:
        raise RuntimeError(f"Could not assign {len(missing)} songs to a group; first IDs: {missing[:10]}")
    missing_entries = [int(row["id"]) for row in entries if int(row["id"]) not in entry_to_group]
    if missing_entries:
        raise RuntimeError(
            f"Could not assign {len(missing_entries)} entries to a group; first IDs: {missing_entries[:10]}"
        )

    group_by_key = {str(row["group_key"]): row for row in group_rows}
    song_rows: list[dict[str, object]] = []
    for row in songs:
        group_key = song_to_group[int(row["id"])]
        group = group_by_key[group_key]
        raw_title = str(row.get("canonical_song_title") or "")
        parsed = parse_song_identity(raw_title)
        song_rows.append(
            {
                "id": int(row["id"]),
                "channel_id": row.get("channel_id"),
                "canonical_song_title": row.get("canonical_song_title"),
                "normalized_song_title": row.get("normalized_song_title"),
                "artist": parsed.artist_text or group.get("artist") or "",
                "group_key": group_key,
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )

    def write(name: str, rows: list[dict[str, object]]) -> None:
        path = OUTPUT_DIR / f"{name}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{name}: {len(rows)} rows -> {path}")

    write("channels", channels)
    write("videos", videos)
    write("song_groups", group_rows)
    write("songs", song_rows)
    write(
        "song_entries",
        [
            {
                **row,
                "group_key": entry_to_group[int(row["id"])],
            }
            for row in entries
        ],
    )
    print(f"Exported {len(group_rows)} groups and {len(entries)} entries.")


if __name__ == "__main__":
    export_seed()
