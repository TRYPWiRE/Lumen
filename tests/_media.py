"""Test media made on the fly: animated GIF/WebP, sprite sheets and a small video (MJPEG in AVI, no ffmpeg)."""
import struct

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QImage, QColor, QPainter

FRAME_COLORS = ["#e53935", "#43a047", "#1e88e5", "#fdd835", "#8e24aa", "#00acc1", "#fb8c00", "#6d4c41",
                "#3949ab", "#c0ca33"]


def color_frame(i, w=160, h=120):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(FRAME_COLORS[i % len(FRAME_COLORS)]))
    p = QPainter(img)
    p.fillRect(4, 4, 20, 20, QColor("white"))
    p.end()
    return img


def _jpeg(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", 95)
    return bytes(ba)


def _chunk(fourcc, data):
    pad = b"\0" if len(data) % 2 else b""
    return fourcc + struct.pack("<I", len(data)) + data + pad


def _list(kind, body):
    return b"LIST" + struct.pack("<I", len(body) + 4) + kind + body


def write_avi(path, frames, fps=10):
    """Write QImages as an MJPEG .avi that FFmpeg (inside Qt Multimedia) can decode."""
    w, h = frames[0].width(), frames[0].height()
    jpegs = [_jpeg(f) for f in frames]
    n = len(jpegs)
    usec = int(1_000_000 / fps)
    avih = struct.pack("<IIIIIIIIIIIIII", usec, max(len(j) for j in jpegs) * fps, 0, 0x10, n, 0, 1,
                       max(len(j) for j in jpegs), w, h, 0, 0, 0, 0)
    strh = struct.pack("<4s4sIHHIIIIIIIIhhhh", b"vids", b"MJPG", 0, 0, 0, 0, 1, fps, 0, n,
                       max(len(j) for j in jpegs), 0xFFFFFFFF, 0, 0, 0, w, h)
    strf = struct.pack("<IiiHH4sIiiII", 40, w, h, 1, 24, b"MJPG", w * h * 3, 0, 0, 0, 0)
    hdrl = _list(b"hdrl", _chunk(b"avih", avih) + _list(b"strl", _chunk(b"strh", strh) + _chunk(b"strf", strf)))
    movi_body = b""
    index = b""
    offset = 4
    for j in jpegs:
        c = _chunk(b"00dc", j)
        index += struct.pack("<4sIII", b"00dc", 0x10, offset, len(j))
        offset += len(c)
        movi_body += c
    body = b"AVI " + hdrl + _list(b"movi", movi_body) + _chunk(b"idx1", index)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def animated(path, n=6, w=120, h=80, fmt="GIF", transparent=True, duration=80):
    """An animated GIF/WebP: a coloured square moving on a (transparent) background."""
    from PIL import Image, ImageDraw
    frames = []
    for i in range(n):
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
        d = ImageDraw.Draw(im)
        x = int(i * (w - 30) / max(1, n - 1))
        d.rectangle([x, 20, x + 30, 50], fill=FRAME_COLORS[i % len(FRAME_COLORS)])
        frames.append(im)
    kw = {"disposal": 2} if fmt == "GIF" else {"lossless": True}
    frames[0].save(path, fmt, save_all=True, append_images=frames[1:], duration=duration, loop=0, **kw)
    return path


def sprite_sheet(path, cols=4, rows=2, cell=64):
    """A sprite sheet: each cell has a border and a different coloured blob on transparency."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for r in range(rows):
        for c in range(cols):
            x, y = c * cell, r * cell
            d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(30, 30, 30, 255), width=2)
            k = r * cols + c
            d.ellipse([x + 10 + k, y + 14, x + 40 + k, y + 44], fill=FRAME_COLORS[k % len(FRAME_COLORS)])
    im.save(path)
    return path


def photo(path, w=400, h=300, alpha=False):
    from PIL import Image
    import random
    rnd = random.Random(1)
    im = Image.new("RGBA" if alpha else "RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            v = (x * 255 // w, y * 255 // h, (x * y) % 255)
            n = rnd.randint(-20, 20)
            c = tuple(max(0, min(255, a + n)) for a in v)
            px[x, y] = c + ((255 if x > w // 4 else 0),) if alpha else c
    im.save(path)
    return path
