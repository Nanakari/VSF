from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from timeline_parser import (
    TimelineEntry,
    clean_song_title,
    is_probable_song_title,
    normalize_song_title,
    select_best_timeline_comment,
)
from song_identity import (
    artist_query_matches,
    choose_display_artist,
    choose_display_title,
    compact_key,
    is_similar_song_key,
    parse_song_identity,
)


class SongDatabase:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                channel_title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                title TEXT NOT NULL,
                published_at TEXT,
                url TEXT NOT NULL,
                indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
            );

            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                canonical_song_title TEXT NOT NULL,
                normalized_song_title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(channel_id),
                UNIQUE (channel_id, normalized_song_title)
            );

            CREATE TABLE IF NOT EXISTS song_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER,
                video_id TEXT NOT NULL,
                timestamp_text TEXT NOT NULL,
                seconds INTEGER NOT NULL,
                raw_song_title TEXT NOT NULL,
                normalized_song_title TEXT NOT NULL,
                source_comment TEXT NOT NULL,
                jump_url TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (song_id) REFERENCES songs(id),
                FOREIGN KEY (video_id) REFERENCES videos(video_id),
                UNIQUE (video_id, seconds, normalized_song_title)
            );

            CREATE INDEX IF NOT EXISTS idx_songs_channel_normalized
                ON songs(channel_id, normalized_song_title);

            CREATE INDEX IF NOT EXISTS idx_song_entries_normalized
                ON song_entries(normalized_song_title);

            CREATE INDEX IF NOT EXISTS idx_videos_published_at
                ON videos(published_at);
            """
        )
        self._migrate_schema()
        if self._needs_song_backfill():
            self._backfill_song_hierarchy()
        self.conn.commit()

    def upsert_channel(self, channel_id: str, channel_title: str) -> None:
        self.conn.execute(
            """
            INSERT INTO channels (channel_id, channel_title)
            VALUES (?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                channel_title = excluded.channel_title
            """,
            (channel_id, channel_title),
        )
        self.conn.commit()

    def upsert_video(
        self,
        video_id: str,
        channel_id: str,
        title: str,
        published_at: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO videos (video_id, channel_id, title, published_at, url, indexed_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(video_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                title = excluded.title,
                published_at = excluded.published_at,
                url = excluded.url,
                indexed_at = CURRENT_TIMESTAMP
            """,
            (video_id, channel_id, title, published_at, make_video_url(video_id)),
        )
        self.conn.commit()

    def insert_song_entries(
        self,
        video_id: str,
        entries: Iterable[TimelineEntry],
        source_comment: str,
    ) -> int:
        channel_id = self._get_video_channel_id(video_id)
        inserted = 0
        for entry in entries:
            song_id = self.upsert_song(
                channel_id=channel_id,
                raw_song_title=entry.raw_song_title,
                normalized_song_title=entry.normalized_song_title,
            )
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO song_entries (
                    song_id,
                    video_id,
                    timestamp_text,
                    seconds,
                    raw_song_title,
                    normalized_song_title,
                    source_comment,
                    jump_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    song_id,
                    video_id,
                    entry.timestamp_text,
                    entry.seconds,
                    entry.raw_song_title,
                    entry.normalized_song_title,
                    source_comment,
                    make_jump_url(video_id, entry.seconds),
                ),
            )
            inserted += cursor.rowcount
            if cursor.rowcount == 0:
                self.conn.execute(
                    """
                    UPDATE song_entries
                    SET song_id = COALESCE(song_id, ?)
                    WHERE video_id = ?
                        AND seconds = ?
                        AND normalized_song_title = ?
                    """,
                    (song_id, video_id, entry.seconds, entry.normalized_song_title),
                )
        self.conn.commit()
        return inserted

    def replace_song_entries_for_video(
        self,
        video_id: str,
        entries: Iterable[TimelineEntry],
        source_comment: str,
    ) -> int:
        self.conn.execute("DELETE FROM song_entries WHERE video_id = ?", (video_id,))
        self._delete_orphan_songs()
        self.conn.commit()
        return self.insert_song_entries(video_id, entries, source_comment)

    def rebuild_best_timeline_comments(self) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT video_id, source_comment
            FROM song_entries
            GROUP BY video_id, source_comment
            """
        ).fetchall()
        comments_by_video: dict[str, list[str]] = {}
        for row in rows:
            comments_by_video.setdefault(row["video_id"], []).append(row["source_comment"])

        videos_changed = 0
        entries_before = self._count_table("song_entries")
        for video_id, comments in comments_by_video.items():
            candidate = select_best_timeline_comment(comments)
            if candidate is None:
                continue
            videos_changed += 1
            self.replace_song_entries_for_video(
                video_id=video_id,
                entries=candidate.entries,
                source_comment=candidate.comment_text,
            )
        self._delete_orphan_songs()
        self.conn.commit()
        entries_after = self._count_table("song_entries")
        return {
            "videos_changed": videos_changed,
            "entries_before": entries_before,
            "entries_after": entries_after,
            "entries_removed": entries_before - entries_after,
        }

    def upsert_song(
        self,
        channel_id: str,
        raw_song_title: str,
        normalized_song_title: str,
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO songs (channel_id, canonical_song_title, normalized_song_title)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id, normalized_song_title) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP
            """,
            (channel_id, raw_song_title, normalized_song_title),
        )
        row = self.conn.execute(
            """
            SELECT id
            FROM songs
            WHERE channel_id = ? AND normalized_song_title = ?
            """,
            (channel_id, normalized_song_title),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Failed to upsert song: {raw_song_title}")
        return int(row["id"])

    def search(self, query: str, limit: int = 25) -> list[sqlite3.Row]:
        return self.search_entries(song_query=query, limit=limit)

    def search_entries(
        self,
        song_query: str | None = None,
        channel_query: str | None = None,
        limit: int | None = 50,
    ) -> list[sqlite3.Row]:
        where_clauses = []
        params: list[object] = []
        order_params: list[object] = []

        normalized_query = normalize_song_title(song_query or "")
        if normalized_query:
            song_clause, song_params = build_song_match_clause(normalized_query)
            where_clauses.append(song_clause)
            params.extend(song_params)
            order_params.extend((normalized_query, f"{escape_like(normalized_query)}%"))

        if channel_query:
            channel_like = f"%{escape_like(channel_query)}%"
            where_clauses.append(
                "(channels.channel_title LIKE ? ESCAPE '\\' OR channels.channel_id = ?)"
            )
            params.extend((channel_like, channel_query))

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        relevance_sql = "2"
        if normalized_query:
            relevance_sql = (
                "CASE "
                "WHEN songs.normalized_song_title = ? THEN 0 "
                "WHEN songs.normalized_song_title LIKE ? ESCAPE '\\' THEN 1 "
                "ELSE 2 END"
            )

        limit_sql = ""
        query_params: tuple[object, ...]
        if limit is None:
            query_params = (*params, *order_params)
        else:
            limit_sql = "LIMIT ?"
            query_params = (*params, *order_params, limit)

        cursor = self.conn.execute(
            f"""
            SELECT
                songs.id AS song_id,
                songs.canonical_song_title,
                songs.normalized_song_title,
                song_entries.raw_song_title,
                song_entries.timestamp_text,
                song_entries.seconds,
                song_entries.jump_url,
                videos.video_id,
                videos.title AS video_title,
                videos.published_at,
                channels.channel_id,
                channels.channel_title
            FROM song_entries
            JOIN songs ON songs.id = song_entries.song_id
            JOIN videos ON videos.video_id = song_entries.video_id
            JOIN channels ON channels.channel_id = videos.channel_id
            {where_sql}
            ORDER BY
                {relevance_sql},
                channels.channel_title,
                songs.normalized_song_title,
                videos.published_at DESC,
                song_entries.seconds ASC
            {limit_sql}
            """,
            query_params,
        )
        return list(cursor.fetchall())

    def search_grouped(
        self,
        song_query: str | None = None,
        channel_query: str | None = None,
        artist_query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        normalized_query = normalize_song_title(song_query or "")
        query_key = compact_key(song_query or "")
        artist_query = (artist_query or "").strip()
        rows = self.search_entries(
            song_query=None if normalized_query else song_query,
            channel_query=channel_query,
            limit=None,
        )
        grouped: dict[tuple[str, str, str], dict[str, object]] = {}
        for row in rows:
            parsed = parse_song_identity(row["raw_song_title"])
            if artist_query and (parsed.ambiguous or not artist_query_matches(parsed.artist_keys, artist_query)):
                continue

            merge_key = compact_key(parsed.song_title)
            row_artist_key = parsed.artist_group_key
            key = self._find_similar_group_key(
                grouped=grouped,
                channel_id=row["channel_id"],
                merge_key=merge_key,
                artist_key=row_artist_key,
            )
            if key not in grouped:
                grouped[key] = {
                    "channel_id": row["channel_id"],
                    "channel_title": row["channel_title"],
                    "song_key": merge_key,
                    "artist_key": row_artist_key,
                    "artist_keys": set(parsed.artist_keys),
                    "title_keys": set(),
                    "song_title": "",
                    "artist": "",
                    "normalized_song_title": merge_key,
                    "raw_titles": [],
                    "entries": [],
                }
            grouped[key]["title_keys"].add(merge_key)
            if row_artist_key and not grouped[key]["artist_key"]:
                grouped[key]["artist_key"] = row_artist_key
            grouped[key]["artist_keys"].update(parsed.artist_keys)
            grouped[key]["raw_titles"].append(row["raw_song_title"])
            grouped[key]["entries"].append(dict(row))

        groups = list(grouped.values())
        if normalized_query:
            groups = [
                group
                for group in groups
                if group_matches_query(group, normalized_query, query_key)
            ]

        for group in groups:
            raw_titles = group.pop("raw_titles")
            group["song_title"] = choose_display_title(raw_titles)
            group["artist"] = choose_display_artist(raw_titles)
            group["entries"].sort(
                key=lambda entry: (
                    entry.get("published_at") or "",
                    entry.get("seconds") or 0,
                ),
                reverse=True,
            )
            group["channels"] = make_channel_groups(group["entries"])

        if not channel_query:
            groups = combine_cross_channel_groups(groups)

        if normalized_query:
            groups.sort(
                key=lambda group: (
                    group_query_relevance(group, normalized_query, query_key),
                    str(group["channel_title"]).casefold(),
                    str(group["song_title"]).casefold(),
                    str(group["artist"]).casefold(),
                )
            )
        elif artist_query:
            groups.sort(
                key=lambda group: (
                    str(group["song_title"]).casefold(),
                    str(group["artist"]).casefold(),
                    str(group["channel_title"]).casefold(),
                    -len(group["entries"]),
                )
            )
        else:
            groups.sort(
                key=lambda group: (
                    -len(group["entries"]),
                    str(group["channel_title"]).casefold(),
                    str(group["song_title"]).casefold(),
                    str(group["artist"]).casefold(),
                )
            )
        return groups[offset : offset + limit]

    def _find_similar_group_key(
        self,
        grouped: dict[tuple[str, str, str], dict[str, object]],
        channel_id: str,
        merge_key: str,
        artist_key: str,
    ) -> tuple[str, str, str]:
        exact_key = (channel_id, merge_key, artist_key)
        if exact_key in grouped:
            return exact_key

        if not artist_key:
            for key, group in grouped.items():
                if key[0] == channel_id and str(group.get("song_key")) == merge_key:
                    return key
            return exact_key

        unknown_key = (channel_id, merge_key, "")
        if unknown_key in grouped:
            return unknown_key

        for key, group in grouped.items():
            if key[0] != channel_id:
                continue
            if str(group.get("song_key")) != merge_key:
                continue
            if are_artist_keys_compatible(str(group.get("artist_key", "")), artist_key):
                return key

        for key, group in grouped.items():
            if key[0] != channel_id:
                continue
            if group.get("artist_key") != artist_key:
                continue
            if is_similar_song_key(str(group["song_key"]), merge_key):
                return key
        return exact_key

    def list_channels(self) -> list[sqlite3.Row]:
        cursor = self.conn.execute(
            """
            SELECT
                channels.channel_id,
                channels.channel_title,
                COALESCE(video_counts.video_count, 0) AS video_count,
                COALESCE(song_counts.song_count, 0) AS song_count,
                COALESCE(entry_counts.entry_count, 0) AS entry_count
            FROM channels
            LEFT JOIN (
                SELECT channel_id, COUNT(*) AS video_count
                FROM videos
                GROUP BY channel_id
            ) AS video_counts ON video_counts.channel_id = channels.channel_id
            LEFT JOIN (
                SELECT channel_id, COUNT(*) AS song_count
                FROM songs
                GROUP BY channel_id
            ) AS song_counts ON song_counts.channel_id = channels.channel_id
            LEFT JOIN (
                SELECT videos.channel_id, COUNT(song_entries.id) AS entry_count
                FROM song_entries
                JOIN videos ON videos.video_id = song_entries.video_id
                GROUP BY videos.channel_id
            ) AS entry_counts ON entry_counts.channel_id = channels.channel_id
            ORDER BY channels.channel_title
            """
        )
        return list(cursor.fetchall())

    def prune_non_song_entries(self) -> int:
        rows = self.conn.execute(
            """
            SELECT id, raw_song_title, normalized_song_title
            FROM song_entries
            """
        ).fetchall()
        bad_ids = []
        for row in rows:
            cleaned_title = clean_song_title(row["raw_song_title"])
            normalized_title = normalize_song_title(cleaned_title)
            if not is_probable_song_title(cleaned_title, normalized_title):
                bad_ids.append(row["id"])
                continue
            if (
                cleaned_title != row["raw_song_title"]
                or normalized_title != row["normalized_song_title"]
            ):
                try:
                    self.conn.execute(
                        """
                        UPDATE song_entries
                        SET raw_song_title = ?, normalized_song_title = ?
                        WHERE id = ?
                        """,
                        (cleaned_title, normalized_title, row["id"]),
                    )
                except sqlite3.IntegrityError:
                    bad_ids.append(row["id"])

        bad_ids.extend(self._low_confidence_entry_ids())
        bad_ids = sorted(set(bad_ids))
        if not bad_ids:
            self._rebuild_song_hierarchy()
            return 0

        self.conn.executemany(
            "DELETE FROM song_entries WHERE id = ?",
            [(bad_id,) for bad_id in bad_ids],
        )
        self._rebuild_song_hierarchy()
        self.conn.commit()
        return len(bad_ids)

    def _rebuild_song_hierarchy(self) -> None:
        self.conn.execute("UPDATE song_entries SET song_id = NULL")
        self.conn.execute(
            """
            DELETE FROM songs
            """
        )
        self._backfill_song_hierarchy()

    def _delete_orphan_songs(self) -> None:
        self.conn.execute(
            """
            DELETE FROM songs
            WHERE id NOT IN (
                SELECT DISTINCT song_id
                FROM song_entries
                WHERE song_id IS NOT NULL
            )
            """
        )

    def _low_confidence_entry_ids(self) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT
                song_entries.id,
                song_entries.raw_song_title,
                songs.normalized_song_title,
                COUNT(song_entries.id) OVER (PARTITION BY songs.id) AS entry_count
            FROM song_entries
            JOIN songs ON songs.id = song_entries.song_id
            """
        ).fetchall()
        bad_ids: list[int] = []
        for row in rows:
            title = row["raw_song_title"]
            normalized = row["normalized_song_title"]
            if row["entry_count"] > 1:
                continue
            if is_low_confidence_singleton(title, normalized):
                bad_ids.append(row["id"])
        return bad_ids

    def search_legacy(self, query: str, limit: int = 25) -> list[sqlite3.Row]:
        normalized_query = normalize_song_title(query)
        like_query = f"%{escape_like(normalized_query)}%"
        cursor = self.conn.execute(
            """
            SELECT
                songs.id AS song_id,
                songs.canonical_song_title,
                song_entries.raw_song_title,
                songs.normalized_song_title,
                song_entries.timestamp_text,
                song_entries.seconds,
                song_entries.jump_url,
                videos.video_id,
                videos.title AS video_title,
                videos.published_at,
                channels.channel_title
            FROM song_entries
            JOIN songs ON songs.id = song_entries.song_id
            JOIN videos ON videos.video_id = song_entries.video_id
            JOIN channels ON channels.channel_id = videos.channel_id
            WHERE songs.normalized_song_title LIKE ? ESCAPE '\\'
            ORDER BY
                CASE
                    WHEN songs.normalized_song_title = ? THEN 0
                    WHEN songs.normalized_song_title LIKE ? ESCAPE '\\' THEN 1
                    ELSE 2
                END,
                videos.published_at DESC,
                song_entries.seconds ASC
            LIMIT ?
            """,
            (like_query, normalized_query, f"{escape_like(normalized_query)}%", limit),
        )
        return list(cursor.fetchall())

    def list_songs(self, channel_query: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        params: list[object] = []
        where = ""
        if channel_query:
            where = "WHERE channels.channel_title LIKE ? ESCAPE '\\' OR channels.channel_id = ?"
            params.extend((f"%{escape_like(channel_query)}%", channel_query))

        cursor = self.conn.execute(
            f"""
            SELECT
                channels.channel_title,
                channels.channel_id,
                songs.id AS song_id,
                songs.canonical_song_title,
                songs.normalized_song_title,
                COUNT(song_entries.id) AS entry_count,
                COUNT(DISTINCT song_entries.video_id) AS video_count,
                MAX(videos.published_at) AS latest_published_at
            FROM songs
            JOIN channels ON channels.channel_id = songs.channel_id
            LEFT JOIN song_entries ON song_entries.song_id = songs.id
            LEFT JOIN videos ON videos.video_id = song_entries.video_id
            {where}
            GROUP BY songs.id
            ORDER BY channels.channel_title, songs.normalized_song_title
            LIMIT ?
            """,
            (*params, limit),
        )
        return list(cursor.fetchall())

    def get_stats(self) -> dict[str, int]:
        return {
            "channels": self._count_table("channels"),
            "videos": self._count_table("videos"),
            "songs": self._count_table("songs"),
            "entries": self._count_table("song_entries"),
        }

    def _get_video_channel_id(self, video_id: str) -> str:
        row = self.conn.execute(
            "SELECT channel_id FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Video must be inserted before song entries: {video_id}")
        return str(row["channel_id"])

    def _count_table(self, table_name: str) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"])

    def _migrate_schema(self) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(song_entries)").fetchall()
        }
        if "song_id" not in columns:
            self.conn.execute("ALTER TABLE song_entries ADD COLUMN song_id INTEGER")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_song_entries_song_id ON song_entries(song_id)"
        )

    def _needs_song_backfill(self) -> bool:
        entry_row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM song_entries"
        ).fetchone()
        entry_count = int(entry_row["count"])
        if entry_count == 0:
            return False

        song_row = self.conn.execute("SELECT COUNT(*) AS count FROM songs").fetchone()
        if int(song_row["count"]) == 0:
            return True

        missing_row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM song_entries WHERE song_id IS NULL"
        ).fetchone()
        return int(missing_row["count"]) > 0

    def _backfill_song_hierarchy(self) -> None:
        rows = self.conn.execute(
            """
            SELECT
                videos.channel_id,
                song_entries.raw_song_title,
                song_entries.normalized_song_title
            FROM song_entries
            JOIN videos ON videos.video_id = song_entries.video_id
            WHERE song_entries.normalized_song_title <> ''
            GROUP BY videos.channel_id, song_entries.normalized_song_title
            """
        ).fetchall()
        for row in rows:
            self.upsert_song(
                channel_id=row["channel_id"],
                raw_song_title=row["raw_song_title"],
                normalized_song_title=row["normalized_song_title"],
            )

        self.conn.execute(
            """
            UPDATE song_entries
            SET song_id = (
                SELECT songs.id
                FROM songs
                JOIN videos ON videos.channel_id = songs.channel_id
                WHERE videos.video_id = song_entries.video_id
                    AND songs.normalized_song_title = song_entries.normalized_song_title
                LIMIT 1
            )
            WHERE song_id IS NULL
            """
        )


def make_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def make_jump_url(video_id: str, seconds: int) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={seconds}s"


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_song_match_clause(normalized_query: str) -> tuple[str, list[object]]:
    escaped_query = escape_like(normalized_query)
    if is_ascii_word_query(normalized_query):
        patterns = [
            f"{escaped_query} %",
            f"{escaped_query}/%",
            f"{escaped_query}-%",
            f"{escaped_query}:%",
            f"% {escaped_query}%",
            f"%/{escaped_query}%",
            f"%-{escaped_query}%",
            f"%|{escaped_query}%",
        ]
        clauses = ["songs.normalized_song_title = ?"]
        params: list[object] = [normalized_query]
        for pattern in patterns:
            clauses.append("songs.normalized_song_title LIKE ? ESCAPE '\\'")
            params.append(pattern)
        return "(" + " OR ".join(clauses) + ")", params

    return "songs.normalized_song_title LIKE ? ESCAPE '\\'", [f"%{escaped_query}%"]


def is_ascii_word_query(value: str) -> bool:
    return bool(value) and all(char.isascii() and (char.isalnum() or char in " _-") for char in value)


def group_matches_query(
    group: dict[str, object],
    normalized_query: str,
    query_key: str,
) -> bool:
    title_keys = [str(key) for key in group.get("title_keys", set())]
    if not query_key:
        return True
    if is_short_ascii_key(query_key):
        return any(
            title_key == query_key
            or title_key.startswith(query_key)
            or is_similar_song_key(title_key, query_key)
            for title_key in title_keys
        )
    for title_key in title_keys:
        if query_key in title_key or title_key in query_key:
            return True
        if is_similar_song_key(title_key, query_key):
            return True
    return normalized_query in str(group.get("normalized_song_title", ""))


def group_query_relevance(
    group: dict[str, object],
    normalized_query: str,
    query_key: str,
) -> int:
    title_keys = [str(key) for key in group.get("title_keys", set())]
    if query_key in title_keys:
        return 0
    if any(title_key.startswith(query_key) for title_key in title_keys):
        return 1
    if any(query_key in title_key for title_key in title_keys):
        return 2
    if any(is_similar_song_key(title_key, query_key) for title_key in title_keys):
        return 3
    if normalized_query in str(group.get("normalized_song_title", "")):
        return 4
    return 5


def combine_cross_channel_groups(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    combined: list[dict[str, object]] = []
    for group in groups:
        target = find_cross_channel_target(combined, group)
        if target is None:
            copied = dict(group)
            copied["title_keys"] = set(group.get("title_keys", set()))
            copied["artist_keys"] = set(group.get("artist_keys", set()))
            copied["entries"] = list(group.get("entries", []))
            copied["channel_titles"] = {group.get("channel_title")}
            combined.append(copied)
            continue

        target["title_keys"].update(group.get("title_keys", set()))
        target["artist_keys"].update(group.get("artist_keys", set()))
        target["entries"].extend(group.get("entries", []))
        target["entries"].sort(
            key=lambda entry: (
                entry.get("published_at") or "",
                entry.get("seconds") or 0,
            ),
            reverse=True,
        )
        target["channel_titles"].add(group.get("channel_title"))
        if len(str(group.get("song_title", ""))) < len(str(target.get("song_title", ""))):
            target["song_title"] = group.get("song_title", "")
        if not target.get("artist") and group.get("artist"):
            target["artist"] = group.get("artist", "")
            target["artist_key"] = group.get("artist_key", "")
        target["channels"] = make_channel_groups(target["entries"])

    for group in combined:
        group["channels"] = make_channel_groups(group.get("entries", []))
        group["channel_count"] = len(group["channels"])
    return combined


def find_cross_channel_target(
    groups: list[dict[str, object]],
    candidate: dict[str, object],
) -> dict[str, object] | None:
    candidate_song_key = str(candidate.get("song_key", ""))
    candidate_artist_key = str(candidate.get("artist_key", ""))
    for group in groups:
        artist_key = str(group.get("artist_key", ""))
        song_key = str(group.get("song_key", ""))
        if candidate_song_key == song_key:
            if are_artist_keys_compatible(artist_key, candidate_artist_key):
                return group
            continue
        if candidate_artist_key != artist_key:
            continue
        if candidate_artist_key and is_similar_song_key(song_key, candidate_song_key):
            return group
    return None


def are_artist_keys_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    if not left or not right:
        return True

    left_tokens = {token for token in left.split("|") if token}
    right_tokens = {token for token in right.split("|") if token}
    if not left_tokens or not right_tokens:
        return True
    if left_tokens & right_tokens:
        return True
    if len(left_tokens) != len(right_tokens):
        return False

    unmatched = set(right_tokens)
    for left_token in left_tokens:
        match = next(
            (
                right_token
                for right_token in unmatched
                if are_artist_tokens_nearly_equal(left_token, right_token)
            ),
            None,
        )
        if match is None:
            return False
        unmatched.remove(match)
    return True


def are_artist_tokens_nearly_equal(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < 4:
        return False
    if abs(len(left) - len(right)) > 2:
        return False

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[right_index - 1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
            row_min = min(row_min, current[-1])
        if row_min > 2:
            return False
        previous = current
    return previous[-1] <= 2


def make_channel_groups(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    channels: dict[str, dict[str, object]] = {}
    for entry in entries:
        channel_id = str(entry.get("channel_id") or "")
        if channel_id not in channels:
            channels[channel_id] = {
                "channel_id": channel_id,
                "channel_title": entry.get("channel_title") or "",
                "entries": [],
            }
        channels[channel_id]["entries"].append(entry)

    result = list(channels.values())
    for channel in result:
        channel["entries"].sort(
            key=lambda entry: (
                entry.get("published_at") or "",
                entry.get("seconds") or 0,
            ),
            reverse=True,
        )
    result.sort(
        key=lambda channel: (
            -len(channel["entries"]),
            str(channel.get("channel_title") or "").casefold(),
        )
    )
    return result


def is_short_ascii_key(value: str) -> bool:
    return len(value) <= 4 and value.isascii() and value.isalnum()


def is_low_confidence_singleton(title: str, normalized_title: str) -> bool:
    lowered = normalized_title.casefold()
    if has_artist_separator(title):
        return False

    non_song_fragments = (
        "fanbox",
        "twitter",
        "x ",
        "youtube",
        "twitch",
        "discord",
        "booth",
        "goods",
        "asmr",
        "apex",
        "bgm",
        "case",
        "\u914d\u4fe1",
        "\u4e88\u5b9a",
        "\u544a\u77e5",
        "\u304a\u77e5\u3089\u305b",
        "\u5831\u544a",
        "\u7a81\u7834",
        "\u9054\u6210",
        "\u5468\u5e74",
        "\u30b0\u30c3\u30ba",
        "\u30d7\u30e9\u30f3",
        "\u5909\u66f4",
        "\u65c5\u884c",
        "\u904b\u8ee2",
        "\u767a\u9001",
        "\u7279\u5178",
        "\u30dc\u30a4\u30b9",
        "\u30b9\u30b1\u30b8\u30e5\u30fc\u30eb",
        "\u660e\u65e5",
        "\u4eca\u65e5",
        "\u6628\u65e5",
        "\u660e\u5f8c\u65e5",
        "\u80cc\u666f",
        "ch\u30ab\u30a6\u30f3\u30bf\u30fc",
        "c\u30d1\u30fc\u30c8",
    )
    if any(fragment in lowered for fragment in non_song_fragments):
        return True

    if any(marker in title for marker in ("?", "\uff1f")):
        return True

    if looks_like_count_marker(title):
        return True

    return False


def has_artist_separator(title: str) -> bool:
    separators = ("/", "\uff0f", " - ", "\u2013", "\u2014", "|", "\uff5c")
    return any(separator in title for separator in separators)


def looks_like_count_marker(title: str) -> bool:
    compact = title.replace(" ", "")
    if "\u4eba" in compact and any(char.isdigit() for char in compact):
        return True
    return False
