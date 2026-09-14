from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_DIR / "dist" / "catalog.json"
DATABASE_PATH = PROJECT_DIR / "vtuber_songs.sqlite3"
sys.path.insert(0, str(PROJECT_DIR))

from database import SongDatabase
from song_identity import parse_song_identity


def export_catalog() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = SongDatabase(DATABASE_PATH)
    db.init_schema()
    try:
        groups = db.search_grouped(limit=100_000, offset=0)
        channels = [dict(row) for row in db.list_channels()]
        stats = db.get_stats()
    finally:
        db.close()

    serialized_groups = []
    for index, group in enumerate(groups):
        serialized_channels = []
        search_parts = [
            str(group.get("song_title") or ""),
            str(group.get("artist") or ""),
        ]
        title_parts = [str(group.get("song_title") or "")]
        artist_parts = [str(group.get("artist") or "")]
        for channel in group.get("channels", []):
            channel_title = str(channel.get("channel_title") or "")
            channel_id = str(channel.get("channel_id") or "")
            search_parts.extend((channel_title, channel_id))
            entries = []
            for entry in channel.get("entries", []):
                video_title = str(entry.get("video_title") or "")
                raw_song_title = str(entry.get("raw_song_title") or "")
                search_parts.append(video_title)
                parsed_identity = parse_song_identity(raw_song_title)
                title_parts.append(parsed_identity.song_title)
                artist_parts.extend(parsed_identity.artist_keys)
                entries.append(
                    {
                        "videoTitle": video_title,
                        "publishedAt": entry.get("published_at"),
                        "timestampText": str(entry.get("timestamp_text") or ""),
                        "jumpUrl": str(entry.get("jump_url") or ""),
                    }
                )
            serialized_channels.append(
                {
                    "id": channel_id,
                    "title": channel_title,
                    "entries": entries,
                }
            )

        song_title = str(group.get("song_title") or "未命名歌曲")
        artist = str(group.get("artist") or "")
        serialized_groups.append(
            {
                "id": f"{group.get('song_key', index)}::{group.get('artist_key', '')}",
                "songTitle": song_title,
                "artist": artist,
                "channelCount": len(serialized_channels),
                "entryCount": sum(len(channel["entries"]) for channel in serialized_channels),
                "searchText": " ".join(search_parts).casefold(),
                "titleSearchText": " ".join(title_parts).casefold(),
                "artistSearchText": " ".join(artist_parts).casefold(),
                "channels": serialized_channels,
            }
        )

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "channels": channels,
        "groups": serialized_groups,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"Exported {len(serialized_groups)} song groups and "
        f"{stats['entries']} timeline entries to {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    export_catalog()
