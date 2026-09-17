from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import site_sync


TABLES = ("channels", "videos", "song_groups", "songs", "song_entries")


def write_snapshot(directory: Path, version: str, rows: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": site_sync.SNAPSHOT_SCHEMA_VERSION,
        "version": version,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "tables": {table: len(rows[table]) for table in TABLES},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for table in TABLES:
        (directory / f"{table}.json").write_text(json.dumps(rows[table]), encoding="utf-8")
    return manifest


def mark_complete(directory: Path) -> None:
    (directory / ".complete").write_text("ok\n", encoding="utf-8")


def dataset(prefix: str) -> dict[str, list[dict[str, object]]]:
    return {
        "channels": [{"channel_id": f"channel-{prefix}", "channel_title": f"Channel {prefix}"}],
        "videos": [{"video_id": f"video-{prefix}", "channel_id": f"channel-{prefix}", "title": f"Video {prefix}", "published_at": "2025-01-01", "url": f"https://example.test/video-{prefix}", "indexed_at": "2025-01-01"}],
        "song_groups": [{"group_key": f"group-{prefix}", "song_title": f"Song {prefix}", "artist": "Artist", "title_search": f"song {prefix}", "artist_search": "artist", "entry_count": 1, "channel_count": 1}],
        "songs": [{"id": int(prefix), "channel_id": f"channel-{prefix}", "canonical_song_title": f"Song {prefix}", "normalized_song_title": f"song {prefix}", "artist": "Artist", "group_key": f"group-{prefix}", "created_at": "2025-01-01", "updated_at": "2025-01-01"}],
        "song_entries": [{"id": int(prefix), "song_id": int(prefix), "group_key": f"group-{prefix}", "video_id": f"video-{prefix}", "timestamp_text": "0:01", "seconds": 1, "raw_song_title": f"Song {prefix}", "normalized_song_title": f"song {prefix}", "source_comment": "", "jump_url": f"https://example.test/video-{prefix}#t=1", "created_at": "2025-01-01"}],
    }


class SiteSyncTests(unittest.TestCase):
    def test_snapshot_diff_reports_changed_rows_and_deletes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline"
            current = root / "current"
            old = dataset("1")
            new = dataset("2")
            new["channels"].append({"channel_id": "channel-3", "channel_title": "Channel 3"})
            write_snapshot(baseline, "old", old)
            mark_complete(baseline)
            write_snapshot(current, "new", new)
            mark_complete(current)

            diff = site_sync.snapshot_diff(current, baseline)

            self.assertEqual(len(diff["channels"]["upserts"]), 2)
            self.assertEqual(diff["channels"]["deletes"], ["channel-1"])
            self.assertEqual(diff["videos"]["deletes"], ["video-1"])
            operations, payload_bytes = site_sync.incremental_change_stats(diff)
            self.assertGreater(operations, 0)
            self.assertTrue(site_sync.should_use_incremental(operations, payload_bytes))

    def test_incremental_import_sends_patch_batches_and_commit(self):
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_request(_session, url, _token, payload):
            calls.append((url, payload))
            if url.endswith("/patch/start"):
                return {"ok": True, "status": "loading"}
            return {"ok": True}

        diff = {table: {"upserts": [], "deletes": []} for table in TABLES}
        diff["channels"]["upserts"] = [{"channel_id": "channel-2", "channel_title": "Channel 2"}]
        diff["channels"]["deletes"] = ["channel-1"]

        site_sync.import_incremental(
            "https://site.test/",
            "secret",
            "old",
            "new",
            {table: 1 for table in TABLES},
            diff,
            request_json_fn=fake_request,
        )

        self.assertEqual([url.rsplit("/", 1)[-1] for url, _ in calls], ["start", "patch", "commit"])
        self.assertEqual(calls[1][1]["upserts"], diff["channels"]["upserts"])
        self.assertEqual(calls[1][1]["deletes"], ["channel-1"])

    def test_sync_uses_full_then_incremental_then_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "d1-seed"
            state = {"version": "v1", "rows": dataset("1")}

            def fake_export(_database_path, target, on_message=None):
                return write_snapshot(target, state["version"], state["rows"])

            full_import = Mock()
            incremental_import = Mock()
            with patch.object(site_sync, "export_d1_seed", side_effect=fake_export), patch.object(
                site_sync, "import_snapshot", full_import
            ), patch.object(site_sync, "import_incremental", incremental_import):
                first = site_sync.sync_database_to_site("db.sqlite3", "https://site.test", "secret", output_dir)
                state["version"] = "v2"
                state["rows"]["channels"][0]["channel_title"] = "Renamed Channel"
                second = site_sync.sync_database_to_site("db.sqlite3", "https://site.test", "secret", output_dir)
                third = site_sync.sync_database_to_site("db.sqlite3", "https://site.test", "secret", output_dir)

            self.assertEqual(first["sync_mode"], "full")
            self.assertEqual(second["sync_mode"], "incremental")
            self.assertEqual(third["sync_mode"], "skipped")
            full_import.assert_called_once()
            incremental_import.assert_called_once()

    def test_large_change_set_requires_full_sync(self):
        self.assertFalse(site_sync.should_use_incremental(site_sync.MAX_INCREMENTAL_OPERATIONS + 1, 1))
        self.assertFalse(site_sync.should_use_incremental(1, site_sync.MAX_INCREMENTAL_PAYLOAD_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
