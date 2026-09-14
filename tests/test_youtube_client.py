import unittest
from unittest.mock import patch

import requests

from youtube_client import CommentsDisabledError, YouTubeAPIError, YouTubeClient


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class YouTubeRetryTests(unittest.TestCase):
    def test_transient_http_error_is_retried(self):
        session = FakeSession(
            [
                FakeResponse(503, {"error": {"message": "temporarily unavailable"}}),
                FakeResponse(200, {"items": [{"id": "ok"}]}),
            ]
        )
        client = YouTubeClient("key", max_retries=3)
        client.session = session
        with patch("youtube_client.time.sleep") as sleep:
            result = client._get("videos", {"id": "ok"})
        self.assertEqual(result["items"][0]["id"], "ok")
        self.assertEqual(session.calls, 2)
        sleep.assert_called_once()

    def test_terminal_http_error_is_not_retried(self):
        session = FakeSession(
            [FakeResponse(400, {"error": {"errors": [{"reason": "badRequest"}], "message": "bad"}})]
        )
        client = YouTubeClient("key", max_retries=3)
        client.session = session
        with patch("youtube_client.time.sleep") as sleep:
            with self.assertRaises(YouTubeAPIError):
                client._get("videos", {"id": "bad"})
        self.assertEqual(session.calls, 1)
        sleep.assert_not_called()

    def test_comments_disabled_is_skipped_without_retry(self):
        session = FakeSession(
            [
                FakeResponse(
                    403,
                    {
                        "error": {
                            "errors": [{"reason": "commentsDisabled"}],
                            "message": "comments disabled",
                        }
                    },
                )
            ]
        )
        client = YouTubeClient("key", max_retries=3)
        client.session = session
        with patch("youtube_client.time.sleep") as sleep:
            with self.assertRaises(CommentsDisabledError):
                client._get("commentThreads", {"videoId": "video"})
        self.assertEqual(session.calls, 1)
        sleep.assert_not_called()

    def test_network_error_is_retried(self):
        session = FakeSession(
            [
                requests.ConnectionError("connection reset"),
                FakeResponse(200, {"ok": True}),
            ]
        )
        client = YouTubeClient("key", max_retries=2)
        client.session = session
        with patch("youtube_client.time.sleep") as sleep:
            result = client._get("channels", {})
        self.assertTrue(result["ok"])
        self.assertEqual(session.calls, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
