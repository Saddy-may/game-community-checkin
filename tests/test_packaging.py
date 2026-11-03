"""Publication privacy checks use only fake files in temporary directories."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "checkin_package_release_test_target", PROJECT / "tools/package_release.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)

SECRET = b"FAKE-PRIVATE-ACCOUNT-MUST-NOT-BE-PUBLISHED"


class PublicationPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.expected_source = set(packaging.TOP_LEVEL) | {
            "adapters/gf2.py", "adapters/kuro.py", "adapters/miyoushe.py",
            "adapters/skland.py", "adapters/tajiduo.py",
            "tests/test_fixture.py", "tools/build_release.py",
            "tools/package_release.py", "tools/fetch_icons.py",
            "tools/bootstrap_deps.py", ".github/workflows/windows-build.yml",
            "plugins/README.md", "tools/checkin.ico",
            "assets/icons/SOURCES.json", "LICENSES/upstream/example.txt",
            "LICENSES/dependencies/example/LICENSE",
        }
        for name in self.expected_source:
            self.write(self.root / name, ("public source: " + name).encode())
        self.release = self.root / "build_release/签到助手"
        self.release_files = {
            "签到助手.exe": b"fake desktop executable",
            "_runtime/python313.dll": b"fake Python runtime",
            "_runtime/playwright/driver/node.exe": b"fake browser driver",
            "adapters/gf2.py": b"fake discovered adapter",
            "plugins/README.md": b"public plugin instructions",
            "assets/icons/SOURCES.json": b"public artwork metadata",
            "assets/icons/gf2.png": b"fake optional game artwork PNG",
            "assets/icons/wuwa.JPG": b"fake optional game artwork JPG",
            "tools/checkin.ico": b"project-owned application artwork",
        }
        for name, data in self.release_files.items():
            self.write(self.release / name, data)
        # These fixtures deliberately resemble a used development checkout.
        # No content from the real data directory is read by these tests.
        for name in (
            "data/credentials.bin", "data/credentials.unreadable-old.bin",
            "data/settings.json", "data/state.json", ".research/capture.har",
            ".local-docs/maintainer-notes.md",
            "vendor/dependency/__init__.py", "_runtime/local-session.bin",
            "config.yaml", ".env", "private-notes.txt",
            "plugins/personal_plugin.py", "assets/icons/gf2.png",
            "tools/__pycache__/capture.py", "tests/__pycache__/capture.py",
        ):
            self.write(self.root / name, SECRET)
        self.root_patch = patch.object(packaging, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def run_package(self, *arguments):
        with redirect_stdout(io.StringIO()):
            packaging.main(list(arguments))

    def assert_no_secret(self, archive):
        for name in archive.namelist():
            self.assertNotIn(SECRET, archive.read(name), name)

    def test_source_archive_uses_allowlist_and_preserves_all_public_source_bytes(self):
        self.run_package("--source-only")
        archive_path = self.root / "artifacts/community-checkin-source.zip"
        with zipfile.ZipFile(archive_path) as archive:
            expected = {"community-checkin-source/" + name for name in self.expected_source}
            self.assertEqual(set(archive.namelist()), expected)
            for name in self.expected_source:
                self.assertEqual(archive.read("community-checkin-source/" + name),
                                 (self.root / name).read_bytes())
            self.assert_no_secret(archive)
        self.assertFalse((self.root / "artifacts/community-checkin-windows-x64.zip").exists())

    def test_public_portable_archive_has_corresponding_source_and_omits_game_bitmaps(self):
        self.run_package()
        with zipfile.ZipFile(self.root / "artifacts/community-checkin-windows-x64.zip") as archive:
            names = set(archive.namelist())
            for name in self.expected_source:
                archived = "签到助手/source/" + name
                self.assertIn(archived, names)
                self.assertEqual(archive.read(archived), (self.root / name).read_bytes())
            for name in self.release_files:
                archived = "签到助手/" + name
                if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg"}:
                    self.assertNotIn(archived, names)
                else:
                    self.assertIn(archived, names)
                    self.assertEqual(archive.read(archived), self.release_files[name])
            self.assert_no_secret(archive)

    def test_personal_icon_option_keeps_artwork_and_still_excludes_checkout_secrets(self):
        self.run_package("--personal-icons")
        path = self.root / "artifacts/签到助手-个人迁移-Windows-x64.zip"
        with zipfile.ZipFile(path) as archive:
            for name, data in self.release_files.items():
                self.assertEqual(archive.read("签到助手/" + name), data)
            self.assert_no_secret(archive)
            self.assertFalse(any(name.endswith("/source/assets/icons/gf2.png")
                                 for name in archive.namelist()))

    def test_checksum_file_matches_each_completed_archive(self):
        self.run_package()
        lines = (self.root / "artifacts/SHA256SUMS.txt").read_text("utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            digest, name = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256((self.root / "artifacts" / name).read_bytes()).hexdigest())

    def test_private_desktop_files_fail_closed_in_both_distribution_modes(self):
        # A dirty desktop build must be rejected, including Windows case variants.
        unsafe_names = (
            "data/credentials.bin", "DATA/credentials.bin", "vendor/capture.txt",
            ".research/capture.har", ".git/config", ".venv/session.bin",
            "__pycache__/capture.py", "source/private.py",
            ".local-docs/maintainer-notes.md", "maintainer-notes.md",
            "settings.json", "Settings.json", "state.json", "STATE.JSON",
            "config.yaml", "CONFIG.YML", ".env", ".ENV", ".env.local", ".ENV.production",
            "credentials.bin", "Credentials.BIN", "credentials.unreadable-old.bin",
        )
        for include_icons in (False, True):
            for name in unsafe_names:
                with self.subTest(name=name, personal_icons=include_icons):
                    path = self.release / name
                    self.write(path, SECRET)
                    try:
                        with self.assertRaises(RuntimeError):
                            list(packaging.portable_files(self.release, include_icons))
                    finally:
                        path.unlink()
                        # Remove empty fixture parents so later case-variant
                        # paths retain the requested spelling on Windows.
                        parent = path.parent
                        while parent != self.release:
                            try:
                                parent.rmdir()
                            except OSError:
                                break
                            parent = parent.parent

    def test_missing_legal_file_blocks_incomplete_source_export(self):
        (self.root / "LICENSE").unlink()
        with self.assertRaises(RuntimeError):
            packaging.source_files()

    def test_missing_game_adapter_blocks_incomplete_corresponding_source(self):
        (self.root / "adapters/skland.py").unlink()
        with self.assertRaises(RuntimeError):
            packaging.source_files()


if __name__ == "__main__":
    unittest.main()
