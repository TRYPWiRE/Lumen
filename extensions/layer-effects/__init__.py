"""Layer Effects: Photoshop layer styles, each created on its own layer (like Layer Style ▸ Create Layer)."""
import math
import numpy as np
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor

ops = None
_api = None


# --------------------------------------------------------------------------- mask maths (0..1 floats)
def _box(p, r, axis):
    if r < 1:
        return p
    n = p.shape[axis]
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(p, pad, mode="constant"), axis=axis, dtype=np.float32)
    return (c[2 * r + 1:2 * r + 1 + n] - c[:n]) / (2 * r + 1) if axis == 0 else \
        (c[:, 2 * r + 1:2 * r + 1 + n] - c[:, :n]) / (2 * r + 1)


def blur(m, size):
    r = int(round(size / 3))
    for _ in range(3):
        m = _box(_box(m, r, 1), r, 0)
    return m


_DISCS = {}


def _disc(r):
    if r not in _DISCS:
        ys, xs = np.mgrid[-r:r + 1, -r:r + 1]
        _DISCS[r] = [(int(y), int(x)) for y, x in zip(ys.ravel(), xs.ravel()) if x * x + y * y <= r * r + r]
    return _DISCS[r]


def dilate(m, r):
    """Round dilation by r px (repeated small discs approximate a big disc)."""
    r = int(round(r))
    while r > 0:
        step = min(r, 4)
        p = np.pad(m, step)
        h, w = m.shape
        out = m.copy()
        for dy, dx in _disc(step):
            np.maximum(out, p[step + dy:step + dy + h, step + dx:step + dx + w], out=out)
        m = out
        r -= step
    return m


def erode(m, r):
    return 1 - dilate(1 - m, r)


