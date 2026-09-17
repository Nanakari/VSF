from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from database import SongDatabase
from song_identity import make_title_search_text, parse_song_identity


TABLE_ORDER = ("channels", "videos", "song_groups", "songs", "song_entries")
BATCH_SIZE = 90
PATCH_BATCH_SIZE = 80
SNAPSHOT_SCHEMA_VERSION = 1
MAX_INCREMENTAL_OPERATIONS = 80
MAX_INCREMENTAL_PAYLOAD_BYTES = 1_200_000
SNAPSHOT_KEYS = {
    "channels": "channel_id",
    "videos": "video_id",
    "song_groups": "group_key",
    "songs": "id",
    "song_entries": "id",
}
SNAPSHOT_FILES = ("manifest.json", *(f"{table}.json" for table in TABLE_ORDER))
LogCallback = Callable[[str], None]


class SiteSyncHTTPError(RuntimeError):
    """An HTTP error returned by a Site sync endpoint."""

    def __init__(self, url: str, status_code: int, message: str) -> None:
        super().__init__(f"{url} failed with HTTP {status_code}: {message}")
        self.url = url
        self.status_code = status_code
        self.message = message


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
        "schema": SNAPSHOT_SCHEMA_VERSION,
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


def _baseline_dir(output_dir: Path | str) -> Path:
    output_dir = Path(output_dir)
    return output_dir.with_name(f"{output_dir.name}-baseline")


