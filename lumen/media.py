"""Shared building blocks for Lumen's file-conversion tools.

Batch Converter, Video to GIF, GIF Optimiser, Image Optimiser, WebP to GIF, Video to Image, WebP Flipbook and
Overlay Studio are separate extensions, but they share a lot: output-size presets, Discord / target-size
presets, file queues, animated previews, background workers and the GIF encoder. It all lives here so every
tool behaves the same way.

Pillow ("PIL") is only imported when a function needs it. The extensions declare it as a runtime pack, so
Lumen downloads it once when the first tool that needs it is installed. Video is read with Qt Multimedia,
which ships with Lumen.
"""
import bisect
import os
import tempfile

from PyQt6.QtCore import (Qt, QObject, QRunnable, QThreadPool, QTimer, pyqtSignal, QSize, QRectF, QEventLoop, QUrl,
                          QSettings, QBuffer, QByteArray, QIODevice, QPointF)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QImageReader, QGuiApplication, QBrush
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QComboBox, QSpinBox,
                             QCheckBox, QPushButton, QSlider, QGroupBox, QInputDialog, QProgressBar, QListWidget,
                             QListWidgetItem, QToolButton, QMenu, QDialog, QLineEdit, QScrollArea, QFrame,
                             QMessageBox, QFileDialog, QSizePolicy, QApplication)

from . import theme

# ====================================================================== constants (match the converter)
MIB = 1024 * 1024
TARGET_SIZE_PRESETS_MIB = [1, 8, 10, 20, 25, 50, 100, 500]
DISCORD_EMOJI_MAX_BYTES = 256 * 1024
DISCORD_EMOJI_SIZE_PX = 128
DISCORD_STICKER_MAX_BYTES = 512 * 1024
DISCORD_STICKER_SIZE_PX = 320
MAX_QUEUE = 50                     # files in a queue at once (the old converter allowed 10)

RESIZE_PRESET_ORIGINAL = "Original size"
RESIZE_PRESET_CUSTOM = "Custom…"
RESIZE_PRESETS = [
    (RESIZE_PRESET_ORIGINAL, None),
    ("Square 1:1 — 1080 × 1080", (1080, 1080)),
    ("Portrait 4:5 — 1080 × 1350", (1080, 1350)),
    ("Story / Reel 9:16 — 1080 × 1920", (1080, 1920)),
    ("Landscape 16:9 — 1920 × 1080", (1920, 1080)),
    ("Landscape 16:9 — 1280 × 720", (1280, 720)),
    ("Link preview 1.91:1 — 1200 × 630", (1200, 630)),
    ("Banner 3:1 — 1500 × 500", (1500, 500)),
    ("Icon 1:1 — 512 × 512", (512, 512)),
    (RESIZE_PRESET_CUSTOM, "custom"),
]
RESIZE_MODES = [
    ("Fit — whole image, padded", "fit"),
    ("Fill — crop to fill", "fill"),
    ("Stretch — ignore ratio", "stretch"),
]

IMAGE_FILTER = ("Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.tif *.tiff *.ico *.avif *.heic *.heif *.psd);;"
                "All files (*)")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".mpg", ".mpeg", ".3gp", ".ts", ".flv")
VIDEO_FILTER = "Videos (" + " ".join("*" + e for e in VIDEO_EXTS) + ");;All files (*)"


def format_size(num_bytes):
    num_bytes = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} B"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def size_change(new, old):
    """'1.2 MB (was 3.4 MB, 65% smaller)'"""
    if not old:
        return format_size(new)
    pct = 100 * (1 - new / old)
    return f"{format_size(new)} (was {format_size(old)}, {abs(pct):.0f}% {'smaller' if pct >= 0 else 'larger'})"


# ====================================================================== settings shared by the tools
def settings():
    override = os.environ.get("LUMEN_SETTINGS")
    return QSettings(override, QSettings.Format.IniFormat) if override else QSettings("Lumen", "Lumen")


def flag(key, default=False):
    v = settings().value(key, default)
    return v in (True, "true", 1, "1")


def set_flag(key, value):
    s = settings()
    s.setValue(key, bool(value))
    s.sync()


DELETE_ORIGINALS = "converter/delete_originals"
SHOW_FILENAMES = "converter/show_filenames"


# ====================================================================== Pillow helpers
def pil_available():
    try:
        import PIL.Image  # noqa: F401
        return True
    except ImportError:
        return False


class _PIL:
    """Lazy access to Pillow and the version-proof constants the tools use."""

    def __getattr__(self, name):
        from PIL import Image, ImageSequence
        R = getattr(Image, "Resampling", Image)
        Q = getattr(Image, "Quantize", Image)
        D = getattr(Image, "Dither", Image)
        values = {"Image": Image, "ImageSequence": ImageSequence, "LANCZOS": R.LANCZOS, "BILINEAR": R.BILINEAR,
                  "FASTOCTREE": Q.FASTOCTREE, "MEDIANCUT": Q.MEDIANCUT, "DITHER_NONE": D.NONE,
                  "DITHER_FS": D.FLOYDSTEINBERG}
        self.__dict__.update(values)
        if name not in values:
            raise AttributeError(name)
        return values[name]


PIL = _PIL()


def avif_supported():
    try:
        from PIL import features
        return bool(features.check("avif"))
    except Exception:
        return False


def heif_supported():
    try:
        import pillow_heif  # noqa: F401
        return True
    except ImportError:
        return False


def raw_supported():
    try:
        import rawpy  # noqa: F401
        return True
    except ImportError:
        return False


