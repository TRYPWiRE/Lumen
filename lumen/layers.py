"""Layers: pixel and type layers, Photoshop blend modes and compositing."""
import itertools
import math
import numpy as np
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from PyQt6.QtGui import QImage, QPainter, QColor, QFont, QFontMetricsF, QTransform

from . import imageops
from .imageops import PREMUL

_uid = itertools.count(1)

# --------------------------------------------------------------------------- blend modes
# (key, label) in Photoshop's menu order; None = separator.
BLEND_MODES = [
    ("norm", "Normal"), ("diss", "Dissolve"), None,
    ("dark", "Darken"), ("mul ", "Multiply"), ("idiv", "Color Burn"), ("lbrn", "Linear Burn"),
    ("dkCl", "Darker Color"), None,
    ("lite", "Lighten"), ("scrn", "Screen"), ("div ", "Color Dodge"), ("lddg", "Linear Dodge (Add)"),
    ("lgCl", "Lighter Color"), None,
    ("over", "Overlay"), ("sLit", "Soft Light"), ("hLit", "Hard Light"), ("vLit", "Vivid Light"),
    ("lLit", "Linear Light"), ("pLit", "Pin Light"), ("hMix", "Hard Mix"), None,
    ("diff", "Difference"), ("smud", "Exclusion"), ("fsub", "Subtract"), ("fdiv", "Divide"), None,
    ("hue ", "Hue"), ("sat ", "Saturation"), ("colr", "Color"), ("lum ", "Luminosity"),
]
BLEND_LABELS = {m[0]: m[1] for m in BLEND_MODES if m}
BLEND_KEYS = [m[0] for m in BLEND_MODES if m]

_CM = QPainter.CompositionMode
QT_MODES = {
    "norm": _CM.CompositionMode_SourceOver, "dark": _CM.CompositionMode_Darken,
    "mul ": _CM.CompositionMode_Multiply, "idiv": _CM.CompositionMode_ColorBurn,
    "lite": _CM.CompositionMode_Lighten, "scrn": _CM.CompositionMode_Screen,
    "div ": _CM.CompositionMode_ColorDodge, "lddg": _CM.CompositionMode_Plus,
    "over": _CM.CompositionMode_Overlay, "sLit": _CM.CompositionMode_SoftLight,
    "hLit": _CM.CompositionMode_HardLight, "diff": _CM.CompositionMode_Difference,
    "smud": _CM.CompositionMode_Exclusion,
}


def _lum(c):
    return c[..., 0] * 0.3 + c[..., 1] * 0.59 + c[..., 2] * 0.11


