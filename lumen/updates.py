"""Update manifest (hosted on GitHub) + app self-update."""
import os
import subprocess
import sys
import tempfile

from PyQt6.QtCore import QObject, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices

from . import __version__, config, net, versioning


class Manifest:
    """Parsed updates/manifest.json:
    {
      "app": {"version": "0.2.0", "url": "...LumenSetup-0.2.0.exe", "sha256": "...", "notes": "..."},
      "extensions": [{"id": "...", "name": "...", "version": "1.0.0", "description": "...",
                      "author": "...", "min_app": "0.2.0", "url": "...zip", "sha256": "..."}]
    }"""

    def __init__(self, data: dict):
        self.raw = data or {}
        self.app = dict(self.raw.get("app") or {})
        self.runtimes = dict(self.raw.get("runtimes") or {})
        self.extensions = {}
        for e in self.raw.get("extensions") or []:
            if isinstance(e, dict) and e.get("id") and e.get("url"):
                self.extensions[e["id"]] = dict(e)

    def runtime(self, rid):
        """Download entry for a runtime pack on this platform (packs are per-OS)."""
        from .runtimes_platform import platform_key
        e = self.runtimes.get(rid)
        if not isinstance(e, dict):
            return None
        if "url" in e:
            return e
        return e.get(platform_key())

    def app_update(self, current=__version__):
        v = self.app.get("version")
        if v and self.app.get("url") and versioning.is_newer(v, current):
            return self.app
        return None

    def extension_updates(self, installed: dict, app_version=__version__):
        """installed: id -> version. Returns manifest entries that are newer and compatible."""
        out = []
        for ext_id, ver in installed.items():
            e = self.extensions.get(ext_id)
            if e and versioning.is_newer(e.get("version"), ver) and versioning.compatible(e.get("min_app"), app_version):
                out.append(e)
        return out


class UpdateChecker(QObject):
    checked = pyqtSignal(object)   # Manifest
    failed = pyqtSignal(str)

    def __init__(self, url=None, parent=None):
        super().__init__(parent)
        self.url = url or config.MANIFEST_URL
        self.manifest = None
        self.busy = False

    def check(self):
        if self.busy:
            return
        self.busy = True
        t = net.Task(net.fetch_json, self.url)
        t.succeeded.connect(self._ok)
        t.failed.connect(self._fail)
        t.start()

    def _ok(self, data):
        self.busy = False
        try:
            self.manifest = Manifest(data)
        except Exception as e:  # malformed manifest
            self.failed.emit(f"Bad update manifest: {e}")
            return
        self.checked.emit(self.manifest)

    def _fail(self, msg):
        self.busy = False
        self.failed.emit(msg)


def can_self_update():
    """Only the installed Windows build replaces itself; source checkouts just open the release page."""
    return config.is_frozen() and sys.platform == "win32"


def installer_command(path):
    """Arguments for a silent in-place upgrade with Inno Setup (relaunches Lumen when done)."""
    return [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]


def launch_installer(path):
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(installer_command(path), close_fds=True, creationflags=flags)


def download_installer_task(entry):
    """Task that downloads the installer named in the manifest to %TEMP%."""
    name = os.path.basename(entry["url"].split("?")[0]) or f"LumenSetup-{entry.get('version', 'new')}.exe"
    dest = os.path.join(tempfile.gettempdir(), "LumenUpdate", name)
    return net.Task(net.download, entry["url"], dest, entry.get("sha256"), with_progress=True)


def open_releases_page():
    QDesktopServices.openUrl(QUrl(config.RELEASES_PAGE))
