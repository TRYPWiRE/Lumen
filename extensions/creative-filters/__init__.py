"""Creative Filters: Photoshop's Blur, Distort, Noise, Pixelate, Render, Stylize and Other filters."""
import math
import numpy as np

ops = None
_api = None


# --------------------------------------------------------------------------- helpers
def to_arr(img):
    """Premultiplied float32 (h, w, 4) — blurring/warping premultiplied pixels avoids dark fringes."""
    src = ops.to_working(img).copy()
    return np.array(ops.view(src), dtype=np.float32)


def to_img(arr):
    return ops.from_array(np.clip(arr + 0.5, 0, 255).astype(np.uint8))


def straight(img):
    a = ops.straight_array(img).astype(np.float32)
    return a


def from_straight(a):
    return ops.from_array(np.clip(a + 0.5, 0, 255).astype(np.uint8), ops.STRAIGHT).convertToFormat(ops.PREMUL)


def remap(arr, xs, ys):
    """Bilinear sample arr (h, w, c) at float coordinates (edge-clamped)."""
    h, w = arr.shape[:2]
    xs = np.clip(xs, 0, w - 1)
    ys = np.clip(ys, 0, h - 1)
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (xs - x0)[..., None]
    fy = (ys - y0)[..., None]
    top = arr[y0, x0] * (1 - fx) + arr[y0, x1] * fx
    bot = arr[y1, x0] * (1 - fx) + arr[y1, x1] * fx
    return top * (1 - fy) + bot * fy


def grid(h, w):
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    return xs, ys


def box(p, r, axis):
    if r < 1:
        return p
    n = p.shape[axis]
    pad = [(0, 0)] * p.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(p, pad, mode="edge"), axis=axis, dtype=np.float32)
    sl_hi = [slice(None)] * p.ndim
    sl_lo = [slice(None)] * p.ndim
    sl_hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
    sl_lo[axis] = slice(0, n)
    return (c[tuple(sl_hi)] - c[tuple(sl_lo)]) / (2 * r + 1)


def blur(arr, r):
    r = int(max(0, round(r)))
    for _ in range(3):
        arr = box(box(arr, r, 0), r, 1)
    return arr


def luminance(a):
    return a[..., 2] * 0.299 + a[..., 1] * 0.587 + a[..., 0] * 0.114


def rolling(arr, r, fn):
    """Square min/max filter of radius r (separable, shifts)."""
    out = arr
    for axis in (0, 1):
        pad = [(0, 0)] * arr.ndim
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        n = out.shape[axis]
        acc = None
        for k in range(2 * r + 1):
            sl = [slice(None)] * arr.ndim
            sl[axis] = slice(k, k + n)
            acc = p[tuple(sl)] if acc is None else fn(acc, p[tuple(sl)])
        out = acc
    return out


# --------------------------------------------------------------------------- blur
def motion_blur(img, angle=0, distance=10):
    a = to_arr(img)
    h, w = a.shape[:2]
    rad = math.radians(angle)
    dx, dy = math.cos(rad), -math.sin(rad)
    n = int(min(max(2, distance), 64))
    acc = np.zeros_like(a)
    xs, ys = grid(h, w)
    for k in range(n):
        t = (k / (n - 1) - 0.5) * distance
        acc += remap(a, xs + dx * t, ys + dy * t)
    return to_img(acc / n)


def radial_blur(img, amount=10, method=0):
    a = to_arr(img)
    h, w = a.shape[:2]
    xs, ys = grid(h, w)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    n = 24
    acc = np.zeros_like(a)
    for k in range(n):
        t = k / (n - 1) - 0.5
        if method == 0:                          # spin
            ang = math.radians(amount) * t
            c, s = math.cos(ang), math.sin(ang)
            sx = cx + (xs - cx) * c - (ys - cy) * s
            sy = cy + (xs - cx) * s + (ys - cy) * c
        else:                                    # zoom
            f = 1 + amount / 100.0 * t * 0.5
            sx = cx + (xs - cx) * f
            sy = cy + (ys - cy) * f
        acc += remap(a, sx, sy)
    return to_img(acc / n)


# --------------------------------------------------------------------------- distort
def _polar(img):
    a = to_arr(img)
    h, w = a.shape[:2]
    xs, ys = grid(h, w)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    R = min(cx, cy) or 1
    dx, dy = xs - cx, ys - cy
    r = np.hypot(dx, dy)
    return a, xs, ys, cx, cy, R, dx, dy, r


