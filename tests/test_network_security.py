"""Secret handling at network boundaries, including rendered tracebacks."""
import logging
from pathlib import Path
import socket
import traceback
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote, quote_plus

from dotenv import dotenv_values
import requests

import indexer_app
from indexing import IndexStats
from site_sync import request_json
from youtube_client import YouTubeClient


class NetworkSecurityTests(unittest.TestCase):
    def setUp(self):
        state = patch.object(indexer_app, "job_state", dict(indexer_app.job_state))
        state.start()
        self.addCleanup(state.stop)

    def assert_safe_error(self, call, secret):
        try:
            call()
        except RuntimeError as error:
            formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            for variant in {secret, quote(secret, safe=""), quote_plus(secret)}:
                self.assertNotIn(variant, str(error))
                self.assertNotIn(variant, formatted)
            self.assertIsNone(error.__cause__)
            self.assertIsNone(error.__context__)
            return error
        self.fail("Expected a safe network error")

    def test_youtube_transport_errors_never_reach_logs_or_status_with_key(self):
        secret = "test-sensitive-value"
        for error_type in (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError):
            client = YouTubeClient(secret, max_retries=1)
            client.session = Mock()
            client.session.get.side_effect = error_type(f"failed https://example.invalid/?key={secret}")
            error = self.assert_safe_error(lambda: client._get("videos", {}), secret)
            self.assertIn(error_type.__name__, str(error))
            with self.assertLogs(indexer_app.logger, logging.INFO) as logs:
                indexer_app.finish_job(False, str(error), IndexStats())
            self.assertNotIn(secret, str(logs.output))
            self.assertNotIn(secret, str(indexer_app.job_state))

    def test_youtube_invalid_json_drops_parser_exception_chain(self):
        secret = "test-sensitive-value"
        client = YouTubeClient(secret, max_retries=1)
        client.session = Mock()
        response = client.session.get.return_value
        response.ok = True
        response.json.side_effect = ValueError(f"invalid response containing {secret}")
        self.assert_safe_error(lambda: client._get("videos", {}), secret)

    def test_real_requests_connection_failure_has_no_sensitive_chain(self):
        secret = "test/sensitive+value"
        # A bound, non-listening local socket reserves the port without a
        # server or any external request. requests still constructs its real
        # prepared URL and urllib3 exception chain.
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            client = YouTubeClient(secret, timeout=0.2, max_retries=1)
            client.session.trust_env = False
            self.addCleanup(client.session.close)
            base_url = f"http://127.0.0.1:{reserved.getsockname()[1]}"
            with patch("youtube_client.YOUTUBE_API_BASE", base_url):
                error = self.assert_safe_error(lambda: client._get("videos", {}), secret)
        with self.assertLogs(indexer_app.logger, logging.INFO) as logs:
            indexer_app.finish_job(False, str(error), IndexStats())
        self.assertNotIn(secret, str(logs.output))
        self.assertNotIn(quote(secret, safe=""), str(indexer_app.job_state))

    def test_youtube_http_errors_redact_echoed_key(self):
        secret = "test/sensitive+value"
        for json_body, echo in ((True, secret), (False, secret), (True, quote(secret, safe="")), (False, quote_plus(secret))):
            client = YouTubeClient(secret, max_retries=1)
            client.session = Mock()
            response = client.session.get.return_value
            response.ok = False
            response.status_code = 400
            response.text = f"failed key={echo}"
            if json_body:
                response.json.return_value = {"error": {"message": response.text, "errors": [{"reason": "badRequest"}]}}
            else:
                response.json.side_effect = ValueError(secret)
            error = self.assert_safe_error(lambda: client._get("videos", {}), secret)
            self.assertIn("400", str(error))

    def test_site_transport_and_http_errors_do_not_expose_token(self):
        secret = "test-sensitive-value"
        session = Mock()
        session.post.side_effect = requests.ConnectionError(f"request failed {secret}")
        self.assert_safe_error(lambda: request_json(session, "https://example.invalid/api", secret, {}), secret)
        session.post.side_effect = None
        session.post.return_value.ok = False
        session.post.return_value.status_code = 403
        session.post.return_value.json.return_value = {"message": f"rejected {secret}"}
        self.assert_safe_error(lambda: request_json(session, "https://example.invalid/api", secret, {}), secret)
        session.post.return_value.ok = True
        session.post.return_value.json.return_value = {"ok": False, "message": f"rejected {secret}"}
        self.assert_safe_error(lambda: request_json(session, "https://example.invalid/api", secret, {}), secret)

    def test_example_configuration_keeps_local_operations_offline(self):
        values = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example")
        with patch.object(indexer_app, "read_saved_site_base_url", return_value=values.get("SITE_BASE_URL", "")), \
             patch.object(indexer_app, "read_saved_site_seed_token", return_value=values.get("SITE_SEED_TOKEN", "")), \
             patch.object(indexer_app, "synchronize_site") as sync, \
             patch.object(indexer_app, "finish_job") as finish:
            url, token = indexer_app.resolve_site_sync_config("", "")
            indexer_app.complete_local_job("local operation complete", IndexStats(), url, token)
        self.assertEqual((url, token), ("", ""))
        sync.assert_not_called()
        self.assertTrue(finish.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
