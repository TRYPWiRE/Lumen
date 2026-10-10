"""Pixel-level helpers built on numpy (fast enough for real-time painting)."""
import math
import numpy as np
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QImage, QColor, QPainter, QPainterPath

PREMUL = QImage.Format.Format_ARGB32_Premultiplied
STRAIGHT = QImage.Format.Format_ARGB32


def to_working(img: QImage) -> QImage:
    if img.format() != PREMUL:
        img = img.convertToFormat(PREMUL)
    return img


class _PixelBuffer:
    """Buffer exporter that owns the QImage, so numpy views keep the pixels alive (view(img.copy()) is safe)."""
    __slots__ = ("img", "ptr")

    def __init__(self, img, ptr):
        self.img, self.ptr = img, ptr

    def __buffer__(self, flags):
        return memoryview(self.ptr)


def view(img: QImage) -> np.ndarray:
    """Writable (h, w, 4) BGRA view onto a 32-bit QImage's pixels. The array keeps `img` alive."""
    w, h = img.width(), img.height()
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    try:
        buf = _PixelBuffer(img, ptr)
        arr = np.frombuffer(buf, np.uint8)
    except TypeError:                       # Python < 3.12: no __buffer__ support (caller must keep img)
        arr = np.frombuffer(ptr, np.uint8)
    return arr.reshape(h, img.bytesPerLine() // 4, 4)[:, :w]


def to_array(img: QImage) -> np.ndarray:
    """Independent (h, w, 4) uint8 copy of the premultiplied BGRA pixels."""
    return np.array(view(to_working(img)), dtype=np.uint8)


def from_array(arr: np.ndarray, fmt=PREMUL) -> QImage:
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, 4 * w, fmt)
    return img.copy()


def straight_array(img: QImage, rect: QRect = None) -> np.ndarray:
    """Copy of the (non-premultiplied) BGRA pixels in rect."""
    part = img.copy(rect) if rect is not None else img
    part = part.convertToFormat(STRAIGHT)
    return view(part).copy()


# ------------------------------------------------------------ brush stamps
def make_stamp(diameter: float, hardness: float, hard_edge=False) -> np.ndarray:
    """uint8 alpha mask for a round brush dab."""
    diameter = max(1.0, float(diameter))
    r = diameter / 2.0
    n = int(math.ceil(diameter)) + 2
    c = n / 2.0
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    d = np.sqrt((xx + 0.5 - c) ** 2 + (yy + 0.5 - c) ** 2)
    if hard_edge:  # pencil – aliased
        a = (d <= max(r, 0.5)).astype(np.float32)
    else:
        edge = np.clip(r - d + 0.5, 0.0, 1.0)  # 1px anti-aliased rim
        hardness = min(max(hardness, 0.0), 1.0)
        if hardness >= 0.999:
            a = edge
        else:
            inner = r * hardness
            t = np.clip((d - inner) / max(r - inner, 1e-3), 0.0, 1.0)
            soft = 1.0 - t * t * (3 - 2 * t)  # smoothstep falloff
            a = np.minimum(soft, edge)
    return (a * 255 + 0.5).astype(np.uint8)


def colorize(alpha: np.ndarray, color: QColor, opacity: float = 1.0) -> QImage:
    """Premultiplied image of a flat colour shaped by an alpha mask."""
    a = alpha.astype(np.float32) * (opacity * color.alphaF() / 255.0)
    out = np.empty(alpha.shape + (4,), np.uint8)
    out[..., 0] = (color.blue() * a + 0.5).astype(np.uint8)
    out[..., 1] = (color.green() * a + 0.5).astype(np.uint8)
    out[..., 2] = (color.red() * a + 0.5).astype(np.uint8)
    out[..., 3] = (a * 255 + 0.5).astype(np.uint8)
    return from_array(out)


# ------------------------------------------------------------ flood fill
def _row_runs(row: np.ndarray):
    """Start/end (exclusive) indices of True runs in a boolean row."""
    padded = np.concatenate(([False], row, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    return starts, ends


def similar_mask(img: QImage, x: int, y: int, tolerance: int) -> np.ndarray:
    arr = straight_array(img).astype(np.int16)
    ref = arr[y, x].copy()
    diff = np.abs(arr - ref)
    if ref[3] == 0:
        # transparent seed: match on alpha only
        return diff[..., 3] <= tolerance
    return diff.max(axis=2) <= tolerance


def flood_mask(img: QImage, x: int, y: int, tolerance: int, contiguous=True) -> np.ndarray:
    mask = similar_mask(img, x, y, tolerance)
    if not contiguous:
        return mask
    h, w = mask.shape
    out = np.zeros_like(mask)
    runs = {}
    visited = {}

    def get(row):
        if row not in runs:
            runs[row] = _row_runs(mask[row])
            visited[row] = np.zeros(len(runs[row][0]), bool)
        return runs[row]

    starts, ends = get(y)
    i = int(np.searchsorted(ends, x, side="right"))
    stack = [(y, i)]
    while stack:
        row, idx = stack.pop()
        if visited[row][idx]:
            continue
        visited[row][idx] = True
        s, e = runs[row][0][idx], runs[row][1][idx]
        out[row, s:e] = True
        for nr in (row - 1, row + 1):
            if 0 <= nr < h:
                ns, ne = get(nr)
                i0 = int(np.searchsorted(ne, s, side="right"))
                i1 = int(np.searchsorted(ns, e, side="left"))
                for j in range(i0, i1):
                    if not visited[nr][j]:
                        stack.append((nr, j))
    return out


def mask_to_image(mask: np.ndarray, color: QColor, opacity=1.0) -> QImage:
    return colorize(mask.astype(np.uint8) * 255, color, opacity)


# ------------------------------------------------------------ adjustments
def invert(img: QImage) -> QImage:
    out = img.convertToFormat(STRAIGHT)
    out.invertPixels(QImage.InvertMode.InvertRgb)
    return out.convertToFormat(PREMUL)


def desaturate(img: QImage) -> QImage:
    arr = straight_array(img).astype(np.float32)
    g = arr[..., 2] * 0.299 + arr[..., 1] * 0.587 + arr[..., 0] * 0.114
    g = np.clip(g + 0.5, 0, 255).astype(np.uint8)
    out = arr.astype(np.uint8)
    out[..., 0] = g
    out[..., 1] = g
    out[..., 2] = g
    return from_array(out, STRAIGHT).convertToFormat(PREMUL)


def sample(img: QImage, x: int, y: int, size: int = 1) -> QColor:
    """Average colour of a size x size block centred on (x, y)."""
    r = size // 2
    rect = QRect(x - r, y - r, size, size).intersected(img.rect())
    if rect.isEmpty():
        return QColor()
    arr = straight_array(img, rect).reshape(-1, 4).astype(np.float64)
    a = arr[:, 3]
    if a.sum() == 0:
        return QColor(0, 0, 0, 0)
    wts = a / a.sum()
    b, g, rr = (arr[:, 0] * wts).sum(), (arr[:, 1] * wts).sum(), (arr[:, 2] * wts).sum()
    return QColor(int(round(rr)), int(round(g)), int(round(b)), int(round(a.mean())))


def masked_copy(img: QImage, path: QPainterPath) -> QImage:
    """Pixels inside the selection path, cropped to its bounds (outside transparent)."""
    rect = path.boundingRect().toAlignedRect().intersected(img.rect())
    if rect.isEmpty():
        return QImage()
    out = QImage(rect.size(), PREMUL)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.translate(-rect.x(), -rect.y())
    p.setClipPath(path)
    p.drawImage(rect.topLeft(), img, rect)
    p.end()
    return out
