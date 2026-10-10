"""Networking that never blocks the UI: small helpers run on a QThread."""
import hashlib
import json
import os
import ssl
import time
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

from . import __version__

USER_AGENT = f"Lumen/{__version__}"


class Cancelled(Exception):
    pass


def _open(url, timeout):
    if url.startswith("http"):
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}_={int(time.time())}" if url.endswith(".json") else url  # dodge CDN caching
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        ctx = ssl.create_default_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    return urllib.request.urlopen(url, timeout=timeout)  # file:// (local testing)


def fetch_json(url, timeout=10):
    with _open(url, timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, sha256=None, progress=None, cancelled=None, timeout=30):
    """Download to dest (via a .part file), verifying sha256 if given."""
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    part = dest + ".part"
    h = hashlib.sha256()
    with _open(url, timeout) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0) if hasattr(r, "headers") and r.headers else 0
        done = 0
        while True:
            if cancelled and cancelled():
                raise Cancelled()
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if sha256 and h.hexdigest().lower() != sha256.lower():
        os.remove(part)
        raise ValueError("Downloaded file failed its integrity check (SHA-256 mismatch).")
    if os.path.exists(dest):
        os.remove(dest)
    os.replace(part, dest)
    return dest


class Task(QThread):
    """Run fn(*args, progress=cb, cancelled=cb) in a thread; result/error come back as signals."""
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    _alive = set()  # keep running tasks referenced

    def __init__(self, fn, *args, with_progress=False, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.with_progress = with_progress
        self._cancel = False
        Task._alive.add(self)
        self.finished.connect(lambda: Task._alive.discard(self))

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            kw = dict(self.kwargs)
            if self.with_progress:
                kw["progress"] = lambda d, t: self.progress.emit(int(d), int(t))
                kw["cancelled"] = lambda: self._cancel
            self.succeeded.emit(self.fn(*self.args, **kw))
        except Cancelled:
            self.failed.emit("Cancelled")
        except Exception as e:  # network errors, bad JSON, etc.
            self.failed.emit(f"{type(e).__name__}: {e}")