def shift(m, dx, dy):
    out = np.zeros_like(m)
    h, w = m.shape
    dx, dy = int(round(dx)), int(round(dy))
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = m[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def spread_blur(m, spread, size):
    """Photoshop's Spread + Size: a soft edge, made harder by spread."""
    if size <= 0:
        return m
    k = spread / 100.0
    grown = dilate(m, size * k) if k > 0 else m
    return np.clip(blur(grown, size * (1 - k) + 1e-3), 0, 1)


def colour_layer(alpha, color, opacity=100):
    h, w = alpha.shape
    out = np.empty((h, w, 4), np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = color.blue(), color.green(), color.red()
    out[..., 3] = np.clip(alpha * 255 * opacity / 100.0 + 0.5, 0, 255).astype(np.uint8)
    return ops.from_array(out, ops.STRAIGHT).convertToFormat(ops.PREMUL)


# --------------------------------------------------------------------------- effects → (image, blend, above?)
def drop_shadow(a, color, opacity=75, angle=120, distance=5, spread=0, size=5):
    t = math.radians(angle)
    m = spread_blur(shift(a, -math.cos(t) * distance, math.sin(t) * distance), spread, size)
    return colour_layer(m, color, opacity), "mul ", False


def outer_glow(a, color, opacity=75, spread=0, size=10):
    m = spread_blur(a, spread, size)
    return colour_layer(np.clip(m, 0, 1), color, opacity), "scrn", False


def inner_shadow(a, color, opacity=75, angle=120, distance=5, size=5):
    t = math.radians(angle)
    inv = 1 - a
    m = blur(shift(inv, -math.cos(t) * distance, math.sin(t) * distance), size)
    return colour_layer(np.clip(m, 0, 1) * a, color, opacity), "mul ", True


def inner_glow(a, color, opacity=75, size=10):
    m = blur(1 - a, size)
    return colour_layer(np.clip(m * 2, 0, 1) * a, color, opacity), "scrn", True


def stroke(a, color, size=3, position=0, opacity=100):
    hard = (a > 0.5).astype(np.float32)
    if position == 0:      # outside
        m = np.clip(dilate(hard, size) - hard, 0, 1)
    elif position == 1:    # inside
        m = np.clip(hard - erode(hard, size), 0, 1)
    else:                  # centre
        m = np.clip(dilate(hard, size / 2) - erode(hard, size / 2), 0, 1)
    return colour_layer(m, color, opacity), "norm", True


def color_overlay(a, color, opacity=100, blend=0):
    return colour_layer(a, color, opacity), ["norm", "mul ", "scrn", "over", "colr"][blend], True


def gradient_overlay(a, start, end, opacity=100, angle=90, reverse=False):
    h, w = a.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    t = math.radians(angle)
    proj = (xs - w / 2) * math.cos(t) - (ys - h / 2) * math.sin(t)
    rng = max(1e-3, abs(w / 2 * math.cos(t)) + abs(h / 2 * math.sin(t)))
    g = np.clip(proj / (2 * rng) + 0.5, 0, 1)
    if reverse:
        g = 1 - g
    c0 = np.array([start.blue(), start.green(), start.red()], np.float32)
    c1 = np.array([end.blue(), end.green(), end.red()], np.float32)
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = np.clip(c0 + (c1 - c0) * g[..., None] + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(a * 255 * opacity / 100.0 + 0.5, 0, 255).astype(np.uint8)
    return ops.from_array(out, ops.STRAIGHT).convertToFormat(ops.PREMUL), "norm", True


def bevel_emboss(a, depth=100, size=6, angle=120, altitude=30):
    hgt = blur(a, size * 2) * size * depth / 100.0
    gy, gx = np.gradient(hgt)
    t, al = math.radians(angle), math.radians(altitude)
    lx, ly, lz = math.cos(t) * math.cos(al), -math.sin(t) * math.cos(al), math.sin(al)
    nz = 1.0
    shade = (-gx * lx - gy * ly + nz * lz) / np.sqrt(gx * gx + gy * gy + nz * nz)
    g = np.clip(128 + (shade - lz) * 255, 0, 255)
    h, w = a.shape
    out = np.empty((h, w, 4), np.uint8)
    out[..., 0] = out[..., 1] = out[..., 2] = g.astype(np.uint8)
    out[..., 3] = np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)
    return ops.from_array(out, ops.STRAIGHT).convertToFormat(ops.PREMUL), "over", True


# --------------------------------------------------------------------------- running an effect
def _source_alpha(doc, L, pad):
    r = L.rect().adjusted(-pad, -pad, pad, pad).intersected(doc.rect())
    if L.background or r.isEmpty():
        return None, None
    a = ops.view(L.region(r))[..., 3].astype(np.float32) / 255.0
    return r, a


def make_effect_layer(doc, L, name, fn, values, pad):
    from lumen.layers import Layer
    r, a = _source_alpha(doc, L, pad)
    if r is None:
        return None, None
    img, blend, above = fn(a, **values)
    E = Layer(f"{L.name}'s {name}", img, r.topLeft())
    E.blend = blend
    return E, above


def run(api, name, fn, params, pad_fn):
    doc = api.current_document()
    if doc is None:
        return
    doc.commit_floating()
    L = doc.active
    if L.background:
        api.status("Layer styles can't be applied to the Background. Double-click it to make it a normal layer.")
        return
    state = {"temp": None}

    def remove_temp():
        T = state["temp"]
        if T is not None and T in doc.layers:
            doc.layers.remove(T)
            doc.invalidate(QRect())
            doc.layersChanged.emit()
        state["temp"] = None

    def preview(values):
        remove_temp()
        if values is None or L not in doc.layers:
            return
        E, above = make_effect_layer(doc, L, name, fn, values, pad_fn(values))
        if E is None:
            return
        i = doc.layers.index(L)
        doc.layers.insert(i + 1 if above else i, E)
        state["temp"] = E
        doc.invalidate(E.rect())
        doc.layersChanged.emit()
    values = api.ask_params(name, params, preview)
    remove_temp()
    if values is None:
        return None
    E, above = make_effect_layer(doc, L, name, fn, values, pad_fn(values))
    if E is None:
        return None
    i = doc.layers.index(L)
    active = doc.active
    doc.add_layer(layer=E, index=i + 1 if above else i, text=name)
    doc.set_active(active)
    return E


def register(api):
    global ops, _api
    ops, _api = api.imageops, api

    def S(key, label, lo, hi, default, suffix=""):
        return {"key": key, "label": label, "min": lo, "max": hi, "default": default, "suffix": suffix}

    def col(key, label, default):
        return {"key": key, "label": label, "type": "color", "default": default}

    M = "Layer/Layer Style"
    effects = [
        ("Drop Shadow", drop_shadow, [col("color", "Color", QColor(0, 0, 0)), S("opacity", "Opacity", 0, 100, 75, "%"),
                                      S("angle", "Angle", -180, 180, 120, "°"), S("distance", "Distance", 0, 300, 5, " px"),
                                      S("spread", "Spread", 0, 100, 0, "%"), S("size", "Size", 0, 250, 5, " px")],
         lambda v: v["distance"] + v["size"] + 4),
        ("Outer Glow", outer_glow, [col("color", "Color", QColor(255, 255, 190)), S("opacity", "Opacity", 0, 100, 75, "%"),
                                    S("spread", "Spread", 0, 100, 0, "%"), S("size", "Size", 0, 250, 10, " px")],
         lambda v: v["size"] + 4),
        ("Inner Shadow", inner_shadow, [col("color", "Color", QColor(0, 0, 0)), S("opacity", "Opacity", 0, 100, 75, "%"),
                                        S("angle", "Angle", -180, 180, 120, "°"), S("distance", "Distance", 0, 300, 5, " px"),
                                        S("size", "Size", 0, 250, 5, " px")], lambda v: 0),
        ("Inner Glow", inner_glow, [col("color", "Color", QColor(255, 255, 190)), S("opacity", "Opacity", 0, 100, 75, "%"),
                                    S("size", "Size", 0, 250, 10, " px")], lambda v: 0),
        ("Stroke", stroke, [col("color", "Color", lambda: api.ctx.fg), S("size", "Size", 1, 250, 3, " px"),
                            {"key": "position", "label": "Position", "type": "choice", "items": ["Outside", "Inside", "Center"]},
                            S("opacity", "Opacity", 0, 100, 100, "%")], lambda v: v["size"] + 2),
        ("Color Overlay", color_overlay, [col("color", "Color", lambda: api.ctx.fg), S("opacity", "Opacity", 0, 100, 100, "%"),
                                          {"key": "blend", "label": "Blend Mode", "type": "choice",
                                           "items": ["Normal", "Multiply", "Screen", "Overlay", "Color"]}], lambda v: 0),
        ("Gradient Overlay", gradient_overlay, [col("start", "From", lambda: api.ctx.fg), col("end", "To", lambda: api.ctx.bg),
                                                S("opacity", "Opacity", 0, 100, 100, "%"), S("angle", "Angle", -180, 180, 90, "°"),
                                                {"key": "reverse", "label": "Reverse", "type": "check"}], lambda v: 0),
        ("Bevel & Emboss", bevel_emboss, [S("depth", "Depth", 1, 1000, 100, "%"), S("size", "Size", 1, 100, 6, " px"),
                                          S("angle", "Angle", -180, 180, 120, "°"), S("altitude", "Altitude", 0, 90, 30, "°")],
         lambda v: 0),
    ]
    register.run = {}
    for name, fn, params, pad in effects:
        go = (lambda n=name, f=fn, p=params, pd=pad: run(api, n, f, p, pd))
        api.add_menu_action(M, name + "…", go)
        register.run[name] = go