def register_heif():
    """Teach Pillow to open HEIC/HEIF (and AVIF via pillow-heif when Pillow lacks it)."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        if hasattr(pillow_heif, "register_avif_opener") and not avif_supported():
            try:
                pillow_heif.register_avif_opener()
            except Exception:
                pass
        return True
    except Exception:
        return False


class Deferred(Exception):
    """Raised by a file reader that will finish later (e.g. after downloading HEIC support): no error shown."""


RAW_EXTS = {".cr2", ".cr3", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".pef", ".dcr", ".mrw",
            ".mos", ".3fr", ".x3f", ".erf", ".raw"}
HEIF_EXTS = {".heic", ".heif"}


def to_rgba(img):
    """Any Pillow mode (incl. 16-bit / float) → RGBA."""
    if img.mode == "RGBA":
        return img.copy()
    try:
        return img.convert("RGBA")
    except (ValueError, OSError):
        return img.convert("I").point(lambda v: v / 256).convert("L").convert("RGBA")


def pil_to_qimage(img):
    img = img if img.mode == "RGBA" else to_rgba(img)
    return QImage(img.tobytes("raw", "RGBA"), img.width, img.height, img.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def qimage_to_pil(qimg):
    q = QImage(qimg).convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = q.constBits()
    ptr.setsize(q.sizeInBytes())
    raw = bytes(ptr)
    return PIL.Image.frombuffer("RGBA", (q.width(), q.height()), raw, "raw", "RGBA", q.bytesPerLine(), 1).copy()


def open_any(path):
    """Open any still image Lumen knows (Pillow, plus RAW via rawpy, HEIC via pillow-heif, PSD/SVG via Qt)."""
    ext = os.path.splitext(path)[1].lower()
    Image = PIL.Image
    if ext in RAW_EXTS:
        if not raw_supported():
            raise RuntimeError("Camera RAW support isn't installed yet.")
        import rawpy
        with rawpy.imread(path) as raw:
            return Image.fromarray(raw.postprocess())
    if ext in HEIF_EXTS:
        if not register_heif():
            raise RuntimeError("HEIC / HEIF support isn't installed yet.")
    if ext == ".avif" and not avif_supported():
        register_heif()
    if ext == ".psd":
        from . import psd as _psd
        from .document import Document
        data = _psd.read_psd(path)
        doc = Document(size=data["size"], layers=data["layers"])
        return qimage_to_pil(doc.flattened())
    try:
        img = Image.open(path)
        img.load()
        return img
    except Exception:
        q = QImageReader(path)
        q.setAutoTransform(True)
        qi = q.read()
        if qi.isNull():
            raise
        return qimage_to_pil(qi)


def open_bytes(data):
    """Pillow image from bytes; falls back to Qt's decoders (SVG, odd ICOs…)."""
    import io
    try:
        img = PIL.Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception:
        qi = QImage.fromData(QByteArray(data))
        if qi.isNull():
            raise ValueError("Unsupported or damaged image")
        return qimage_to_pil(qi)


def frame_count(img):
    return getattr(img, "n_frames", 1) if getattr(img, "is_animated", False) else 1


def read_frames(path_or_img, limit=None, min_duration=20):
    """All frames of a (possibly animated) image as RGBA Pillow images plus their durations (ms)."""
    opened = isinstance(path_or_img, (str, bytes, os.PathLike))
    img = path_or_img if not opened else (
        open_bytes(path_or_img) if isinstance(path_or_img, bytes) else open_any(path_or_img))
    frames, durations = [], []
    try:
        if frame_count(img) > 1:
            for i, fr in enumerate(PIL.ImageSequence.Iterator(img)):
                if limit and i >= limit:
                    break
                frames.append(to_rgba(fr))
                durations.append(max(min_duration, int(fr.info.get("duration", 100) or 100)))
        else:
            frames, durations = [to_rgba(img)], [100]
    finally:
        if opened:
            try:
                img.close()
            except Exception:
                pass
    return frames, durations


def has_transparency(img):
    return ("transparency" in img.info) or (img.mode in ("RGBA", "LA", "PA"))


