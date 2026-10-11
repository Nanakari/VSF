"""Exercise frozen-app shutdown timing without starting threads or exiting tests."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import app as search_app
import indexer_app


class PortableLifecycleTests(unittest.TestCase):
    def exercise(self, module, scenario):
        with ExitStack() as stack:
            stack.enter_context(patch.object(module, "AUTO_EXIT_ENABLED", True))
            stack.enter_context(patch.object(module, "active_clients", {}))
            stack.enter_context(patch.object(module, "clients_idle_since", None, create=True))
            stack.enter_context(patch.object(module, "shutdown_timer", None))
            clock = stack.enter_context(patch.object(module.time, "monotonic", return_value=100.0))
            schedule = stack.enter_context(patch.object(module, "schedule_shutdown_check"))
            shutdown = stack.enter_context(patch.object(module.os, "_exit"))
            if module is indexer_app:
                busy = stack.enter_context(patch.object(module, "is_index_job_running", return_value=False))
            else:
                busy = None
            client = module.app.test_client()
            client.set_cookie(module.LOCAL_SESSION_COOKIE, module.LOCAL_SESSION_TOKEN)
            def post(path, name):
                self.assertEqual(client.post(path, json={"client_id": name}).status_code, 204)
            scenario(module, post, clock, schedule, shutdown, busy)

    def test_existing_timer_cannot_exit_during_page_navigation(self):
        def scenario(module, post, clock, schedule, shutdown, busy):
            post('/client-ping', 'old-page')
            clock.return_value = 102.99
            post('/client-close', 'old-page')
            clock.return_value = 103.0
            module.shutdown_if_still_idle()
            shutdown.assert_not_called()
            post('/client-ping', 'next-page')
            clock.return_value = 110.0
            module.shutdown_if_still_idle()
            shutdown.assert_not_called()
            post('/client-close', 'next-page')
            clock.return_value = 112.99
            module.shutdown_if_still_idle()
            shutdown.assert_not_called()
            clock.return_value = 113.01
            module.shutdown_if_still_idle()
            shutdown.assert_called_once_with(0)
        for module in (search_app, indexer_app):
            with self.subTest(module=module.__name__):
                self.exercise(module, scenario)

    def test_another_tab_keeps_app_alive_until_last_tab_closes(self):
        def scenario(module, post, clock, schedule, shutdown, busy):
            post('/client-ping', 'first')
            post('/client-ping', 'second')
            post('/client-close', 'first')
            clock.return_value = 200.0
            module.shutdown_if_still_idle()
            shutdown.assert_not_called()
            post('/client-close', 'second')
            clock.return_value = 203.01
            module.shutdown_if_still_idle()
            shutdown.assert_called_once_with(0)
        for module in (search_app, indexer_app):
            with self.subTest(module=module.__name__):
                self.exercise(module, scenario)

    def test_setup_keeps_running_until_background_job_finishes(self):
        def scenario(module, post, clock, schedule, shutdown, busy):
            post('/client-ping', 'setup')
            post('/client-close', 'setup')
            busy.return_value = True
            clock.return_value = 110.0
            module.shutdown_if_still_idle()
            shutdown.assert_not_called()
            busy.return_value = False
            module.shutdown_if_still_idle()
            shutdown.assert_called_once_with(0)
        self.exercise(indexer_app, scenario)