def _read_snapshot(
    directory: Path | str,
    *,
    require_complete: bool = False,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    directory = Path(directory)
    marker = directory / ".complete"
    if require_complete and not marker.is_file():
        raise ValueError("snapshot baseline is incomplete")

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("snapshot baseline uses an unsupported schema")

    tables: dict[str, list[dict[str, object]]] = {}
    expected_tables = manifest.get("tables")
    if not isinstance(expected_tables, dict):
        raise ValueError("snapshot manifest does not contain table counts")
    for table in TABLE_ORDER:
        rows = json.loads((directory / f"{table}.json").read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"snapshot table {table} is invalid")
        if expected_tables.get(table) != len(rows):
            raise ValueError(f"snapshot table {table} count does not match its manifest")
        key_name = SNAPSHOT_KEYS[table]
        seen: set[str] = set()
        for row in rows:
            key = str(row.get(key_name, ""))
            if not key or key in seen:
                raise ValueError(f"snapshot table {table} contains duplicate or empty keys")
            seen.add(key)
        tables[table] = rows
    return manifest, tables


def snapshot_diff(
    current_dir: Path | str,
    baseline_dir: Path | str,
) -> dict[str, dict[str, list[object]]]:
    """Return row-level upserts and deletes between two exported snapshots."""
    _, current_tables = _read_snapshot(current_dir)
    _, baseline_tables = _read_snapshot(baseline_dir, require_complete=True)
    diff: dict[str, dict[str, list[object]]] = {}
    for table in TABLE_ORDER:
        key_name = SNAPSHOT_KEYS[table]
        current_by_key = {str(row[key_name]): row for row in current_tables[table]}
        baseline_by_key = {str(row[key_name]): row for row in baseline_tables[table]}
        upserts = [
            current_by_key[key]
            for key in current_by_key.keys() - baseline_by_key.keys()
        ]
        upserts.extend(
            current_by_key[key]
            for key in current_by_key.keys() & baseline_by_key.keys()
            if current_by_key[key] != baseline_by_key[key]
        )
        deletes = [
            baseline_by_key[key][key_name]
            for key in baseline_by_key.keys() - current_by_key.keys()
        ]
        upserts.sort(key=lambda row: str(row[key_name]))  # type: ignore[index]
        deletes.sort(key=str)
        diff[table] = {"upserts": upserts, "deletes": deletes}
    return diff


def incremental_change_stats(
    diff: dict[str, dict[str, list[object]]],
) -> tuple[int, int]:
    """Return operation count and approximate JSON payload bytes."""
    operations = 0
    payload_bytes = 0
    for table in TABLE_ORDER:
        changes = diff[table]
        upserts = changes["upserts"]
        deletes = changes["deletes"]
        operations += len(upserts) + len(deletes)
        payload_bytes += len(
            json.dumps(
                {"table": table, "upserts": upserts, "deletes": deletes},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return operations, payload_bytes


def should_use_incremental(operation_count: int, payload_bytes: int) -> bool:
    return (
        0 < operation_count <= MAX_INCREMENTAL_OPERATIONS
        and 0 < payload_bytes <= MAX_INCREMENTAL_PAYLOAD_BYTES
    )


def _write_baseline(current_dir: Path | str, baseline_dir: Path | str) -> None:
    """Persist a complete baseline only after the remote sync succeeds."""
    current_dir = Path(current_dir)
    baseline_dir = Path(baseline_dir)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    marker = baseline_dir / ".complete"
    marker.unlink(missing_ok=True)
    for name in SNAPSHOT_FILES:
        source = current_dir / name
        if not source.is_file():
            raise ValueError(f"current snapshot is missing {name}")
        temporary = baseline_dir / f".{name}.tmp"
        shutil.copyfile(source, temporary)
        os.replace(temporary, baseline_dir / name)
    marker_temp = baseline_dir / ".complete.tmp"
    marker_temp.write_text("ok\n", encoding="utf-8")
    os.replace(marker_temp, marker)


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
        raise SiteSyncHTTPError(
            url,
            response.status_code,
            str(body.get("message", "unknown error")),
        )
    if body.get("ok") is False:
        raise RuntimeError(f"{url} failed: {body.get('message', 'unknown error')}")
    return body


def _patch_batches(
    upserts: list[object],
    deletes: list[object],
) -> list[tuple[list[object], list[object]]]:
    batches: list[tuple[list[object], list[object]]] = []
    upsert_index = 0
    delete_index = 0
    while upsert_index < len(upserts) or delete_index < len(deletes):
        remaining = PATCH_BATCH_SIZE
        upsert_batch = upserts[upsert_index : upsert_index + remaining]
        upsert_index += len(upsert_batch)
        remaining -= len(upsert_batch)
        delete_batch = deletes[delete_index : delete_index + remaining]
        delete_index += len(delete_batch)
        batches.append((upsert_batch, delete_batch))
    return batches


def import_incremental(
    base_url: str,
    token: str,
    base_version: str,
    version: str,
    tables: dict[str, int],
    diff: dict[str, dict[str, list[object]]],
    on_message: LogCallback | None = None,
    request_json_fn: Callable[
        [requests.Session, str, str, dict[str, object]], dict[str, object]
    ] = request_json,
) -> None:
    """Apply a small row-level change set with an atomic Worker commit."""
    base_url = base_url.rstrip("/")
    session = requests.Session()
    changes = {
        table: {
            "upserts": len(diff[table]["upserts"]),
            "deletes": len(diff[table]["deletes"]),
        }
        for table in TABLE_ORDER
    }
    start_result = request_json_fn(
        session,
        f"{base_url}/api/admin/patch/start",
        token,
        {
            "version": version,
            "base_version": base_version,
            "tables": tables,
            "changes": changes,
        },
    )
    if start_result.get("status") == "ready":
        _emit(on_message, f"站点增量版本 {version} 已经同步")
        return

    for table in TABLE_ORDER:
        for upserts, deletes in _patch_batches(
            diff[table]["upserts"], diff[table]["deletes"]
        ):
            request_json_fn(
                session,
                f"{base_url}/api/admin/patch",
                token,
                {
                    "version": version,
                    "table": table,
                    "upserts": upserts,
                    "deletes": deletes,
                },
            )

    request_json_fn(
        session,
        f"{base_url}/api/admin/patch/commit",
        token,
        {"version": version},
    )
    _emit(on_message, f"站点增量版本 {version} 已完成切换")


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
    output_dir = Path(output_dir)
    manifest = export_d1_seed(database_path, output_dir, on_message=on_message)
    baseline_dir = _baseline_dir(output_dir)
    previous_manifest: dict[str, object] | None = None
    try:
        previous_manifest, _ = _read_snapshot(baseline_dir)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        _emit(on_message, "未找到可用的站点同步基线，将执行完整同步。")

    current_version = str(manifest["version"])
    if previous_manifest and previous_manifest.get("version") == current_version:
        _emit(on_message, "本地数据没有变化，跳过站点上传。")
        return {
            **manifest,
            "sync_mode": "skipped",
            "changed_rows": 0,
        }

    mode = "full"
    changed_rows = 0
    if previous_manifest:
        try:
            diff = snapshot_diff(output_dir, baseline_dir)
            changed_rows, payload_bytes = incremental_change_stats(diff)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            diff = None
            payload_bytes = 0

        if diff is not None and (changed_rows == 0 or should_use_incremental(changed_rows, payload_bytes)):
            if changed_rows == 0:
                _emit(on_message, "本地数据指纹发生变化但没有可上传的行变更，将执行完整同步。")
            else:
                _emit(on_message, f"检测到 {changed_rows} 行变更，执行增量同步。")
                try:
                    import_incremental(
                        base_url,
                        token,
                        str(previous_manifest["version"]),
                        current_version,
                        {
                            table: int(manifest["tables"][table])  # type: ignore[index]
                            for table in TABLE_ORDER
                        },
                        diff,
                        on_message=on_message,
                    )
                    mode = "incremental"
                except SiteSyncHTTPError as exc:
                    if exc.status_code not in (404, 405, 409):
                        raise
                    _emit(on_message, "增量同步基线不匹配或站点尚未支持增量接口，改为完整同步。")
        else:
            _emit(on_message, "变更量较大或快照结构不兼容，执行完整同步。")

    if mode == "full":
        import_snapshot(base_url, token, output_dir, on_message=on_message)

    _write_baseline(output_dir, baseline_dir)
    _emit(on_message, f"站点同步完成（{mode}）。")
    return {
        **manifest,
        "sync_mode": mode,
        "changed_rows": changed_rows,
    }
