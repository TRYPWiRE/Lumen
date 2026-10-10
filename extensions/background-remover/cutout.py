"""Cut-out model + preview canvas for the Background Remover."""
import math

import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QRect
from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QPixmap, QBrush, QCursor
from PyQt6.QtWidgets import QWidget

from lumen import theme


def _box(a, r, axis):
    if r < 1:
        return a
    n = a.shape[axis]
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
    if axis == 0:
        return (c[2 * r + 1:2 * r + 1 + n] - c[:n]) / (2 * r + 1)
    return (c[:, 2 * r + 1:2 * r + 1 + n] - c[:, :n]) / (2 * r + 1)


def blur(a, r=1):
    f = a.astype(np.float32)
    for _ in range(2):
        f = _box(_box(f, r, 1), r, 0)
    return np.clip(f + 0.5, 0, 255).astype(np.uint8)


def min_filter(a, r=1):
    out = a.copy()
    p = np.pad(a, r, mode="edge")
    h, w = a.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            np.minimum(out, p[r + dy:r + dy + h, r + dx:r + dx + w], out=out)
    return out


def max_filter(a, r=1):
    out = a.copy()
    p = np.pad(a, r, mode="edge")
    h, w = a.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            np.maximum(out, p[r + dy:r + dy + h, r + dx:r + dx + w], out=out)
    return out


class Cutout:
    """Source pixels never change; only the alpha mask is edited (with undo)."""

    def __init__(self, img: QImage, ops):
        self.ops = ops
        self.source = img.convertToFormat(QImage.Format.Format_ARGB32)
        self.bgra = ops.straight_array(self.source)          # (h, w, 4) straight B, G, R, A
        self.base_alpha = self.bgra[..., 3].copy()
        self.alpha = self.base_alpha.copy()
        self.history = []

    @property
    def size(self):
        return self.alpha.shape[1], self.alpha.shape[0]

    def push(self):
        self.history.append(self.alpha.copy())
        if len(self.history) > 40:
            self.history.pop(0)

    def undo(self):
        if self.history:
            self.alpha = self.history.pop()
            return True
        return False

    def reset(self):
        self.push()
        self.alpha = self.base_alpha.copy()

    def similar(self, colour, tolerance):
        rgb = self.bgra[..., :3].astype(np.int16)
        return np.abs(rgb - np.asarray(colour, np.int16)).max(axis=2) <= tolerance

    def wand(self, x, y, tolerance, contiguous=True):
        w, h = self.size
        if not (0 <= x < w and 0 <= y < h):
            return 0
        mask = self.similar(self.bgra[y, x, :3], tolerance) & (self.alpha > 0)
        if contiguous:
            mask = self.ops.flood_region(mask, x, y)
        n = int(mask.sum())
        if n:
            self.push()
            self.alpha[mask] = 0
        return n

    def clear_edges(self, tolerance):
        """Clear everything connected to the four corners that matches their colours."""
        w, h = self.size
        total = np.zeros(self.alpha.shape, bool)
        for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if total[y, x] or self.alpha[y, x] == 0:
                continue
            sim = self.similar(self.bgra[y, x, :3], tolerance) & (self.alpha > 0)
            total |= self.ops.flood_region(sim, x, y)
        n = int(total.sum())
        if n:
            self.push()
            self.alpha[total] = 0
        return n

    def brush(self, a: QPointF, b: QPointF, radius, restore):
        """Erase (or restore) along the segment a→b with a round brush."""
        w, h = self.size
        r = max(0.5, radius)
        x0 = int(max(0, math.floor(min(a.x(), b.x()) - r)))
        x1 = int(min(w, math.ceil(max(a.x(), b.x()) + r) + 1))
        y0 = int(max(0, math.floor(min(a.y(), b.y()) - r)))
        y1 = int(min(h, math.ceil(max(a.y(), b.y()) + r) + 1))
        if x0 >= x1 or y0 >= y1:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = np.clip(((xs + 0.5 - ax) * dx + (ys + 0.5 - ay) * dy) / L2, 0, 1) if L2 > 0 else 0
        dist = np.hypot(xs + 0.5 - (ax + t * dx), ys + 0.5 - (ay + t * dy))
        hit = dist <= r
        region = self.alpha[y0:y1, x0:x1]
        if restore:
            region[hit] = self.base_alpha[y0:y1, x0:x1][hit]
        else:
            region[hit] = 0

    def apply_mask(self, mask):
        self.push()
        self.alpha = np.minimum(self.base_alpha, mask).astype(np.uint8)

    def soften(self):
        self.push()
        self.alpha = np.minimum(blur(self.alpha, 1), self.base_alpha)

    def tighten(self):
        self.push()
        self.alpha = min_filter(self.alpha, 1)

    def grow(self):
        self.push()
        self.alpha = np.minimum(max_filter(self.alpha, 1), self.base_alpha)

    def bounds(self):
        rows = np.flatnonzero((self.alpha > 8).any(axis=1))
        cols = np.flatnonzero((self.alpha > 8).any(axis=0))
        if rows.size == 0:
            return None
        return QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))

    def result(self, crop=None) -> QImage:
        """Premultiplied image of the cut-out (optionally cropped)."""
        arr = self.bgra.copy()
        arr[..., 3] = self.alpha
        img = self.ops.from_array(arr, self.ops.STRAIGHT).convertToFormat(self.ops.PREMUL)
        return img.copy(crop) if crop is not None else img

    def subject_fraction(self):
        return float((self.alpha > 128).mean())


