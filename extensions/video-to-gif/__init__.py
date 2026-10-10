"""Video to GIF for Lumen: trim a clip, pick fps and width, preview the real GIF and its size, save."""
import os
import shutil
from datetime import datetime

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QCheckBox, QWidget, QFileDialog,
                             QLabel, QComboBox, QPlainTextEdit, QProgressBar)

from lumen import media

MAX_LENGTH = 20            # seconds - so nobody accidentally makes a 200 MB GIF
FPS_DEFAULT, FPS_MIN, FPS_MAX = 10, 5, 30
WIDTH_DEFAULT, WIDTH_MIN, WIDTH_MAX = 320, 100, 800


def encode(job, frames, fps, path, fmt):
    pils = [media.qimage_to_pil(f) for f in frames]
    job.progress(0.5)
    dur = max(int(1000 / fps), 20)
    if fmt == "gif":
        media.save_gif(pils, [dur] * len(pils), path, transparent=False)
    else:
        media.save_animation(pils, [dur] * len(pils), path, fmt)
    return path


class VideoToGifPage(media.ToolPage):
    def __init__(self, api):
        super().__init__("Video to GIF", "Turn a clip into a GIF - trim it, pick the frame rate and width, and see "
                         "the real size before you save.", "film", api)
        self.reader = None
        self.path = None
        self.result = None
        self.frames = []
        self.busy = False
        cols = QHBoxLayout()
        cols.setSpacing(16)
        left = QVBoxLayout()
        src, sl = media.group("Video")
        row = QHBoxLayout()
        self.open_btn = media.primary("Open Video…")
        self.open_btn.clicked.connect(self.choose)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        sl.addLayout(row)
        self.file_label = media.dim("No video selected - open one or drop it here")
        sl.addWidget(self.file_label)
        left.addWidget(src)

        box = QGroupBox("GIF Settings")
        g = QGridLayout(box)
        g.setContentsMargins(14, 16, 14, 14)
        g.setColumnStretch(1, 1)
        self.start, self.start_label = media.slider_row(g, 0, "Start time", 0, 0, 0)
        self.length, self.length_label = media.slider_row(g, 1, "Length", 1, MAX_LENGTH * 10, 30)
        self.fps, _ = media.slider_row(g, 2, "Frame rate", FPS_MIN, FPS_MAX, FPS_DEFAULT, " fps")
        self.width, self.width_label = media.slider_row(g, 3, "Width", WIDTH_MIN, WIDTH_MAX, WIDTH_DEFAULT, " px")
        self.keep_width = QCheckBox("Keep original")
        self.keep_width.toggled.connect(self._keep_width)
        g.addWidget(self.keep_width, 3, 3)
        g.addWidget(QLabel("Format"), 4, 0)
        self.fmt = QComboBox()
        self.fmt.addItem("GIF", "gif")
        self.fmt.addItem("Animated WebP (smaller, full colour)", "webp")
        g.addWidget(self.fmt, 4, 1, 1, 3)
        self.start.valueChanged.connect(self._times_changed)
        self.length.valueChanged.connect(self._times_changed)
        self.fps.valueChanged.connect(lambda _: self._estimate())
        left.addWidget(box)
        self.estimate = media.dim("")
        left.addWidget(self.estimate)
        self.generate_btn = media.primary("Generate Preview")
        self.generate_btn.setMinimumHeight(36)
        self.generate_btn.setToolTip("Makes the real GIF so you can see exactly how big it will be")
        self.generate_btn.clicked.connect(self.generate)
        left.addWidget(self.generate_btn)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        left.addWidget(self.progress)
        res, rl = media.group("Result")
        self.size_label = QLabel("")
        self.size_label.setStyleSheet("font-weight: 700;")
        rl.addWidget(self.size_label)
        brow = QHBoxLayout()
        self.save_btn = media.primary("Save")
        self.save_btn.setToolTip("Saves next to the video")
        self.save_btn.clicked.connect(lambda: self.save_to(self.default_out()))
        self.save_to_btn = media.button("Save To…")
        self.save_to_btn.clicked.connect(self.save_as)
        self.lumen_btn = media.button("Open in Lumen", "Open the frames as layers in Lumen")
        self.lumen_btn.clicked.connect(self.open_in_lumen)
        for b in (self.save_btn, self.save_to_btn, self.lumen_btn):
            brow.addWidget(b)
        brow.addStretch(1)
        rl.addLayout(brow)
        left.addWidget(res)
        log_box, ll = media.group("Log")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(110)
        self.log.setPlaceholderText("Conversion activity will show up here…")
        ll.addWidget(self.log)
        left.addWidget(log_box)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(500)
        cols.addWidget(lw)
        right = QVBoxLayout()
        pv, pl = media.group("Preview")
        self.start_caption = media.dim("Start frame")
        pl.addWidget(self.start_caption)
        self.start_view = media.AnimationView("Open a video to see it here", (260, 150))
        pl.addWidget(self.start_view, 1)
        self.result_caption = media.dim("GIF")
        pl.addWidget(self.result_caption)
        self.view = media.AnimationView("Press Generate Preview", (260, 150))
        pl.addWidget(self.view, 1)
        right.addWidget(pv, 1)
        cols.addLayout(right, 1)
        self.body.addLayout(cols, 1)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(120)
        self._thumb_timer.timeout.connect(self._show_start_frame)
        self._times_changed()
        self._update()

    # -- helpers
    def _log(self, text):
        self.log.appendPlainText(f"[{datetime.now():%H:%M:%S}] {text}")

    def _keep_width(self, on):
        self.width.setEnabled(not on)
        self.width_label.setText("Original" if on else f"{self.width.value()} px")

    def _times_changed(self, *_):
        self.start_label.setText(f"{self.start.value() / 10:.1f} s")
        self.length_label.setText(f"{self.length.value() / 10:.1f} s")
        self._estimate()
        if self.reader is not None:
            self._thumb_timer.start()

    def _estimate(self):
        if self.reader is None:
            self.estimate.setText("")
            return
        start, length = self.start.value() / 10, self.length.value() / 10
        length = min(length, self.reader.duration - start)
        self.estimate.setText(f"{max(1, round(length * self.fps.value()))} frames, "
                              f"{start:.1f}s – {start + length:.1f}s of {self.reader.duration:.1f}s")

    def _update(self):
        has = self.reader is not None
        self.generate_btn.setEnabled(has and not self.busy)
        self.open_btn.setEnabled(not self.busy)
        for b in (self.save_btn, self.save_to_btn, self.lumen_btn):
            b.setEnabled(self.result is not None and not self.busy)

    # -- opening
    def files_dropped(self, paths):
        self.load(paths[0])

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a video", media.settings().value("last_video_dir", ""),
                                              media.VIDEO_FILTER)
        if path:
            media.settings().setValue("last_video_dir", os.path.dirname(path))
            self.load(path)

    def load(self, path):
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        try:
            reader = media.VideoReader(path).open()
        except Exception as e:  # noqa: BLE001
            self._log(f"ERROR opening {os.path.basename(path)}: {e}")
            media.error(self, "Couldn't open video", str(e))
            self._update()
            return False
        self.reader, self.path = reader, path
        size = os.path.getsize(path)
        dur = reader.duration
        self.file_label.setText(f"{os.path.basename(path)} — {dur:.1f}s, {reader.size.width()}×"
                                f"{reader.size.height()}, {reader.fps:.0f} fps, {media.format_size(size)}")
        self._log(f"Loaded {os.path.basename(path)} — {dur:.1f}s, {media.format_size(size)}")
        self.start.blockSignals(True)
        self.start.setRange(0, max(0, int(dur * 10) - 1))
        self.start.setValue(0)
        self.start.blockSignals(False)
        cap = max(1, min(int(dur * 10), MAX_LENGTH * 10))
        self.length.setRange(1, cap)
        self.length.setValue(cap)
        self._clear_result()
        self._times_changed()
        self._show_start_frame()
        self._update()
        return True

    def _show_start_frame(self):
        if self.reader is None or self.busy:
            return
        try:
            img = self.reader.frame(int(self.start.value() / 10 * self.reader.fps + 1e-6))
        except Exception:
            return
        self.start_view.set_image(img)
        self.start_caption.setText(f"Start frame — {self.start.value() / 10:.1f}s")

    def _clear_result(self):
        self.result, self.frames = None, []
        self.view.clear("Press Generate Preview")
        self.size_label.setText("")
        self.result_caption.setText("GIF")

    # -- making the GIF
    def settings_now(self):
        width = None if self.keep_width.isChecked() else self.width.value()
        return (self.start.value() / 10, self.length.value() / 10, self.fps.value(), width,
                self.fmt.currentData())

    def generate(self):
        if self.reader is None or self.busy:
            return
        start, length, fps, width, fmt = self.settings_now()
        self._clear_result()
        self.busy = True
        self._update()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self._log(f"Converting {os.path.basename(self.path)} — start={start:.1f}s, length={length:.1f}s, {fps} fps, "
                  f"{'original width' if width is None else f'{width}px wide'}, {fmt.upper()}")
        try:
            frames = self.reader.frames(start, length, fps, width,
                                        progress=lambda f: self.progress.setValue(int(f * 60)))
        except Exception as e:  # noqa: BLE001
            return self._failed(str(e))
        if not frames:
            return self._failed("No frames could be read from this clip.")
        self.frames = frames
        out = media.temp_path("." + fmt)
        media.run(encode, frames, fps, out, fmt, done=lambda p: self._done(p, fps), failed=self._failed,
                  progress=lambda f: self.progress.setValue(60 + int(f * 40)))

    def _done(self, path, fps):
        self.busy = False
        self.progress.hide()
        self.result = path
        size = os.path.getsize(path)
        self.size_label.setText(f"Output file size: {media.format_size(size)}")
        kind = "GIF" if path.endswith(".gif") else "WebP"
        self.result_caption.setText(f"{kind} — {len(self.frames)} frames, {media.format_size(size)}")
        self.view.set_frames(self.frames, [int(1000 / fps)] * len(self.frames))
        self._log(f"Converted {os.path.basename(self.path)} — output size: {media.format_size(size)}")
        self._update()

    def _failed(self, msg):
        self.busy = False
        self.progress.hide()
        self._log(f"ERROR converting {os.path.basename(self.path or '')}: {msg}")
        self._update()
        media.error(self, "GIF generation failed", msg)

    # -- saving
    def default_out(self):
        ext = os.path.splitext(self.result or ".gif")[1]
        return os.path.splitext(self.path)[0] + ext

    def save_as(self):
        ext = os.path.splitext(self.result or ".gif")[1]
        dest = media.ask_save_path(self, "Save As", self.default_out(), f"{ext[1:].upper()} image (*{ext})")
        if dest:
            self.save_to(dest)

    def save_to(self, dest):
        if not self.result:
            return False
        try:
            shutil.copyfile(self.result, dest)
        except OSError as e:
            self._log(f"ERROR saving to {dest}: {e}")
            media.error(self, "Save failed", str(e))
            return False
        self._log(f"Saved {dest}")
        if self.api:
            self.api.status(f"Saved {os.path.basename(dest)}")
        media.after_save(self, [dest], [self.path])
        return True

    def open_in_lumen(self):
        if self.frames and self.api:
            self.api.open_layers(self.frames, os.path.splitext(os.path.basename(self.path))[0])

    def shutdown(self):
        super().shutdown()
        if self.reader is not None:
            self.reader.close()


def register(api):
    page = VideoToGifPage(api)
    api.add_workspace("Video to GIF", page, icon="film")
    api.add_menu_action("Plugins", "Video to GIF", lambda: api.show_workspace(page), needs_document=False)
    register.workspace = page