def twirl(img, angle=50):
    a, xs, ys, cx, cy, R, dx, dy, r = _polar(img)
    d = np.clip(1 - r / R, 0, 1)
    rot = np.radians(angle) * d * d
    c, s = np.cos(rot), np.sin(rot)
    return to_img(remap(a, cx + dx * c - dy * s, cy + dx * s + dy * c))


def pinch(img, amount=50):
    a, xs, ys, cx, cy, R, dx, dy, r = _polar(img)
    d = np.clip(r / R, 1e-6, 1)
    # positive amount samples further out, squeezing the middle inwards (negative bulges it)
    scale = np.where(r < R, np.power(np.sin(np.pi / 2 * d), -amount / 100.0), 1.0)
    return to_img(remap(a, cx + dx * scale, cy + dy * scale))


def spherize(img, amount=100, mode=0):
    a, xs, ys, cx, cy, R, dx, dy, r = _polar(img)
    if mode == 1:
        R = cx or 1
        dy = dy * 0
        r = np.abs(dx)
    elif mode == 2:
        R = cy or 1
        dx = dx * 0
        r = np.abs(dy)
    d = np.clip(r / R, 0, 1)
    k = amount / 100.0
    bulge = np.where(d > 0, (2 / np.pi) * np.arcsin(np.clip(d, 0, 1)) / np.maximum(d, 1e-6), 1)
    pinchf = np.where(d > 0, np.sin(np.pi / 2 * d) / np.maximum(d, 1e-6), 1)
    f = 1 + (bulge - 1) * k if k >= 0 else 1 + (pinchf - 1) * (-k)
    f = np.where(r < R, f, 1)
    cxs, cys = (cx + dx * f) if mode != 2 else xs, (cy + dy * f) if mode != 1 else ys
    return to_img(remap(a, cxs, cys))


def ripple(img, amount=100, size=1):
    a = to_arr(img)
    h, w = a.shape[:2]
    xs, ys = grid(h, w)
    wl = [10, 20, 40][size]
    amp = amount / 100.0 * [1.0, 1.6, 2.5][size]
    return to_img(remap(a, xs + amp * np.sin(2 * np.pi * ys / wl), ys + amp * np.sin(2 * np.pi * xs / wl)))


def wave(img, wavelength=120, amplitude=12, kind=0, horizontal=100, vertical=100):
    a = to_arr(img)
    h, w = a.shape[:2]
    xs, ys = grid(h, w)

    def f(t):
        p = (t / max(wavelength, 1)) % 1.0
        if kind == 1:
            return 1 - 4 * np.abs(p - 0.5)
        if kind == 2:
            return np.where(p < 0.5, 1.0, -1.0)
        return np.sin(2 * np.pi * p)
    return to_img(remap(a, xs + amplitude * horizontal / 100 * f(ys), ys + amplitude * vertical / 100 * f(xs)))


def polar_coordinates(img, mode=0):
    a = to_arr(img)
    h, w = a.shape[:2]
    xs, ys = grid(h, w)
    cx, cy = w / 2, h / 2
    if mode == 0:     # rectangular to polar
        dx, dy = xs - cx, ys - cy
        ang = (np.arctan2(dx, -dy) / (2 * np.pi)) % 1.0
        r = np.hypot(dx / cx, dy / cy)
        sx, sy = ang * (w - 1), r * (h - 1)
    else:             # polar to rectangular
        ang = xs / max(w - 1, 1) * 2 * np.pi
        r = ys / max(h - 1, 1)
        sx = cx + np.sin(ang) * r * cx
        sy = cy - np.cos(ang) * r * cy
    return to_img(remap(a, sx, sy))


