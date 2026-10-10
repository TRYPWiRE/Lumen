"""Platform keys used for per-OS runtime packs in updates/manifest.json."""
import sys
import platform


def platform_key():
    if sys.platform == "win32":
        return "win64"
    if sys.platform == "darwin":
        return "mac"
    return "linux64" if platform.machine() in ("x86_64", "AMD64") else "linux-" + platform.machine()
