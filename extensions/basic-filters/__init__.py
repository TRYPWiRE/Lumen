"""Basic Filters for Lumen. All maths is numpy on premultiplied pixels so transparency blurs correctly."""
import math
import numpy as np

_ops = None  # api.imageops, set in register()


# ---------------------------------------------------------------- pixel helpers
def _to_float(img):
    """QImage -> float32 (h, w, 4) premultiplied BGRA."""
    return _ops.view(_ops.to_working(img).copy()).astype(np.float32)


def _to_image(arr):
    return _ops.from_array(np.clip(arr + 0.5, 0, 255).astype(np.uint8))


def _straight(img):
    """QImage -> float32 straight-alpha BGRA."""
    return _ops.straight_array(img).astype(np.float32)


def _from_straight(arr):
    return _ops.from_array(np.clip(arr + 0.5, 0, 255).astype(np.uint8), _ops.STRAIGHT).convertToFormat(_ops.PREMUL)


def _box_axis(a, r, axis):
    """Box blur of a 2-D float32 plane along one axis (running sum, edge-clamped)."""
    if r < 1:
        return a
    n = a.shape[axis]
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
    if axis == 0:
        return (c[2 * r + 1:2 * r + 1 + n] - c[:n]) * (1.0 / (2 * r + 1))
    return (c[:, 2 * r + 1:2 * r + 1 + n] - c[:, :n]) * (1.0 / (2 * r + 1))


def _planes(fn, a):
    """Apply fn to each channel plane of (h, w, c) data; values centred on 0 for float32 accuracy."""
    out = np.empty_like(a)
    for ch in range(a.shape[-1]):
        plane = np.ascontiguousarray(a[..., ch]) - 127.5
        out[..., ch] = fn(plane) + 127.5
    return out


def box_blur(a, r):
    return _planes(lambda p: _box_axis(np.ascontiguousarray(_box_axis(p, r, 1).T), r, 1).T, a)


def _boxes_for_gauss(sigma, n=3):
    w_ideal = math.sqrt(12 * sigma * sigma / n + 1)
    wl = int(math.floor(w_ideal))
    if wl % 2 == 0:
        wl -= 1
    wu = wl + 2
    m_ideal = (12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4)
    m = round(m_ideal)
    return [wl if i < m else wu for i in range(n)]


def gaussian(a, sigma):
    if sigma < 0.3:
        return a
    radii = [(w - 1) // 2 for w in _boxes_for_gauss(sigma)]

    def blur(p):
        for r in radii:                 # rows (cache-friendly)
            p = _box_axis(p, r, 1)
        p = np.ascontiguousarray(p.T)   # then columns, as rows of the transpose
        for r in radii:
            p = _box_axis(p, r, 1)
        return p.T
    return _planes(blur, a)


# ---------------------------------------------------------------- filters
def f_gaussian(img, radius=2.0):
    return _to_image(gaussian(_to_float(img), radius))


def f_box(img, radius=3):
    return _to_image(box_blur(_to_float(img), int(radius)))


def f_blur(img):
    return _to_image(gaussian(_to_float(img), 1.0))


def f_unsharp(img, amount=100, radius=1.0, threshold=0):
    a = _straight(img)
    rgb = a[..., :3]
    diff = rgb - gaussian(rgb.copy(), radius)
    if threshold > 0:
        mask = (np.abs(diff).max(axis=2, keepdims=True) >= threshold)
        diff = diff * mask
    a[..., :3] = rgb + diff * (amount / 100.0)
    return _from_straight(a)


def f_sharpen(img):
    return f_unsharp(img, 60, 1.0, 0)


def f_noise(img, amount=10):
    a = _straight(img)
    rng = np.random.default_rng()
    a[..., :3] += rng.uniform(-1, 1, a[..., :3].shape).astype(np.float32) * (amount * 2.55)
    return _from_straight(a)


def f_mosaic(img, cell=10):
    cell = max(2, int(cell))
    a = _to_float(img)
    h, w = a.shape[:2]
    H, W = -(-h // cell) * cell, -(-w // cell) * cell
    p = np.pad(a, ((0, H - h), (0, W - w), (0, 0)), mode="edge")
    blocks = p.reshape(H // cell, cell, W // cell, cell, 4).mean(axis=(1, 3))
    out = np.repeat(np.repeat(blocks, cell, axis=0), cell, axis=1)[:h, :w]
    return _to_image(out)


def f_brightness_contrast(img, brightness=0, contrast=0):
    a = _straight(img)
    rgb = a[..., :3] + brightness
    c = contrast * 2.55
    factor = (259 * (c + 255)) / (255 * (259 - c))
    a[..., :3] = (rgb - 127.5) * factor + 127.5
    return _from_straight(a)


def f_posterize(img, levels=4):
    levels = max(2, int(levels))
    a = _straight(img)
    step = 255.0 / (levels - 1)
    a[..., :3] = np.round(np.round(a[..., :3] / step) * step)
    return _from_straight(a)


def f_threshold(img, level=128):
    a = _straight(img)
    lum = a[..., 2] * 0.299 + a[..., 1] * 0.587 + a[..., 0] * 0.114
    v = np.where(lum >= level, 255.0, 0.0).astype(np.float32)
    a[..., 0] = a[..., 1] = a[..., 2] = v
    return _from_straight(a)


# ---------------------------------------------------------------- registration
def register(api):
    global _ops
    _ops = api.imageops

    def P(key, label, lo, hi, default, suffix="", decimals=0):
        return {"key": key, "label": label, "min": lo, "max": hi, "default": default,
                "suffix": suffix, "decimals": decimals}

    api.add_filter("Filter/Blur", "Blur", f_blur)
    api.add_filter("Filter/Blur", "Box Blur…", f_box, [P("radius", "Radius", 1, 250, 3, " px")])
    api.add_filter("Filter/Blur", "Gaussian Blur…", f_gaussian, [P("radius", "Radius", 0.1, 250, 2.0, " px", 1)])
    api.add_filter("Filter/Sharpen", "Sharpen", f_sharpen)
    api.add_filter("Filter/Sharpen", "Unsharp Mask…", f_unsharp,
                   [P("amount", "Amount", 1, 500, 100, " %"), P("radius", "Radius", 0.1, 250, 1.0, " px", 1),
                    P("threshold", "Threshold", 0, 255, 0, " levels")])
    api.add_filter("Filter/Noise", "Add Noise…", f_noise, [P("amount", "Amount", 0, 100, 10, " %", 1)])
    api.add_filter("Filter/Pixelate", "Mosaic…", f_mosaic, [P("cell", "Cell Size", 2, 200, 10, " px")])
    api.add_filter("Image/Adjustments", "Brightness/Contrast…", f_brightness_contrast,
                   [P("brightness", "Brightness", -150, 150, 0), P("contrast", "Contrast", -50, 100, 0)])
    api.add_filter("Image/Adjustments", "Posterize…", f_posterize, [P("levels", "Levels", 2, 255, 4)])
    api.add_filter("Image/Adjustments", "Threshold…", f_threshold, [P("level", "Threshold Level", 1, 255, 128)])
