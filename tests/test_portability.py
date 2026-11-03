"""Migration tests use fake credentials and never alter Windows scheduled tasks."""
from datetime import datetime
import json
from pathlib import Path
import queue
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from checkin_core import (AuthRequired, BEIJING, CheckinEngine, CredentialUnavailable,
                         CredentialVault, Registry, RunResult, SettingsStore)
from scheduler import task_name, task_xml


def fake_user_crypto(raw, decrypt=False):
    """Deliberately non-production encoding solely for fixture assertions."""
    if decrypt:
        if not raw.startswith(b"CURRENT-USER:"):
            raise CredentialUnavailable("Please log in under the new user")
        return raw[len(b"CURRENT-USER:"):][::-1]
    return b"CURRENT-USER:" + raw[::-1]


class CredentialMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = CredentialVault(self.root)
        self.old = self.vault.MAGIC + b"OLD-PC-ENCRYPTED-FIXTURE"
        self.vault.path.write_bytes(self.old)

    def tearDown(self):
        self.temp.cleanup()

    def test_new_pc_requests_login_then_can_save_new_login_without_deleting_old_file(self):
        with patch("checkin_core._dpapi", side_effect=fake_user_crypto):
            with self.assertRaises(AuthRequired):
                self.vault.get("demo")
            self.vault.set("demo", {"token": "new-user-test-token"})
            self.assertEqual(self.vault.get("demo"), {"token": "new-user-test-token"})
            self.assertEqual(self.vault.platforms(), ["demo"])
        backups = list(self.root.glob("credentials.unreadable-*.bin"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.old)
        self.assertNotIn(b"new-user-test-token", self.vault.path.read_bytes())

    def test_failed_new_encryption_keeps_the_existing_encrypted_file(self):
        def unavailable(raw, decrypt=False):
            if decrypt:
                raise CredentialUnavailable("Another Windows user")
            raise RuntimeError("Encryption is unavailable")
        with patch("checkin_core._dpapi", side_effect=unavailable):
            with self.assertRaises(RuntimeError):
                self.vault.set("demo", {"token": "fictional-token"})
        self.assertEqual(self.vault.path.read_bytes(), self.old)
        self.assertEqual(list(self.root.glob("credentials.unreadable-*.bin")), [])

    def test_failed_atomic_write_restores_existing_vault(self):
        with patch("checkin_core._dpapi", side_effect=fake_user_crypto), \
             patch("checkin_core._atomic_write", side_effect=PermissionError("fixture")):
            with self.assertRaises(PermissionError):
                self.vault.set("demo", {"token": "fictional-token"})
        self.assertEqual(self.vault.path.read_bytes(), self.old)

    def test_unreadable_migrated_credentials_are_login_required_not_a_retry_loop(self):
        module = types.SimpleNamespace(id="demo", name="Demo", platform="demo", site="https://example.com/", run=Mock())
        registry = Registry()
        registry.register(module)
        engine = CheckinEngine(registry, SettingsStore(self.root), self.vault, self.root)
        with patch("checkin_core._dpapi", side_effect=fake_user_crypto):
            result = engine.run()["demo"]
        self.assertEqual(result.status, "needs_login")
        module.run.assert_not_called()


class SchedulerMigrationTests(unittest.TestCase):
    def test_packaged_task_uses_this_executable_not_the_original_build_python(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "portable"
            executable = project / "签到助手.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
                xml = task_xml(project, now=datetime(2026, 11, 3, tzinfo=BEIJING), user="NEW-PC\\user")
            root = ET.fromstring(xml)
            ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
            self.assertEqual(root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns), str(executable.resolve()))
            self.assertEqual(root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns), "--headless --scheduled")
            self.assertNotIn("app.py", xml)
            self.assertNotIn("python.exe", xml.lower())

    def test_moved_directory_gets_a_distinct_task_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertNotEqual(task_name(Path(directory) / "old"), task_name(Path(directory) / "new"))

    def test_copied_enabled_setting_is_disabled_when_new_pc_has_no_registered_task(self):
        from gui import CheckinWindow
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsStore(directory)
            settings.update({"background_enabled": True})
            window = CheckinWindow.__new__(CheckinWindow)
            window._background_generation = 0
            window.project_dir = Path(directory)
            window.settings = settings
            window.background = Mock()
            window.background_hint = Mock()
            window.refresh = Mock()
            window.queue = queue.Queue()
            class ImmediateThread:
                def __init__(self, target, **kwargs):
                    self.target = target
                def start(self):
                    self.target()
            with patch("gui.background_task_exists", return_value=False), patch("gui.threading.Thread", ImmediateThread):
                window._check_background_state()
            kind, callback = window.queue.get_nowait()
            self.assertEqual(kind, "call")
            callback()
            self.assertFalse(settings.read()["background_enabled"])
            window.background.set.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
