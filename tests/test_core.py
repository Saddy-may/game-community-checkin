"""No network, login, check-in, or Windows-task changes are made by these tests."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from checkin_core import (AlreadyRunning, AuthRequired, BEIJING, CheckinEngine,
                         CredentialVault, FileRunLock, JsonStore, Registry,
                         RunResult, SettingsStore)
from scheduler import DailyScheduler, daily_target, next_run, should_run, task_xml


class MemoryVault:
    def __init__(self):
        self.data = {"demo": {"token": "very-secret-login-token"}}

    def get(self, platform):
        return dict(self.data.get(platform, {}))

    def set(self, platform, value):
        self.data[platform] = dict(value)


class DemoModule:
    id = "demo"
    name = "示例游戏"
    platform = "demo"
    site = "https://example.com/"

    def __init__(self, status="success"):
        self.status = status
        self.calls = 0

    def run(self, context):
        self.calls += 1
        if self.status == "auth":
            raise AuthRequired("登录过期")
        if self.status == "exception":
            raise RuntimeError("token=very-secret-login-token")
        if self.status == "refresh":
            context.credential["token"] = "new-secret-login-token"
            context.save_credential(context.credential)
            return RunResult("success", "更新成功：" + context.credential["token"])
        return RunResult(self.status, "已完成" if self.status == "success" else "网络暂时不可用")


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def engine(self, module):
        registry = Registry()
        registry.register(module)
        settings = SettingsStore(self.root)
        vault = MemoryVault()
        events = []
        return CheckinEngine(registry, settings, vault, self.root, events.append), events

    def test_only_success_suppresses_same_day_execution_and_force_rechecks(self):
        module = DemoModule()
        engine, _ = self.engine(module)
        self.assertEqual(engine.run()["demo"].status, "success")
        self.assertEqual(engine.run()["demo"].status, "already_signed")
        self.assertEqual(module.calls, 1)
        engine.run(force=True)
        self.assertEqual(module.calls, 2)

    def test_changing_login_invalidates_same_day_success_but_preserves_history(self):
        module = DemoModule()
        engine, _ = self.engine(module)
        engine.run()
        self.assertIn("demo", engine.snapshot()["last_success"])
        engine.invalidate_platform("demo")
        state = engine.snapshot()
        self.assertNotIn("demo", state["last_success"])
        self.assertNotIn("demo", state["modules"])
        self.assertEqual(len(state["history"]), 1)
        engine.run()
        self.assertEqual(module.calls, 2)

    def test_old_account_finishing_after_login_change_cannot_mark_new_account_done(self):
        module = DemoModule()
        engine, _ = self.engine(module)
        def old_account_run(context):
            engine.invalidate_platform("demo")
            return RunResult("success", "old account done")
        module.run = old_account_run
        result = engine.run()["demo"]
        self.assertEqual(result.status, "skipped")
        self.assertNotIn("demo", engine.snapshot().get("last_success", {}))

    def test_old_account_refresh_cannot_overwrite_replaced_login(self):
        module = DemoModule()
        engine, _ = self.engine(module)
        def old_account_run(context):
            engine.invalidate_platform("demo")
            engine.vault.set("demo", {"token": "new-account-login"})
            context.save_credential({"token": "old-account-refreshed-login"})
            return RunResult("success", "old account done")
        module.run = old_account_run
        result = engine.run()["demo"]
        self.assertEqual(result.status, "skipped")
        self.assertEqual(engine.vault.get("demo"), {"token": "new-account-login"})

    def test_failures_and_expired_login_remain_retryable(self):
        for status in ("error", "auth"):
            module = DemoModule(status)
            engine, _ = self.engine(module)
            engine.run(force=True)
            engine.run()
            self.assertEqual(module.calls, 2)
            self.assertNotIn("demo", engine.snapshot().get("last_success", {}))

    def test_disabled_modules_do_not_make_requests(self):
        module = DemoModule()
        engine, _ = self.engine(module)
        engine.settings.set_module("demo", enabled=False)
        self.assertEqual(engine.run()["demo"].status, "skipped")
        self.assertEqual(module.calls, 0)

    def test_module_option_defaults_are_merged_with_user_options(self):
        module = DemoModule()
        module.option_defaults = {"daily": True, "count": 3}
        received = []
        module.run = lambda ctx: (received.append(dict(ctx.options)) or RunResult("success", "done"))
        engine, _ = self.engine(module)
        engine.settings.set_module("demo", options={"count": 1})
        self.assertEqual(engine.settings.options_for("demo", module.option_defaults), {"daily": True, "count": 1})
        engine.run()
        self.assertEqual(received, [{"daily": True, "count": 1}])

    def test_credential_refresh_supports_mutating_same_dict(self):
        module = DemoModule("refresh")
        engine, events = self.engine(module)
        result = engine.run()["demo"]
        self.assertTrue(result.ok)
        self.assertEqual(engine.vault.get("demo")["token"], "new-secret-login-token")
        self.assertNotIn("new-secret-login-token", result.message)
        self.assertNotIn("new-secret-login-token", json.dumps(events))
        self.assertNotIn("new-secret-login-token", (self.root / "state.json").read_text("utf-8"))

    def test_error_logs_do_not_contain_credentials(self):
        module = DemoModule("exception")
        engine, events = self.engine(module)
        result = engine.run()["demo"]
        self.assertEqual(result.status, "error")
        for value in (result.message, json.dumps(events), (self.root / "state.json").read_text("utf-8")):
            self.assertNotIn("very-secret-login-token", value)

    def test_json_parse_failure_keeps_original_file(self):
        path = self.root / "state.json"
        path.write_bytes(b"{bad json")
        with self.assertRaises(RuntimeError):
            JsonStore(path).update({"a": 1})
        self.assertEqual(path.read_bytes(), b"{bad json")

    def test_concurrent_module_settings_updates_do_not_lose_keys(self):
        settings = SettingsStore(self.root)
        errors = []
        def write(index):
            try:
                settings.set_module(f"module_{index}", enabled=False)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=write, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(settings.read()["modules"]), 12)

    def test_run_lock_blocks_another_process(self):
        lockfile = self.root / "running.lock"
        script = (
            "import sys; from checkin_core import FileRunLock,AlreadyRunning; "
            "lock=FileRunLock(sys.argv[1]); "
            "\ntry:\n lock.__enter__()\nexcept AlreadyRunning:\n sys.exit(23)\nelse:\n lock.__exit__()\n sys.exit(0)\n"
        )
        with FileRunLock(lockfile):
            result = subprocess.run([sys.executable, "-c", script, str(lockfile)],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True)
        self.assertEqual(result.returncode, 23, result.stderr.decode(errors="replace"))
        with FileRunLock(lockfile):
            pass

    def test_plugin_error_does_not_hide_valid_modules(self):
        plugins = self.root / "plugins"
        plugins.mkdir()
        (plugins / "bad.py").write_text("raise RuntimeError('bad module')", "utf-8")
        (plugins / "good.py").write_text(
            "from checkin_core import RunResult\nclass Demo:\n id='good'\n name='Good'\n platform='good'\n site='https://example.com/'\n def run(self,ctx):return RunResult('success','done')\nMODULES=[Demo()]\n", "utf-8")
        registry = Registry().discover(plugins)
        self.assertEqual(list(registry.modules), ["good"])
        self.assertEqual(len(registry.errors), 1)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI integration")
    def test_dpapi_roundtrip_is_encrypted_at_rest(self):
        vault = CredentialVault(self.root)
        value = {"token": "dpapi-test-token-never-real-credentials", "nested": {"id": 42}}
        vault.set("demo", value)
        self.assertEqual(CredentialVault(self.root).get("demo"), value)
        self.assertNotIn(value["token"].encode(), vault.path.read_bytes())
        vault.delete("demo")
        self.assertEqual(vault.get("demo"), {})


class SchedulingTests(unittest.TestCase):
    def test_daily_clock_waits_for_ten_seconds_after_midnight(self):
        self.assertFalse(should_run(datetime(2026, 11, 3, 0, 0, 9, tzinfo=BEIJING)))
        self.assertTrue(should_run(datetime(2026, 11, 3, 0, 0, 10, tzinfo=BEIJING)))
        self.assertFalse(should_run(datetime(2026, 11, 3, 1, 0, tzinfo=BEIJING), "2026-11-03"))
        self.assertTrue(should_run(datetime(2026, 11, 4, 0, 0, 10, tzinfo=BEIJING), "2026-11-03"))

    def test_scheduler_uses_beijing_day_regardless_of_host_timezone(self):
        # 16:00:09 UTC = 00:00:09 in Beijing on the next day.
        self.assertFalse(should_run(datetime(2026, 11, 2, 16, 0, 9, tzinfo=timezone.utc)))
        self.assertTrue(should_run(datetime(2026, 11, 2, 16, 0, 10, tzinfo=timezone.utc)))

    def test_scheduler_only_runs_when_enabled_and_once_each_day(self):
        calls = []
        enabled = [False]
        scheduler = DailyScheduler(lambda: calls.append(True), lambda: enabled[0])
        now = datetime(2026, 11, 3, 12, 0, tzinfo=BEIJING)
        self.assertFalse(scheduler.tick(now))
        enabled[0] = True
        self.assertTrue(scheduler.tick(now))
        self.assertFalse(scheduler.tick(now + timedelta(seconds=10)))
        self.assertFalse(scheduler.tick(datetime(2026, 11, 4, 0, 0, 9, tzinfo=BEIJING)))
        self.assertTrue(scheduler.tick(datetime(2026, 11, 4, 0, 0, 10, tzinfo=BEIJING)))
        self.assertEqual(len(calls), 2)

    def test_no_startup_catchup_can_be_selected(self):
        calls = []
        scheduler = DailyScheduler(lambda: calls.append(True), lambda: True, catch_up=lambda: False)
        self.assertFalse(scheduler.tick(datetime(2026, 11, 3, 12, 0, tzinfo=BEIJING)))
        self.assertTrue(scheduler.tick(datetime(2026, 11, 4, 0, 0, 10, tzinfo=BEIJING)))
        self.assertEqual(calls, [True])

    def test_enabling_auto_after_target_respects_disabled_catchup(self):
        calls = []
        enabled = [False]
        scheduler = DailyScheduler(lambda: calls.append(True), lambda: enabled[0], catch_up=lambda: False)
        self.assertFalse(scheduler.tick(datetime(2026, 11, 3, 0, 0, 0, tzinfo=BEIJING)))
        enabled[0] = True
        self.assertFalse(scheduler.tick(datetime(2026, 11, 3, 12, 0, tzinfo=BEIJING)))
        self.assertTrue(scheduler.tick(datetime(2026, 11, 4, 0, 0, 10, tzinfo=BEIJING)))
        self.assertEqual(calls, [True])

    def test_next_scheduled_time_rolls_to_following_day(self):
        before = datetime(2026, 11, 3, 0, 0, 9, tzinfo=BEIJING)
        at = datetime(2026, 11, 3, 0, 0, 10, tzinfo=BEIJING)
        self.assertEqual(next_run(before), at)
        self.assertEqual(next_run(at), at + timedelta(days=1))

    def test_background_task_is_current_user_opt_in_not_elevated(self):
        xml = task_xml(Path(__file__).resolve().parents[1], now=datetime(2026, 11, 3, 12, tzinfo=BEIJING), user="TEST\\user")
        root = ET.fromstring(xml)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns), "InteractiveToken")
        self.assertEqual(root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns), "LeastPrivilege")
        self.assertEqual(root.findtext("t:Settings/t:WakeToRun", namespaces=ns), "false")
        self.assertEqual(root.findtext("t:Settings/t:StartWhenAvailable", namespaces=ns), "true")
        self.assertEqual(root.findtext("t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=ns), "2026-11-03T00:00:10+08:00")
        self.assertIn("--headless --scheduled", root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns))

    def test_background_task_without_catchup_has_no_login_trigger(self):
        xml = task_xml(Path(__file__).resolve().parents[1], user="TEST\\user", catch_up=False)
        root = ET.fromstring(xml)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertIsNone(root.find("t:Triggers/t:LogonTrigger", ns))
        self.assertEqual(root.findtext("t:Settings/t:StartWhenAvailable", namespaces=ns), "false")


class AppScheduledEntryTests(unittest.TestCase):
    """Exercise the real CLI decision path with entirely fake adapters and notifier."""
    def setUp(self):
        import app
        self.app = app
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = Registry()
        self.registry.register(DemoModule())
        self.settings = SettingsStore(self.root)
        self.engine = Mock()
        self.engine.run.return_value = {"demo": RunResult("success", "done")}
        self.services = (self.root, self.registry, self.settings, MemoryVault(), self.engine)
        self.notifier = types.ModuleType("notify")
        self.notifier.notify = Mock()

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, now):
        with patch.object(self.app, "create_services", return_value=self.services), \
             patch.object(self.app, "beijing_now", return_value=now), \
             patch.dict(sys.modules, {"notify": self.notifier}):
            return self.app.main(["--headless", "--scheduled"])

    def test_background_disabled_never_calls_adapters(self):
        self.assertEqual(self.invoke(datetime(2026, 11, 3, 12, tzinfo=BEIJING)), 0)
        self.engine.run.assert_not_called()

    def test_background_waits_until_ten_seconds(self):
        self.settings.update({"background_enabled": True})
        self.assertEqual(self.invoke(datetime(2026, 11, 3, 0, 0, 9, tzinfo=BEIJING)), 0)
        self.engine.run.assert_not_called()
        self.assertEqual(self.invoke(datetime(2026, 11, 3, 0, 0, 10, tzinfo=BEIJING)), 0)
        self.engine.run.assert_called_once()

    def test_expired_login_notifies_but_does_not_request_system_retry(self):
        self.settings.update({"background_enabled": True})
        self.engine.run.return_value = {"demo": RunResult("needs_login", "重新登录")}
        self.assertEqual(self.invoke(datetime(2026, 11, 3, 0, 0, 10, tzinfo=BEIJING)), 0)
        self.notifier.notify.assert_called_once()

    def test_network_error_requests_bounded_system_retry(self):
        self.settings.update({"background_enabled": True})
        self.engine.run.return_value = {"demo": RunResult("error", "网络故障")}
        self.assertEqual(self.invoke(datetime(2026, 11, 3, 0, 0, 10, tzinfo=BEIJING)), 1)
        self.notifier.notify.assert_called_once()


class GUIAndLoginIntegrationTests(unittest.TestCase):
    def test_scheduled_run_is_not_lost_while_manual_run_is_busy(self):
        from gui import CheckinWindow
        window = CheckinWindow.__new__(CheckinWindow)
        window.busy = True
        window.pending_scheduled = False
        window.footer = Mock()
        window.run_all(source="scheduled")
        self.assertTrue(window.pending_scheduled)

    def test_browser_login_keeps_refreshed_credentials_and_closes_session(self):
        from auth import BrowserLogin
        module = DemoModule()
        def validate(context):
            context.save_credential({"token": "refreshed-test-token"})
            return RunResult("success", "valid")
        module.validate = validate
        session = Mock()
        with patch("requests.Session", return_value=session):
            login = BrowserLogin("demo", module, {}, Mock(), Mock(), Mock())
            credential, message = login._validate({"token": "expired-test-token"})
        self.assertEqual(credential, {"token": "refreshed-test-token"})
        session.close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
