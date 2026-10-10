"""Package every folder in extensions/ into updates/extensions/<id>-<version>.zip and list it in
updates/manifest.json (with SHA-256), ready to commit and push to GitHub.

    python tools/build_extensions.py            # all extensions
    python tools/build_extensions.py basic-filters
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lumen import config  # noqa: E402

SRC = os.path.join(ROOT, "extensions")
OUT = os.path.join(ROOT, "updates", "extensions")
MANIFEST = os.path.join(ROOT, "updates", "manifest.json")


def load_manifest(path=MANIFEST):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"app": {}, "extensions": []}


def save_manifest(data, path=MANIFEST):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data["extensions"] = sorted(data.get("extensions", []), key=lambda e: e["id"])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def zip_folder(folder, dest):
    """Byte-for-byte identical zip on every computer, so the SHA-256 in the manifest always matches.

    Files are stored, not compressed: Python on Windows (3.14+, zlib-ng) and on Linux compress differently,
    which made the same extension produce different hashes on different machines. Extensions are tiny, and
    GitHub compresses downloads anyway. Timestamps, permissions and the "made on" OS are fixed too."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:
        for base, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
            for name in sorted(files):
                if name.endswith((".pyc", ".pyo")) or name.startswith("."):
                    continue
                full = os.path.join(base, name)
                arc = os.path.relpath(full, folder).replace(os.sep, "/")
                info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o644 << 16
                info.create_system = 3          # the default differs on Windows (0) and Linux (3)
                with open(full, "rb") as f:
                    z.writestr(info, f.read())


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def build(only=None, src=SRC, out=OUT, manifest_path=MANIFEST, base_url=None):
    base_url = (base_url or f"{config.RAW_BASE}/updates/extensions").rstrip("/")
    os.makedirs(out, exist_ok=True)
    data = load_manifest(manifest_path)
    entries = {e["id"]: e for e in data.get("extensions", [])}
    built = []
    for name in sorted(os.listdir(src)):
        folder = os.path.join(src, name)
        mpath = os.path.join(folder, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        with open(mpath, encoding="utf-8") as f:
            m = json.load(f)
        if only and m["id"] not in only:
            continue
        for old in os.listdir(out):  # drop previous versions of this extension
            if old.startswith(m["id"] + "-") and old.endswith(".zip"):
                os.remove(os.path.join(out, old))
        fname = f"{m['id']}-{m['version']}.zip"
        dest = os.path.join(out, fname)
        zip_folder(folder, dest)
        entries[m["id"]] = {
            "id": m["id"], "name": m.get("name", m["id"]), "version": m["version"],
            "description": m.get("description", ""), "author": m.get("author", ""),
            "min_app": m.get("min_app", ""), "url": f"{base_url}/{fname}",
            "sha256": sha256(dest), "size": os.path.getsize(dest),
        }
        reqs = [r if isinstance(r, str) else r.get("id") for r in m.get("requires", []) or []]
        if reqs:
            entries[m["id"]]["requires"] = [r for r in reqs if r]
        built.append(f"{m['id']} {m['version']}")
    data["extensions"] = list(entries.values())
    save_manifest(data, manifest_path)
    return built


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--base-url")
    a = ap.parse_args()
    done = build(a.ids or None, base_url=a.base_url)
    print("Packaged:", ", ".join(done) if done else "nothing")
    print(f"Updated {os.path.relpath(MANIFEST, ROOT)} - commit and push the updates/ folder to publish.")