def _clip_color(c):
    l = _lum(c)[..., None]
    n = c.min(axis=-1, keepdims=True)
    x = c.max(axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(n < 0, l + (c - l) * l / np.maximum(l - n, 1e-6), c)
        c = np.where(x > 1, l + (c - l) * (1 - l) / np.maximum(x - l, 1e-6), c)
    return c


def _set_lum(c, l):
    return _clip_color(c + (l - _lum(c))[..., None])


def _sat(c):
    return c.max(axis=-1) - c.min(axis=-1)


def _set_sat(c, s):
    mx = c.max(axis=-1, keepdims=True)
    mn = c.min(axis=-1, keepdims=True)
    rng = mx - mn
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(rng > 1e-6, (c - mn) * s[..., None] / np.maximum(rng, 1e-6), 0.0)
    return out


def _blend(key, b, s):
    """B(Cb, Cs) for straight RGB in 0..1 arrays (h, w, 3)."""
    if key == "lbrn":
        return np.clip(b + s - 1, 0, 1)
    if key == "vLit":
        with np.errstate(divide="ignore", invalid="ignore"):
            burn = np.where(s <= 0, 0.0, 1 - np.clip((1 - b) / np.maximum(2 * s, 1e-6), 0, 1))
            dodge = np.where(s >= 1, 1.0, np.clip(b / np.maximum(2 * (1 - s), 1e-6), 0, 1))
        return np.where(s <= 0.5, burn, dodge)
    if key == "lLit":
        return np.clip(b + 2 * s - 1, 0, 1)
    if key == "pLit":
        return np.where(s <= 0.5, np.minimum(b, 2 * s), np.maximum(b, 2 * s - 1))
    if key == "hMix":
        return np.where(b + s >= 1, 1.0, 0.0)
    if key == "fsub":
        return np.clip(b - s, 0, 1)
    if key == "fdiv":
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(s <= 0, np.where(b > 0, 1.0, 0.0), np.clip(b / np.maximum(s, 1e-6), 0, 1))
    if key in ("dkCl", "lgCl"):
        pick_s = _lum(s) < _lum(b) if key == "dkCl" else _lum(s) > _lum(b)
        return np.where(pick_s[..., None], s, b)
    if key == "hue ":
        return _set_lum(_set_sat(s, _sat(b)), _lum(b))
    if key == "sat ":
        return _set_lum(_set_sat(b, _sat(s)), _lum(b))
    if key == "colr":
        return _set_lum(s, _lum(b))
    if key == "lum ":
        return _set_lum(b, _lum(s))
    return s


def _dissolve_noise(rect: QRect):
    """Deterministic per-pixel noise (stable while painting/scrolling)."""
    ys, xs = np.mgrid[rect.top():rect.top() + rect.height(), rect.left():rect.left() + rect.width()]
    h = (xs.astype(np.uint32) * np.uint32(374761393) + ys.astype(np.uint32) * np.uint32(668265263))
    h = (h ^ (h >> np.uint32(13))) * np.uint32(1274126177)
    return ((h >> np.uint32(8)) & np.uint32(0xFFFF)).astype(np.float32) / 65535.0


def composite_custom(dest: QImage, src: QImage, at: QPoint, rect: QRect, key: str, opacity: float):
    """Blend src (drawn at `at`) onto dest inside rect with a mode Qt lacks. Both premultiplied."""
    r = rect.intersected(QRect(at, src.size())).intersected(dest.rect())
    if r.isEmpty():
        return
    d = imageops.view(dest)[r.top():r.bottom() + 1, r.left():r.right() + 1]
    sr = r.translated(-at)
    sv = imageops.view(src)[sr.top():sr.bottom() + 1, sr.left():sr.right() + 1]
    ds = d.astype(np.float32) / 255.0
    ss = sv.astype(np.float32) / 255.0
    ab = ds[..., 3:4]
    a_s = ss[..., 3:4] * opacity
    if key == "diss":
        noise = _dissolve_noise(r)[..., None]
        keep = (noise < a_s).astype(np.float32)
        with np.errstate(divide="ignore", invalid="ignore"):
            cs = np.where(ss[..., 3:4] > 0, ss[..., :3] / np.maximum(ss[..., 3:4], 1e-6), 0)
        out_a = keep + ab * (1 - keep)
        out_c = cs * keep + ds[..., :3] * (1 - keep)
        d[..., :3] = np.clip(out_c * 255 + 0.5, 0, 255).astype(np.uint8)
        d[..., 3] = np.clip(out_a[..., 0] * 255 + 0.5, 0, 255).astype(np.uint8)
        return
    with np.errstate(divide="ignore", invalid="ignore"):
        cb = np.where(ab > 0, ds[..., :3] / np.maximum(ab, 1e-6), 0)          # straight backdrop
        cs = np.where(ss[..., 3:4] > 0, ss[..., :3] / np.maximum(ss[..., 3:4], 1e-6), 0)
    # channels are stored B, G, R; non-separable modes need R, G, B order
    bm = _blend(key, cb[..., ::-1], cs[..., ::-1])[..., ::-1]
    co = cs * a_s * (1 - ab) + ds[..., :3] * (1 - a_s) + a_s * ab * bm
    ao = a_s + ab - a_s * ab
    d[..., :3] = np.clip(co * 255 + 0.5, 0, 255).astype(np.uint8)
    d[..., 3] = np.clip(ao[..., 0] * 255 + 0.5, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- type
class TextData:
    """Editable point-type: text + character settings + a transform placing it in the document.
    Local coordinates: first baseline at y=0, anchor at x=0 (alignment is relative to the anchor)."""

    def __init__(self, text="", family="Arial", size=48.0, bold=False, italic=False, underline=False,
                 color=QColor(0, 0, 0), align=0, tracking=0, transform=None):
        self.text = text
        self.family = family
        self.size = float(size)
        self.bold = bool(bold)
        self.italic = bool(italic)
        self.underline = bool(underline)
        self.color = QColor(color)
        self.align = int(align)          # 0 left, 1 centre, 2 right
        self.tracking = int(tracking)    # Photoshop units: 1/1000 em
        self.transform = QTransform(transform) if transform is not None else QTransform()

    def copy(self):
        return TextData(self.text, self.family, self.size, self.bold, self.italic, self.underline,
                        self.color, self.align, self.tracking, self.transform)

    def __eq__(self, o):
        return isinstance(o, TextData) and self.to_dict() == o.to_dict()

    def font(self):
        f = QFont(self.family)
        f.setPixelSize(max(1, int(round(self.size))))
        f.setBold(self.bold)
        f.setItalic(self.italic)
        f.setUnderline(self.underline)
        f.setKerning(True)
        if self.tracking:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.tracking / 1000.0 * self.size)
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return f

    def lines(self):
        return self.text.split("\n")

    def leading(self):
        return self.size * 1.2          # Photoshop "Auto" leading = 120%

    def metrics(self):
        return QFontMetricsF(self.font())

    def line_x(self, i, fm=None):
        fm = fm or self.metrics()
        w = fm.horizontalAdvance(self.lines()[i])
        return 0.0 if self.align == 0 else -w / 2 if self.align == 1 else -w

    def local_bounds(self):
        fm = self.metrics()
        lines = self.lines()
        w = max([fm.horizontalAdvance(ln) for ln in lines] + [1.0])
        x0 = 0.0 if self.align == 0 else -w / 2 if self.align == 1 else -w
        top = -fm.ascent()
        bottom = (len(lines) - 1) * self.leading() + fm.descent()
        pad = self.size * 0.15 + 2       # italics and antialiasing overhang
        return QRectF(x0 - pad, top - 2, w + 2 * pad, bottom - top + 4)

    # caret geometry (local coords) -------------------------------------
    def index_to_line_col(self, idx):
        idx = max(0, min(idx, len(self.text)))
        before = self.text[:idx]
        line = before.count("\n")
        col = idx - (before.rfind("\n") + 1)
        return line, col

    def line_col_to_index(self, line, col):
        lines = self.lines()
        line = max(0, min(line, len(lines) - 1))
        col = max(0, min(col, len(lines[line])))
        return sum(len(l) + 1 for l in lines[:line]) + col

    def caret_pos(self, idx):
        fm = self.metrics()
        line, col = self.index_to_line_col(idx)
        x = self.line_x(line, fm) + fm.horizontalAdvance(self.lines()[line][:col])
        y = line * self.leading()
        return QPointF(x, y)

    def hit_index(self, local: QPointF):
        fm = self.metrics()
        lines = self.lines()
        line = int(math.floor((local.y() + fm.ascent()) / self.leading()))
        line = max(0, min(line, len(lines) - 1))
        x0 = self.line_x(line, fm)
        txt = lines[line]
        best, best_d = 0, abs(local.x() - x0)
        for c in range(1, len(txt) + 1):
            d = abs(local.x() - (x0 + fm.horizontalAdvance(txt[:c])))
            if d < best_d:
                best, best_d = c, d
        return self.line_col_to_index(line, best)

    def render(self):
        """(image, offset) of the rendered type in document coordinates."""
        local = self.local_bounds()
        doc_rect = self.transform.mapRect(local).toAlignedRect().adjusted(-1, -1, 1, 1)
        img = QImage(max(1, doc_rect.width()), max(1, doc_rect.height()), PREMUL)
        img.fill(Qt.GlobalColor.transparent)
        if self.text.strip():
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.translate(-doc_rect.x(), -doc_rect.y())
            p.setTransform(self.transform, True)
            p.setFont(self.font())
            p.setPen(self.color)
            fm = self.metrics()
            for i, ln in enumerate(self.lines()):
                p.drawText(QPointF(self.line_x(i, fm), i * self.leading()), ln)
            p.end()
        return img, doc_rect.topLeft()

    # serialisation (PSD metadata / extensions) --------------------------
    def to_dict(self):
        t = self.transform
        return {"text": self.text, "family": self.family, "size": self.size, "bold": self.bold,
                "italic": self.italic, "underline": self.underline, "color": self.color.name(),
                "align": self.align, "tracking": self.tracking,
                "transform": [t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy()]}

    @classmethod
    def from_dict(cls, d):
        m = d.get("transform") or [1, 0, 0, 1, 0, 0]
        return cls(d.get("text", ""), d.get("family", "Arial"), d.get("size", 48), d.get("bold", False),
                   d.get("italic", False), d.get("underline", False), QColor(d.get("color", "#000000")),
                   d.get("align", 0), d.get("tracking", 0), QTransform(m[0], m[1], m[2], m[3], m[4], m[5]))


# --------------------------------------------------------------------------- layer
class Layer:
    def __init__(self, name="Layer", image=None, offset=QPoint(0, 0), background=False, text=None):
        self.uid = next(_uid)
        self.name = name
        self.visible = True
        self.opacity = 100           # %
        self.fill = 100              # % (same as opacity until layer styles exist)
        self.blend = "norm"
        self.lock_alpha = False
        self.lock_pixels = False
        self.lock_position = False
        self.lock_all = False
        self.background = background
        self.text = text             # TextData for type layers
        self.preview = None          # temporary pixels while a tool is working
        self.version = 0             # bumps whenever pixels change (thumbnail cache)
        if text is not None:
            self.image, self.offset = text.render()
        else:
            self.image = imageops.to_working(image).copy() if image is not None else QImage(1, 1, PREMUL)
            if image is None:
                self.image.fill(Qt.GlobalColor.transparent)
            self.offset = QPoint(offset)

    # -- info -------------------------------------------------------------
    @property
    def is_text(self):
        return self.text is not None

    def rect(self) -> QRect:
        return QRect(self.offset, self.image.size())

    def display(self):
        return self.preview if self.preview is not None else self.image

    def pixels_locked(self):
        return self.lock_pixels or self.lock_all

    def position_locked(self):
        return self.lock_position or self.lock_all or self.background

    def alpha_locked(self):
        return self.lock_alpha or self.lock_all or self.background

    def props(self):
        return {k: getattr(self, k) for k in ("name", "visible", "opacity", "fill", "blend", "lock_alpha",
                                              "lock_pixels", "lock_position", "lock_all", "background")}

    def clone(self, keep_uid=False):
        L = Layer.__new__(Layer)
        L.__dict__.update(self.__dict__)
        L.uid = self.uid if keep_uid else next(_uid)
        L.image = self.image.copy()
        L.offset = QPoint(self.offset)
        L.text = self.text.copy() if self.text else None
        L.preview = None
        return L

    # -- pixels -----------------------------------------------------------
    def touch(self):
        self.version += 1

    def rerender_text(self):
        self.image, self.offset = self.text.render()
        self.touch()

    def ensure_covers(self, r: QRect):
        """Grow the pixel buffer (transparent) so it includes document rect r."""
        if r.isEmpty():
            return
        cur = self.rect()
        if cur.contains(r):
            return
        new = cur.united(r) if not self.image.isNull() and cur.width() > 0 else QRect(r)
        img = QImage(new.size(), PREMUL)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(cur.topLeft() - new.topLeft(), self.image)
        p.end()
        self.image, self.offset = img, new.topLeft()
        if self.preview is not None:
            pv = QImage(new.size(), PREMUL)
            pv.fill(Qt.GlobalColor.transparent)
            p = QPainter(pv)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(cur.topLeft() - new.topLeft(), self.preview)
            p.end()
            self.preview = pv

    def region(self, r: QRect, source=None) -> QImage:
        """Copy of this layer's pixels inside document rect r (transparent where the layer is empty)."""
        src = source if source is not None else self.image
        out = QImage(r.size(), PREMUL)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(self.offset - r.topLeft(), src)
        p.end()
        return out

    def put_region(self, r: QRect, img: QImage):
        """Write img into document rect r (replacing pixels)."""
        self.ensure_covers(r)
        p = QPainter(self.image)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(r.topLeft() - self.offset, img)
        p.end()
        self.touch()

    def translate(self, dx, dy):
        self.offset += QPoint(dx, dy)
        if self.text is not None:
            self.text.transform = self.text.transform * QTransform.fromTranslate(dx, dy)
        self.touch()

    def content_bounds(self) -> QRect:
        """Document rect of non-transparent pixels."""
        a = imageops.view(self.image)[..., 3]
        rows = np.flatnonzero(a.any(axis=1))
        if rows.size == 0:
            return QRect()
        cols = np.flatnonzero(a.any(axis=0))
        return QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1),
                     int(rows[-1] - rows[0] + 1)).translated(self.offset)

    def alpha_at(self, pt: QPoint) -> int:
        local = pt - self.offset
        if not self.image.rect().contains(local):
            return 0
        return self.display().pixelColor(local).alpha()


