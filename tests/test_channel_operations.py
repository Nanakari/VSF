"""User workflows, exercised against disposable databases and fake services."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from database import SongDatabase
import indexer_app
from indexing import run_index_channel
from site_sync import export_d1_seed
import site_sync
from test_indexing import FakeClient, video
from timeline_parser import TimelineEntry, normalize_song_title
from youtube_client import ChannelInfo, QuotaExceededError, YouTubeClient


def entry(title: str, seconds: int) -> TimelineEntry:
    return TimelineEntry(f"00:{seconds:02d}", seconds, title, normalize_song_title(title))


class ChannelDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "songs.db"
        self.db = SongDatabase(self.path)
        self.addCleanup(self.db.close)
        self.db.init_schema()
        self.db.upsert_channel("channel", "Test Channel")

    def test_unchanged_update_keeps_export_version_and_record_ids(self):
        upload = video("song", "2026-01-02", "karaoke")
        client = FakeClient([upload])
        run_index_channel(self.db, client, "@handle", 10, 20, False,
                          incremental=True, on_message=lambda _: None)
        self.db.conn.execute("UPDATE videos SET indexed_at = '2000-01-01'")
        self.db.conn.execute("UPDATE songs SET created_at = '2000-01-01', updated_at = '2000-01-01'")
        self.db.conn.execute("UPDATE song_entries SET created_at = '2000-01-01'")
        self.db.conn.commit()
        before = export_d1_seed(self.path, Path(self.temp.name) / "before")
        ids = [tuple(row) for row in self.db.conn.execute("SELECT id, song_id FROM song_entries")]

        run_index_channel(self.db, client, "channel", 10, 20, False,
                          incremental=True, on_message=lambda _: None)
        inserted = self.db.replace_song_entries_for_video(
            "song", [entry("First Song", 1), entry("Second Song", 2)], client.comment_text,
        )
        after = export_d1_seed(self.path, Path(self.temp.name) / "after")
        self.assertEqual(inserted, 0)
        self.assertEqual(after["version"], before["version"])
        self.assertEqual([tuple(row) for row in self.db.conn.execute("SELECT id, song_id FROM song_entries")], ids)
        self.assertEqual(client.comment_attempts, 1)
        self.assertEqual(self.db.get_stats()["channels"], 1)

    def test_replacement_only_removes_obsolete_entries_and_preserves_shared_songs(self):
        self.db.upsert_video("one", "channel", "karaoke", "2026-01-02")
        self.db.upsert_video("two", "channel", "karaoke", "2026-01-01")
        self.db.insert_song_entries("one", [entry("Keep Song", 1), entry("Old Song", 2)], "old")
        self.db.insert_song_entries("two", [entry("Old Song", 3)], "other")
        kept = dict(self.db.conn.execute("SELECT * FROM song_entries WHERE video_id = 'one' AND seconds = 1").fetchone())

        inserted = self.db.replace_song_entries_for_video(
            "one", [entry("Keep Song", 1), entry("New Song", 4)], "new comment",
        )
        rows = [dict(row) for row in self.db.conn.execute("SELECT * FROM song_entries WHERE video_id = 'one' ORDER BY seconds")]
        self.assertEqual(inserted, 1)
        self.assertEqual(rows[0]["id"], kept["id"])
        self.assertEqual(rows[0]["song_id"], kept["song_id"])
        self.assertEqual(rows[0]["source_comment"], "new comment")
        self.assertEqual([row["seconds"] for row in rows], [1, 4])
        self.assertEqual(self.db.get_stats()["songs"], 3)
        self.db.replace_song_entries_for_video("two", [], "")
        self.assertEqual(self.db.get_stats()["songs"], 2)
        self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_changed_metadata_is_saved_but_missing_duration_preserves_existing_value(self):
        self.db.upsert_video("one", "channel", "old", "2026-01-01", 120)
        self.db.conn.execute("UPDATE videos SET indexed_at = '2000-01-01'")
        self.db.conn.commit()
        self.db.upsert_video("one", "channel", "new", "2026-01-02")
        row = self.db.conn.execute("SELECT * FROM videos WHERE video_id = 'one'").fetchone()
        self.assertEqual((row["title"], row["published_at"], row["duration_seconds"]), ("new", "2026-01-02", 120))
        self.assertNotEqual(row["indexed_at"], "2000-01-01")

    def test_replacement_rolls_back_obsolete_deletion_when_a_later_insert_fails(self):
        self.db.upsert_video("one", "channel", "karaoke", "2026-01-01")
        self.db.insert_song_entries("one", [entry("Old Song", 1)], "old")
        before = list(self.db.conn.execute("SELECT * FROM song_entries"))
        self.db.conn.execute("""
            CREATE TRIGGER reject_new_entry BEFORE INSERT ON song_entries
            WHEN NEW.raw_song_title = 'New Song'
            BEGIN SELECT RAISE(ABORT, 'blocked for test'); END
        """)
        self.db.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.replace_song_entries_for_video("one", [entry("New Song", 2)], "new")
        self.assertEqual(list(self.db.conn.execute("SELECT * FROM song_entries")), before)
        self.assertEqual(self.db.get_stats()["songs"], 1)

    def test_incremental_include_all_recovers_older_filtered_and_discovered_uploads(self):
        uploads = [video("new", "2026-01-03", "karaoke"),
                   video("filtered", "2026-01-02", "Chat"),
                   video("discovered", "2026-01-01", "karaoke")]
        for upload, status in zip(uploads, ("indexed", "filtered", "discovered")):
            self.db.upsert_video(upload.video_id, upload.channel_id, upload.title, upload.published_at)
            self.db.mark_video_index_status(upload.video_id, status)
        client = FakeClient(uploads)
        for _ in range(2):
            run_index_channel(self.db, client, "channel", 1, 20, True,
                              incremental=True, on_message=lambda _: None)
        self.assertEqual(client.comment_attempts, 2)
        for upload in uploads:
            self.assertEqual(self.db.get_video_index_state(upload.video_id)["index_status"], "indexed")

    def test_channel_id_search_never_matches_another_channels_display_name(self):
        self.db.upsert_channel("other", "channel fan archive")
        for channel_id in ("channel", "other"):
            self.db.upsert_video(channel_id, channel_id, "karaoke", "2026-01-01")
            self.db.insert_song_entries(channel_id, [entry("KING / Kanaria", 1)], "timeline")
        groups = self.db.search_grouped(channel_query="channel")
        self.assertEqual([group["channel_id"] for group in groups], ["channel"])
        self.assertEqual(len(self.db.search_grouped(channel_query="annel")), 2)

    def test_delete_revalidates_name_and_clears_all_scan_state_before_readding(self):
        self.db.upsert_video("one", "channel", "karaoke", "2026-01-01")
        self.db.insert_song_entries("one", [entry("Song", 1)], "timeline")
        self.db.update_backfill_cursor("channel", "2026-01-01", "one")
        self.db.begin_incremental_scan("channel")
        with self.assertRaises(ValueError):
            self.db.delete_channel("channel", expected_title="Stale Name")
        self.assertIsNotNone(self.db.get_channel("channel"))
        self.db.delete_channel("channel", expected_title="Test Channel")
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM channel_incremental_state").fetchone()[0], 0)
        self.assertIsNone(self.db.get_backfill_state("channel"))
        client = FakeClient([video("one", "2026-01-01", "karaoke")])
        run_index_channel(self.db, client, "@handle", 1, 20, False,
                          incremental=True, on_message=lambda _: None)
        self.assertEqual(client.comment_attempts, 1)

    def test_export_reads_one_snapshot_during_a_concurrent_channel_deletion(self):
        self.db.conn.execute("PRAGMA journal_mode = WAL")
        self.db.upsert_video("one", "channel", "karaoke", "2026-01-01")
        self.db.insert_song_entries("one", [entry("Song", 1)], "timeline")
        writer = self.db

        class ConcurrentExportDatabase(SongDatabase):
            def search_grouped(self, **kwargs):
                groups = super().search_grouped(**kwargs)
                writer.delete_channel("channel")
                return groups

        output = Path(self.temp.name) / "concurrent-export"
        with patch.object(site_sync, "SongDatabase", ConcurrentExportDatabase):
            manifest = export_d1_seed(self.path, output)
        self.assertEqual(manifest["tables"]["channels"], 1)
        self.assertEqual(manifest["tables"]["song_entries"], 1)
        channels = json.loads((output / "channels.json").read_text(encoding="utf-8"))
        self.assertEqual(channels[0]["channel_id"], "channel")
        self.assertIsNone(self.db.get_channel("channel"))

    def test_empty_channel_backfill_finishes_and_missing_dates_resume_by_id(self):
        empty = FakeClient([])
        run_index_channel(self.db, empty, "channel", 1, 20, True,
                          backfill=True, on_message=lambda _: None)
        self.assertTrue(self.db.get_backfill_state("channel")["backfill_complete"])
        client = FakeClient([video("one", None, "karaoke"), video("two", None, "karaoke")])
        run_index_channel(self.db, client, "channel", 1, 20, True,
                          backfill=True, reset_backfill=True, on_message=lambda _: None)
        run_index_channel(self.db, client, "channel", 1, 20, True,
                          backfill=True, on_message=lambda _: None)
        self.assertEqual(client.comment_attempts, 2)
        self.assertTrue(self.db.get_backfill_state("channel")["backfill_complete"])


class ChannelResolutionTests(unittest.TestCase):
    def test_handle_url_uses_api_without_fetching_channel_html(self):
        client = YouTubeClient("key")
        channel = ChannelInfo("UCchannel", "Channel", "uploads")
        with patch.object(client, "_get_channel_by_handle", return_value=channel) as resolve, patch.object(
            client, "_extract_channel_id_from_channel_page", side_effect=AssertionError("unnecessary HTML request")
        ):
            self.assertEqual(client.get_channel("https://www.youtube.com/@channel/videos"), channel)
        resolve.assert_called_once_with("@channel")

    def test_quota_error_is_preserved_without_trying_another_handle(self):
        client = YouTubeClient("key")
        with patch.object(client, "_get_channel_by_handle", side_effect=QuotaExceededError("quota")) as resolve:
            with self.assertRaises(QuotaExceededError):
                client.get_channel("channel")
        resolve.assert_called_once()


class ImmediateWorker:
    def __init__(self, *, target, args, daemon):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class ChannelManagementTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "songs.db"
        self.stack.enter_context(patch.object(indexer_app, "get_database_path", return_value=self.path))
        self.stack.enter_context(patch.object(indexer_app, "get_app_dir", return_value=Path(directory)))
        self.stack.enter_context(patch.object(indexer_app, "read_saved_api_key", return_value=""))
        self.stack.enter_context(patch.object(indexer_app, "read_saved_site_base_url", return_value=""))
        self.stack.enter_context(patch.object(indexer_app, "read_saved_site_seed_token", return_value=""))
        self.stack.enter_context(patch.object(indexer_app.threading, "Thread", ImmediateWorker))
        indexer_app.reset_job_state()
        self.addCleanup(indexer_app.reset_job_state)
        db = SongDatabase(self.path)
        db.init_schema()
        db.upsert_channel("channel", "Test Channel")
        db.close()
        self.client = indexer_app.app.test_client()
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_local_only_delete_does_not_require_site_or_youtube_configuration(self):
        with patch.object(indexer_app, "sync_database_to_site") as sync:
            response = self.client.post("/delete-channel", data={"channel_id": "channel", "confirmation": "Test Channel"})
        self.assertEqual(response.status_code, 202)
        sync.assert_not_called()
        self.assertTrue(indexer_app.job_state["ok"])
        self.assertTrue(indexer_app.job_state["local_changed"])
        db = SongDatabase(self.path)
        try:
            self.assertIsNone(db.get_channel("channel"))
        finally:
            db.close()

    def test_setup_page_delivers_script_configuration_and_management_actions(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-sync-url="/sync-site"', page)
        self.assertIn('data-mode="backfill"', page)
        self.assertIn('src="/static/setup.js"', page)
        with self.client.get("/static/setup.js") as script:
            self.assertEqual(script.status_code, 200)
            self.assertIn("root.dataset.syncUrl", script.get_data(as_text=True))
            self.assertNotIn("{{", script.get_data(as_text=True))

    def test_failed_delete_sync_can_retry_without_repeating_delete_or_index(self):
        config = {"site_base_url": "https://site.test", "site_seed_token": "secret"}
        with patch.object(indexer_app, "save_site_sync_config"), patch.object(
            indexer_app, "sync_database_to_site", side_effect=RuntimeError("offline")
        ):
            response = self.client.post("/delete-channel", data={**config, "channel_id": "channel", "confirmation": "Test Channel"})
        self.assertEqual(response.status_code, 202)
        self.assertFalse(indexer_app.job_state["ok"])
        self.assertTrue(indexer_app.job_state["local_changed"])
        with patch.object(indexer_app, "save_site_sync_config"), patch.object(
            indexer_app, "sync_database_to_site", return_value={"tables": {"channels": 0}}
        ) as sync, patch.object(indexer_app, "YouTubeClient") as youtube:
            response = self.client.post("/sync-site", data=config)
        self.assertEqual(response.status_code, 202)
        sync.assert_called_once()
        youtube.assert_not_called()
        self.assertTrue(indexer_app.job_state["ok"])

    def test_sync_and_config_save_refuse_conflict_without_side_effects(self):
        indexer_app.job_state["running"] = True
        config = {"site_base_url": "https://site.test", "site_seed_token": "secret"}
        with patch.object(indexer_app, "save_site_sync_config") as save, patch.object(
            indexer_app, "sync_database_to_site"
        ) as sync:
            for endpoint in ("/sync-site", "/save-site-config"):
                self.assertEqual(self.client.post(endpoint, data=config).status_code, 409)
        save.assert_not_called()
        sync.assert_not_called()

    def test_missing_or_partial_site_configuration_cannot_start_sync(self):
        for config in ({}, {"site_base_url": "https://site.test"}):
            with self.subTest(config=config), patch.object(indexer_app, "sync_database_to_site") as sync:
                self.assertEqual(self.client.post("/sync-site", data=config).status_code, 400)
                sync.assert_not_called()
                self.assertFalse(indexer_app.job_state["running"])

    def test_quota_failure_preserves_completed_progress_and_retry_state(self):
        client = FakeClient([video("one", "2026-01-02", "karaoke"), video("two", "2026-01-01", "karaoke")])
        original = client.get_video

        def get_video(video_id):
            if video_id == "two":
                raise QuotaExceededError("quota")
            return original(video_id)

        client.get_video = get_video
        with patch.object(indexer_app, "YouTubeClient", return_value=client):
            indexer_app.run_index_job("key", "channel", 10, 20, False, "incremental", False)
        self.assertFalse(indexer_app.job_state["running"])
        self.assertFalse(indexer_app.job_state["ok"])
        self.assertEqual(indexer_app.job_state["stats"]["videos_indexed"], 1)
        self.assertEqual(indexer_app.job_state["stats"]["videos_failed"], 1)
        self.assertEqual(indexer_app.job_state["stats"]["videos_seen"], 2)
        self.assertTrue(indexer_app.job_state["local_changed"])
        db = SongDatabase(self.path)
        try:
            self.assertEqual(db.get_video_index_state("two")["index_status"], "retry")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
