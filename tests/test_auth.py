"""Official-login collection tests using fake browser objects; never open a browser."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # Adds the project's vendor directory before importing optional dependencies.
from auth import ALLOWED_DOMAINS, BrowserLogin, LOGIN_SITES, belongs, token_values
from checkin_core import RunResult


class FakePage:
    def __init__(self, context, store):
        self.context = context
        self.store = store
        self.url = "about:blank"
        self.pumps = 0

    def goto(self, url, **kwargs):
        self.url = url
        for headers in self.context.request_headers:
            request = types.SimpleNamespace(
                url="https://api.kurobbs.com/user/mineV2",
                all_headers=lambda value=headers: dict(value))
            self.context.handlers["request"](request)
        for payload in self.context.responses:
            response = types.SimpleNamespace(
                url="https://api.kurobbs.com/user/sdkLogin",
                json=lambda value=payload: value)
            self.context.handlers["response"](response)

    def wait_for_timeout(self, milliseconds):
        self.pumps += 1
        if self.pumps > 2:
            self.context.controller.cancel.set()
        self.context.controller.check.set()

    def evaluate(self, script):
        return dict(self.store)


class FakeContext:
    def __init__(self, store, request_headers=None, responses=None):
        self.handlers = {}
        self.pages = []
        self.store = store
        self.request_headers = request_headers or []
        self.responses = responses or []
        self.controller = None

    def on(self, event, fn):
        self.handlers[event] = fn

    def new_page(self):
        page = FakePage(self, self.store)
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, context):
        self.context = context
        self.closed = False

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        self.closed = True


class FakePlaywrightManager:
    def __init__(self, browser):
        self.value = types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda **kwargs: browser))

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        pass


class KuroLoginCollectionTests(unittest.TestCase):
    def run_fake_login(self, store, headers=None, responses=None, validate=None):
        context = FakeContext(store, headers, responses)
        browser = FakeBrowser(context)
        fake_package = types.ModuleType("playwright")
        fake_package.__path__ = []
        fake_api = types.ModuleType("playwright.sync_api")
        fake_api.sync_playwright = lambda: FakePlaywrightManager(browser)
        success, finish, message = Mock(), Mock(), Mock()
        module = types.SimpleNamespace(id="wuwa")
        controller = BrowserLogin("kuro", module, {}, message, success, finish)
        context.controller = controller
        controller._validate = validate or (lambda value: (dict(value), "valid"))
        with patch.dict(sys.modules, {"playwright": fake_package, "playwright.sync_api": fake_api}):
            controller._run()
        finish.assert_called_once()
        self.assertTrue(browser.closed)
        return controller, success, message, context

    def test_current_raw_auth_token_wins_over_nested_and_request_tokens(self):
        store = {"auth": json.dumps({"userId": "user-a", "token": "nested-token"}),
                 "auth_token": "raw-current-token", "dc": "stored-dc"}
        _, success, _, context = self.run_fake_login(store, [{"token": "captured-token", "source": "h5", "version": "3.3.2"}])
        candidate = success.call_args.args[0]
        self.assertEqual(candidate["token"], "raw-current-token")
        self.assertEqual(candidate["user_id"], "user-a")
        self.assertEqual(context.pages[0].url, "https://www.kurobbs.com/mc/home/9")

    def test_json_encoded_raw_token_is_unwrapped(self):
        _, success, _, _ = self.run_fake_login({"auth": json.dumps({"userId": 123}), "auth_token": json.dumps("raw-json-token")})
        self.assertEqual(success.call_args.args[0]["token"], "raw-json-token")
        self.assertEqual(str(success.call_args.args[0]["user_id"]), "123")

    def test_current_auth_identity_stays_paired_with_current_raw_token(self):
        store = {"auth": json.dumps({"userId": "current-user", "token": "nested-current-token"}),
                 "auth_token": "current-raw-token"}
        _, success, _, _ = self.run_fake_login(store, responses=[{"data": {"userId": "old-user", "token": "old-response-token"}}])
        candidate = success.call_args.args[0]
        self.assertEqual(candidate["token"], "current-raw-token")
        self.assertEqual(candidate["user_id"], "current-user")

    def test_observed_device_headers_take_priority_over_storage_fallback(self):
        store = {"auth": json.dumps({"userId": "user-a"}), "auth_token": "current-token",
                 "dc": "stored-dc", "distinct_id": "stored-distinct"}
        headers = [{"token": "current-token", "devcode": "request-devcode", "distinct_id": "request-distinct",
                    "source": "h5", "version": "3.3.5"}]
        _, success, _, _ = self.run_fake_login(store, headers)
        candidate = success.call_args.args[0]
        self.assertEqual(candidate["devcode"], "request-devcode")
        self.assertEqual(candidate["distinct_id"], "request-distinct")
        self.assertEqual(candidate["source"], "h5")
        self.assertEqual(candidate["version"], "3.3.5")

    def test_storage_device_id_is_used_when_no_headers_were_observed(self):
        _, success, _, _ = self.run_fake_login({"auth": json.dumps({"userId": "user-a"}),
                                              "auth_token": "current-token", "dc": "stored-dc"})
        candidate = success.call_args.args[0]
        self.assertEqual(candidate["devcode"], "stored-dc")
        self.assertEqual(candidate["distinct_id"], "stored-dc")
        self.assertEqual(candidate["source"], "h5")

    def test_cancel_during_validation_never_calls_save_callback(self):
        controller_ref = []
        def validate(candidate):
            controller_ref[0].cancel.set()
            return candidate, "valid"
        # Set the reference inside a wrapper before _run starts.
        context = FakeContext({"auth_token": "test-token"})
        browser = FakeBrowser(context)
        fake_api = types.ModuleType("playwright.sync_api")
        fake_api.sync_playwright = lambda: FakePlaywrightManager(browser)
        package = types.ModuleType("playwright")
        package.__path__ = []
        success, finish = Mock(), Mock()
        controller = BrowserLogin("kuro", types.SimpleNamespace(id="wuwa"), {}, Mock(), success, finish)
        context.controller = controller
        controller_ref.append(controller)
        controller._validate = validate
        with patch.dict(sys.modules, {"playwright": package, "playwright.sync_api": fake_api}):
            controller._run()
        success.assert_not_called()
        finish.assert_called_once()
        self.assertTrue(browser.closed)


class AuthenticationHelpersTests(unittest.TestCase):
    def test_nested_auth_json_extracts_uid_but_not_arbitrary_private_fields(self):
        data = token_values(json.dumps({"user": {"userId": 42}, "token": "test-token", "phone": "test-phone", "other": "other-private"}))
        self.assertEqual(data, {"user_id": 42, "token": "test-token"})

    def test_domain_filter_does_not_accept_similarly_named_hosts(self):
        domains = ALLOWED_DOMAINS["kuro"]
        self.assertTrue(belongs("api.kurobbs.com", domains))
        self.assertFalse(belongs("kurobbs.com.evil.example", domains))
        self.assertFalse(belongs("notkurobbs.com", domains))

    def test_validation_preserves_refresh_and_closes_session(self):
        def validate(context):
            context.save_credential({"token": "new-test-token", "user_id": "same-user"})
            return RunResult("success", "valid")
        module = types.SimpleNamespace(id="wuwa", validate=validate)
        controller = BrowserLogin("kuro", module, {}, Mock(), Mock(), Mock())
        session = Mock()
        original = {"token": "old-test-token", "user_id": "same-user"}
        with patch("requests.Session", return_value=session):
            refreshed, _ = controller._validate(original)
        self.assertEqual(refreshed, {"token": "new-test-token", "user_id": "same-user"})
        self.assertEqual(original["token"], "old-test-token")
        session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
