"""WebP Flipbook for Lumen: animated WebP and sprite sheets → animated GIF (or PNG frames / Lumen layers)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (QHBoxLayout, QVBoxLayout, QGridLayout, QWidget, QFileDialog, QLabel, QLineEdit,
                             QComboBox, QSpinBox, QCheckBox, QProgressBar, QMessageBox)

from lumen import media, theme
from . import flipbook as fb


class FlipbookPage(media.ToolPage):
    def __init__(self, api):
        super().__init__("WebP Flipbook", "Animated WebP and sprite / flipbook sheets → animated GIF.", "grid", api)
        self.path = ""
        self.base = ""
        self.output_dir = ""
        self.source = None          # Pillow image
        self.animated = False
        self.from_lumen = False
        self.busy = False
        self.showing_slices = False
        row = QHBoxLayout()
        self.choose_btn = media.primary("Select WebP…")
        self.choose_btn.clicked.connect(self.choose)
        row.addWidget(self.choose_btn)
        self.lumen_src_btn = media.button("Use Lumen Image", "Treat the picture open in Lumen as a sprite sheet")
        self.lumen_src_btn.clicked.connect(self.use_lumen)
        row.addWidget(self.lumen_src_btn)
        self.file_label = media.dim("No file selected - pick one or drop it here")
        row.addWidget(self.file_label, 1)
        self.body.addLayout(row)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        ctl, cl = media.group("Flipbook / sprite sheet")
        g = QGridLayout()
        g.addWidget(QLabel("Columns"), 0, 0)
        self.cols_edit = QLineEdit("Auto")
        self.cols_edit.setFixedWidth(90)
        self.cols_edit.setToolTip("Frames across. 'Auto' lets the detector decide.")
        self.cols_edit.editingFinished.connect(self.refresh)
        g.addWidget(self.cols_edit, 0, 1)
        g.addWidget(QLabel("Rows"), 1, 0)
        self.rows_edit = QLineEdit("Auto")
        self.rows_edit.setFixedWidth(90)
        self.rows_edit.setToolTip("Frames down. 'Auto' lets the detector decide.")
        self.rows_edit.editingFinished.connect(self.refresh)
        g.addWidget(self.rows_edit, 1, 1)
        self.detect_btn = media.button("Auto Detect Grid")
        self.detect_btn.clicked.connect(lambda: self.detect(quiet=False))
        g.addWidget(self.detect_btn, 0, 2, 2, 1)
        g.setColumnStretch(3, 1)
        cl.addLayout(g)
        cl.addWidget(media.dim("Leave both on Auto for a normal animated WebP. For a flipbook or sprite sheet, Auto "
                               "looks for the repeating frame grid - you can always type the real numbers in."))
        g2 = QGridLayout()
        g2.addWidget(QLabel("Frame order"), 0, 0)
        self.order = QComboBox()
        self.order.addItems(["Row → Column", "Column → Row"])
        self.order.currentIndexChanged.connect(self.refresh)
        g2.addWidget(self.order, 0, 1, 1, 2)
        g2.addWidget(QLabel("GIF FPS"), 1, 0)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(fb.DEFAULT_FPS)
        self.fps.setSuffix(" fps")
        self.fps.valueChanged.connect(lambda _: self.showing_slices and self.preview_animation())
        g2.addWidget(self.fps, 1, 1)
        g2.setColumnStretch(3, 1)
        cl.addLayout(g2)
        cl.addWidget(media.dim("FPS is used for sprite sheets. An animated WebP keeps its own frame timings."))
        rrow = QHBoxLayout()
        self.resize_check = QCheckBox("Resize output")
        self.resize_check.toggled.connect(self._toggle_resize)
        rrow.addWidget(self.resize_check)
        self.w_spin, self.h_spin = QSpinBox(), QSpinBox()
        for s, pre in ((self.w_spin, "W "), (self.h_spin, "H ")):
            s.setRange(1, 10000)
            s.setValue(512)
            s.setPrefix(pre)
            rrow.addWidget(s)
        rrow.addStretch(1)
        cl.addLayout(rrow)
        self.export_frames = QCheckBox("Also export individual PNG frames")
        cl.addWidget(self.export_frames)
        self.transparency = QCheckBox("Keep transparent background")
        self.transparency.setChecked(True)
        self.transparency.setToolTip("Keep see-through areas see-through in the GIF. GIF transparency is "
                                     "all-or-nothing, so soft edges become solid or fully clear.")
        cl.addWidget(self.transparency)
        self.optimize = QCheckBox("Optimise GIF where possible")
        self.optimize.setChecked(True)
        self.optimize.setToolTip("Skipped automatically when a transparent background is being kept.")
        cl.addWidget(self.optimize)
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Output folder"))
        self.out_label = media.dim("Same folder as the source")
        orow.addWidget(self.out_label, 1)
        browse = media.button("Browse")
        browse.clicked.connect(self.choose_output)
        orow.addWidget(browse)
        cl.addLayout(orow)
        self.convert_btn = media.primary("Convert to GIF")
        self.convert_btn.setMinimumHeight(36)
        self.convert_btn.clicked.connect(lambda: self.start(fb.gif_job))
        cl.addWidget(self.convert_btn)
        brow = QHBoxLayout()
        self.png_btn = media.button("Export PNG frame(s)")
        self.png_btn.clicked.connect(lambda: self.start(fb.png_job))
        brow.addWidget(self.png_btn)
        self.layers_btn = media.button("Open Frames in Lumen", "Every frame becomes a layer in a new document")
        self.layers_btn.clicked.connect(self.open_layers)
        brow.addWidget(self.layers_btn)
        cl.addLayout(brow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        cl.addWidget(self.progress)
        self.status_label = media.dim("Ready.")
        cl.addWidget(self.status_label)
        cl.addStretch(1)
        ctl.setFixedWidth(480)
        cols.addWidget(ctl)

        pv, pl = media.group("Source preview")
        self.view = media.AnimationView("Select a WebP to preview it here.", (320, 300))
        self.view.overlay = self._draw_grid
        pl.addWidget(self.view, 1)
        prow = QHBoxLayout()
        self.grid_check = QCheckBox("Show detected grid over the sheet")
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(lambda _: self.view.update())
        prow.addWidget(self.grid_check)
        prow.addStretch(1)
        self.anim_btn = media.button("Preview Animation", "Slice the sheet and play the frames")
        self.anim_btn.clicked.connect(self.toggle_animation)
        prow.addWidget(self.anim_btn)
        pl.addLayout(prow)
        self.info = media.dim("No source loaded.")
        pl.addWidget(self.info)
        self.player = media.PlayerControls(self.view)
        pl.addWidget(self.player)
        cols.addWidget(pv, 1)
        self.body.addLayout(cols, 1)
        self._toggle_resize(False)
        self._update()

    # -- source
    def files_dropped(self, paths):
        self.load(paths[0])

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select WebP", media.settings().value("last_dir", ""),
                                              "WebP files (*.webp);;Image files (*.webp *.png *.gif *.jpg *.jpeg "
                                              "*.bmp *.tif *.tiff);;All files (*)")
        if path:
            media.settings().setValue("last_dir", os.path.dirname(path))
            self.load(path)

    def load(self, path):
        try:
            with media.PIL.Image.open(path) as f:
                f.load()
                n = getattr(f, "n_frames", 1)
                frames, durs = media.read_frames(f, limit=fb.MAX_PREVIEW_FRAMES) if n > 1 else \
                    ([media.to_rgba(f)], [100])
        except Exception as e:  # noqa: BLE001
            media.error(self, "Could not open file", str(e))
            return False
        self.path, self.from_lumen = path, False
        self.base = os.path.splitext(os.path.basename(path))[0]
        self.output_dir = os.path.dirname(path)
        self.file_label.setText(path)
        self.out_label.setText(self.output_dir)
        self._set_source(frames[0], os.path.getsize(path), n, frames, durs)
        return True

    def use_lumen(self):
        img = self.lumen_image()
        if img is None:
            media.error(self, "Lumen", "Open or create an image in Lumen first.")
            return
        doc = self.api.current_document()
        self.path, self.from_lumen = "", True
        self.base = os.path.splitext(getattr(doc, "name", "sheet"))[0]
        self.output_dir = os.path.dirname(getattr(doc, "path", "") or "") or os.path.expanduser("~")
        self.file_label.setText(f"Lumen: {getattr(doc, 'name', 'image')}")
        self.out_label.setText(self.output_dir)
        pil = media.qimage_to_pil(img)
        self._set_source(pil, 0, 1, [pil], [100])

    def _set_source(self, first, size, n_frames, frames, durs):
        """first: the (first) frame as RGBA - the file itself is already closed."""
        self.source = first
        self.animated = n_frames > 1
        self.showing_slices = False
        self.view.set_frames(frames, durs)
        kind = "Animated WebP" if self.animated else "Static image / sprite sheet"
        lines = [f"Type: {kind}", f"Canvas: {first.width} × {first.height}", f"Native frames: {n_frames}"]
        if size:
            lines.append(f"File size: {media.format_size(size)}")
        self.info.setText("\n".join(lines))
        if self.animated:
            self.cols_edit.setText("Auto")
            self.rows_edit.setText("Auto")
            self.status_label.setText("Animated WebP loaded — frame timings will be kept.")
        else:
            self.detect(quiet=True)
        self._update()

    def choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder", self.output_dir)
        if d:
            self.output_dir = d
            self.out_label.setText(d)

    # -- grid
    def parse_grid(self):
        def parse(text, name):
            t = text.strip().lower()
            if t in ("", "auto"):
                return None
            try:
                v = int(t)
            except ValueError:
                raise ValueError(f"{name} must be a whole number, or 'Auto'.") from None
            if v < 1:
                raise ValueError(f"{name} must be at least 1.")
            return v
        return parse(self.cols_edit.text(), "Columns"), parse(self.rows_edit.text(), "Rows")

    def detect(self, quiet=False):
        if self.source is None:
            return
        try:
            c, r, why = fb.detect_grid(self.source, self.animated)
        except Exception as e:  # noqa: BLE001
            if not quiet:
                media.error(self, "Auto detection failed", str(e))
            return
        self.cols_edit.setText(str(c))
        self.rows_edit.setText(str(r))
        self.status_label.setText(f"Detected {c} × {r} grid — {why}.")
        self.refresh()

    def grid(self):
        if self.animated or self.source is None:
            return None
        try:
            c, r = self.parse_grid()
        except ValueError:
            return None
        if not c or not r or (c == 1 and r == 1):
            return None
        return c, r

    def _draw_grid(self, p, rect, _size):
        g = self.grid()
        if not g or self.showing_slices or not self.grid_check.isChecked():
            return
        c, r = g
        p.setPen(QPen(QColor(theme.C["accent"]), 1))
        for i in range(1, c):
            x = rect.left() + rect.width() * i / c
            p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
        for i in range(1, r):
            y = rect.top() + rect.height() * i / r
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

    def refresh(self):
        if self.showing_slices:
            self.preview_animation()
        self.view.update()

    def toggle_animation(self):
        if self.showing_slices:
            self.showing_slices = False
            self.view.set_frames([media.to_rgba(self.source)], [100])
            self.anim_btn.setText("Preview Animation")
        else:
            self.preview_animation()
        self.player.refresh()

    def preview_animation(self):
        if self.source is None or self.animated:
            return
        try:
            frames, durs, _ = fb.extract_frames(self.settings())
        except ValueError as e:
            media.error(self, "Check the settings", str(e))
            return
        self.showing_slices = True
        self.anim_btn.setText("Show Sheet")
        self.view.set_frames(frames[:fb.MAX_PREVIEW_FRAMES], durs)
        self.player.refresh()

    # -- converting
    def _toggle_resize(self, on):
        self.w_spin.setEnabled(on)
        self.h_spin.setEnabled(on)

    def _update(self):
        has = self.source is not None
        sprite = has and not self.animated
        for w in (self.convert_btn, self.png_btn, self.layers_btn):
            w.setEnabled(has and not self.busy)
        for w in (self.cols_edit, self.rows_edit, self.detect_btn, self.order, self.fps, self.grid_check,
                  self.anim_btn):
            w.setEnabled(sprite)
        self.player.refresh()

    def settings(self):
        c, r = self.parse_grid()
        return {"path": self.path, "image": self.source.copy() if self.from_lumen or not self.path else None,
                "cols": c, "rows": r, "order": "row" if self.order.currentIndex() == 0 else "column",
                "fps": float(self.fps.value()),
                "resize": (self.w_spin.value(), self.h_spin.value()) if self.resize_check.isChecked() else None,
                "export_frames": self.export_frames.isChecked(), "optimize": self.optimize.isChecked(),
                "transparency": self.transparency.isChecked(), "output_dir": self.output_dir, "base": self.base}

    def start(self, job_fn):
        if self.source is None or self.busy:
            return
        try:
            s = self.settings()
        except ValueError as e:
            media.error(self, "Check the settings", str(e))
            return
        self.busy = True
        self._update()
        self.progress.setValue(0)
        self.status_label.setText("Working…")
        media.run(job_fn, s, done=self._done, failed=self._failed,
                  progress=lambda v: self.progress.setValue(int(max(0.0, min(1.0, v)) * 100)),
                  status=self.status_label.setText)

    def _done(self, result):
        self.busy = False
        self._update()
        self.progress.setValue(100)
        self.last_result = result
        saved = [result["gif"]] if result.get("gif") else []
        QMessageBox.information(self, result["title"], result["message"])
        media.after_save(self, saved or [result.get("folder")], [] if self.from_lumen else [self.path])

    def _failed(self, msg):
        self.busy = False
        self._update()
        self.progress.setValue(0)
        self.status_label.setText("Failed.")
        media.error(self, "Conversion failed", msg)

    def open_layers(self):
        if self.source is None or self.api is None:
            return
        try:
            frames, _, _ = fb.extract_frames(self.settings())
            frames = fb.resize_frames(frames, self.settings()["resize"])
        except ValueError as e:
            media.error(self, "Check the settings", str(e))
            return
        self.api.open_layers([media.pil_to_qimage(f) for f in frames], f"{self.base} frames")


def register(api):
    page = FlipbookPage(api)
    api.add_workspace("WebP Flipbook", page, icon="grid")
    api.add_menu_action("Plugins", "WebP Flipbook", lambda: api.show_workspace(page), needs_document=False)
    register.workspace = page
