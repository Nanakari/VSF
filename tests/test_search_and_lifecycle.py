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
            shutdown_response = client.post("/shutdown")
            close_response = client.get("/shutdown-close")
            self.assertEqual(shutdown_response.status_code, 409)
            self.assertEqual(close_response.status_code, 409)
        finally:
            with indexer_app.job_lock:
                indexer_app.job_state["running"] = previous

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
