import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as search_app
import indexer_app
from database import SongDatabase
from timeline_parser import TimelineEntry


def entry(raw_title: str, seconds: int) -> TimelineEntry:
    return TimelineEntry(
        timestamp_text=f"00:{seconds:02d}",
        seconds=seconds,
        raw_song_title=raw_title,
        normalized_song_title=raw_title.casefold(),
    )


class SearchAndLifecycleTests(unittest.TestCase):
    def test_channel_only_search_matches_all_channels_and_merges_song_identity(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        db.upsert_channel("channel-a", "Test Alpha")
        db.upsert_channel("channel-b", "Test Beta")
        db.upsert_video("video-a1", "channel-a", "歌枠 A", "2026-01-02")
        db.upsert_video("video-a2", "channel-a", "歌枠 B", "2026-01-01")
        db.upsert_video("video-b1", "channel-b", "歌枠 C", "2025-12-31")
        db.insert_song_entries("video-a1", [entry("KING", 1)], "timeline")
        db.insert_song_entries("video-a2", [entry("KING / Kanaria", 2)], "timeline")
        db.insert_song_entries("video-b1", [entry("KING / Kanaria", 3)], "timeline")

        channel_only = db.search_grouped(channel_query="Test", limit=50)
        self.assertEqual({group["channel_id"] for group in channel_only}, {"channel-a", "channel-b"})
        alpha_groups = [group for group in channel_only if group["channel_id"] == "channel-a"]
        self.assertEqual(len(alpha_groups), 1)
        self.assertEqual(len(alpha_groups[0]["entries"]), 2)

        combined = db.search_grouped(channel_query="Test", song_query="KING", limit=50)
        self.assertEqual({group["channel_id"] for group in combined}, {"channel-a", "channel-b"})
        self.assertEqual(len([group for group in combined if group["channel_id"] == "channel-a"]), 1)
        db.close()

    def test_replacing_entries_rolls_back_when_insertion_fails(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        db.upsert_channel("channel", "Test Channel")
        db.upsert_video("video", "channel", "歌枠", "2026-01-01")
        db.insert_song_entries("video", [entry("Old Song", 1)], "old timeline")

        def failing_entries():
            yield entry("New Song", 2)
            raise RuntimeError("simulated insert failure")

        with self.assertRaises(RuntimeError):
            db.replace_song_entries_for_video("video", failing_entries(), "new timeline")

        rows = db.conn.execute(
            "SELECT raw_song_title, source_comment FROM song_entries WHERE video_id = ?",
            ("video",),
        ).fetchall()
        self.assertEqual([(row["raw_song_title"], row["source_comment"]) for row in rows], [("Old Song", "old timeline")])
        db.close()

    def test_delete_channel_cascades_local_data_in_one_transaction(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        db.upsert_channel("channel-a", "Channel A")
        db.upsert_channel("channel-b", "Channel B")
        db.upsert_video("video-a", "channel-a", "歌枠 A", "2026-01-01")
        db.upsert_video("video-b", "channel-b", "歌枠 B", "2026-01-02")
        db.insert_song_entries("video-a", [entry("Old Song", 1)], "timeline")
        db.update_backfill_cursor("channel-a", "2026-01-01", "video-a")

        deleted = db.delete_channel("channel-a")

        self.assertEqual(deleted["channel_title"], "Channel A")
        self.assertEqual(deleted["videos"], 1)
        self.assertEqual(deleted["songs"], 1)
        self.assertEqual(deleted["entries"], 1)
        self.assertIsNone(db.get_channel("channel-a"))
        self.assertIsNotNone(db.get_channel("channel-b"))
        self.assertIsNone(db.get_video_index_state("video-a"))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0], 0)
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM song_entries").fetchone()[0], 0)
        self.assertIsNone(db.get_backfill_state("channel-a"))
        db.close()

    def test_delete_channel_rolls_back_when_a_child_delete_fails(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        db.upsert_channel("channel", "Channel")
        db.upsert_video("video", "channel", "歌枠", "2026-01-01")
        db.insert_song_entries("video", [entry("Song", 1)], "timeline")
        db.conn.execute(
            """
            CREATE TRIGGER block_video_delete
            BEFORE DELETE ON videos
            BEGIN
                SELECT RAISE(ABORT, 'blocked for test');
            END
            """
        )
        db.conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            db.delete_channel("channel")

        self.assertIsNotNone(db.get_channel("channel"))
        self.assertIsNotNone(db.get_video_index_state("video"))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM song_entries").fetchone()[0], 1)
        db.close()

    def test_search_clients_are_not_expired_by_heartbeat_gap(self):
        with search_app.active_clients_lock:
            search_app.active_clients.clear()
            search_app.active_clients["old-client"] = 0.0
        try:
            self.assertTrue(search_app.has_active_clients())
        finally:
            with search_app.active_clients_lock:
                search_app.active_clients.clear()

    def test_setup_tool_refuses_exit_while_indexing(self):
        with indexer_app.job_lock:
            previous = indexer_app.job_state["running"]
            indexer_app.job_state["running"] = True
        try:
            client = indexer_app.app.test_client()
            client.get("/")
            shutdown_response = client.post("/shutdown")
            close_response = client.get("/shutdown-close")
            self.assertEqual(shutdown_response.status_code, 409)
            self.assertEqual(close_response.status_code, 409)
        finally:
            with indexer_app.job_lock:
                indexer_app.job_state["running"] = previous

    def test_local_management_requires_session_and_get_close_is_safe(self):
        client = indexer_app.app.test_client()
        self.assertEqual(client.post("/shutdown").status_code, 403)
        self.assertEqual(client.get("/shutdown-close").status_code, 403)

        client.get("/")
        with patch.object(indexer_app, "force_shutdown") as force_shutdown:
            response = client.get("/shutdown-close")
            self.assertEqual(response.status_code, 200)
            force_shutdown.assert_not_called()

    def test_search_management_requires_session_and_get_close_is_safe(self):
        previous_schema_ready = search_app.SCHEMA_READY
        search_app.SCHEMA_READY = False
        try:
            with tempfile.TemporaryDirectory() as directory:
                db_path = Path(directory) / "search.sqlite3"
                with patch.object(search_app, "get_database_path", return_value=db_path):
                    client = search_app.app.test_client()
                    self.assertEqual(client.post("/shutdown").status_code, 403)
                    self.assertEqual(client.get("/").status_code, 200)
                    with patch.object(search_app, "force_shutdown") as force_shutdown:
                        response = client.get("/shutdown-close")
                        self.assertEqual(response.status_code, 200)
                        force_shutdown.assert_not_called()
        finally:
            search_app.SCHEMA_READY = previous_schema_ready

    def test_api_key_save_preserves_env_and_updates_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            app_dir = Path(directory)
            env_path = app_dir / ".env"
            env_path.write_text(
                "# keep this comment\nOTHER_SETTING=keep\nYOUTUBE_API_KEY=old-key\n",
                encoding="utf-8",
            )
            with patch.object(indexer_app, "get_app_dir", return_value=app_dir):
                with patch.dict(os.environ, {"YOUTUBE_API_KEY": "old-key"}, clear=False):
                    indexer_app.write_env_api_key("new-key")
                    self.assertEqual(os.environ["YOUTUBE_API_KEY"], "new-key")
            content = env_path.read_text(encoding="utf-8")
            self.assertIn("# keep this comment\n", content)
            self.assertIn("OTHER_SETTING=keep\n", content)
            self.assertIn("YOUTUBE_API_KEY=new-key\n", content)
            self.assertNotIn("YOUTUBE_API_KEY=old-key", content)

    def test_indexer_initialization_failure_marks_job_finished(self):
        class BrokenDatabase:
            def __init__(self, _path):
                pass

            def init_schema(self):
                raise RuntimeError("数据库初始化失败")

            def close(self):
                pass

        indexer_app.reset_job_state()
        with indexer_app.job_lock:
            indexer_app.job_state["running"] = True
        try:
            with patch.object(indexer_app, "SongDatabase", BrokenDatabase):
                indexer_app.run_index_job("key", "channel", 1, 1, False, "incremental", False)
            with indexer_app.job_lock:
                self.assertFalse(indexer_app.job_state["running"])
                self.assertTrue(indexer_app.job_state["done"])
                self.assertFalse(indexer_app.job_state["ok"])
                self.assertIn("数据库初始化失败", indexer_app.job_state["message"])
        finally:
            indexer_app.reset_job_state()


if __name__ == "__main__":
    unittest.main()