# ---------------------------------------------------------------------- resizing (converter's ResizeOptions)
def resize_to_spec(image, spec):
    """Return `image` at exactly spec["size"] (fit = pad, fill = crop, stretch = squash)."""
    if not spec:
        return image
    Image = PIL.Image
    tw, th = spec["size"]
    mode = spec.get("mode", "fit")
    src = image if image.mode == "RGBA" else image.convert("RGBA")
    w, h = src.size
    if (w, h) == (tw, th):
        return src
    if not spec.get("upscale", True) and w <= tw and h <= th and mode != "stretch":
        canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        canvas.paste(src, ((tw - w) // 2, (th - h) // 2))
        return canvas
    if mode == "stretch":
        return src.resize((tw, th), PIL.LANCZOS)
    if mode == "fill":
        r = max(tw / w, th / h)
        scaled = src.resize((max(1, round(w * r)), max(1, round(h * r))), PIL.LANCZOS)
        left, top = (scaled.width - tw) // 2, (scaled.height - th) // 2
        return scaled.crop((left, top, left + tw, top + th))
    r = min(tw / w, th / h)
    scaled = src.resize((max(1, round(w * r)), max(1, round(h * r))), PIL.LANCZOS)
    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    canvas.paste(scaled, ((tw - scaled.width) // 2, (th - scaled.height) // 2))
    return canvas


def spec_adds_transparency(spec):
    return bool(spec) and spec.get("mode", "fit") == "fit"


def fit_in_square(frame, square, scale=1.0):
    """Scale `frame` to fit a square×square transparent canvas (content shrinks with `scale`)."""
    Image = PIL.Image
    box = max(int(square * scale), 16)
    w, h = frame.size
    r = min(box / w, box / h)
    nw, nh = max(1, int(w * r)), max(1, int(h * r))
    resized = frame.resize((nw, nh), PIL.LANCZOS)
    canvas = Image.new("RGBA", (square, square), (0, 0, 0, 0))
    canvas.paste(resized, ((square - nw) // 2, (square - nh) // 2), resized)
    return canvas


# ---------------------------------------------------------------------- GIF encoding
KEY_COLOR = (255, 0, 255)


def find_palette_index(quantized, rgb):
    pal = quantized.getpalette()
    if not pal:
        return None
    best, best_d = None, None
    for i in range(len(pal) // 3):
        r, g, b = pal[i * 3:i * 3 + 3]
        if (r, g, b) == rgb:
            return i
        d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def frames_have_alpha(frames, threshold=128):
    for f in frames:
        if f.mode == "RGBA" and f.getchannel("A").getextrema()[0] < threshold:
            return True
    return False


def save_gif(frames, durations, path, colors=256, dither=None, transparent=None, optimize=True, loop=0):
    """Encode RGBA frames as a GIF with one shared palette so transparency stays on one index in every frame
    (the converter's method). transparent=None works it out from the frames."""
    Image = PIL.Image
    colors = max(2, min(256, int(colors)))
    dither = PIL.DITHER_FS if dither is None else dither
    if transparent is None:
        transparent = frames_have_alpha(frames)
    extra = {}
    if transparent:
        keyed = []
        for f in frames:
            k = Image.new("RGB", f.size, KEY_COLOR)
            k.paste(f, mask=f.getchannel("A") if f.mode == "RGBA" else None)
            keyed.append(k)
        base = keyed[0].quantize(colors=colors, method=PIL.FASTOCTREE, dither=dither)
        processed = [base] + [k.quantize(palette=base, dither=dither) for k in keyed[1:]]
        idx = find_palette_index(base, KEY_COLOR)
        if idx is not None:
            extra["transparency"] = idx
    else:
        processed = [f.convert("RGB").quantize(colors=colors, method=PIL.FASTOCTREE, dither=dither) for f in frames]
    kw = dict(format="GIF", optimize=optimize, disposal=2, **extra)
    if len(processed) > 1:
        kw.update(save_all=True, append_images=processed[1:], duration=[max(20, int(d)) for d in durations],
                  loop=loop)
    processed[0].save(path, **kw)
    return path


def save_animation(frames, durations, path, fmt, loop=0):
    """Write frames as PNG (first frame), GIF, WebP or AVIF (the converter's Web Images writer)."""
    fmt = fmt.lower()
    if fmt == "png" or len(frames) == 1:
        f = frames[0]
        if fmt == "png":
            f.save(path, "PNG", optimize=True)
        elif fmt == "webp":
            f.save(path, "WEBP", quality=95, method=6)
        elif fmt == "avif":
            f.save(path, "AVIF", quality=90)
        else:
            save_gif([f], [100], path)
        return path
    if fmt == "webp":
        frames[0].save(path, "WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=loop,
                       quality=95, method=6)
    elif fmt == "avif":
        try:
            frames[0].save(path, "AVIF", save_all=True, append_images=frames[1:], duration=durations, loop=loop,
                           quality=90)
        except Exception:
            frames[0].save(path, "AVIF", quality=90)
    else:
        save_gif(frames, durations, path, loop=loop)
    return path


def animation_formats():
    out = ["PNG", "GIF", "WebP"]
    if avif_supported():
        out.append("AVIF")
    return out


def temp_path(suffix):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="lumen-")
    os.close(fd)
    return path


# ====================================================================== background work
class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(float)
    status = pyqtSignal(str)


class Job(QRunnable):
    """fn(job, *args) runs on a worker thread; job.progress(0..1) / job.status(text) report back."""

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()
        self.cancelled = False
        self.setAutoDelete(False)

    def progress(self, value):
        self.signals.progress.emit(float(value))

    def status(self, text):
        self.signals.status.emit(text)

    def run(self):
        try:
            result = self.fn(self, *self.args)
        except Exception as e:  # noqa: BLE001
            msg = str(e) or e.__class__.__name__
            self.signals.failed.emit(msg if len(msg) < 400 else msg[:397] + "…")
        else:
            self.signals.done.emit(result)
        finally:
            _running.discard(self)


_pool = None
_running = set()


def pool():
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(2)          # "1–2 at a time", like the converter: light on CPU and disk
    return _pool


def run(fn, *args, done=None, failed=None, progress=None, status=None):
    """Run fn(job, *args) in the background. Callbacks run on the GUI thread."""
    job = Job(fn, *args)
    if done:
        job.signals.done.connect(done)
    if failed:
        job.signals.failed.connect(failed)
    if progress:
        job.signals.progress.connect(progress)
    if status:
        job.signals.status.connect(status)
    _running.add(job)
    pool().start(job)
    return job


def wait_all(timeout_ms=30000):
    """Tests / shutdown: wait for background jobs, delivering their results."""
    import time
    end = time.monotonic() + timeout_ms / 1000
    while (_running or (pool().activeThreadCount() > 0)) and time.monotonic() < end:
        QApplication.processEvents()
        pool().waitForDone(20)
    QApplication.processEvents()
    QApplication.processEvents()


# ====================================================================== video (Qt Multimedia, ships with Lumen)
class VideoReader(QObject):
    """Frame-accurate stills from a video file, using Qt Multimedia (FFmpeg inside Qt).

    Runs on the GUI thread with short nested event loops, so the window keeps repainting while it works."""

    def __init__(self, path):
        super().__init__()
        from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
        self.path = path
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoOutput(self.sink)
        self._last = None          # (start_us, end_us, QImage)
        self.sink.videoFrameChanged.connect(self._frame)
        self.duration_ms = 0
        self.fps = 0.0
        self.size = QSize()
        self.error = ""
        self.closed = False

    def _frame(self, f):
        if f.isValid():
            img = f.toImage()
            if not img.isNull():
                self._last = (f.startTime(), f.endTime(), img)

    def _wait(self, signal, ms):
        loop = QEventLoop()
        signal.connect(loop.quit)
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
        try:
            signal.disconnect(loop.quit)
        except TypeError:
            pass

    def open(self, timeout_ms=15000):
        from PyQt6.QtMultimedia import QMediaPlayer, QMediaMetaData
        MS = QMediaPlayer.MediaStatus
        errors = []
        self.player.errorOccurred.connect(lambda e, msg: errors.append(msg or str(e)))
        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(self.path)))
        loop = QEventLoop()

        def status(s):
            if s in (MS.LoadedMedia, MS.InvalidMedia, MS.BufferedMedia):
                loop.quit()
        self.player.mediaStatusChanged.connect(status)
        QTimer.singleShot(timeout_ms, loop.quit)
        if self.player.mediaStatus() not in (MS.LoadedMedia, MS.BufferedMedia):
            loop.exec()
        self.player.mediaStatusChanged.disconnect(status)
        if errors or self.player.mediaStatus() == MS.InvalidMedia or not self.player.hasVideo():
            raise ValueError(errors[0] if errors else "This file has no video Lumen can read.")
        md = self.player.metaData()
        self.duration_ms = max(1, self.player.duration())
        fps = md.value(QMediaMetaData.Key.VideoFrameRate)
        self.fps = float(fps) if fps else 0.0
        res = md.value(QMediaMetaData.Key.Resolution)
        self.size = res if isinstance(res, QSize) else QSize()
        self.player.pause()                      # paused players show a frame after every seek
        self._wait(self.sink.videoFrameChanged, 3000)
        if (not self.fps or self.fps > 240) and self._last is not None:
            self.fps = 25.0
        self.fps = self.fps or 25.0
        if (self.size.isEmpty()) and self._last is not None:
            self.size = self._last[2].size()
        return self

    @property
    def duration(self):
        return self.duration_ms / 1000.0

    @property
    def frame_total(self):
        return max(1, int(self.duration * self.fps))

    def _cached(self, ms):
        if self._last is None:
            return None
        start, end, img = self._last
        if start >= 0 and end > start and start <= ms * 1000 < end:
            return img
        return None

    def frame_at(self, ms):
        """The frame showing at `ms` (QImage)."""
        if self.closed:
            raise ValueError("The video has been closed.")
        ms = max(0, min(int(round(ms)), self.duration_ms - 1))
        hit = self._cached(ms)
        if hit is not None:                  # already showing: Qt won't send it again
            return QImage(hit)
        before = self._last
        self.player.setPosition(ms)
        self._wait(self.sink.videoFrameChanged, 2000)
        if self._last is None:
            raise ValueError("Couldn't read a frame from this video.")
        return QImage(self._last[2])

    def frame(self, index):
        """Frame number `index`. Decoders round seeks differently (MP4: the frame containing the time, MJPEG:
        the nearest frame), so ask for 1 ms after the frame starts, which both agree on."""
        step = 1000.0 / self.fps
        index = max(0, min(int(index), self.frame_total - 1))
        return self.frame_at(index * step + 1)

    def frames(self, start_s, length_s, fps, width=None, progress=None):
        """Frames sampled at `fps` from start_s for length_s seconds, optionally scaled to `width` px."""
        out = []
        end = min(self.duration, start_s + length_s)
        n = max(1, int(round((end - start_s) * fps)))
        for i in range(n):
            t = start_s + i / fps
            img = self.frame(int(t * self.fps + 1e-6))
            if width and img.width() != width:
                img = img.scaledToWidth(int(width), Qt.TransformationMode.SmoothTransformation)
            out.append(img.convertToFormat(QImage.Format.Format_RGBA8888))
            if progress:
                progress((i + 1) / n)
        return out

    def close(self):
        self.closed = True
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except RuntimeError:
            pass


# ====================================================================== UI building blocks
def primary(text):
    b = QPushButton(text)
    b.setObjectName("Primary")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def button(text, tip=None, flat=False, small=False):
    b = QPushButton(text)
    if flat:
        b.setObjectName("Flat")
    if small:
        b.setStyleSheet("QPushButton { padding: 4px 8px; min-width: 0; }")
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def dim(text, wrap=True):
    lab = QLabel(text)
    lab.setObjectName("Dim")
    lab.setWordWrap(wrap)
    return lab


def group(title):
    box = QGroupBox(title)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 16, 14, 14)
    lay.setSpacing(10)
    return box, lay


def slider_row(grid, row, name, minimum=0, maximum=100, value=0, suffix=""):
    grid.addWidget(QLabel(name), row, 0)
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(minimum, maximum)
    s.setValue(value)
    grid.addWidget(s, row, 1)
    lab = QLabel(f"{value}{suffix}")
    lab.setMinimumWidth(70)
    grid.addWidget(lab, row, 2)
    s.valueChanged.connect(lambda v: lab.setText(f"{v}{suffix}"))
    return s, lab


def busy_bar():
    b = QProgressBar()
    b.setRange(0, 0)
    b.setTextVisible(False)
    b.setFixedHeight(6)
    b.hide()
    return b


def error(parent, title, message):
    QMessageBox.warning(parent, title, message)


class ResizeOptions(QWidget):
    """One row of output-size controls (presets for social posts, or a custom size)."""
    changed = pyqtSignal()

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        if compact:
            grid = QGridLayout(self)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            row = QHBoxLayout()
            row.setSpacing(8)
        else:
            row = QHBoxLayout(self)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(QLabel("Output size"))
        self.preset = QComboBox()
        for name, _ in RESIZE_PRESETS:
            self.preset.addItem(name)
        self.preset.setToolTip("Resize the output to a set shape - handy for social posts.\n"
                               "Choose Custom… to type your own size.")
        self.preset.currentIndexChanged.connect(self._preset_changed)
        if compact:
            grid.addWidget(self.preset, 0, 0, 1, 2)
        else:
            row.addWidget(self.preset, 1)
        self.w = QSpinBox()
        self.h = QSpinBox()
        for s in (self.w, self.h):
            s.setRange(1, 20000)
            s.setValue(1080)
            s.setSuffix(" px")
            s.setMaximumWidth(96)
            s.valueChanged.connect(lambda _: self.changed.emit())
        row.addWidget(self.w)
        self.times = QLabel("×")
        row.addWidget(self.times)
        row.addWidget(self.h)
        if compact:
            row.addStretch(1)
            grid.addLayout(row, 1, 0)
        self.mode = QComboBox()
        for name, _ in RESIZE_MODES:
            self.mode.addItem(name)
        self.mode.setToolTip("Fit keeps the whole image and pads the gaps (see-through, or white where the "
                             "format can't do transparency).\nFill crops the overflow so the frame is covered.\n"
                             "Stretch squashes the image to shape.")
        self.mode.currentIndexChanged.connect(lambda _: self.changed.emit())
        if compact:
            grid.addWidget(self.mode, 2, 0)
        else:
            row.addWidget(self.mode, 1)
        self.upscale = QCheckBox("Allow upscaling")
        self.upscale.setChecked(True)
        self.upscale.setToolTip("Off: a picture smaller than the target is centred at its own size rather than "
                                "being blown up and going soft.")
        self.upscale.toggled.connect(lambda _: self.changed.emit())
        if compact:
            grid.addWidget(self.upscale, 2, 1)
        else:
            row.addWidget(self.upscale)
        self._preset_changed(0)

    def _preset_changed(self, i):
        _, value = RESIZE_PRESETS[i]
        if isinstance(value, tuple):
            for s, v in ((self.w, value[0]), (self.h, value[1])):
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
        custom = value == "custom"
        for wdg in (self.w, self.h, self.times):
            wdg.setEnabled(custom)
        for wdg in (self.mode, self.upscale):
            wdg.setEnabled(value is not None)
        self.changed.emit()

    def spec(self):
        _, value = RESIZE_PRESETS[self.preset.currentIndex()]
        if value is None:
            return None
        size = (self.w.value(), self.h.value()) if value == "custom" else value
        return {"size": size, "mode": RESIZE_MODES[self.mode.currentIndex()][1], "upscale": self.upscale.isChecked()}

    def set_spec(self, spec):
        """Tests / restoring: pick a preset by size (or Custom)."""
        if not spec:
            self.preset.setCurrentIndex(0)
            return
        for i, (_, v) in enumerate(RESIZE_PRESETS):
            if v == tuple(spec["size"]):
                self.preset.setCurrentIndex(i)
                break
        else:
            self.preset.setCurrentIndex(len(RESIZE_PRESETS) - 1)
            self.w.setValue(spec["size"][0])
            self.h.setValue(spec["size"][1])
        self.mode.setCurrentIndex([m for _, m in RESIZE_MODES].index(spec.get("mode", "fit")))
        self.upscale.setChecked(spec.get("upscale", True))


class TargetSizeBox(QGroupBox):
    """Discord Emoji / Discord Sticker / 1–500 MiB / Custom… buttons. chosen(target_bytes, square_px or 0)."""
    chosen = pyqtSignal(int, int)

    def __init__(self, discord=True, columns=4, parent=None):
        super().__init__("Target Size", parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(14, 16, 14, 14)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.buttons = []
        items = []
        if discord:
            items += [("Discord Emoji", f"Fits within {DISCORD_EMOJI_SIZE_PX}×{DISCORD_EMOJI_SIZE_PX}px and under "
                       f"{DISCORD_EMOJI_MAX_BYTES // 1024}KB", DISCORD_EMOJI_MAX_BYTES, DISCORD_EMOJI_SIZE_PX),
                      ("Discord Sticker", f"Exactly {DISCORD_STICKER_SIZE_PX}×{DISCORD_STICKER_SIZE_PX}px and under "
                       f"{DISCORD_STICKER_MAX_BYTES // 1024}KB", DISCORD_STICKER_MAX_BYTES, DISCORD_STICKER_SIZE_PX)]
        items += [(f"{m} MiB", f"Shrinks to fit under {m} MiB", m * MIB, 0) for m in TARGET_SIZE_PRESETS_MIB]
        items.append(("Custom…", "Choose your own target size", -1, 0))
        for i, (label, tip, target, square) in enumerate(items):
            b = button(label, tip, small=True)
            b.clicked.connect(lambda _=False, t=target, s=square: self._clicked(t, s))
            grid.addWidget(b, i // columns, i % columns)
            self.buttons.append(b)

    def _clicked(self, target, square):
        if target < 0:
            mib, ok = QInputDialog.getDouble(self, "Custom Target Size", "Target size (MiB):", 10.0, 0.05, 2048.0, 2)
            if not ok:
                return
            target = int(mib * MIB)
        self.chosen.emit(int(target), int(square))

    def setEnabled(self, on):
        for b in self.buttons:
            b.setEnabled(on)


class Checker:
    @staticmethod
    def brush_pixmap(size=8):
        c = theme.C
        a, b = QColor(theme.mix(c["pasteboard"], c["window"], 0.5)), QColor(theme.mix(c["pasteboard"], c["text"], 0.08))
        pm = QPixmap(size * 2, size * 2)
        pm.fill(a)
        p = QPainter(pm)
        p.fillRect(0, 0, size, size, b)
        p.fillRect(size, size, size, size, b)
        p.end()
        return pm


class AnimationView(QWidget):
    """Plays a list of QImages (with per-frame durations) fitted inside the widget, over a checkerboard."""
    frameChanged = pyqtSignal(int)

    def __init__(self, placeholder="Nothing to preview yet", min_size=(260, 170), parent=None):
        super().__init__(parent)
        self.setMinimumSize(*min_size)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.placeholder = placeholder
        self.frames = []
        self.durations = []
        self.index = 0
        self.overlay = None              # fn(painter, target_rect, image_size)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next)
        self.playing = False

    # -- content
    def clear(self, placeholder=None):
        self.stop()
        self.frames, self.durations, self.index = [], [], 0
        if placeholder is not None:
            self.placeholder = placeholder
        self.update()

    def set_frames(self, frames, durations=None, autoplay=True):
        self.stop()
        self.frames = [f if isinstance(f, QImage) else pil_to_qimage(f) for f in frames]
        self.durations = list(durations or [100] * len(self.frames))
        self.index = 0
        self.update()
        if autoplay and len(self.frames) > 1:
            self.play()

    def set_image(self, img):
        self.set_frames([img], [100], autoplay=False)

    def load_file(self, path, limit=600):
        """Read every frame of an image file with Qt (GIF / WebP / PNG… - no Pillow needed)."""
        r = QImageReader(path)
        r.setAutoTransform(True)
        frames, durs = [], []
        while len(frames) < limit:
            img = r.read()
            if img.isNull():
                break
            frames.append(img)
            durs.append(max(20, r.nextImageDelay() or 100))
            if not r.supportsAnimation() or r.imageCount() <= 1:
                break
            if r.currentImageNumber() >= r.imageCount() - 1:
                break
        if not frames:
            raise ValueError(r.errorString() or "Couldn't read that image")
        self.set_frames(frames, durs)
        return len(frames)

    # -- playback
    def play(self):
        if len(self.frames) > 1:
            self.playing = True
            self._timer.start(self.durations[self.index])

    def stop(self):
        self.playing = False
        self._timer.stop()

    def toggle(self):
        self.stop() if self.playing else self.play()

    def step(self, delta):
        if self.frames:
            self.stop()
            self.index = (self.index + delta) % len(self.frames)
            self.frameChanged.emit(self.index)
            self.update()

    def _next(self):
        if not self.frames:
            return
        self.index = (self.index + 1) % len(self.frames)
        self.frameChanged.emit(self.index)
        self.update()
        if self.playing:
            self._timer.start(self.durations[self.index])

    def image_rect(self):
        if not self.frames:
            return QRectF()
        img = self.frames[self.index]
        avail = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        s = min(avail.width() / max(1, img.width()), avail.height() / max(1, img.height()), 1.0 if
                max(img.width(), img.height()) > 64 else 8.0)
        w, h = img.width() * s, img.height() * s
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()                          # never leave a painter open, even if drawing fails

    def _paint(self, p):
        c = theme.C
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(c["separator"]), 1))
        p.setBrush(QColor(c["pasteboard"]))
        p.drawRoundedRect(r, 6, 6)
        if not self.frames:
            p.setPen(QColor(c["text_dim"]))
            p.drawText(self.rect().adjusted(12, 12, -12, -12),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.placeholder)
            return
        ir = self.image_rect()
        p.fillRect(ir, QBrush(Checker.brush_pixmap()))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(ir, self.frames[self.index])
        if self.overlay:
            self.overlay(p, ir, self.frames[self.index].size())

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.playing:
            self._timer.start(self.durations[self.index] if self.durations else 100)


class PlayerControls(QWidget):
    """◀  ▶ Play  Frame n / N  ▶ for an AnimationView."""

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.prev = button("◀")
        self.prev.setFixedWidth(44)
        self.prev.clicked.connect(lambda: view.step(-1))
        self.play = button("▶ Play")
        self.play.clicked.connect(self._toggle)
        self.label = QLabel("Frame 0 / 0")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next = button("▶")
        self.next.setFixedWidth(44)
        self.next.clicked.connect(lambda: view.step(1))
        for w in (self.prev, self.play):
            row.addWidget(w)
        row.addWidget(self.label, 1)
        row.addWidget(self.next)
        view.frameChanged.connect(lambda _: self.refresh())
        self.refresh()

    def _toggle(self):
        self.view.toggle()
        self.refresh()

    def refresh(self):
        n = len(self.view.frames)
        self.label.setText(f"Frame {self.view.index + 1 if n else 0} / {n}")
        self.play.setText("⏸ Pause" if self.view.playing else "▶ Play")
        for w in (self.prev, self.play, self.next):
            w.setEnabled(n > 1)


# ---------------------------------------------------------------------- file queues
class SelectedRow(QWidget):
    """'name — ready' plus a ✕ to remove it before converting."""

    def __init__(self, text, path, on_remove):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 4, 3)
        lay.setSpacing(6)
        self.label = QLabel(text)
        self.label.setToolTip(path)
        lay.addWidget(self.label, 1)
        self.remove = QToolButton()
        self.remove.setText("✕")
        self.remove.setToolTip("Remove this file")
        self.remove.setFixedSize(22, 22)
        self.remove.clicked.connect(on_remove)
        lay.addWidget(self.remove)

    def set_text(self, text):
        self.label.setText(text)

    def set_removable(self, on):
        self.remove.setVisible(on)


class CompletedRow(QWidget):
    """Name, a busy bar while working, then a status (Converted / size) plus action buttons."""

    def __init__(self, name, path, actions=()):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(8)
        self.name = QLabel(name)
        self.name.setToolTip(path)
        self.name.setMinimumWidth(120)
        lay.addWidget(self.name, 2)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar, 3)
        self.status = QLabel("")
        self.status.hide()
        lay.addWidget(self.status, 3)
        self.buttons = {}
        for label, cb, tip in actions:
            b = QPushButton(label)
            b.setToolTip(tip or "")
            b.setEnabled(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(cb)
            b.setStyleSheet("QPushButton { padding: 3px 10px; min-width: 0; }")
            lay.addWidget(b)
            self.buttons[label] = b
        self.state = "working"

    def _show(self, text, tone):
        self.bar.hide()
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.tone(tone)}; font-weight: 700;")
        self.status.show()

    def mark_done(self, text="Converted"):
        self.state = "done"
        self._show(text, "ok")
        for b in self.buttons.values():
            b.setEnabled(True)

    def mark_failed(self, message):
        self.state = "failed"
        self._show(f"Failed: {message}", "error")

    def flash_saved(self):
        old, style = self.status.text(), self.status.styleSheet()
        self.status.setText("Saved ✓")
        self.status.setStyleSheet(f"color: {theme.tone('info')}; font-weight: 700;")

        def back():
            try:
                self.status.setText(old)
                self.status.setStyleSheet(style)
            except RuntimeError:
                pass
        QTimer.singleShot(1200, back)


class RowList(QListWidget):
    """A QListWidget that holds row widgets keyed by path."""

    def __init__(self):
        super().__init__()
        self.setSpacing(2)
        self.rows = {}

    def add(self, key, widget):
        it = QListWidgetItem()
        it.setSizeHint(widget.sizeHint())
        self.addItem(it)
        self.setItemWidget(it, widget)
        self.rows[key] = (it, widget)
        return widget

    def remove(self, key):
        it, _ = self.rows.pop(key, (None, None))
        if it is not None:
            self.takeItem(self.row(it))

    def widget_for(self, key):
        return self.rows.get(key, (None, None))[1]

    def keys(self):
        return list(self.rows)


# ---------------------------------------------------------------------- after-save conveniences
class FilenamesWindow(QDialog):
    """Lists the files just saved, each with a Copy button (converter's "show filenames" option)."""
    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saved File Names")
        self.setMinimumSize(420, 340)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("File names of what was just saved:"))
        self.area = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.area)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(holder)
        lay.addWidget(sa, 1)
        row = QHBoxLayout()
        copy_all = button("Copy All")
        copy_all.clicked.connect(lambda: QGuiApplication.clipboard().setText("\n".join(self.names)))
        row.addWidget(copy_all)
        row.addStretch(1)
        close = button("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.names = []

    def set_names(self, names):
        self.names = list(names)
        while self.area.count():
            w = self.area.takeAt(0).widget()
            if w:
                w.deleteLater()
        for n in self.names:
            r = QWidget()
            rl = QHBoxLayout(r)
            rl.setContentsMargins(0, 0, 0, 0)
            f = QLineEdit(n)
            f.setReadOnly(True)
            rl.addWidget(f, 1)
            b = button("Copy")
            b.clicked.connect(lambda _=False, t=n: QGuiApplication.clipboard().setText(t))
            rl.addWidget(b)
            self.area.addWidget(r)
        self.area.addStretch(1)

    @classmethod
    def show_names(cls, parent, names):
        if cls._instance is None:
            cls._instance = FilenamesWindow(parent)
        cls._instance.set_names(names)
        cls._instance.show()
        cls._instance.raise_()


def after_save(parent, saved_paths, originals=()):
    """What every tool does after saving: optional 'delete originals' and 'show file names'."""
    saved_paths = [p for p in saved_paths if p]
    if not saved_paths:
        return
    if flag(DELETE_ORIGINALS):
        deleted, failed = [], []
        for src in dict.fromkeys(originals):
            if not src or not os.path.isfile(src) or src in saved_paths:
                continue
            try:
                os.remove(src)
                deleted.append(os.path.basename(src))
            except OSError as e:
                failed.append(f"{os.path.basename(src)} ({e.strerror or e})")
        lines = []
        if deleted:
            lines.append(f"Deleted {len(deleted)} original file(s):\n" + "\n".join(deleted))
        if failed:
            lines.append(f"Couldn't delete {len(failed)} original file(s):\n" + "\n".join(failed))
        if lines:
            QMessageBox.information(parent, "Original Files", "\n\n".join(lines))
    if flag(SHOW_FILENAMES):
        FilenamesWindow.show_names(parent, [os.path.basename(p) for p in saved_paths])


def ask_save_path(parent, title, default_path, filters):
    path, _ = QFileDialog.getSaveFileName(parent, title, default_path, filters)
    return path


def unique_path(path):
    """path, or 'name (2).ext' if it already exists."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


# ---------------------------------------------------------------------- page chrome
class ToolPage(QWidget):
    """A tool's workspace: a header (icon, title, subtitle, Options menu) above a scrollable body.

    Subclasses put their UI into self.body (a QVBoxLayout). Files dropped anywhere on the page go to
    self.files_dropped(paths)."""
    accepts_drops = True

    def __init__(self, title, subtitle, icon=None, api=None):
        super().__init__()
        self.api = api
        self.setAcceptDrops(self.accepts_drops)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("ToolHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 12, 14, 12)
        hl.setSpacing(12)
        if icon:
            from . import icons
            ic = QLabel()
            ic.setObjectName("ToolHeaderIcon")
            if icon in icons.DRAWINGS:
                ic.setPixmap(icons.pixmap(icon, 26, QColor(theme.C["accent"])))
            self._icon_label, self._icon_name = ic, icon
            hl.addWidget(ic)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        t = QLabel(title)
        t.setObjectName("Heading")
        tl.addWidget(t)
        s = dim(subtitle)
        tl.addWidget(s)
        hl.addLayout(tl, 1)
        self.header_tools = QHBoxLayout()
        self.header_tools.setSpacing(6)
        hl.addLayout(self.header_tools)
        opts = QToolButton()
        opts.setText("Options  ▾")
        opts.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        opts.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        menu = QMenu(opts)
        self.opt_delete = menu.addAction("Delete original files after saving")
        self.opt_delete.setCheckable(True)
        self.opt_delete.toggled.connect(lambda on: set_flag(DELETE_ORIGINALS, on))
        self.opt_names = menu.addAction("Show file names after saving")
        self.opt_names.setCheckable(True)
        self.opt_names.toggled.connect(lambda on: set_flag(SHOW_FILENAMES, on))
        menu.aboutToShow.connect(self._sync_options)
        opts.setMenu(menu)
        hl.addWidget(opts)
        outer.addWidget(head)
        holder = QWidget()
        holder.setObjectName("ToolBody")
        self.body = QVBoxLayout(holder)
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(12)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(holder)
        outer.addWidget(self.scroll, 1)
        theme.notifier.changed.connect(self._theme_changed)

    def _sync_options(self):
        for act, key in ((self.opt_delete, DELETE_ORIGINALS), (self.opt_names, SHOW_FILENAMES)):
            act.blockSignals(True)
            act.setChecked(flag(key))
            act.blockSignals(False)

    def _theme_changed(self, *_):
        lab = getattr(self, "_icon_label", None)
        if lab is not None:
            from . import icons
            lab.setPixmap(icons.pixmap(self._icon_name, 26, QColor(theme.C["accent"])))

    # -- drag and drop of files
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            ev.acceptProposedAction()
            self.files_dropped(paths)

    def files_dropped(self, paths):
        pass

    # -- Lumen helpers
    def lumen_image(self):
        """The current Lumen document, flattened (QImage), or None."""
        if self.api is None:
            return None
        return self.api.composite()

    def shutdown(self):
        """Stop everything that could fire after the page is gone (timers, playback)."""
        for t in self.findChildren(QTimer):
            t.stop()
        for v in self.findChildren(AnimationView):
            v.stop()


# ====================================================================== optimiser page (GIF + Image Optimiser)
class OptimiserPage(ToolPage):
    """Open a file, shrink it with a Compression slider or a Target Size preset, compare before/after, save.

    Subclasses set the class attributes and implement build(source, level, out_path, square, spec) -> path."""
    kind = "image"                       # "GIF" / "image" in messages
    open_filter = IMAGE_FILTER
    out_filter = "Images (*.png *.jpg)"
    max_level = 100
    default_level = 40

    def __init__(self, title, subtitle, icon, api):
        super().__init__(title, subtitle, icon, api)
        self.source = None               # path being optimised
        self.source_label = ""
        self.original_size = 0
        self.result = None               # temp output path
        self.lumen_source = False
        self._job = None
        cols = QHBoxLayout()
        cols.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(12)
        src, sl = group("Source")
        row = QHBoxLayout()
        self.open_btn = primary(f"Open {self.kind}…")
        self.open_btn.clicked.connect(self.choose)
        row.addWidget(self.open_btn)
        if self.allow_lumen_source():
            self.lumen_btn = button("Use Lumen Image", "Optimise the picture that's open in Lumen right now")
            self.lumen_btn.clicked.connect(self.use_lumen)
            row.addWidget(self.lumen_btn)
        row.addStretch(1)
        sl.addLayout(row)
        self.file_label = dim(f"No {self.kind} selected - open one or drop it here")
        sl.addWidget(self.file_label)
        left.addWidget(src)
        size_box, szl = group("Output size")
        self.resize = ResizeOptions(compact=True)
        self.resize.setToolTip("Resize the output. With a size chosen, the compression slider controls quality "
                               "rather than dimensions.")
        szl.addWidget(self.resize)
        left.addWidget(size_box)
        opt = QGroupBox(title)
        grid = QGridLayout(opt)
        grid.setContentsMargins(14, 16, 14, 14)
        grid.setColumnStretch(1, 1)
        self.level, self.level_label = slider_row(grid, 0, "Compression", 1, self.max_level, self.default_level, "%")
        self.optimise_btn = primary("Optimise")
        self.optimise_btn.clicked.connect(self.optimise)
        grid.addWidget(self.optimise_btn, 1, 0, 1, 3)
        grid.addWidget(dim(self.level_hint()), 2, 0, 1, 3)
        left.addWidget(opt)
        self.targets = TargetSizeBox(discord=True)
        self.targets.chosen.connect(self.target)
        left.addWidget(self.targets)
        self.bar = busy_bar()
        left.addWidget(self.bar)
        res, rl = group("Result")
        self.size_label = QLabel("")
        self.size_label.setWordWrap(True)
        self.size_label.setStyleSheet("font-weight: 700;")
        rl.addWidget(self.size_label)
        brow = QHBoxLayout()
        self.save_btn = primary("Save")
        self.save_btn.setToolTip("Saves next to the original (with “-optimized” added to the name)")
        self.save_btn.clicked.connect(lambda: self.save_to(self.default_out()))
        self.save_to_btn = button("Save To…", "Choose a location and file name")
        self.save_to_btn.clicked.connect(self.save_as)
        self.lumen_out_btn = button("Open in Lumen", "Open the optimised result as a Lumen document")
        self.lumen_out_btn.clicked.connect(self.open_in_lumen)
        for b in (self.save_btn, self.save_to_btn, self.lumen_out_btn):
            brow.addWidget(b)
        brow.addStretch(1)
        rl.addLayout(brow)
        left.addWidget(res)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(480)
        cols.addWidget(lw)
        right = QVBoxLayout()
        pv, pl = group("Preview")
        self.before_caption = dim("Original")
        pl.addWidget(self.before_caption)
        self.before = AnimationView("Open a file to see it here")
        pl.addWidget(self.before, 1)
        self.after_caption = dim("Optimised")
        pl.addWidget(self.after_caption)
        self.after = AnimationView("Press Optimise or a Target Size to see the result")
        pl.addWidget(self.after, 1)
        right.addWidget(pv, 1)
        cols.addLayout(right, 1)
        self.body.addLayout(cols, 1)
        self._update()

    # -- hooks
    def allow_lumen_source(self):
        return False

    def level_hint(self):
        return "Higher compression = smaller file, lower quality."

    def build(self, source, level, out, square, spec):
        raise NotImplementedError

    def default_out(self):
        if self.lumen_source or not self.source:
            base = os.path.join(os.path.expanduser("~"), "Pictures")
            base = base if os.path.isdir(base) else os.path.expanduser("~")
            name = self.source_label or "image"
        else:
            base = os.path.dirname(self.source)
            name = os.path.splitext(os.path.basename(self.source))[0]
        ext = os.path.splitext(self.result or ".png")[1]
        return os.path.join(base, f"{os.path.splitext(name)[0]}-optimized{ext}")

    # -- state
    def _update(self):
        has = self.source is not None
        busy = self._job is not None
        self.optimise_btn.setEnabled(has and not busy)
        self.targets.setEnabled(has and not busy)
        for b in (self.save_btn, self.save_to_btn, self.lumen_out_btn):
            b.setEnabled(self.result is not None and not busy)
        self.open_btn.setEnabled(not busy)
        self.bar.setVisible(busy)

    def files_dropped(self, paths):
        self.load(paths[0])

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, f"Choose a {self.kind}", settings().value("last_dir", ""),
                                              self.open_filter)
        if path:
            settings().setValue("last_dir", os.path.dirname(path))
            self.load(path)

    def use_lumen(self):
        img = self.lumen_image()
        if img is None:
            error(self, "Lumen", "Open or create an image in Lumen first.")
            return
        path = temp_path(".png")
        img.save(path, "PNG")
        doc = self.api.current_document() if self.api else None
        self.load(path, label=os.path.splitext(getattr(doc, "name", "image"))[0], from_lumen=True)

    def load(self, path, label=None, from_lumen=False):
        try:
            size = os.path.getsize(path)
            n = self.before.load_file(path)
        except Exception as e:  # noqa: BLE001
            error(self, f"Couldn't open {self.kind}", str(e))
            return False
        self.source, self.original_size, self.lumen_source = path, size, from_lumen
        self.source_label = label or os.path.basename(path)
        img = self.before.frames[0]
        frames = f", {n} frames" if n > 1 else ""
        self.file_label.setText(f"{self.source_label} — {img.width()}×{img.height()}{frames}, {format_size(size)}")
        self.before_caption.setText(f"Original — {format_size(size)}")
        self.after.clear("Press Optimise or a Target Size to see the result")
        self.after_caption.setText("Optimised")
        self.size_label.setText(f"Original size: {format_size(size)}")
        self.result = None
        self._update()
        return True

    # -- work
    def optimise(self):
        self._start(lambda job, src, lvl, sq, spec: (self.build(src, lvl, temp_path(".tmp"), sq, spec), lvl, True),
                    self.level.value(), 0)

    def target(self, target_bytes, square):
        def search(job, src, _lvl, sq, spec):
            path, used = None, self.max_level
            for lvl in range(10, self.max_level + 1, 10):
                path = self.build(src, lvl, temp_path(".tmp"), sq, spec)
                job.progress(lvl / self.max_level)
                used = lvl
                if os.path.getsize(path) <= target_bytes:
                    return path, lvl, True
            return path, used, False
        self._start(search, 0, square)

    def _start(self, fn, level, square):
        if not self.source:
            return
        self._job = run(fn, self.source, level, square or None, self.resize.spec(), done=self._done,
                        failed=self._failed)
        self._update()

    def _done(self, result):
        path, level, met = result
        self._job = None
        self.result = path
        self.level.blockSignals(True)
        self.level.setValue(level)
        self.level.blockSignals(False)
        self.level_label.setText(f"{level}%")
        size = os.path.getsize(path)
        self.size_label.setText(f"Optimised size: {size_change(size, self.original_size)}")
        self.after_caption.setText(f"Optimised — {format_size(size)}")
        try:
            self.after.load_file(path)
        except Exception:
            pass
        self._update()
        if not met:
            error(self, "Couldn't fully meet target",
                  f"Even at maximum compression, the result is {format_size(size)}, which is still over the target "
                  f"size. This {self.kind} may have too many frames or too much detail to fit - consider trimming "
                  "it first.")

    def _failed(self, msg):
        self._job = None
        self._update()
        error(self, "Optimisation failed", msg)

    # -- output
    def save_as(self):
        ext = os.path.splitext(self.result or "")[1]
        path = ask_save_path(self, "Save As", self.default_out(), f"{ext[1:].upper()} image (*{ext})")
        if path:
            self.save_to(path)

    def save_to(self, dest):
        if not self.result:
            return False
        import shutil
        try:
            shutil.copyfile(self.result, dest)
        except OSError as e:
            error(self, "Save failed", str(e))
            return False
        if self.api:
            self.api.status(f"Saved {os.path.basename(dest)}")
        self.last_saved = dest
        after_save(self, [dest], [] if self.lumen_source else [self.source])
        return True

    def open_in_lumen(self):
        if not self.result or self.api is None:
            return
        frames = self.after.frames
        name = os.path.splitext(self.source_label)[0] + "-optimized"
        if len(frames) > 1:
            self.api.open_layers(frames, name)
        else:
            self.api.open_image(QImage(frames[0]), name)


# ====================================================================== batch queue (Batch Converter, WebP to GIF)
class FileQueue(QWidget):
    """'Selected Files' (waiting, removable) beside 'Completed' (busy bar → status + per-file buttons).

    actions: [(label, fn(path), tooltip)] buttons on each finished row."""
    changed = pyqtSignal()

    def __init__(self, actions=(), limit=MAX_QUEUE):
        super().__init__()
        self.limit = limit
        self.actions = list(actions)
        self.queued = {}            # path -> text
        self.completed = {}         # path -> {"state", "result", "info"}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        left = QGroupBox("Selected Files")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 14, 10, 10)
        self.selected = RowList()
        ll.addWidget(self.selected)
        left.setMinimumWidth(260)
        left.setMaximumWidth(380)
        right = QGroupBox("Completed")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 14, 10, 10)
        self.done_list = RowList()
        rl.addWidget(self.done_list)
        lay.addWidget(left)
        lay.addWidget(right, 1)
        self.setMinimumHeight(220)

    def add(self, paths, describe=None, parent=None):
        """Queue files. Returns the paths actually added."""
        room = self.limit - len(self.queued) - len(self.completed)
        if room <= 0:
            error(parent or self, "Limit reached", f"You already have {self.limit} files in progress. Clear "
                  "some before adding more.")
            return []
        paths = [os.path.abspath(p) for p in paths]
        if len(paths) > room:
            error(parent or self, "Too many files", f"You picked {len(paths)} files, but only {room} more can be "
                  f"added (limit is {self.limit}). Only the first {room} will be queued.")
            paths = paths[:room]
        added = []
        for p in paths:
            if p in self.queued or p in self.completed:
                continue
            try:
                text = describe(p) if describe else os.path.basename(p)
            except Exception as e:  # noqa: BLE001
                error(parent or self, "Couldn't open file", f"{os.path.basename(p)}: {e}")
                continue
            self.queued[p] = text
            self.selected.add(p, SelectedRow(f"{text} — ready", p, lambda _=False, q=p: self.remove(q)))
            added.append(p)
        self.changed.emit()
        return added

    def remove(self, path):
        self.queued.pop(path, None)
        self.selected.remove(path)
        self.changed.emit()

    def pending(self):
        return list(self.queued)

    def start(self, path):
        """Move a queued file into Completed with a busy bar."""
        self.queued.pop(path, None)
        self.selected.remove(path)
        acts = [(label, (lambda _=False, f=fn, q=path: f(q)), tip) for label, fn, tip in self.actions]
        self.done_list.add(path, CompletedRow(os.path.basename(path), path, acts))
        self.completed[path] = {"state": "working", "result": None, "info": None}
        self.changed.emit()

    def finish(self, path, result, status="Converted", info=None):
        e = self.completed.get(path)
        if e is None:
            return
        e.update(state="done", result=result, info=info)
        row = self.done_list.widget_for(path)
        if row:
            row.mark_done(status)
        self.changed.emit()

    def fail(self, path, message):
        e = self.completed.get(path)
        if e is None:
            return
        e.update(state="failed")
        row = self.done_list.widget_for(path)
        if row:
            row.mark_failed(message)
        self.changed.emit()

    def flash(self, path):
        row = self.done_list.widget_for(path)
        if row:
            row.flash_saved()

    def results(self):
        return {p: e["result"] for p, e in self.completed.items() if e["state"] == "done"}

    def clear_completed(self):
        gone = [p for p, e in self.completed.items() if e["state"] in ("done", "failed")]
        for p in gone:
            self.completed.pop(p)
            self.done_list.remove(p)
        self.changed.emit()
        return gone

    def summary(self):
        ready = len(self.queued)
        working = sum(1 for e in self.completed.values() if e["state"] == "working")
        done = sum(1 for e in self.completed.values() if e["state"] == "done")
        failed = sum(1 for e in self.completed.values() if e["state"] == "failed")
        parts = [f"{n} {t}" for n, t in ((ready, "ready to convert"), (working, "converting"),
                                         (done, "ready to save"), (failed, "failed")) if n]
        return " · ".join(parts) or "Ready - add files with Open, or drop them here"
