"""Fetch optional publisher artwork for local display; artwork is not AGPL code."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))
from PIL import Image


def main():
    directory = ROOT / "assets" / "icons"
    entries = json.loads((directory / "SOURCES.json").read_text("utf-8"))["icons"]
    query = urllib.parse.urlencode({"id": ",".join(str(x["app_store_id"]) for x in entries), "country": "cn", "entity": "software"})
    with urllib.request.urlopen("https://itunes.apple.com/lookup?" + query, timeout=30) as response:
        metadata = {str(x["trackId"]): x for x in json.load(response)["results"]}
    for entry in entries:
        app = metadata.get(str(entry["app_store_id"]))
        if not app or app.get("bundleId") != entry["bundle_id"]:
            raise RuntimeError("Official app identity changed: " + entry["id"])
        url = app.get("artworkUrl512") or app.get("artworkUrl100")
        host = urllib.parse.urlparse(url or "").hostname or ""
        if not host.endswith(".mzstatic.com") or not url.startswith("https://"):
            raise RuntimeError("Unexpected artwork host")
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise RuntimeError("Artwork too large")
        with Image.open(io.BytesIO(raw)) as source:
            source.convert("RGBA").save(directory / (entry["id"] + ".png"))
        print(entry["name"] + "：图标已保存")


if __name__ == "__main__":
    main()
