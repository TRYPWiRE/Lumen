"""Video to Image for Lumen: pick the exact frame you want out of a video."""
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QHBoxLayout, QVBoxLayout, QGridLayout, QWidget, QFileDialog, QLabel, QSlider,
                             QSpinBox, QComboBox, QProgressBar, QMessageBox)

from lumen import media

MIN_ZOOM_WINDOW = 10


class VideoToImagePage(media.ToolPage):
    def __init__(self, api):
        super().__init__("Video to Image", "Pull a single frame - or a run of frames - out of a video.",
                         "frame_grab", api)
        self.reader = None
        self.path = None
        self.total = 0                 # last frame index
        self.window_start = 0
        self.window_size = 0
        self.current = None            # QImage
        self.current_index = None
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

        fr, fl = media.group("Frame")
        self.info = QLabel("")
        self.info.setStyleSheet("font-weight: 700;")
        fl.addWidget(self.info)
        srow = QHBoxLayout()
        self.prev_btn = media.button("◀", "Previous frame (←)")
        self.prev_btn.setFixedWidth(40)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        srow.addWidget(self.prev_btn)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._slider_moved)
        srow.addWidget(self.slider, 1)
        self.next_btn = media.button("▶", "Next frame (→)")
        self.next_btn.setFixedWidth(40)
        self.next_btn.clicked.connect(lambda: self.step(1))
        srow.addWidget(self.next_btn)
        fl.addLayout(srow)
        zrow = QHBoxLayout()
        self.zoom_label = media.dim("")
        zrow.addWidget(self.zoom_label, 1)
        self.zoom_out_btn = media.button("Zoom Out")
        self.zoom_out_btn.clicked.connect(lambda: self.zoom(self.window_size * 2))
        self.zoom_in_btn = media.button("Zoom In", "Narrow the slider around the current frame for precise picking")
        self.zoom_in_btn.clicked.connect(lambda: self.zoom(self.window_size // 2))
        zrow.addWidget(self.zoom_out_btn)
        zrow.addWidget(self.zoom_in_btn)
        fl.addLayout(zrow)
        left.addWidget(fr)

        out, ol = media.group("This frame")
        b1 = QHBoxLayout()
        self.save_btn = media.primary("Save")
        self.save_btn.setToolTip("Saves a PNG next to the video")
        self.save_btn.clicked.connect(lambda: self.save_to(self.default_out()))
        self.save_to_btn = media.button("Save To…", "PNG, JPEG, WebP, BMP or TIFF")
        self.save_to_btn.clicked.connect(self.save_as)
        self.copy_btn = media.button("Copy")
        self.copy_btn.clicked.connect(self.copy)
        for b in (self.save_btn, self.save_to_btn, self.copy_btn):
            b1.addWidget(b)
        b1.addStretch(1)
        ol.addLayout(b1)
        b2 = QHBoxLayout()
        self.lumen_btn = media.button("Open in Lumen", "Open this frame as a new Lumen document")
        self.lumen_btn.clicked.connect(self.open_in_lumen)
        self.layer_btn = media.button("Add as Layer", "Place this frame in the current Lumen document")
        self.layer_btn.clicked.connect(self.add_layer)
        b2.addWidget(self.lumen_btn)
        b2.addWidget(self.layer_btn)
        b2.addStretch(1)
        ol.addLayout(b2)
        left.addWidget(out)

        seq, ql = media.group("Export a run of frames")
        g = QGridLayout()
        g.addWidget(QLabel("From frame"), 0, 0)
        self.from_spin = QSpinBox()
        g.addWidget(self.from_spin, 0, 1)
        g.addWidget(QLabel("to"), 0, 2)
        self.to_spin = QSpinBox()
        g.addWidget(self.to_spin, 0, 3)
        g.addWidget(QLabel("Every"), 1, 0)
        self.every = QSpinBox()
        self.every.setRange(1, 1000)
        self.every.setSuffix(" frame(s)")
        g.addWidget(self.every, 1, 1, 1, 3)
        g.addWidget(QLabel("As"), 2, 0)
        self.seq_as = QComboBox()
        self.seq_as.addItem("PNG files in a folder", "png")
        self.seq_as.addItem("Layers in a new Lumen document", "layers")
        g.addWidget(self.seq_as, 2, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        ql.addLayout(g)
        mrow = QHBoxLayout()
        self.mark_in = media.button("Set From = current", "Use the frame you're looking at as the first frame")
        self.mark_in.clicked.connect(lambda: self.from_spin.setValue(self.slider.value()))
        self.mark_out = media.button("Set To = current")
        self.mark_out.clicked.connect(lambda: self.to_spin.setValue(self.slider.value()))
        mrow.addWidget(self.mark_in)
        mrow.addWidget(self.mark_out)
        mrow.addStretch(1)
        ql.addLayout(mrow)
        self.export_btn = media.button("Export Frames…")
        self.export_btn.clicked.connect(self.export_run)
        ql.addWidget(self.export_btn)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        ql.addWidget(self.progress)
        left.addWidget(seq)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(500)
        cols.addWidget(lw)
        pv, pl = media.group("Preview")
        self.view = media.AnimationView("Open a video, then drag the slider to the frame you want", (320, 240))
        pl.addWidget(self.view, 1)
        cols.addWidget(pv, 1)
        self.body.addLayout(cols, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._extract)
        for key, d in ((Qt.Key.Key_Left, -1), (Qt.Key.Key_Right, 1)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=d: self.step(d))
        self._update()

    # -- state
    def _update(self):
        has = self.reader is not None
        for w in (self.slider, self.prev_btn, self.next_btn, self.from_spin, self.to_spin, self.every, self.seq_as,
                  self.mark_in, self.mark_out, self.export_btn):
            w.setEnabled(has)
        got = self.current is not None
        for b in (self.save_btn, self.save_to_btn, self.copy_btn, self.lumen_btn, self.layer_btn):
            b.setEnabled(got)
        self.zoom_in_btn.setEnabled(has and self.window_size > MIN_ZOOM_WINDOW)
        self.zoom_out_btn.setEnabled(has and self.window_size <= self.total)

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
            media.error(self, "Couldn't open video", str(e))
            self._update()
            return False
        self.reader, self.path = reader, path
        self.total = max(reader.frame_total - 1, 1)
        self.window_start, self.window_size = 0, self.total + 1
        self.file_label.setText(f"{os.path.basename(path)} — {reader.duration:.1f}s, ~{self.total + 1} frames at "
                                f"{reader.fps:.1f} fps, {reader.size.width()}×{reader.size.height()}")
        for s in (self.from_spin, self.to_spin):
            s.setRange(0, self.total)
        self.from_spin.setValue(0)
        self.to_spin.setValue(self.total)
        self.every.setValue(max(1, round(reader.fps)))
        self.slider.blockSignals(True)
        self.slider.setRange(0, self.total)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.current = None
        self._zoom_label()
        self._info(0)
        self._extract()
        return True

    def _info(self, i):
        t = i / self.reader.fps if self.reader else 0
        self.info.setText(f"Frame {i} of {self.total} — {t:.2f}s")

    def _zoom_label(self):
        end = self.window_start + self.window_size - 1
        self.zoom_label.setText(f"Showing frames {self.window_start}–{end} of {self.total}")

    def zoom(self, size):
        if self.reader is None:
            return
        size = max(MIN_ZOOM_WINDOW, min(size, self.total + 1))
        cur = self.slider.value()
        start = max(0, min(cur - size // 2, self.total + 1 - size))
        self.window_start, self.window_size = start, size
        self.slider.blockSignals(True)
        self.slider.setRange(start, start + size - 1)
        self.slider.setValue(cur)
        self.slider.blockSignals(False)
        self._zoom_label()
        self._update()

    def step(self, d):
        if self.reader is None:
            return
        v = max(0, min(self.total, self.slider.value() + d))
        if not (self.slider.minimum() <= v <= self.slider.maximum()):
            self.window_start = max(0, min(v - self.window_size // 2, self.total + 1 - self.window_size))
            self.slider.blockSignals(True)
            self.slider.setRange(self.window_start, self.window_start + self.window_size - 1)
            self.slider.blockSignals(False)
            self._zoom_label()
        self.slider.setValue(v)

    def _slider_moved(self, v):
        self._info(v)
        self._timer.start()                # don't decode a frame for every pixel of a drag

    def _extract(self):
        if self.reader is None:
            return
        i = self.slider.value()
        try:
            img = self.reader.frame(i)
        except Exception as e:  # noqa: BLE001
            media.error(self, "Couldn't extract frame", str(e))
            return
        self.current, self.current_index = img, i
        self.view.set_image(img)
        self._update()

    # -- this frame
    def default_out(self):
        return os.path.splitext(self.path)[0] + f"-frame{self.current_index}.png"

    def save_as(self):
        dest = media.ask_save_path(self, "Save Frame As", self.default_out(),
                                   "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;BMP (*.bmp);;TIFF (*.tif)")
        if dest:
            self.save_to(dest)

    def save_to(self, dest):
        if self.current is None:
            return False
        if not os.path.splitext(dest)[1]:
            dest += ".png"
        ext = os.path.splitext(dest)[1].lower()
        img = self.current.convertToFormat(self.current.Format.Format_RGB32) if ext in (".jpg", ".jpeg", ".bmp") \
            else self.current
        if not img.save(dest, quality=95 if ext in (".jpg", ".jpeg", ".webp") else -1):
            media.error(self, "Save failed", f"Couldn't write {os.path.basename(dest)}")
            return False
        if self.api:
            self.api.status(f"Saved {os.path.basename(dest)}")
        media.after_save(self, [dest], [])          # never deletes the video: you may want more frames
        return True

    def copy(self):
        if self.current is not None:
            QGuiApplication.clipboard().setImage(self.current)
            if self.api:
                self.api.status("Frame copied")

    def frame_name(self):
        return f"{os.path.splitext(os.path.basename(self.path))[0]} frame {self.current_index}"

    def open_in_lumen(self):
        if self.current is not None and self.api:
            self.api.open_image(self.current, self.frame_name())

    def add_layer(self):
        if self.current is not None and self.api:
            self.api.add_image_as_layer(self.current, self.frame_name(), show=True)

    # -- a run of frames
    def run_indices(self):
        a, b = sorted((self.from_spin.value(), self.to_spin.value()))
        return list(range(a, b + 1, self.every.value()))

    def export_run(self):
        if self.reader is None:
            return
        idx = self.run_indices()
        if len(idx) > 500 and QMessageBox.question(self, "Export Frames", f"That's {len(idx)} frames. Continue?") \
                != QMessageBox.StandardButton.Yes:
            return
        mode = self.seq_as.currentData()
        base = os.path.splitext(os.path.basename(self.path))[0]
        folder = None
        if mode == "png":
            parent = QFileDialog.getExistingDirectory(self, "Choose a folder for the frames",
                                                      os.path.dirname(self.path))
            if not parent:
                return
            folder = media.unique_path(os.path.join(parent, f"{base}_frames"))
            os.makedirs(folder, exist_ok=True)
        self.progress.setRange(0, len(idx))
        self.progress.show()
        images, names, saved = [], [], []
        try:
            for n, i in enumerate(idx):
                img = self.reader.frame(i)
                if folder:
                    p = os.path.join(folder, f"frame_{i:05d}.png")
                    img.save(p)
                    saved.append(p)
                else:
                    images.append(img)
                    names.append(f"Frame {i}")
                self.progress.setValue(n + 1)
        except Exception as e:  # noqa: BLE001
            media.error(self, "Couldn't export frames", str(e))
        finally:
            self.progress.hide()
        self.slider.setValue(self.slider.value())
        if folder and saved:
            if self.api:
                self.api.status(f"Exported {len(saved)} frames to {folder}")
            QMessageBox.information(self, "Frames exported", f"Exported {len(saved)} frame(s) to:\n\n{folder}")
        elif images and self.api:
            self.api.open_layers(images, f"{base} frames", names)
        return folder or images

    def shutdown(self):
        super().shutdown()
        if self.reader is not None:
            self.reader.close()


def register(api):
    page = VideoToImagePage(api)
    api.add_workspace("Video to Image", page, icon="frame_grab")
    api.add_menu_action("Plugins", "Video to Image", lambda: api.show_workspace(page), needs_document=False)
    register.workspace = page
