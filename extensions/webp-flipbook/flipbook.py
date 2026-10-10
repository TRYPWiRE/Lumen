"""Flipbook / sprite-sheet slicing and GIF writing (ported from the File Converter's WebP Flipbook tab)."""
import os

import numpy as np

from lumen import media

DEFAULT_FPS = 12
MAX_PREVIEW_FRAMES = 200
ALPHA_THRESHOLD = 128              # GIF transparency is all-or-nothing
TRANSPARENT_INDEX = 255


def boundary_profile(image, axis):
    """Mean colour change between neighbouring columns/rows - sheet seams show up as spikes."""
    PIL = media.PIL
    scale = min(1.0, 900 / max(image.size))
    small = image.resize((max(2, int(image.width * scale)), max(2, int(image.height * scale))), PIL.BILINEAR) \
        if scale < 1 else image.copy()
    a = np.asarray(small.convert("RGB"), dtype="int16")
    if axis == "x":
        return np.abs(a[:, 1:] - a[:, :-1]).mean(axis=(0, 2))
    return np.abs(a[1:] - a[:-1]).mean(axis=(1, 2))


def repeating_period(profile, length):
    """Strongest repeating period (autocorrelation) in original pixels, or None."""
    if len(profile) < 8:
        return None
    v = profile.astype(float)
    v -= v.mean()
    corr = np.correlate(v, v, mode="full")[len(v) - 1:]
    scale = len(profile) / float(length)
    best_rows, best = None, -1e30
    for rows in range(1, min(24, length // 24) + 1):
        if length % rows:
            continue
        tile = length / rows
        if tile < 24:
            continue
        period = int(round(tile * scale))
        if period < 2 or period >= len(corr):
            continue
        score = float(corr[period])
        score *= 0.45 if rows == 1 else 0.75 if rows == 2 else 1.0
        if tile < 48:
            score *= 0.5
        if score > best:
            best, best_rows = score, rows
    if best_rows in (None, 1):
        return None
    return length // best_rows


def strong_split(profile, length):
    """A strong, evenly spaced split (catches common 2-8 column sheets)."""
    if len(profile) < 4:
        return 1
    median = float(np.median(profile)) + 1e-6
    thr = max(float(np.percentile(profile, 97)), median * 2.2)
    peaks = [(profile[i], (i + 1) / len(profile) * length) for i in range(1, len(profile) - 1)
             if profile[i] >= profile[i - 1] and profile[i] >= profile[i + 1] and profile[i] >= thr]
    # Lumen: prefer the column count whose seams are ALL present and that explains the most strong peaks,
    # so a 4-column sheet isn't mistaken for 2 columns just because its middle seam is the strongest
    tol = 0.012 * length
    best_cols, best_explained = 1, 0
    for cols in range(2, 9):
        seams = [length * k / cols for k in range(1, cols)]
        if not all(any(abs(pos - e) <= tol for _, pos in peaks) for e in seams):
            continue
        explained = sum(1 for _, pos in peaks if any(abs(pos - e) <= tol for e in seams))
        if explained > best_explained:
            best_cols, best_explained = cols, explained
    if best_cols > 1:
        return best_cols
    # the converter's original rule: the strongest peak that sits on an even split
    best_val = 0
    for value, pos in peaks:
        for cols in range(2, 9):
            expected = length * round(pos / (length / cols)) / cols
            if abs(pos - expected) / length < 0.012 and value > best_val:
                best_val, best_cols = value, cols
    return best_cols


def detect_grid(image, animated):
    """(columns, rows, reason)."""
    if animated:
        return 1, 1, "native animated WebP"
    rgb = image.convert("RGB")
    w, h = rgb.size
    cols = strong_split(boundary_profile(rgb, "x"), w)
    period = repeating_period(boundary_profile(rgb, "y"), h)
    rows = round(h / period) if period else 1
    cols, rows = max(1, min(cols, 12)), max(1, min(rows, 24))
    if w / cols < 32 or h / rows < 32:
        cols, rows = 1, 1
    return cols, rows, "sprite/flipbook grid detected"


def slice_sheet(image, cols, rows, order="row"):
    img = image.convert("RGBA")
    fw, fh = img.width // cols, img.height // rows
    if fw * cols != img.width or fh * rows != img.height:
        raise ValueError(f"The grid ({cols} × {rows}) doesn't divide the image exactly.\n"
                         f"Image size: {img.width} × {img.height}")
    cells = [(r, c) for r in range(rows) for c in range(cols)] if order == "row" else \
        [(r, c) for c in range(cols) for r in range(rows)]
    return [img.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh)) for r, c in cells]


