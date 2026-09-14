import unittest

from database import SongDatabase
from main import run_index_channel
from youtube_client import ChannelInfo, CommentInfo, VideoInfo, YouTubeAPIError


class FakeClient:
    def __init__(self, uploads, fail_comments_once=False):
        self.uploads = uploads
        self.fail_comments_once = fail_comments_once
        self.comment_attempts = 0

    def get_channel(self, _channel):
        return ChannelInfo("channel", "Test Channel", "uploads")

    def iter_uploads_playlist(self, _playlist, max_videos=None):
        for upload in self.uploads[:max_videos] if max_videos is not None else self.uploads:
            yield upload

    def get_video(self, video_id):
        return next(upload for upload in self.uploads if upload.video_id == video_id)

    def get_comments(self, _video_id, max_comments=None):
        self.comment_attempts += 1
        if self.fail_comments_once and self.comment_attempts == 1:
            raise YouTubeAPIError("temporary failure")
        yield CommentInfo("comment", "00:01 First Song\n00:02 Second Song", "tester", None)


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


if __name__ == "__main__":
    unittest.main()
