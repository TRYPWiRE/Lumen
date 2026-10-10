"""Point updates/manifest.json at a new installer.

    python tools/release.py release/LumenSetup-0.2.0.exe [--notes "What's new"]

The installer must then be uploaded to a GitHub release tagged v<version> (publish.bat does this).
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from lumen import __version__, config  # noqa: E402
from build_extensions import load_manifest, save_manifest, sha256, MANIFEST  # noqa: E402


def set_app(installer, notes="", manifest_path=MANIFEST, version=__version__, base_url=None):
    name = os.path.basename(installer)
    base = base_url or f"https://github.com/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/download/v{version}"
    data = load_manifest(manifest_path)
    data["app"] = {"version": version, "url": f"{base.rstrip('/')}/{name}", "sha256": sha256(installer),
                   "size": os.path.getsize(installer), "notes": notes or data.get("app", {}).get("notes", "")}
    save_manifest(data, manifest_path)
    return data["app"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("installer")
    ap.add_argument("--notes", default="")
    a = ap.parse_args()
    app = set_app(a.installer, a.notes)
    print(f"Manifest now offers Lumen {app['version']} -> {app['url']}")
