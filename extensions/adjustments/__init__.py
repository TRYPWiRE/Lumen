"""Adjustments Pro: Photoshop's colour and tone adjustments (all with live preview)."""
import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath
from PyQt6.QtWidgets import QWidget, QComboBox, QHBoxLayout, QLabel, QPushButton

ops = None   # api.imageops


# --------------------------------------------------------------------------- pixel helpers
def to_rgb(img):
    """QImage -> (rgb float32 0..1 in R,G,B order, alpha uint8)."""
    a = ops.straight_array(img)
    return a[..., [2, 1, 0]].astype(np.float32) / 255.0, a[..., 3].copy()


def from_rgb(rgb, alpha):
    out = np.empty(rgb.shape[:2] + (4,), np.uint8)
    c = np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8)
    out[..., 0], out[..., 1], out[..., 2], out[..., 3] = c[..., 2], c[..., 1], c[..., 0], alpha
    return ops.from_array(out, ops.STRAIGHT).convertToFormat(ops.PREMUL)


def lum(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def apply_lut(img, luts):
    """luts: dict channel index (0 R, 1 G, 2 B) -> 256-entry uint8 table."""
    a = ops.straight_array(img)
    for ch, lut in luts.items():
        idx = 2 - ch
        a[..., idx] = lut[a[..., idx]]
    return ops.from_array(a, ops.STRAIGHT).convertToFormat(ops.PREMUL)


def rgb_to_hsv(rgb):
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    with np.errstate(divide="ignore", invalid="ignore"):
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        h = np.where(mx == r, ((g - b) / d) % 6, h)
        h = np.where(mx == g, (b - r) / d + 2, h)
        h = np.where(mx == b, (r - g) / d + 4, h)
        h = np.where(d == 0, 0, h) / 6.0
        s = np.where(mx > 0, d / mx, 0)
    return h % 1.0, s, mx


def hsv_to_rgb(h, s, v):
    i = np.floor(h * 6).astype(np.int32) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    choices = [np.stack(c, -1) for c in ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))]
    out = np.zeros(h.shape + (3,), np.float32)
    for k in range(6):
        out = np.where((i == k)[..., None], choices[k], out)
    return out


# --------------------------------------------------------------------------- adjustments
def levels(img, channel=0, in_black=0, gamma=1.0, in_white=255, out_black=0, out_white=255):
    x = np.arange(256, dtype=np.float32)
    v = np.clip((x - in_black) / max(1.0, in_white - in_black), 0, 1) ** (1.0 / max(gamma, 0.01))
    lut = np.clip(out_black + v * (out_white - out_black) + 0.5, 0, 255).astype(np.uint8)
    chans = [0, 1, 2] if channel == 0 else [channel - 1]
    return apply_lut(img, {c: lut for c in chans})


def monotone_curve(points):
    """256-entry table through (x, y) points (0..255) using monotone cubic interpolation."""
    pts = sorted(set((int(round(x)), float(y)) for x, y in points))
    xs = np.array([p[0] for p in pts], np.float64)
    ys = np.array([p[1] for p in pts], np.float64)
    if len(xs) == 1:
        return np.full(256, np.clip(ys[0], 0, 255), np.uint8)
    d = np.diff(ys) / np.maximum(np.diff(xs), 1e-9)
    m = np.empty_like(ys)
    m[0], m[-1] = d[0], d[-1]
    m[1:-1] = (d[:-1] + d[1:]) / 2
    for k in range(len(d)):                     # Fritsch–Carlson limiter keeps it monotone
        if d[k] == 0:
            m[k] = m[k + 1] = 0
        else:
            a, b = m[k] / d[k], m[k + 1] / d[k]
            s = a * a + b * b
            if s > 9:
                t = 3 / np.sqrt(s)
                m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    x = np.arange(256, dtype=np.float64)
    k = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
    h = xs[k + 1] - xs[k]
    t = np.clip((x - xs[k]) / np.maximum(h, 1e-9), 0, 1)
    h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
    h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    y = h00 * ys[k] + h10 * h * m[k] + h01 * ys[k + 1] + h11 * h * m[k + 1]
    y = np.where(x < xs[0], ys[0], np.where(x > xs[-1], ys[-1], y))
    return np.clip(y + 0.5, 0, 255).astype(np.uint8)


