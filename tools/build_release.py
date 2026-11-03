from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))
import PyInstaller.__main__

args = [str(ROOT / "app.py"), "--noconfirm", "--onedir", "--windowed", "--name", "签到助手",
        "--contents-directory", "_runtime", "--distpath", str(ROOT / "build_release"),
        "--workpath", str(ROOT / "build" / "work"), "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT / "vendor"), "--paths", str(ROOT), "--collect-all", "playwright", "--collect-all", "customtkinter",
        "--exclude-module", "numpy"]
for name in ("adapters.gf2", "adapters.kuro", "adapters.miyoushe", "adapters.skland", "adapters.tajiduo", "requests", "yaml"):
    args.extend(["--hidden-import", name])
icon = ROOT / "tools" / "checkin.ico"
if icon.exists():
    args.extend(["--icon", str(icon)])
PyInstaller.__main__.run(args)
source = ROOT / "build_release" / "签到助手"
for folder in ("adapters", "assets"):
    shutil.copytree(ROOT / folder, source / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_preview.png"))
(source / "plugins").mkdir(exist_ok=True)
shutil.copy2(ROOT / "plugins" / "README.md", source / "plugins" / "README.md")
(source / "tools").mkdir(exist_ok=True)
if icon.exists():
    shutil.copy2(icon, source / "tools" / "checkin.ico")
for name in ("使用说明.md", "SOURCES.md", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "DEPENDENCY_LICENSES.md", "VALIDATION.md"):
    if (ROOT / name).is_file():
        shutil.copy2(ROOT / name, source / name)
if (ROOT / "LICENSES").is_dir():
    shutil.copytree(ROOT / "LICENSES", source / "LICENSES", dirs_exist_ok=True)
print("Desktop build ready:", source / "签到助手.exe")
