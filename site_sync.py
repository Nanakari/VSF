from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from database import SongDatabase
from song_identity import make_title_search_text, parse_song_identity


TABLE_ORDER = ("channels", "videos", "song_groups", "songs", "song_entries")
BATCH_SIZE = 90
LogCallback = Callable[[str], None]


def _row_value(row: object, key: str, default: object = None) -> object:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return default


def _emit(callback: LogCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def export_d1_seed(
    database_path: Path | str,
    output_dir: Path | str,
    on_message: LogCallback | None = None,
) -> dict[str, object]:
    """Export the local database in the format accepted by the Site Worker."""
    database_path = Path(database_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db = SongDatabase(database_path)
    db.init_schema()
    try:
        groups = db.search_grouped(limit=100_000, offset=0)
        channels = [dict(row) for row in db.list_channels()]
        videos = [
            dict(row)
            for row in db.conn.execute(
                """
                SELECT video_id, channel_id, title, published_at, url, indexed_at
                FROM videos
                ORDER BY video_id
                """
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
        group_key = str(group.get("group_key") or f"{song_key}::{artist_key}")
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
                song_id = _row_value(entry, "song_id")
                if song_id is not None:
                    song_to_group[int(song_id)] = group_key
                entry_id = _row_value(entry, "entry_id")
                if entry_id is not None:
                    entry_to_group[int(entry_id)] = group_key
        group_rows.append(
            {
                "group_key": group_key,
                "song_title": str(group.get("song_title") or "未命名歌曲"),
                "artist": str(group.get("artist") or ""),
                "title_search": make_title_search_text(title_parts),
                "artist_search": " ".join(artist_parts).casefold(),
                "entry_count": entry_count,
                "channel_count": len(channel_ids),
            }
        )

    missing = [
        int(row["id"])
        for row in songs
        if int(row["id"]) not in song_to_group
    ]
    if missing:
        raise RuntimeError(
            f"Could not assign {len(missing)} songs to a group; first IDs: {missing[:10]}"
        )
    missing_entries = [
        int(row["id"])
        for row in entries
        if int(row["id"]) not in entry_to_group
    ]
    if missing_entries:
        raise RuntimeError(
            "Could not assign "
            f"{len(missing_entries)} entries to a group; first IDs: {missing_entries[:10]}"
        )

    song_rows: list[dict[str, object]] = []
    for row in songs:
        group_key = song_to_group[int(row["id"])]
        raw_title = str(row.get("canonical_song_title") or "")
        parsed = parse_song_identity(raw_title)
        song_rows.append(
            {
                "id": int(row["id"]),
                "channel_id": row.get("channel_id"),
                "canonical_song_title": row.get("canonical_song_title"),
                "normalized_song_title": row.get("normalized_song_title"),
                "artist": parsed.artist_text or "",
                "group_key": group_key,
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )

    seed_entries = [
        {
            **row,
            "group_key": entry_to_group[int(row["id"])],
        }
        for row in entries
    ]
    seed_tables: dict[str, list[dict[str, object]]] = {
        "channels": channels,
        "videos": videos,
        "song_groups": group_rows,
        "songs": song_rows,
        "song_entries": seed_entries,
    }

    def write(name: str, rows: list[dict[str, object]]) -> None:
        path = output_dir / f"{name}.json"
        path.write_text(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        _emit(on_message, f"已导出 {name}: {len(rows)} 条")

    for name in TABLE_ORDER:
        write(name, seed_tables[name])

    version_payload = json.dumps(
        seed_tables,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    version = hashlib.sha256(version_payload).hexdigest()[:24]
    manifest: dict[str, object] = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {name: len(rows) for name, rows in seed_tables.items()},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _emit(on_message, f"快照已生成，版本 {version}")
    return manifest


def request_json(
    session: requests.Session,
    url: str,
    token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    response = session.post(
        url,
        headers={"x-seed-token": token},
        json=payload,
        timeout=120,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        raise RuntimeError(
            f"{url} failed with HTTP {response.status_code}: "
            f"{body.get('message', 'unknown error')}"
        )
    if body.get("ok") is False:
        raise RuntimeError(f"{url} failed: {body.get('message', 'unknown error')}")
    return body


def import_snapshot(
    base_url: str,
    token: str,
    input_dir: Path | str,
    on_message: LogCallback | None = None,
    request_json_fn: Callable[
        [requests.Session, str, str, dict[str, object]], dict[str, object]
    ] = request_json,
) -> None:
    """Import a complete snapshot using the Worker's staged atomic swap."""
    input_dir = Path(input_dir)
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise RuntimeError("manifest.json does not contain a snapshot version")

    base_url = base_url.rstrip("/")
    session = requests.Session()
    tables = manifest.get("tables")
    if not isinstance(tables, dict):
        raise RuntimeError("manifest.json does not contain table row counts")
    start_result = request_json_fn(
        session,
        f"{base_url}/api/admin/snapshot/start",
        token,
        {"version": version, "tables": tables},
    )
    if start_result.get("status") == "ready":
        _emit(on_message, f"站点快照 {version} 已经同步")
        return

    for table in TABLE_ORDER:
        rows = json.loads((input_dir / f"{table}.json").read_text(encoding="utf-8"))
        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start : start + BATCH_SIZE]
            request_json_fn(
                session,
                f"{base_url}/api/admin/seed",
                token,
                {"version": version, "table": table, "rows": batch},
            )
        _emit(on_message, f"站点正在接收 {table} 数据")

    request_json_fn(
        session,
        f"{base_url}/api/admin/snapshot/commit",
        token,
        {"version": version},
    )
    _emit(on_message, f"站点快照 {version} 已完成切换")


def sync_database_to_site(
    database_path: Path | str,
    base_url: str,
    token: str,
    output_dir: Path | str,
    on_message: LogCallback | None = None,
) -> dict[str, object]:
    manifest = export_d1_seed(database_path, output_dir, on_message=on_message)
    import_snapshot(base_url, token, output_dir, on_message=on_message)
    return manifest