def curves(img, curves=None):
    curves = curves or {}
    luts = {}
    master = monotone_curve(curves.get(0, [(0, 0), (255, 255)]))
    for ch in range(3):
        own = monotone_curve(curves.get(ch + 1, [(0, 0), (255, 255)]))
        luts[ch] = own[master]
    return apply_lut(img, luts)


def exposure(img, exposure=0.0, offset=0.0, gamma=1.0):
    rgb, a = to_rgb(img)
    lin = rgb ** 2.2 * (2.0 ** exposure) + offset
    out = np.clip(lin, 0, 1) ** (1 / 2.2)
    out = out ** (1.0 / max(gamma, 0.01))
    return from_rgb(out, a)


def vibrance(img, vibrance=0, saturation=0):
    rgb, a = to_rgb(img)
    L = lum(rgb)[..., None]
    sat = (rgb.max(-1) - rgb.min(-1))[..., None]
    v = vibrance / 100.0
    factor = 1 + v * (1 - sat) if v > 0 else 1 + v + 0 * sat      # boosts muted colours more than vivid ones
    factor = factor * (1 + saturation / 100.0)
    return from_rgb(np.clip(L + (rgb - L) * factor, 0, 1), a)


def hue_saturation(img, hue=0, saturation=0, lightness=0, colorize=False):
    rgb, a = to_rgb(img)
    if colorize:
        L = lum(rgb)
        h = np.full(L.shape, ((hue % 360) / 360.0), np.float32)
        s = np.full(L.shape, max(0.0, (saturation + 100) / 200.0 if saturation else 0.25), np.float32)
        out = hsv_to_rgb(h, s, np.ones_like(L))
        out = out * (L / np.maximum(lum(out), 1e-6))[..., None]
    else:
        h, s, v = rgb_to_hsv(rgb)
        h = (h + hue / 360.0) % 1.0
        s = np.clip(s * (1 + saturation / 100.0), 0, 1)
        out = hsv_to_rgb(h, s, v)
    if lightness > 0:
        out = out + (1 - out) * (lightness / 100.0)
    elif lightness < 0:
        out = out * (1 + lightness / 100.0)
    return from_rgb(np.clip(out, 0, 1), a)


def color_balance(img, tone=1, cyan_red=0, magenta_green=0, yellow_blue=0, preserve=True):
    rgb, a = to_rgb(img)
    L = lum(rgb)
    w = [np.clip(1 - L * 2.5, 0, 1),                      # shadows
         np.clip(1 - np.abs(L - 0.5) * 2.2, 0, 1),        # midtones
         np.clip((L - 0.6) * 2.5, 0, 1)][tone][..., None]  # highlights
    shift = np.array([cyan_red, magenta_green, yellow_blue], np.float32) / 100.0 * 0.4
    out = np.clip(rgb + w * shift, 0, 1)
    if preserve:
        out = np.clip(out * (L / np.maximum(lum(out), 1e-6))[..., None], 0, 1)
    return from_rgb(out, a)


