import unittest
from datetime import datetime, timedelta, timezone

from database import SongDatabase
from main import run_index_channel
from youtube_client import ChannelInfo, CommentInfo, VideoInfo, YouTubeAPIError


class FakeClient:
    def __init__(
        self,
        uploads,
        fail_comments_once=False,
        fail_comments_times=0,
        fail_video_ids=None,
        comment_text="00:01 First Song\n00:02 Second Song",
    ):
        self.uploads = uploads
        self.fail_comments_once = fail_comments_once
        self.fail_comments_times = fail_comments_times
        self.fail_video_ids = set(fail_video_ids or ())
        self.failed_video_ids = set()
        self.comment_text = comment_text
        self.comment_attempts = 0

    def get_channel(self, _channel):
        return ChannelInfo("channel", "Test Channel", "uploads")

    def iter_uploads_playlist(self, _playlist, max_videos=None):
        for upload in self.uploads[:max_videos] if max_videos is not None else self.uploads:
            yield upload

    def get_video(self, video_id):
        return next(upload for upload in self.uploads if upload.video_id == video_id)

    def get_comments(self, video_id, max_comments=None):
        self.comment_attempts += 1
        if self.fail_comments_once and self.comment_attempts == 1:
            raise YouTubeAPIError("temporary failure")
        if self.comment_attempts <= self.fail_comments_times:
            raise YouTubeAPIError("repeated temporary failure")
        if video_id in self.fail_video_ids and video_id not in self.failed_video_ids:
            self.failed_video_ids.add(video_id)
            raise YouTubeAPIError("video-specific temporary failure")
        yield CommentInfo("comment", self.comment_text, "tester", None)


def video(video_id, published_at):
    return VideoInfo(video_id, video_id, "channel", "Test Channel", published_at, 120)


class IndexingTests(unittest.TestCase):
    def test_incremental_scan_does_not_stop_at_existing_video(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        db.upsert_channel("channel", "Test Channel")
        db.upsert_video("existing", "channel", "existing", "2026-01-03")
        db.mark_video_index_status("existing", "indexed")
        client = FakeClient([video("existing", "2026-01-03"), video("new", "2026-01-02")])

        stats = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)

        self.assertEqual(stats.videos_failed, 0)
        self.assertEqual(db.get_video_index_state("new")["index_status"], "indexed")
        self.assertEqual(db.get_video_index_state("existing")["index_status"], "indexed")
        db.close()

    def test_failed_comments_are_retried_on_the_next_run(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        client = FakeClient([video("retry", "2026-01-02")], fail_comments_once=True)

        first = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)
        self.assertEqual(first.videos_failed, 1)
        self.assertEqual(db.get_video_index_state("retry")["index_status"], "retry")

        second = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)
        self.assertEqual(second.videos_failed, 0)
        self.assertEqual(db.get_video_index_state("retry")["index_status"], "indexed")
        db.close()

    def test_backfill_cursor_resumes_after_a_batch(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        uploads = [video(f"v{index}", f"2026-01-0{5 - index}") for index in range(1, 5)]
        client = FakeClient(uploads)

        first = run_index_channel(db, client, "channel", 2, 20, True, backfill=True, reset_backfill=True)
        self.assertEqual(first.videos_indexed, 2)
        state = db.get_backfill_state("channel")
        self.assertEqual(state["backfill_before_video_id"], "v2")

        second = run_index_channel(db, client, "channel", 2, 20, True, backfill=True)
        self.assertEqual(second.videos_indexed, 2)
        self.assertEqual(db.get_backfill_state("channel")["backfill_complete"], 1)
        db.close()

    def test_backfill_continues_past_a_failed_video_and_keeps_retry_state(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        uploads = [video(f"v{index}", f"2026-01-0{5 - index}") for index in range(1, 5)]
        client = FakeClient(uploads, fail_video_ids={"v2"})

        stats = run_index_channel(db, client, "channel", 10, 20, True, backfill=True)

        self.assertEqual(stats.videos_failed, 1)
        self.assertEqual(stats.videos_indexed, 3)
        self.assertEqual(db.get_video_index_state("v2")["index_status"], "retry")
        self.assertEqual(db.get_backfill_state("channel")["backfill_complete"], 1)
        db.close()

    def test_repeated_failures_are_backed_off_until_due(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        client = FakeClient([video("retry", "2026-01-02")], fail_comments_times=2)

        first = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)
        self.assertEqual(first.videos_failed, 1)
        second = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)
        self.assertEqual(second.videos_failed, 1)
        self.assertEqual(client.comment_attempts, 2)

        deferred = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)
        self.assertEqual(deferred.videos_failed, 0)
        self.assertEqual(client.comment_attempts, 2)
        state = db.get_video_index_state("retry")
        self.assertEqual(state["index_attempts"], 2)
        self.assertIsNotNone(state["next_retry_at"])

        db.conn.execute(
            "UPDATE videos SET next_retry_at = datetime('now', '-1 second') WHERE video_id = 'retry'"
        )
        db.conn.commit()
        recovered = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)
        self.assertEqual(recovered.videos_failed, 0)
        self.assertEqual(db.get_video_index_state("retry")["index_status"], "indexed")
        db.close()

    def test_recent_no_timeline_video_is_rechecked_before_seven_days(self):
        db = SongDatabase(":memory:")
        db.init_schema()
        published_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        client = FakeClient(
            [video("late", published_at)],
            comment_text="",
        )

        first = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)
        self.assertEqual(first.videos_indexed, 1)
        self.assertEqual(db.get_video_index_state("late")["index_status"], "no_timeline")

        client.comment_text = "00:01 First Song\n00:02 Second Song"
        db.conn.execute(
            "UPDATE videos SET last_index_attempt_at = datetime('now', '-2 days') WHERE video_id = 'late'"
        )
        db.conn.commit()
        second = run_index_channel(db, client, "channel", 10, 20, True, incremental=True)

        self.assertEqual(second.videos_indexed, 1)
        self.assertEqual(db.get_video_index_state("late")["index_status"], "indexed")
        db.close()


if __name__ == "__main__":
    unittest.main()