# --------------------------------------------------------------------------- noise
def _median(a, r):
    from numpy.lib.stride_tricks import sliding_window_view
    p = np.pad(a, ((r, r), (r, r), (0, 0)), mode="edge")
    out = np.empty_like(a)
    h = a.shape[0]
    step = max(1, 2_000_000 // max(1, a.shape[1] * (2 * r + 1) ** 2))
    for y0 in range(0, h, step):
        y1 = min(h, y0 + step)
        win = sliding_window_view(p[y0:y1 + 2 * r], (2 * r + 1, 2 * r + 1), axis=(0, 1))
        out[y0:y1] = np.median(win.reshape(win.shape[0], win.shape[1], win.shape[2], -1), axis=-1)
    return out


def median(img, radius=2):
    return to_img(_median(to_arr(img), int(radius)))


def dust_scratches(img, radius=2, threshold=10):
    a = to_arr(img)
    m = _median(a, int(radius))
    diff = np.abs(a - m).max(axis=-1, keepdims=True)
    return to_img(np.where(diff > threshold, m, a))


def diffuse(img, amount=2):
    a = to_arr(img)
    h, w = a.shape[:2]
    rng = np.random.default_rng(7)
    xs, ys = grid(h, w)
    return to_img(remap(a, np.round(xs + rng.uniform(-amount, amount, (h, w))),
                        np.round(ys + rng.uniform(-amount, amount, (h, w)))))


# --------------------------------------------------------------------------- pixelate
def color_halftone(img, radius=8, c_angle=108, m_angle=162, y_angle=90):
    s = straight(img)
    h, w = s.shape[:2]
    rgb = s[..., [2, 1, 0]] / 255.0
    cell = max(4, int(radius)) * 2
    xs, ys = grid(h, w)
    out = np.ones((h, w, 3), np.float32)
    smooth = blur(rgb.copy(), cell // 4)
    for ch, ang in ((0, c_angle), (1, m_angle), (2, y_angle)):
        t = math.radians(ang)
        c, si = math.cos(t), math.sin(t)
        u = xs * c + ys * si
        v = -xs * si + ys * c
        cu = (np.floor(u / cell) + 0.5) * cell
        cv = (np.floor(v / cell) + 0.5) * cell
        px = cu * c - cv * si
        py = cu * si + cv * c
        ink = 1 - remap(smooth[..., ch:ch + 1], px, py)[..., 0]           # amount of C, M or Y
        dist = np.hypot(u - cu, v - cv)
        rdot = cell * 0.7071 * np.sqrt(np.clip(ink, 0, 1))
        cover = np.clip(rdot - dist + 0.5, 0, 1)
        out[..., ch] = 1 - cover
    res = s.copy()
    res[..., 2], res[..., 1], res[..., 0] = out[..., 0] * 255, out[..., 1] * 255, out[..., 2] * 255
    return from_straight(res)


def crystallize(img, cell=10):
    a = to_arr(img)
    h, w = a.shape[:2]
    cell = max(3, int(cell))
    gh, gw = h // cell + 2, w // cell + 2
    rng = np.random.default_rng(11)
    px = (np.arange(gw)[None, :] + rng.uniform(0.1, 0.9, (gh, gw))) * cell
    py = (np.arange(gh)[:, None] + rng.uniform(0.1, 0.9, (gh, gw))) * cell
    xs, ys = grid(h, w)
    gx, gy = (xs // cell).astype(np.int32), (ys // cell).astype(np.int32)
    best = np.full((h, w), np.inf, np.float32)
    bx = np.zeros((h, w), np.float32)
    by = np.zeros((h, w), np.float32)
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            cy_ = np.clip(gy + oy, 0, gh - 1)
            cx_ = np.clip(gx + ox, 0, gw - 1)
            qx, qy = px[cy_, cx_], py[cy_, cx_]
            d = (qx - xs) ** 2 + (qy - ys) ** 2
            better = d < best
            best = np.where(better, d, best)
            bx = np.where(better, qx, bx)
            by = np.where(better, qy, by)
    return to_img(remap(a, bx, by))


# --------------------------------------------------------------------------- render
def _noise(h, w, seed, octaves=6):
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = 2 ** (o + 2)
        g = rng.random((cells + 2, cells + 2)).astype(np.float32)
        ys = np.linspace(0, cells, h, dtype=np.float32)
        xs = np.linspace(0, cells, w, dtype=np.float32)
        X, Y = np.meshgrid(xs, ys)
        x0, y0 = X.astype(np.int32), Y.astype(np.int32)
        fx, fy = X - x0, Y - y0
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        top = g[y0, x0] * (1 - fx) + g[y0, x0 + 1] * fx
        bot = g[y0 + 1, x0] * (1 - fx) + g[y0 + 1, x0 + 1] * fx
        out += (top * (1 - fy) + bot * fy) * amp
        total += amp
        amp *= 0.5
    return out / total


def clouds(img, seed=1):
    s = straight(img)
    h, w = s.shape[:2]
    n = _noise(h, w, int(seed))[..., None]
    fg, bg = _api.ctx.fg, _api.ctx.bg
    c0 = np.array([fg.blue(), fg.green(), fg.red()], np.float32)
    c1 = np.array([bg.blue(), bg.green(), bg.red()], np.float32)
    s[..., :3] = c0 + (c1 - c0) * n
    s[..., 3] = 255
    return from_straight(s)


def difference_clouds(img, seed=2):
    s = straight(img)
    c = straight(clouds(img, seed))
    s[..., :3] = np.abs(s[..., :3] - c[..., :3])
    return from_straight(s)


def vignette(img, amount=-50, midpoint=50):
    s = straight(img)
    h, w = s.shape[:2]
    xs, ys = grid(h, w)
    d = np.hypot((xs - w / 2) / (w / 2), (ys - h / 2) / (h / 2)) / math.sqrt(2)
    m = midpoint / 100.0
    t = np.clip((d - m * 0.7) / max(1 - m * 0.7, 1e-3), 0, 1) ** 2
    k = amount / 100.0
    rgb = s[..., :3]
    s[..., :3] = rgb * (1 + k * t[..., None]) if k < 0 else rgb + (255 - rgb) * k * t[..., None]
    return from_straight(s)


# --------------------------------------------------------------------------- stylize
def emboss(img, angle=135, height=3, amount=100):
    s = straight(img)
    L = luminance(s)
    t = math.radians(angle)
    dx, dy = math.cos(t) * height, -math.sin(t) * height
    h, w = L.shape
    xs, ys = grid(h, w)
    shifted = remap(L[..., None], xs + dx, ys + dy)[..., 0]
    g = np.clip(128 + (L - shifted) * amount / 100.0, 0, 255)
    s[..., 0] = s[..., 1] = s[..., 2] = g
    return from_straight(s)


def find_edges(img):
    s = straight(img)
    rgb = s[..., :3]
    p = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), mode="edge")
    gx = (p[1:-1, 2:] - p[1:-1, :-2]) * 2 + (p[:-2, 2:] - p[:-2, :-2]) + (p[2:, 2:] - p[2:, :-2])
    gy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 2 + (p[2:, :-2] - p[:-2, :-2]) + (p[2:, 2:] - p[:-2, 2:])
    s[..., :3] = 255 - np.clip(np.hypot(gx, gy) / 4, 0, 255)
    return from_straight(s)


def solarize(img):
    s = straight(img)
    s[..., :3] = np.minimum(s[..., :3], 255 - s[..., :3]) * 2      # positive and negative blended
    return from_straight(s)


def oil_paint(img, radius=4):
    """Kuwahara filter: each pixel takes the mean of its least-varied quadrant."""
    s = straight(img)
    rgb = s[..., :3]
    L = luminance(s)
    r = int(max(1, radius))
    h, w = L.shape

    def win_mean(x):
        return box(box(x, r // 2 + 1, 0), r // 2 + 1, 1)
    m = win_mean(rgb)
    mL = win_mean(L[..., None])[..., 0]
    vL = win_mean((L * L)[..., None])[..., 0] - mL * mL
    xs, ys = grid(h, w)
    off = r / 2 + 0.5
    best_v = np.full((h, w), np.inf, np.float32)
    out = np.zeros_like(rgb)
    for ox, oy in ((-off, -off), (off, -off), (-off, off), (off, off)):
        v = remap(vL[..., None], xs + ox, ys + oy)[..., 0]
        mm = remap(m, xs + ox, ys + oy)
        better = v < best_v
        best_v = np.where(better, v, best_v)
        out = np.where(better[..., None], mm, out)
    s[..., :3] = out
    return from_straight(s)


# --------------------------------------------------------------------------- other
def high_pass(img, radius=10):
    s = straight(img)
    rgb = s[..., :3]
    s[..., :3] = np.clip(rgb - blur(rgb.copy(), radius / 3) + 128, 0, 255)
    return from_straight(s)


def minimum(img, radius=1):
    return to_img(rolling(to_arr(img), int(radius), np.minimum))


def maximum(img, radius=1):
    return to_img(rolling(to_arr(img), int(radius), np.maximum))


def offset(img, horizontal=50, vertical=50, wrap=True):
    a = to_arr(img)
    if wrap:
        return to_img(np.roll(np.roll(a, int(vertical), axis=0), int(horizontal), axis=1))
    h, w = a.shape[:2]
    out = np.zeros_like(a)
    dx, dy = int(horizontal), int(vertical)
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = a[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return to_img(out)


# --------------------------------------------------------------------------- registration
def register(api):
    global ops, _api
    ops, _api = api.imageops, api

    def S(key, label, lo, hi, default, suffix="", decimals=0):
        return {"key": key, "label": label, "min": lo, "max": hi, "default": default, "suffix": suffix,
                "decimals": decimals}

    def C(key, label, items, default=0):
        return {"key": key, "label": label, "type": "choice", "items": items, "default": default}

    F = "Filter"
    api.add_filter(F + "/Blur", "Motion Blur…", motion_blur, [S("angle", "Angle", -90, 90, 0, "°"),
                                                               S("distance", "Distance", 1, 500, 10, " px")])
    api.add_filter(F + "/Blur", "Radial Blur…", radial_blur, [S("amount", "Amount", 1, 100, 10),
                                                               C("method", "Blur Method", ["Spin", "Zoom"])])
    D = F + "/Distort"
    api.add_filter(D, "Pinch…", pinch, [S("amount", "Amount", -100, 100, 50, "%")])
    api.add_filter(D, "Polar Coordinates…", polar_coordinates,
                   [C("mode", "Mode", ["Rectangular to Polar", "Polar to Rectangular"])])
    api.add_filter(D, "Ripple…", ripple, [S("amount", "Amount", -999, 999, 100, "%"),
                                          C("size", "Size", ["Small", "Medium", "Large"], 1)])
    api.add_filter(D, "Spherize…", spherize, [S("amount", "Amount", -100, 100, 100, "%"),
                                              C("mode", "Mode", ["Normal", "Horizontal only", "Vertical only"])])
    api.add_filter(D, "Twirl…", twirl, [S("angle", "Angle", -999, 999, 50, "°")])
    api.add_filter(D, "Wave…", wave, [S("wavelength", "Wavelength", 2, 999, 120, " px"),
                                      S("amplitude", "Amplitude", 1, 999, 12, " px"),
                                      C("kind", "Type", ["Sine", "Triangle", "Square"]),
                                      S("horizontal", "Horizontal Scale", 0, 100, 100, "%"),
                                      S("vertical", "Vertical Scale", 0, 100, 100, "%")])
    N = F + "/Noise"
    api.add_filter(N, "Dust & Scratches…", dust_scratches, [S("radius", "Radius", 1, 10, 2, " px"),
                                                             S("threshold", "Threshold", 0, 255, 10, " levels")])
    api.add_filter(N, "Median…", median, [S("radius", "Radius", 1, 10, 2, " px")])
    P = F + "/Pixelate"
    api.add_filter(P, "Color Halftone…", color_halftone, [S("radius", "Max. Radius", 4, 127, 8, " px"),
                                                           S("c_angle", "Cyan angle", 0, 360, 108, "°"),
                                                           S("m_angle", "Magenta angle", 0, 360, 162, "°"),
                                                           S("y_angle", "Yellow angle", 0, 360, 90, "°")])
    api.add_filter(P, "Crystallize…", crystallize, [S("cell", "Cell Size", 3, 300, 10)])
    R = F + "/Render"
    api.add_filter(R, "Clouds", clouds)
    api.add_filter(R, "Difference Clouds", difference_clouds)
    api.add_filter(R, "Vignette…", vignette, [S("amount", "Amount", -100, 100, -50),
                                              S("midpoint", "Midpoint", 0, 100, 50)])
    St = F + "/Stylize"
    api.add_filter(St, "Diffuse…", diffuse, [S("amount", "Amount", 1, 20, 2, " px")])
    api.add_filter(St, "Emboss…", emboss, [S("angle", "Angle", -180, 180, 135, "°"), S("height", "Height", 1, 10, 3, " px"),
                                           S("amount", "Amount", 1, 500, 100, "%")])
    api.add_filter(St, "Find Edges", find_edges)
    api.add_filter(St, "Oil Paint…", oil_paint, [S("radius", "Stylization", 1, 10, 4)])
    api.add_filter(St, "Solarize", solarize)
    O = F + "/Other"
    api.add_filter(O, "High Pass…", high_pass, [S("radius", "Radius", 1, 250, 10, " px")])
    api.add_filter(O, "Maximum…", maximum, [S("radius", "Radius", 1, 20, 1, " px")])
    api.add_filter(O, "Minimum…", minimum, [S("radius", "Radius", 1, 20, 1, " px")])
    api.add_filter(O, "Offset…", offset, [S("horizontal", "Horizontal", -2000, 2000, 50, " px right"),
                                          S("vertical", "Vertical", -2000, 2000, 50, " px down"),
                                          {"key": "wrap", "label": "Wrap Around", "type": "check", "default": True}])
