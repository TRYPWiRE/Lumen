"""Decoding and writing for the Batch Converter (the File Converter's Images tab, plus animation)."""
import os

from lumen import media

# "Convert from" (file picker filter) - common formats first, camera RAW after
FORMATS = {
    "All Supported Formats": None,
    "JPG / JPEG": ["*.jpg", "*.jpeg"], "PNG": ["*.png"], "BMP": ["*.bmp"], "GIF": ["*.gif"],
    "TIFF": ["*.tif", "*.tiff"], "ICO": ["*.ico"], "PSD": ["*.psd"], "WEBP": ["*.webp"],
    "HEIC / HEIF": ["*.heic", "*.heif"], "AVIF": ["*.avif"], "SVG": ["*.svg"],
    "CR2 (Canon RAW)": ["*.cr2"], "CR3 (Canon RAW)": ["*.cr3"], "CRW (Canon RAW)": ["*.crw"],
    "NEF (Nikon RAW)": ["*.nef"], "ARW (Sony RAW)": ["*.arw"], "DNG (Adobe RAW)": ["*.dng"],
    "RAF (Fujifilm RAW)": ["*.raf"], "RW2 (Panasonic RAW)": ["*.rw2"], "ORF (Olympus RAW)": ["*.orf"],
    "PEF (Pentax RAW)": ["*.pef"], "DCR (Kodak RAW)": ["*.dcr"], "MRW (Minolta RAW)": ["*.mrw"],
    "MOS (Leaf RAW)": ["*.mos"], "3FR (Hasselblad RAW)": ["*.3fr"], "X3F (Sigma RAW)": ["*.x3f"],
    "ERF (Epson RAW)": ["*.erf"], "RAW (generic)": ["*.raw"],
}
FORMATS["All Supported Formats"] = [p for v in FORMATS.values() if v for p in v]
EXT_TO_FORMAT = {p[2:].lower(): name for name, pats in FORMATS.items() if name != "All Supported Formats"
                 for p in pats}

OUTPUT_FORMATS = {
    "PNG": {"ext": ".png", "pil": "PNG"},
    "JPG / JPEG": {"ext": ".jpg", "pil": "JPEG", "quality": 95},
    "WEBP": {"ext": ".webp", "pil": "WEBP", "quality": 95},
    "AVIF": {"ext": ".avif", "pil": "AVIF", "quality": 90},
    "BMP": {"ext": ".bmp", "pil": "BMP"},
    "GIF": {"ext": ".gif", "pil": "GIF"},
    "TIFF": {"ext": ".tif", "pil": "TIFF"},
    "ICO": {"ext": ".ico", "pil": "ICO"},
}
ANIMATED_OUT = {"GIF", "WEBP", "AVIF"}
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
MAX_FRAMES = 600


def output_formats():
    out = dict(OUTPUT_FORMATS)
    if not media.avif_supported():
        out.pop("AVIF")
    return out


def needs_camera_pack(path):
    ext = os.path.splitext(path)[1].lower()
    return (ext in media.HEIF_EXTS and not media.heif_supported()) or \
        (ext in media.RAW_EXTS and not media.raw_supported())


def decode(path):
    """In-memory decode (no disk writes): {"frames": [RGBA], "durations": [...], "size": (w, h)}."""
    img = media.open_any(path)
    try:
        if media.frame_count(img) > 1:
            frames, durs = media.read_frames(img, limit=MAX_FRAMES)
        else:
            frames, durs = [media.to_rgba(img)], [100]
            frames[0].load()
    finally:
        img.close()                      # Windows can't delete files that are still open
    return {"frames": frames, "durations": durs, "size": frames[0].size}


def prepare(image, pil_fmt, quality=None):
    """Handle each format's quirks: JPEG/BMP have no alpha (flatten on white), GIF needs a palette, ICO sizes."""
    Image = media.PIL.Image
    if pil_fmt in ("JPEG", "BMP"):
        bg = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "RGBA":
            bg.paste(image, mask=image.getchannel("A"))
        else:
            bg.paste(image.convert("RGB"))
        return bg, ({"quality": quality or 95} if pil_fmt == "JPEG" else {})
    if pil_fmt == "GIF":
        return image, {}
    if pil_fmt == "ICO":
        w, h = image.size
        return image, {"sizes": [s for s in ICO_SIZES if s[0] <= max(w, h)] or [(16, 16)]}
    if pil_fmt in ("WEBP", "AVIF"):
        return image, {"quality": quality or (95 if pil_fmt == "WEBP" else 90)}
    return image, {}


def write(decoded, out_path, fmt_name, spec=None, quality=None, keep_animation=True):
    """Resize (at save time, so changing the size never needs re-converting) and write."""
    fmt = OUTPUT_FORMATS[fmt_name]
    frames = decoded["frames"]
    if spec:
        frames = [media.resize_to_spec(f, spec) for f in frames]
    if keep_animation and len(frames) > 1 and fmt_name in ANIMATED_OUT:
        if fmt_name == "GIF":
            media.save_gif(frames, decoded["durations"], out_path)
        else:
            frames[0].save(out_path, fmt["pil"], save_all=True, append_images=frames[1:],
                           duration=decoded["durations"], loop=0, quality=quality or fmt.get("quality", 90))
        return out_path
    img = frames[0]
    if fmt_name == "GIF":
        media.save_gif([img], [100], out_path)
        return out_path
    prepared, kw = prepare(img, fmt["pil"], quality)
    prepared.save(out_path, fmt["pil"], **kw)
    return out_path


# ---------------------------------------------------------------- Lumen File ▸ Open / Save As support
def read_for_lumen(path):
    from PyQt6.QtGui import QImage
    with media.open_any(path) as img:
        if media.frame_count(img) > 1:
            img.seek(0)
        return media.pil_to_qimage(media.to_rgba(img))


def writer(fmt_name):
    def fn(qimage, path, doc=None):
        decoded = {"frames": [media.qimage_to_pil(qimage)], "durations": [100]}
        write(decoded, path, fmt_name)
    return fn
