"""Where Lumen looks for updates and keeps user data. Change the GitHub repo here."""
import os
import sys

GITHUB_OWNER = "TRYPWiRE"
GITHUB_REPO = "Lumen"
GITHUB_BRANCH = "main"

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
MANIFEST_URL = os.environ.get("LUMEN_MANIFEST_URL", f"{RAW_BASE}/updates/manifest.json")
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# Windows installer mutex (must match installer/lumen.iss)
APP_MUTEX = "LumenImageEditorMutex"


def offline():
    """Tests set LUMEN_OFFLINE=1 so the app never auto-contacts the network."""
    return os.environ.get("LUMEN_OFFLINE") == "1"


def data_dir():
    override = os.environ.get("LUMEN_DATA_DIR")
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Lumen")
    else:
        base = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "Lumen")
    os.makedirs(base, exist_ok=True)
    return base


def extensions_dir():
    d = os.path.join(data_dir(), "extensions")
    os.makedirs(d, exist_ok=True)
    return d


def is_frozen():
    return bool(getattr(sys, "frozen", False))