def black_white(img, reds=40, yellows=60, greens=40, cyans=60, blues=20, magentas=80, tint=False,
                tint_color=QColor(225, 211, 179)):
    """Photoshop's Black & White: gray = min + (mid-min)·W(secondary) + (max-mid)·W(primary)."""
    rgb, a = to_rgb(img)
    order = np.argsort(rgb, axis=-1)
    srt = np.take_along_axis(rgb, order, -1)
    mn, mid, mx = srt[..., 0], srt[..., 1], srt[..., 2]
    prim = order[..., 2]           # 0 R, 1 G, 2 B
    second = order[..., 1]
    wp = np.select([prim == 0, prim == 1, prim == 2], [reds, greens, blues]) / 100.0
    pair = prim + second           # R+G=1 yellow, G+B=3 cyan, R+B=2 magenta
    ws = np.select([pair == 1, pair == 3, pair == 2], [yellows, cyans, magentas]) / 100.0
    gray = np.clip(mn + (mid - mn) * ws + (mx - mid) * wp, 0, 1)
    out = np.repeat(gray[..., None], 3, -1)
    if tint:
        t = np.array([tint_color.redF(), tint_color.greenF(), tint_color.blueF()], np.float32)
        out = np.where(gray[..., None] < 0.5, 2 * gray[..., None] * t,
                       1 - 2 * (1 - gray[..., None]) * (1 - t))
    return from_rgb(out, a)


PHOTO_FILTERS = [("Warming Filter (85)", "#ec8a00"), ("Warming Filter (LBA)", "#fa9600"),
                 ("Warming Filter (81)", "#ebb113"), ("Cooling Filter (80)", "#006dff"),
                 ("Cooling Filter (LBB)", "#005dff"), ("Cooling Filter (82)", "#00b5ff"),
                 ("Red", "#ea1a1a"), ("Orange", "#f28417"), ("Yellow", "#f9e31c"), ("Green", "#19c919"),
                 ("Cyan", "#1dcbea"), ("Blue", "#1d35ea"), ("Violet", "#9b1dea"), ("Magenta", "#e318e3"),
                 ("Sepia", "#ac7a33"), ("Deep Red", "#ff0000"), ("Deep Blue", "#0022cd"), ("Underwater", "#00c1b1")]


def photo_filter(img, filter=0, density=25, preserve=True):
    rgb, a = to_rgb(img)
    c = QColor(PHOTO_FILTERS[filter][1])
    col = np.array([c.redF(), c.greenF(), c.blueF()], np.float32)
    out = rgb * (1 - density / 100.0) + rgb * col * (density / 100.0) * 2.0
    out = np.clip(out, 0, 1)
    if preserve:
        out = np.clip(out * (lum(rgb) / np.maximum(lum(out), 1e-6))[..., None], 0, 1)
    return from_rgb(out, a)


def gradient_map(img, start=QColor(0, 0, 0), end=QColor(255, 255, 255), reverse=False):
    rgb, a = to_rgb(img)
    t = lum(rgb)[..., None]
    c0 = np.array([start.redF(), start.greenF(), start.blueF()], np.float32)
    c1 = np.array([end.redF(), end.greenF(), end.blueF()], np.float32)
    if reverse:
        c0, c1 = c1, c0
    return from_rgb(c0 + (c1 - c0) * t, a)


def _blur_plane(p, r):
    r = int(max(1, r))
    for _ in range(3):
        for axis in (0, 1):
            n = p.shape[axis]
            pad = [(0, 0), (0, 0)]
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(p, pad, mode="edge"), axis=axis, dtype=np.float32)
            p = (c[2 * r + 1:2 * r + 1 + n] - c[:n]) / (2 * r + 1) if axis == 0 else \
                (c[:, 2 * r + 1:2 * r + 1 + n] - c[:, :n]) / (2 * r + 1)
    return p


def shadows_highlights(img, shadows=35, highlights=0, radius=30):
    rgb, a = to_rgb(img)
    L = lum(rgb)
    Lb = _blur_plane(L, radius / 3)
    lift = (shadows / 100.0) * (1 - Lb) ** 2
    cut = (highlights / 100.0) * Lb ** 2
    out = rgb + lift[..., None] * (1 - rgb) * 0.9 - cut[..., None] * rgb * 0.6
    return from_rgb(np.clip(out, 0, 1), a)


