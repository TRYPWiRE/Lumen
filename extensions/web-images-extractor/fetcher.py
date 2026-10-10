"""Image downloading that looks like the embedded browser (same user agent, cookies and referer),
so hot-link-protected images still download."""
import base64
import threading
import urllib.error
import urllib.request
from urllib.parse import unquote_to_bytes, urlparse

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QImage, QImageReader

MAX_BYTES = 60 * 1024 * 1024


def decode_data_uri(uri):
    header, _, payload = uri.partition(",")
    if header.endswith(";base64"):
        return base64.b64decode(payload)
    return unquote_to_bytes(payload)


def _qbytes(value):
    try:
        return bytes(value.data()).decode("utf-8", "ignore")
    except AttributeError:
        return str(value)


class Fetcher:
    def __init__(self):
        self.user_agent = ""
        self.referer = ""
        self._cookies = {}           # (domain, name) -> value
        self._cache = {}
        self._lock = threading.Lock()

    def add_cookie(self, cookie):
        try:
            self._cookies[(cookie.domain(), _qbytes(cookie.name()))] = _qbytes(cookie.value())
        except Exception:
            pass

    def clear_cache(self):
        with self._lock:
            self._cache.clear()

    def headers(self, url):
        h = {"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
        if self.user_agent:
            h["User-Agent"] = self.user_agent
        if self.referer:
            h["Referer"] = self.referer
        host = (urlparse(url).hostname or "").lower()
        jar = []
        for (domain, name), value in list(self._cookies.items()):
            d = (domain or "").lower().lstrip(".")
            if d and (host == d or host.endswith("." + d)):
                jar.append(f"{name}={value}")
        if jar:
            h["Cookie"] = "; ".join(jar)
        return h

    def get(self, url):
        with self._lock:
            if url in self._cache:
                return self._cache[url]
        if url.startswith("data:"):
            data = decode_data_uri(url)
        else:
            req = urllib.request.Request(url, headers=self.headers(url))
            chunks, total = [], 0
            try:
                r = urllib.request.urlopen(req, timeout=25)
            except urllib.error.HTTPError as e:
                e.close()
                raise ValueError(f"HTTP {e.code} {e.reason}") from None
            with r:
                while True:
                    c = r.read(65536)
                    if not c:
                        break
                    chunks.append(c)
                    total += len(c)
                    if total > MAX_BYTES:
                        raise ValueError("Image is larger than 60 MB")
            data = b"".join(chunks)
        with self._lock:
            self._cache[url] = data
        return data


def probe(data):
    """(first-frame QImage, format name, frame count) from raw bytes."""
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setAutoTransform(True)
    fmt = bytes(reader.format()).decode().upper() or "IMAGE"
    frames = max(1, reader.imageCount())
    img = reader.read()
    if img.isNull():
        img = QImage.fromData(QByteArray(data))
    if img.isNull():
        raise ValueError("Unsupported or damaged image")
    return img, {"JPG": "JPEG"}.get(fmt, fmt), frames


def suggested_name(url, index):
    import os
    if url.startswith("data:"):
        return f"image_{index + 1}"
    base = os.path.splitext(os.path.basename(urlparse(url).path))[0]
    return base[:60] or f"image_{index + 1}"


def extension_for(fmt):
    return {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "SVG": ".svg", "BMP": ".bmp",
            "ICO": ".ico", "AVIF": ".avif"}.get(fmt.upper(), ".img")
