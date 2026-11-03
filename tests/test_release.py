"""Validate release-folder assembly with a fake packager; no EXE is built/run."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from checkin_core import Registry


class ReleaseAssemblyTests(unittest.TestCase):
    def test_release_contains_discoverable_external_modules_and_icons(self):
        build_script = Path(__file__).resolve().parents[1] / "tools" / "build_release.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("tools", "adapters", "assets/icons", "plugins"):
                (root / folder).mkdir(parents=True, exist_ok=True)
            (root / "app.py").write_text("# fake application entry", "utf-8")
            for name in ("使用说明.md", "SOURCES.md"):
                (root / name).write_text("release documentation", "utf-8")
            (root / "tools/checkin.ico").write_bytes(b"fake-icon")
            (root / "assets/icons/demo.png").write_bytes(b"fake-png-artwork")
            (root / "plugins/README.md").write_text("plugin guide", "utf-8")
            (root / "adapters/demo.py").write_text(
                "from checkin_core import RunResult\n"
                "class Demo:\n id='demo'\n name='Demo'\n platform='demo'\n site='https://example.com/'\n"
                " def run(self,ctx):return RunResult('success','done')\nMODULES=[Demo()]\n", "utf-8")
            package = types.ModuleType("PyInstaller")
            package.__path__ = []
            packager = types.ModuleType("PyInstaller.__main__")
            def fake_build(arguments):
                target = Path(arguments[arguments.index("--distpath") + 1]) / "签到助手"
                (target / "_runtime").mkdir(parents=True)
                (target / "_runtime/fake-runtime.dat").write_bytes(b"runtime")
                (target / "签到助手.exe").write_bytes(b"fake-executable")
            packager.run = fake_build
            package.__main__ = packager
            source = build_script.read_text("utf-8")
            with patch.dict(sys.modules, {"PyInstaller": package, "PyInstaller.__main__": packager}), \
                 patch.object(sys, "path", list(sys.path)):
                exec(compile(source, str(build_script), "exec"),
                     {"__file__": str(root / "tools/build_release.py"), "__name__": "__main__"})
            release = root / "build_release/签到助手"
            registry = Registry().discover(release / "adapters", release / "plugins")
            self.assertEqual(registry.errors, [])
            self.assertIn("demo", registry.modules, "The release directory must retain filesystem-discovered game modules")
            self.assertEqual((release / "assets/icons/demo.png").read_bytes(), b"fake-png-artwork")
            self.assertTrue((release / "plugins/README.md").is_file())
            self.assertFalse((release / "data").exists(), "Personal login/state data must not be copied into a clean release")
            self.assertFalse((release / "vendor").exists(), "The executable release must not depend on source-only vendor libraries")


if __name__ == "__main__":
    unittest.main()
