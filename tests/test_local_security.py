"""Local management boundaries; no servers or background jobs are started."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as search_app
import indexer_app


class LocalSecurityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(search_app, "SCHEMA_READY", False))
        for module in (search_app, indexer_app):
            self.stack.enter_context(patch.object(module, "get_database_path", return_value=Path(directory) / f"{module.__name__}.sqlite3"))
            self.stack.enter_context(patch.object(module, "schedule_shutdown_check"))
            self.stack.enter_context(patch.object(module, "active_clients", {}))
        for name in ("read_saved_api_key", "read_saved_site_base_url", "read_saved_site_seed_token"):
            self.stack.enter_context(patch.object(indexer_app, name, return_value=""))

    def test_untrusted_hosts_never_receive_a_session_or_reach_management(self):
        for module in (search_app, indexer_app):
            for host in ("attacker.invalid", "localhost.attacker.invalid", "127.0.0.1.attacker.invalid"):
                with self.subTest(module=module.__name__, host=host):
                    client = module.app.test_client()
                    with patch.object(module, "get_database_path") as database:
                        response = client.get("/", base_url=f"http://{host}:5001")
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn("Set-Cookie", response.headers)
                    database.assert_not_called()
                    response = client.post("/client-ping", base_url=f"http://{host}:5001",
                        headers={"X-VTuber-Session": module.LOCAL_SESSION_TOKEN, "Origin": f"http://{host}:5001"},
                        json={"client_id": "untrusted"})
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn("untrusted", module.active_clients)

    def test_loopback_hosts_and_same_origin_browser_posts_work(self):
        for module in (search_app, indexer_app):
            for host in ("localhost", "127.0.0.1", "[::1]"):
                with self.subTest(module=module.__name__, host=host):
                    client = module.app.test_client()
                    origin = f"http://{host}:5001"
                    self.assertEqual(client.get("/", base_url=origin).status_code, 200)
                    response = client.post("/client-ping", base_url=origin,
                        headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
                        json={"client_id": "trusted"})
                    self.assertEqual(response.status_code, 204)

    def test_cookie_does_not_authorize_cross_origin_posts(self):
        for module in (search_app, indexer_app):
            client = module.app.test_client()
            client.get("/")
            for headers in (
                {"Origin": "https://attacker.invalid"},
                {"Origin": "http://localhost:5001"},
                {"Origin": "http://localhost:0"},
                {"Origin": "http://127.0.0.1"},
                {"Origin": "null"},
                {"Origin": "http://localhost/path"},
                {"Sec-Fetch-Site": "cross-site"},
                {"Sec-Fetch-Site": "same-site"},
            ):
                with self.subTest(module=module.__name__, headers=headers):
                    response = client.post("/client-ping", headers=headers, json={"client_id": "untrusted"})
                    self.assertEqual(response.status_code, 403)
            self.assertNotIn("untrusted", module.active_clients)
            # Existing authenticated local clients do not have browser headers.
            self.assertEqual(client.post("/client-ping", json={"client_id": "native"}).status_code, 204)


if __name__ == "__main__":
    unittest.main()
