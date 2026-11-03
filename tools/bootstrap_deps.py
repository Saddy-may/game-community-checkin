"""Download verified compatible wheels into this project's private dependency folder."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import sys
import time
import urllib.request
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "vendor"
TAGS = set(sys_tags())
ENV = {**default_environment(), "extra": ""}
seen = set()


def fetch_json(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=25) as response:
                return json.load(response)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


def choose(req):
    data = fetch_json("https://pypi.org/pypi/" + req.name + "/json")
    version = data["info"]["version"]
    if not req.specifier.contains(version):
        versions = sorted((Version(v) for v in data["releases"] if not Version(v).is_prerelease and req.specifier.contains(v)), reverse=True)
        if not versions:
            raise RuntimeError("No compatible release: " + req.name)
        data = fetch_json("https://pypi.org/pypi/" + req.name + "/" + str(versions[0]) + "/json")
        version = data["info"]["version"]
    for item in data["urls"]:
        if item["filename"].endswith(".whl") and not item.get("yanked"):
            _, _, _, tags = parse_wheel_filename(item["filename"])
            if TAGS.intersection(tags):
                return req, version, item, data["info"].get("requires_dist") or []
    raise RuntimeError("No compatible wheel: " + req.name)


def install(item):
    req, version, asset, deps = item
    with urllib.request.urlopen(asset["url"], timeout=45) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != asset["digests"]["sha256"]:
        raise RuntimeError("Wheel checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
        for info in wheel.infolist():
            target = (DEST / info.filename).resolve()
            if not target.is_relative_to(DEST.resolve()):
                raise RuntimeError("Invalid wheel path")
        wheel.extractall(DEST)
    print(req.name, version, flush=True)
    return deps


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    pending = [Requirement(x) for x in (sys.argv[1:] or ["playwright<2", "pyinstaller<7", "PyYAML<7"])]
    while pending:
        current, pending = pending, []
        selected = []
        for req in current:
            key = canonicalize_name(req.name)
            if key in seen or (req.marker and not req.marker.evaluate(ENV)):
                continue
            seen.add(key)
            selected.append(req)
        with ThreadPoolExecutor(max_workers=5) as pool:
            metadata = list(pool.map(choose, selected))
            dependencies = list(pool.map(install, metadata))
        for values in dependencies:
            pending.extend(Requirement(value) for value in values)


if __name__ == "__main__":
    main()
