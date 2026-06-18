from __future__ import annotations

from database import SongDatabase


def search_songs(
    db: SongDatabase,
    query: str,
    limit: int = 25,
    channel_query: str | None = None,
) -> list[dict[str, object]]:
    rows = db.search_entries(song_query=query, channel_query=channel_query, limit=limit)
    return [dict(row) for row in rows]