def extract_frames(s, report=None):
    """(frames, durations, kind) for settings dict s (path or image, cols, rows, order, fps)."""
    PIL = media.PIL
    if s.get("image") is None:
        with PIL.Image.open(s["path"]) as f:
            f.load()
            if getattr(f, "n_frames", 1) > 1:
                frames, durs = media.read_frames(f)
                return frames, durs, "native"
            src = media.to_rgba(f)
    else:
        src = s["image"]
    if getattr(src, "n_frames", 1) > 1:
        frames, durs = [], []
        for fr in PIL.ImageSequence.Iterator(src):
            frames.append(fr.convert("RGBA").copy())
            durs.append(max(20, int(fr.info.get("duration", 100) or 100)))
        return frames, durs, "native"
    cols, rows = s.get("cols"), s.get("rows")
    if not cols or not rows:
        cols, rows, _ = detect_grid(src, False)
    if cols < 1 or rows < 1:
        raise ValueError("Rows and columns must be at least 1.")
    frames = slice_sheet(src, cols, rows, s.get("order", "row"))
    fps = float(s.get("fps", DEFAULT_FPS))
    if fps <= 0:
        raise ValueError("FPS must be greater than zero.")
    if report:
        report(f"Sliced {len(frames)} frames from a {cols} × {rows} sheet.")
    return frames, [max(1, int(round(1000 / fps)))] * len(frames), "sprite"


def frames_have_transparency(frames):
    return any(f.mode == "RGBA" and f.getchannel("A").getextrema()[0] < ALPHA_THRESHOLD for f in frames)


def quantize_frame(frame, keep_transparency, background=(255, 255, 255)):
    """RGBA → palette frame for GIF; reserves index 255 for see-through pixels when keeping transparency."""
    PIL = media.PIL
    rgba = frame.convert("RGBA")
    if not keep_transparency:
        flat = PIL.Image.new("RGBA", rgba.size, background + (255,))
        flat.alpha_composite(rgba)
        return flat.convert("RGB").quantize(colors=256, method=PIL.MEDIANCUT, dither=PIL.DITHER_FS), None
    mask = rgba.getchannel("A").point(lambda v: 255 if v < ALPHA_THRESHOLD else 0)
    opaque = PIL.Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    opaque.alpha_composite(rgba)
    pal = opaque.convert("RGB").quantize(colors=TRANSPARENT_INDEX, method=PIL.MEDIANCUT, dither=PIL.DITHER_FS)
    pal.paste(TRANSPARENT_INDEX, mask)
    return pal, TRANSPARENT_INDEX


def resize_frames(frames, size):
    if not size:
        return frames
    w, h = size
    if w < 1 or h < 1:
        raise ValueError("Resize dimensions must be greater than zero.")
    return [f.resize((w, h), media.PIL.LANCZOS) for f in frames]


def save_png_frames(frames, output_dir, base, job=None, start=0.0, span=1.0):
    folder = media.unique_path(os.path.join(output_dir, base + "_frames"))
    os.makedirs(folder, exist_ok=True)
    for i, f in enumerate(frames, start=1):
        f.save(os.path.join(folder, f"frame_{i:04d}.png"))
        if job:
            job.progress(start + span * i / len(frames))
    return folder


def gif_job(job, s):
    job.status("Extracting frames…")
    frames, durs, _ = extract_frames(s, job.status)
    frames = resize_frames(frames, s.get("resize"))
    if not frames:
        raise ValueError("No frames were found.")
    out_dir = s["output_dir"]
    os.makedirs(out_dir, exist_ok=True)
    out = s.get("output_path") or os.path.join(out_dir, s["base"] + ".gif")
    job.status(f"Encoding {len(frames)} frames…")
    job.progress(0.35)
    keep = s.get("transparency", True) and frames_have_transparency(frames)
    gif_frames, tindex = [], None
    for i, f in enumerate(frames):
        q, tindex = quantize_frame(f, keep)
        gif_frames.append(q)
        job.progress(0.35 + 0.45 * (i + 1) / len(frames))
    job.status("Writing GIF…")
    opts = {"save_all": True, "append_images": gif_frames[1:], "duration": durs, "loop": 0,
            "optimize": s.get("optimize", True) and not keep}
    if tindex is not None:
        opts["transparency"] = tindex
        opts["disposal"] = 2
    gif_frames[0].save(out, **opts)
    msg = (f"GIF created.\n\n{out}\n\nTransparent background: {'kept' if keep else 'no'}\nFrames: {len(frames)}\n"
           f"Size: {frames[0].width} × {frames[0].height}\nFile size: {media.format_size(os.path.getsize(out))}")
    folder = None
    if s.get("export_frames"):
        job.status("Exporting PNG frames…")
        folder = save_png_frames(frames, out_dir, s["base"], job, 0.8, 0.2)
        msg += f"\n\nPNG frames: {folder}"
    job.progress(1.0)
    job.status(f"Done — {os.path.basename(out)}")
    return {"title": "Conversion complete", "message": msg, "gif": out, "folder": folder}


def png_job(job, s):
    job.status("Extracting frames…")
    frames, _, _ = extract_frames(s, job.status)
    frames = resize_frames(frames, s.get("resize"))
    if not frames:
        raise ValueError("No frames were found.")
    os.makedirs(s["output_dir"], exist_ok=True)
    job.status(f"Writing {len(frames)} PNG frames…")
    folder = save_png_frames(frames, s["output_dir"], s["base"], job)
    job.progress(1.0)
    job.status(f"PNG frames exported — {os.path.basename(folder)}")
    return {"title": "PNG export complete", "message": f"Exported {len(frames)} PNG frame(s) to:\n\n{folder}",
            "folder": folder}