def equalize(img):
    rgb, a = to_rgb(img)
    L = (lum(rgb) * 255).astype(np.uint8)
    hist = np.bincount(L[a > 0].ravel() if (a > 0).any() else L.ravel(), minlength=256).astype(np.float64)
    cdf = hist.cumsum()
    cdf = (cdf - cdf[cdf > 0].min()) / max(cdf[-1] - cdf[cdf > 0].min(), 1)
    target = np.clip(cdf, 0, 1)[L]
    out = rgb * (target / np.maximum(L / 255.0, 1e-3))[..., None]
    return from_rgb(np.clip(out, 0, 1), a)


def _stretch(rgb, a, per_channel, clip=0.001):
    mask = a > 0 if (a > 0).any() else np.ones(a.shape, bool)
    out = rgb.copy()
    if per_channel:
        for c in range(3):
            v = rgb[..., c][mask]
            lo, hi = np.quantile(v, clip), np.quantile(v, 1 - clip)
            out[..., c] = (rgb[..., c] - lo) / max(hi - lo, 1e-3)
    else:
        v = lum(rgb)[mask]
        lo, hi = np.quantile(v, clip), np.quantile(v, 1 - clip)
        out = (rgb - lo) / max(hi - lo, 1e-3)
    return np.clip(out, 0, 1)


def auto_tone(img):
    rgb, a = to_rgb(img)
    return from_rgb(_stretch(rgb, a, True), a)


def auto_contrast(img):
    rgb, a = to_rgb(img)
    return from_rgb(_stretch(rgb, a, False), a)


def auto_color(img):
    """Neutralise the midtone colour cast, then stretch each channel."""
    rgb, a = to_rgb(img)
    mask = a > 0 if (a > 0).any() else np.ones(a.shape, bool)
    means = np.array([rgb[..., c][mask].mean() for c in range(3)])
    gray = means.mean()
    rgb = np.clip(rgb * (gray / np.maximum(means, 1e-3)), 0, 1)
    return from_rgb(_stretch(rgb, a, True, 0.0005), a)


# --------------------------------------------------------------------------- curves editor
class CurveEditor(QWidget):
    changed = pyqtSignal()
    SIZE = 256

    def __init__(self, histogram=None):
        super().__init__()
        self.setFixedSize(self.SIZE + 2, self.SIZE + 2)
        self.points = {c: [(0, 0), (255, 255)] for c in range(4)}
        self.channel = 0
        self.hist = histogram
        self._drag = None
        self.setToolTip("Click to add a point · drag to move · drag a point off the graph to remove it")

    def _to_px(self, x, y):
        return QPointF(1 + x, 1 + 255 - y)

    def _from_px(self, pos):
        return (min(255, max(0, pos.x() - 1)), min(255, max(0, 255 - (pos.y() - 1))))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1c1c1c"))
        if self.hist is not None:
            h = self.hist / max(self.hist.max(), 1)
            p.setPen(QColor(90, 90, 90))
            for x in range(256):
                p.drawLine(QPointF(1 + x, 257), QPointF(1 + x, 257 - h[x] * 255))
        p.setPen(QPen(QColor(70, 70, 70), 1))
        for i in range(1, 4):
            p.drawLine(QPointF(1 + i * 64, 1), QPointF(1 + i * 64, 257))
            p.drawLine(QPointF(1, 1 + i * 64), QPointF(257, 1 + i * 64))
        p.drawLine(QPointF(1, 257), QPointF(257, 1))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = [QColor("#dddddd"), QColor("#ff5555"), QColor("#55dd55"), QColor("#5599ff")][self.channel]
        lut = monotone_curve(self.points[self.channel])
        path = QPainterPath(self._to_px(0, lut[0]))
        for x in range(1, 256):
            path.lineTo(self._to_px(x, lut[x]))
        p.setPen(QPen(col, 2))
        p.drawPath(path)
        p.setBrush(col)
        p.setPen(QPen(QColor("#111"), 1))
        for x, y in self.points[self.channel]:
            c = self._to_px(x, y)
            p.drawRect(QRectF(c.x() - 3.5, c.y() - 3.5, 7, 7))

    def mousePressEvent(self, ev):
        x, y = self._from_px(ev.position())
        pts = self.points[self.channel]
        near = [i for i, (px, py) in enumerate(pts) if abs(px - x) < 8 and abs(py - y) < 8]
        if near:
            self._drag = near[0]
        else:
            pts.append((x, y))
            pts.sort()
            self._drag = pts.index((x, y))
        self.update()
        self.changed.emit()

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return
        pts = self.points[self.channel]
        x, y = self._from_px(ev.position())
        outside = not self.rect().adjusted(-20, -20, 20, 20).contains(ev.position().toPoint())
        if outside and len(pts) > 2 and 0 < self._drag < len(pts) - 1:
            pts.pop(self._drag)
            self._drag = None
        else:
            lo = pts[self._drag - 1][0] + 1 if self._drag > 0 else 0
            hi = pts[self._drag + 1][0] - 1 if self._drag < len(pts) - 1 else 255
            pts[self._drag] = (min(hi, max(lo, x)), y)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def reset(self):
        self.points[self.channel] = [(0, 0), (255, 255)]
        self.update()
        self.changed.emit()


