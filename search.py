from __future__ import annotations

from database import SongDatabase


def search_songs(
    db: SongDatabase,
    query: str,
    limit: int = 25,
    channel_query: str | None = None,
    artist_query: str | None = None,
) -> list[dict[str, object]]:
    """Return the legacy flat entry shape using the grouped search contract.

    The CLI historically printed entries rather than groups.  Keep that output
    shape while sourcing matches, merging, and ordering from ``search_grouped``
    so compact, fuzzy, version, channel, and artist queries behave like the
    local web search.
    """
    max_entries = max(0, int(limit))
    if max_entries == 0:
        return []

    rows: list[dict[str, object]] = []
    group_offset = 0
    group_page_size = max(50, max_entries)
    while len(rows) < max_entries:
        groups = db.search_grouped(
            song_query=query,
            channel_query=channel_query,
            artist_query=artist_query,
            limit=group_page_size,
            offset=group_offset,
        )
        if not groups:
            break
        for group in groups:
            # ``channels`` is hydrated for every grouped search.  Flattening it
            # avoids duplicate rows for cross-channel groups and keeps channel
            # filtering scoped to the selected channel.
            channels = group.get("channels") or []
            if channels:
                for channel in channels:
                    rows.extend(dict(entry) for entry in channel.get("entries", []))
            else:
                rows.extend(dict(entry) for entry in group.get("entries", []))
            if len(rows) >= max_entries:
                break
        if len(groups) < group_page_size:
            break
        group_offset += len(groups)
    return rows[:max_entries]