def _checker():
    pm = QPixmap(16, 16)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor("#cccccc"))
    p.fillRect(8, 8, 8, 8, QColor("#cccccc"))
    p.end()
    return QBrush(pm)


class CutoutCanvas(QWidget):
    """Shows the cut-out over a checkerboard. Wheel zooms at the cursor, right/middle-drag pans."""
    pressed = pyqtSignal(QPointF)
    dragged = pyqtSignal(QPointF)
    released = pyqtSignal()
    viewChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 320)
        self.setMouseTracking(True)
        self.image = None
        self.zoom = 1.0
        self.fit = 1.0
        self.offset = QPointF(0, 0)
        self._pan = None
        self._mouse = None
        self.brush_radius = 0          # image px; 0 = no brush outline (wand)
        self._checker = _checker()
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, img, reset=False):
        old = self.image
        self.image = img
        if reset or old is None or old.size() != img.size():
            self.reset_view()
        self.update()

    def reset_view(self):
        if self.image is None:
            return
        self.fit = min((self.width() - 20) / self.image.width(), (self.height() - 20) / self.image.height(), 1.0)
        self.zoom = self.fit
        self._center()
        self.viewChanged.emit()

    def _center(self):
        w, h = self.image.width() * self.zoom, self.image.height() * self.zoom
        self.offset = QPointF((self.width() - w) / 2, (self.height() - h) / 2)

    def resizeEvent(self, ev):
        if self.image is not None and abs(self.zoom - self.fit) < 1e-6:
            self.reset_view()
        super().resizeEvent(ev)

    def to_image(self, pos):
        return QPointF((pos.x() - self.offset.x()) / self.zoom, (pos.y() - self.offset.y()) / self.zoom)

    def zoom_by(self, f, anchor=None):
        if self.image is None:
            return
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        ip = self.to_image(anchor)
        self.zoom = max(self.fit * 0.5, min(32.0, self.zoom * f))
        self.offset = QPointF(anchor.x() - ip.x() * self.zoom, anchor.y() - ip.y() * self.zoom)
        self.update()
        self.viewChanged.emit()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.PASTEBOARD))       # follows the Lumen theme
        if self.image is None:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Open an image, or bring one over from Lumen.\nThe chequered areas will be see-through.")
            return
        r = QRectF(self.offset.x(), self.offset.y(), self.image.width() * self.zoom, self.image.height() * self.zoom)
        p.setBrushOrigin(r.topLeft())
        p.fillRect(r, self._checker)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 2)
        p.drawImage(r, self.image)
        if self._mouse is not None and self.brush_radius > 0:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rad = self.brush_radius * self.zoom
            for col, w in ((QColor(0, 0, 0, 180), 3), (QColor(255, 255, 255, 230), 1)):
                p.setPen(QPen(col, w))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(self._mouse, rad, rad)

    def wheelEvent(self, ev):
        dy = ev.angleDelta().y()
        if dy:
            self.zoom_by(1.25 if dy > 0 else 0.8, ev.position())

    def mousePressEvent(self, ev):
        if ev.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._pan = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif ev.button() == Qt.MouseButton.LeftButton and self.image is not None:
            self.pressed.emit(self.to_image(ev.position()))

    def mouseMoveEvent(self, ev):
        self._mouse = ev.position()
        if self._pan is not None:
            self.offset += ev.position() - self._pan
            self._pan = ev.position()
            self.update()
            return
        if ev.buttons() & Qt.MouseButton.LeftButton and self.image is not None:
            self.dragged.emit(self.to_image(ev.position()))
        if self.brush_radius > 0:
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._pan is not None:
            self._pan = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif ev.button() == Qt.MouseButton.LeftButton:
            self.released.emit()

    def leaveEvent(self, ev):
        self._mouse = None
        self.update()
