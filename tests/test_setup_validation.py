from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import indexer_app
from database import SongDatabase


class SetupValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_directory = tempfile.TemporaryDirectory()
        self.app_dir = Path(self._temp_directory.name)
        self.log_path = self.app_dir / "logs" / "setup.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._reset_job_state()

    def tearDown(self) -> None:
        self._reset_job_state()
        self._temp_directory.cleanup()

    def _reset_job_state(self) -> None:
        with indexer_app.job_lock:
            indexer_app.reset_job_state()

    def _authorized_client(self):
        client = indexer_app.app.test_client()
        # GET / supplies the local session cookie.  Keep setup tests independent
        # of the repository .env while the request itself is under test.
        with patch.object(indexer_app, "read_saved_api_key", return_value=""):
            self.assertEqual(client.get("/").status_code, 200)
        return client

    def _state(self) -> dict[str, object]:
        with indexer_app.job_lock:
            return dict(indexer_app.job_state)

    def test_invalid_channel_or_mode_returns_400_without_saving_key(self):
        client = self._authorized_client()
        save_key = Mock()

        with patch.object(indexer_app, "write_env_api_key", save_key), patch.dict(
            os.environ, {"YOUTUBE_API_KEY": "old-key"}, clear=False
        ):
            missing_channel = client.post(
                "/start",
                data={"api_key": "new-key", "channel": "", "mode": "full"},
            )
            invalid_mode = client.post(
                "/start",
                data={"api_key": "new-key", "channel": "@channel", "mode": "bad"},
            )
            self.assertEqual(missing_channel.status_code, 400)
            self.assertEqual(invalid_mode.status_code, 400)
            self.assertEqual(os.environ["YOUTUBE_API_KEY"], "old-key")

        save_key.assert_not_called()
        self.assertFalse(self._state()["running"])

    def test_running_conflict_returns_409_without_saving_key(self):
        with indexer_app.job_lock:
            indexer_app.job_state["running"] = True
        client = self._authorized_client()
        save_key = Mock()

        with patch.object(indexer_app, "write_env_api_key", save_key), patch.dict(
            os.environ, {"YOUTUBE_API_KEY": "old-key"}, clear=False
        ):
            response = client.post(
                "/start",
                data={"api_key": "new-key", "channel": "@channel", "mode": "full"},
            )
            self.assertEqual(os.environ["YOUTUBE_API_KEY"], "old-key")

        self.assertEqual(response.status_code, 409)
        save_key.assert_not_called()
        self.assertTrue(self._state()["running"])

    def test_save_failure_returns_500_without_starting_or_leaking_running_state(self):
        self._reset_job_state()
        with indexer_app.job_lock:
            indexer_app.job_state.update(
                {"done": True, "ok": True, "message": "previous result", "log": ["old"]}
            )
        client = self._authorized_client()
        save_key = Mock(side_effect=OSError("read-only .env"))

        with patch.object(indexer_app, "write_env_api_key", save_key), patch.object(
            indexer_app.threading, "Thread"
        ) as thread_factory, patch.object(indexer_app.logger, "exception"):
            response = client.post(
                "/start",
                data={"api_key": "new-key", "channel": "@channel", "mode": "full"},
            )

        self.assertEqual(response.status_code, 500)
        thread_factory.assert_not_called()
        self.assertEqual(self._state()["running"], False)
        self.assertEqual(self._state()["done"], True)
        self.assertEqual(self._state()["message"], "previous result")
        save_key.assert_called_once_with("new-key")

    def test_normal_save_reserves_job_and_starts_patched_worker(self):
        class FakeWorker:
            instances: list["FakeWorker"] = []

            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self.started = False
                self.instances.append(self)

            def start(self):
                self.started = True

        client = self._authorized_client()

        with patch.object(indexer_app, "get_app_dir", return_value=self.app_dir), patch.object(
            indexer_app.threading, "Thread", FakeWorker
        ), patch.dict(os.environ, {}, clear=False):
            response = client.post(
                "/start",
                data={
                    "api_key": "new-key",
                    "channel": "@channel",
                    "mode": "backfill",
                    "reset_backfill": "on",
                    "max_videos": "3",
                    "max_comments": "4",
                    "recent_rescan_days": "5",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(FakeWorker.instances), 1)
        worker = FakeWorker.instances[0]
        self.assertTrue(worker.started)
        self.assertEqual(worker.args, ())
        self.assertEqual(worker.kwargs["target"], indexer_app.run_index_job)
        self.assertEqual(
            worker.kwargs["args"],
            ("new-key", "@channel", 3, 4, False, "backfill", True, 5),
        )
        self.assertEqual(worker.kwargs["daemon"], True)
        self.assertIn("YOUTUBE_API_KEY=new-key", (self.app_dir / ".env").read_text(encoding="utf-8"))
        self.assertTrue(self._state()["running"])

    def test_worker_start_failure_restores_non_running_state(self):
        class FailingWorker:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("thread unavailable")

        client = self._authorized_client()
        with patch.object(indexer_app, "write_env_api_key"), patch.object(
            indexer_app.threading, "Thread", FailingWorker
        ), patch.object(indexer_app.logger, "exception"):
            response = client.post(
                "/start",
                data={"api_key": "new-key", "channel": "@channel", "mode": "full"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(self._state()["running"])

    def test_delete_channel_requires_exact_confirmation_and_site_sync_config(self):
        db_path = self.app_dir / "songs.sqlite3"
        db = SongDatabase(db_path)
        db.init_schema()
        db.upsert_channel("channel", "Test Channel")
        db.close()

        with patch.object(indexer_app, "get_database_path", return_value=db_path), patch.object(
            indexer_app, "read_saved_site_base_url", return_value=""
        ), patch.object(indexer_app, "read_saved_site_seed_token", return_value=""):
            client = self._authorized_client()
            wrong = client.post(
                "/delete-channel",
                data={"channel_id": "channel", "confirmation": "wrong"},
            )
            missing_sync = client.post(
                "/delete-channel",
                data={"channel_id": "channel", "confirmation": "Test Channel"},
            )

        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(missing_sync.status_code, 400)
        db = SongDatabase(db_path)
        db.init_schema()
        self.assertIsNotNone(db.get_channel("channel"))
        db.close()

    def test_delete_channel_removes_local_data_and_starts_site_resync(self):
        class ImmediateWorker:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def start(self):
                self.kwargs["target"](*self.kwargs["args"])

        db_path = self.app_dir / "songs.sqlite3"
        db = SongDatabase(db_path)
        db.init_schema()
        db.upsert_channel("channel", "Test Channel")
        db.upsert_video("video", "channel", "歌枠", "2026-01-01")
        db.close()
        sync = Mock(return_value={"tables": {"channels": 0}})

        with patch.object(indexer_app, "get_database_path", return_value=db_path), patch.object(
            indexer_app, "get_app_dir", return_value=self.app_dir
        ), patch.object(indexer_app, "read_saved_site_base_url", return_value="https://site.test"), patch.object(
            indexer_app, "read_saved_site_seed_token", return_value="secret"
        ), patch.object(indexer_app, "sync_database_to_site", sync), patch.object(
            indexer_app.threading, "Thread", ImmediateWorker
        ):
            client = self._authorized_client()
            response = client.post(
                "/delete-channel",
                data={"channel_id": "channel", "confirmation": "Test Channel"},
            )

        self.assertEqual(response.status_code, 202)
        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[:3], (db_path, "https://site.test", "secret"))
        self.assertEqual(sync.call_args.args[3], self.app_dir / "build" / "d1-seed")
        db = SongDatabase(db_path)
        db.init_schema()
        self.assertIsNone(db.get_channel("channel"))
        db.close()
        self.assertTrue(self._state()["ok"])
        self.assertFalse(self._state()["running"])

    def test_concurrent_starts_allow_only_one_key_save_and_worker(self):
        class FakeWorker:
            instances: list["FakeWorker"] = []

            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self.instances.append(self)

            def start(self):
                pass

        first_save_entered = threading.Event()
        release_first_save = threading.Event()
        save_calls: list[str] = []
        save_calls_lock = threading.Lock()

        def save_key(api_key: str) -> None:
            with save_calls_lock:
                save_calls.append(api_key)
                first_call = len(save_calls) == 1
            if first_call:
                first_save_entered.set()
                self.assertTrue(release_first_save.wait(5))

        first_client = self._authorized_client()
        second_client = self._authorized_client()
        first_result: list[object] = []
        second_result: list[object] = []

        def post(client, key: str, result: list[object]) -> None:
            result.append(
                client.post(
                    "/start",
                    data={"api_key": key, "channel": "@channel", "mode": "full"},
                )
            )

        # Keep a reference to the real class because patching the module's
        # threading.Thread attribute also changes the shared threading module.
        real_thread = threading.Thread
        with patch.object(indexer_app, "write_env_api_key", save_key), patch.object(
            indexer_app.threading, "Thread", FakeWorker
        ):
            first_request = real_thread(target=post, args=(first_client, "first-key", first_result))
            second_request = real_thread(target=post, args=(second_client, "second-key", second_result))
            first_request.start()
            self.assertTrue(first_save_entered.wait(5))
            second_request.start()
            release_first_save.set()
            first_request.join(5)
            second_request.join(5)

        self.assertFalse(first_request.is_alive())
        self.assertFalse(second_request.is_alive())
        self.assertEqual([first_result[0].status_code, second_result[0].status_code], [200, 409])
        self.assertEqual(save_calls, ["first-key"])
        self.assertEqual(len(FakeWorker.instances), 1)
        self.assertTrue(self._state()["running"])


if __name__ == "__main__":
    unittest.main()