def _histogram(api):
    doc = api.current_document()
    if doc is None:
        return None
    img = doc.layer_pixels()
    a = ops.straight_array(img)
    L = (a[..., 2] * 0.299 + a[..., 1] * 0.587 + a[..., 0] * 0.114).astype(np.uint8)
    m = a[..., 3] > 0
    return np.bincount(L[m] if m.any() else L.ravel(), minlength=256).astype(np.float64)


# --------------------------------------------------------------------------- registration
def register(api):
    global ops
    ops = api.imageops
    A = "Image/Adjustments"

    def S(key, label, lo, hi, default, suffix="", decimals=0):
        return {"key": key, "label": label, "min": lo, "max": hi, "default": default, "suffix": suffix,
                "decimals": decimals}

    def curves_hook(dlg):
        ed = CurveEditor(_histogram(api))
        row = QHBoxLayout()
        chan = QComboBox()
        chan.addItems(["RGB", "Red", "Green", "Blue"])
        chan.currentIndexChanged.connect(lambda i: (setattr(ed, "channel", i), ed.update()))
        row.addWidget(QLabel("Channel:"))
        row.addWidget(chan)
        row.addStretch(1)
        reset = QPushButton("Reset")
        reset.setObjectName("Flat")
        reset.clicked.connect(ed.reset)
        row.addWidget(reset)
        dlg.extra.addLayout(row)
        dlg.extra.addWidget(ed, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = QLabel("Drag the curve up to brighten, down to darken. An S-shape adds contrast.")
        hint.setObjectName("Dim")
        dlg.extra.addWidget(hint)
        dlg.extra_values = lambda: {"curves": {c: list(v) for c, v in ed.points.items()}}
        ed.changed.connect(dlg._schedule)
        dlg.curve_editor = ed

    def levels_hook(dlg):
        hist = _histogram(api)
        if hist is None:
            return
        ed = CurveEditor(hist)
        ed.setEnabled(False)
        ed.setFixedHeight(120)
        ed.setFixedWidth(258)
        dlg.extra.addWidget(ed, 0, Qt.AlignmentFlag.AlignHCenter)

    api.add_filter(A, "Levels…", levels,
                   [{"key": "channel", "label": "Channel", "type": "choice", "items": ["RGB", "Red", "Green", "Blue"]},
                    S("in_black", "Input Black", 0, 253, 0), S("gamma", "Midtones (gamma)", 0.10, 9.99, 1.0, "", 2),
                    S("in_white", "Input White", 2, 255, 255), S("out_black", "Output Black", 0, 255, 0),
                    S("out_white", "Output White", 0, 255, 255)], shortcut="Ctrl+L", dialog_hook=levels_hook)
    api.add_filter(A, "Curves…", curves, [], shortcut="Ctrl+M", dialog_hook=curves_hook)
    api.add_filter(A, "Exposure…", exposure,
                   [S("exposure", "Exposure", -5, 5, 0.0, "", 2), S("offset", "Offset", -0.5, 0.5, 0.0, "", 3),
                    S("gamma", "Gamma Correction", 0.01, 9.99, 1.0, "", 2)])
    api.menu(A).addSeparator()
    api.add_filter(A, "Vibrance…", vibrance, [S("vibrance", "Vibrance", -100, 100, 0),
                                              S("saturation", "Saturation", -100, 100, 0)])
    api.add_filter(A, "Hue/Saturation…", hue_saturation,
                   [S("hue", "Hue", -180, 180, 0, "°"), S("saturation", "Saturation", -100, 100, 0),
                    S("lightness", "Lightness", -100, 100, 0), {"key": "colorize", "label": "Colorize", "type": "check"}],
                   shortcut="Ctrl+U")
    api.add_filter(A, "Color Balance…", color_balance,
                   [{"key": "tone", "label": "Tone", "type": "choice", "items": ["Shadows", "Midtones", "Highlights"],
                     "default": 1},
                    S("cyan_red", "Cyan ↔ Red", -100, 100, 0), S("magenta_green", "Magenta ↔ Green", -100, 100, 0),
                    S("yellow_blue", "Yellow ↔ Blue", -100, 100, 0),
                    {"key": "preserve", "label": "Preserve Luminosity", "type": "check", "default": True}],
                   shortcut="Ctrl+B")
    api.add_filter(A, "Black & White…", black_white,
                   [S("reds", "Reds", -200, 300, 40, "%"), S("yellows", "Yellows", -200, 300, 60, "%"),
                    S("greens", "Greens", -200, 300, 40, "%"), S("cyans", "Cyans", -200, 300, 60, "%"),
                    S("blues", "Blues", -200, 300, 20, "%"), S("magentas", "Magentas", -200, 300, 80, "%"),
                    {"key": "tint", "label": "Tint", "type": "check"},
                    {"key": "tint_color", "label": "Tint Color", "type": "color", "default": QColor(225, 211, 179)}],
                   shortcut="Alt+Shift+Ctrl+B")
    api.add_filter(A, "Photo Filter…", photo_filter,
                   [{"key": "filter", "label": "Filter", "type": "choice", "items": [n for n, _ in PHOTO_FILTERS]},
                    S("density", "Density", 1, 100, 25, "%"),
                    {"key": "preserve", "label": "Preserve Luminosity", "type": "check", "default": True}])
    api.menu(A).addSeparator()
    api.add_filter(A, "Gradient Map…", gradient_map,
                   [{"key": "start", "label": "Shadows", "type": "color", "default": lambda: api.ctx.fg},
                    {"key": "end", "label": "Highlights", "type": "color", "default": lambda: api.ctx.bg},
                    {"key": "reverse", "label": "Reverse", "type": "check"}])
    api.add_filter(A, "Shadows/Highlights…", shadows_highlights,
                   [S("shadows", "Shadows Amount", 0, 100, 35, "%"), S("highlights", "Highlights Amount", 0, 100, 0, "%"),
                    S("radius", "Radius", 1, 300, 30, " px")])
    api.add_filter(A, "Equalize", equalize)
    api.add_filter("Image", "Auto Tone", auto_tone, shortcut="Shift+Ctrl+L")
    api.add_filter("Image", "Auto Contrast", auto_contrast, shortcut="Alt+Shift+Ctrl+L")
    api.add_filter("Image", "Auto Color", auto_color, shortcut="Shift+Ctrl+B")
