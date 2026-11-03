"""Export an explicit source allowlist and a portable ZIP, never personal data."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = (
    ".gitignore", ".gitattributes", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "DEPENDENCY_LICENSES.md", "SOURCES.md", "VALIDATION.md", "使用说明.md",
    "启动签到助手.vbs", "app.py", "auth.py", "checkin_core.py", "gui.py",
    "scheduler.py", "notify.py", "requirements.txt", "requirements-dev.txt",
)


def source_files():
    files = [ROOT / name for name in TOP_LEVEL]
    for folder, pattern in (("adapters", "*.py"), ("tests", "*.py"),
                            ("tools", "*.py"), ("LICENSES", "*"),
                            (".github/workflows", "*.yml")):
        files.extend(p for p in (ROOT / folder).rglob(pattern)
                     if p.is_file() and "__pycache__" not in p.parts)
    files.extend(ROOT / name for name in (
        "plugins/README.md", "tools/checkin.ico", "assets/icons/SOURCES.json",
        "adapters/gf2.py", "adapters/kuro.py", "adapters/miyoushe.py",
        "adapters/skland.py", "adapters/tajiduo.py", "tools/build_release.py",
        "tools/package_release.py", "tools/fetch_icons.py", ".github/workflows/windows-build.yml"))
    missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    if missing:
        raise RuntimeError("Required source files missing: " + ", ".join(missing))
    return sorted(set(files))


def archive_sources(path: Path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in source_files():
            archive.write(file, Path("community-checkin-source") / file.relative_to(ROOT))


def portable_files(directory: Path, include_icons=False):
    forbidden_parts = {"data", "vendor", ".research", ".git", "__pycache__", ".venv", ".local-docs", "source"}
    private_names = {"credentials.bin", "settings.json", "state.json", "config.yaml", "config.yml", ".env"}
    for file in sorted(directory.rglob("*")):
        if not file.is_file():
            continue
        relative = file.relative_to(directory)
        if len(relative.parts) == 1 and file.suffix.casefold() == ".md" and file.name not in TOP_LEVEL:
            raise RuntimeError("Unexpected document in desktop build: " + str(relative))
        if any(part.casefold() in forbidden_parts for part in relative.parts):
            raise RuntimeError("Unexpected private/source directory in desktop build: " + str(relative))
        if (file.name.casefold() in private_names
                or file.name.casefold().startswith(("credentials.", ".env."))):
            raise RuntimeError("Unexpected private configuration in desktop build: " + str(relative))
        if tuple(part.casefold() for part in relative.parts[:2]) == ("assets", "icons") and file.suffix.lower() in {".png", ".jpg", ".jpeg"} and not include_icons:
            continue
        yield file, relative


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--personal-icons", action="store_true", help="Include existing game artwork for a personal migration archive")
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args(argv)
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    sources = source_files()
    source_zip = output / "community-checkin-source.zip"
    archive_sources(source_zip)
    created = [source_zip]
    if not args.source_only:
        directory = ROOT / "build_release" / "签到助手"
        if not (directory / "签到助手.exe").is_file():
            raise RuntimeError("Build the desktop application first")
        name = "签到助手-个人迁移-Windows-x64.zip" if args.personal_icons else "community-checkin-windows-x64.zip"
        target = output / name
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file, relative in portable_files(directory, args.personal_icons):
                archive.write(file, Path("签到助手") / relative)
            for file in sources:
                archive.write(file, Path("签到助手/source") / file.relative_to(ROOT))
        created.append(target)
    checksums = []
    personal_checksums = []
    completed = [output / name for name in (
        "community-checkin-source.zip", "community-checkin-windows-x64.zip",
        "签到助手-个人迁移-Windows-x64.zip") if (output / name).is_file()]
    for path in completed:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        line = f"{digest}  {path.name}"
        if path.name == "签到助手-个人迁移-Windows-x64.zip":
            personal_checksums.append(line)
        else:
            checksums.append(line)
        if path in created:
            print(path.name, path.stat().st_size, "bytes")
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", "utf-8")
    if personal_checksums:
        (output / "SHA256SUMS-personal.txt").write_text("\n".join(personal_checksums) + "\n", "utf-8")


if __name__ == "__main__":
    main()