def apply_alpha_lock(before: QImage, after: QImage) -> QImage:
    """Keep `after`'s colour but `before`'s transparency (Lock Transparent Pixels)."""
    b = imageops.view(before).astype(np.float32)
    a = imageops.view(after).astype(np.float32)
    aa = a[..., 3:4]
    with np.errstate(divide="ignore", invalid="ignore"):
        straight = np.where(aa > 0, a[..., :3] / np.maximum(aa, 1e-6), 0)
    ba = b[..., 3:4]
    out = np.empty_like(a)
    out[..., :3] = np.where(aa > 0, straight * ba, b[..., :3])
    out[..., 3:4] = ba
    return imageops.from_array(np.clip(out + 0.5, 0, 255).astype(np.uint8))


def draw_layer(p: QPainter, dest: QImage, layer: Layer, rect: QRect, opacity_scale=1.0):
    """Composite one layer onto dest (inside document rect `rect`)."""
    op = layer.opacity / 100.0 * layer.fill / 100.0 * opacity_scale
    if op <= 0:
        return
    img = layer.display()
    if layer.blend in QT_MODES or layer.blend not in BLEND_LABELS:
        p.save()
        p.setClipRect(rect)
        p.setCompositionMode(QT_MODES.get(layer.blend, QT_MODES["norm"]))
        p.setOpacity(op)
        p.drawImage(layer.offset, img)
        p.restore()
    else:
        p.end()
        composite_custom(dest, img, layer.offset, rect, layer.blend, op)
        p.begin(dest)


def flatten(layers, size, rect=None, background_fill=None) -> QImage:
    """Composite visible layers into a new image of `size` (only `rect` is rendered if given)."""
    out = QImage(size, PREMUL)
    out.fill(Qt.GlobalColor.transparent if background_fill is None else background_fill)
    r = rect or QRect(QPoint(0, 0), size)
    p = QPainter(out)
    for L in layers:
        if L.visible:
            draw_layer(p, out, L, r)
    p.end()
    return out
