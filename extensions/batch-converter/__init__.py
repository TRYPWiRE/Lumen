"""Batch Converter for Lumen: convert and resize images in batches (the File Converter's Images tab)."""
import os

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QComboBox, QToolButton, QMenu, QFileDialog, QSpinBox,
                             QMessageBox)

from lumen import media
from . import convert as cv

IMAGE_EXTS = {p[1:].lower() for p in cv.FORMATS["All Supported Formats"]}


class BatchConverterPage(media.ToolPage):
    def __init__(self, api):
        super().__init__("Batch Converter", "Convert and resize images in batches - PSD, HEIC and camera RAW "
                         "included.", "convert", api)
        self.from_manual = False
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.open_btn = QToolButton()
        self.open_btn.setText("Open  ▾")
        self.open_btn.setObjectName("Primary")
        self.open_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.open_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        m = QMenu(self.open_btn)
        m.addAction("Choose a File…", self.choose_one)
        m.addAction("Choose Multiple Files…", self.choose_many)
        m.addAction("Choose a Folder…", self.choose_folder)
        self.open_btn.setMenu(m)
        bar.addWidget(self.open_btn)
        bar.addSpacing(10)
        bar.addWidget(QLabel("Convert from:"))
        self.from_combo = QComboBox()
        self.from_combo.addItems(list(cv.FORMATS))
        self.from_combo.activated.connect(self._from_set)
        bar.addWidget(self.from_combo)
        bar.addSpacing(10)
        bar.addWidget(QLabel("Convert to:"))
        self.to_combo = QComboBox()
        self.to_combo.addItems(list(cv.output_formats()))
        self.to_combo.currentTextChanged.connect(self._to_changed)
        bar.addWidget(self.to_combo)
        self.quality_label = QLabel("Quality")
        bar.addWidget(self.quality_label)
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(95)
        self.quality.setSuffix("%")
        bar.addWidget(self.quality)
        bar.addStretch(1)
        self.convert_btn = media.primary("Convert")
        self.convert_btn.setMinimumWidth(110)
        self.convert_btn.clicked.connect(self.convert)
        bar.addWidget(self.convert_btn)
        self.body.addLayout(bar)
        self.resize = media.ResizeOptions()
        self.body.addWidget(self.resize)
        self.queue = media.FileQueue([
            ("Save", self.save_one, "Saves next to the original"),
            ("Save To…", self.save_one_to, "Choose a location and file name"),
            ("Open in Lumen", self.open_in_lumen, "Open the converted picture in Lumen"),
        ])
        self.queue.changed.connect(self._update)
        self.body.addWidget(self.queue, 1)
        foot = QHBoxLayout()
        self.status = media.dim("")
        foot.addWidget(self.status, 1)
        clear = media.button("Clear Completed", "Remove finished / failed files from Completed")
        clear.clicked.connect(self.queue.clear_completed)
        foot.addWidget(clear)
        self.all_btn = QToolButton()
        self.all_btn.setText("Download All  ▾")
        self.all_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.all_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        am = QMenu(self.all_btn)
        am.addAction("Save to location found", lambda: self.save_all(None))
        am.addAction("Save to desired location…", self.save_all_to)
        self.all_btn.setMenu(am)
        foot.addWidget(self.all_btn)
        self.body.addLayout(foot)
        self._to_changed(self.to_combo.currentText())
        self._update()

    # -- picking files
    def _filter(self):
        name = self.from_combo.currentText()
        return f"{name} ({' '.join(cv.FORMATS[name])});;All files (*)"

    def _from_set(self, _i):
        self.from_manual = True

    def _start_dir(self):
        return media.settings().value("last_dir", "")

    def choose_one(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a file", self._start_dir(), self._filter())
        if p:
            self.add([p])

    def choose_many(self):
        ps, _ = QFileDialog.getOpenFileNames(self, "Choose files", self._start_dir(), self._filter())
        if ps:
            self.add(ps)

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder of images", self._start_dir())
        if d:
            pats = {p[1:].lower() for p in cv.FORMATS[self.from_combo.currentText()]}
            files = sorted(os.path.join(d, f) for f in os.listdir(d)
                           if os.path.splitext(f)[1].lower() in pats and os.path.isfile(os.path.join(d, f)))
            if not files:
                media.error(self, "No images", "That folder has no images of the chosen type.")
                return
            self.add(files)

    def files_dropped(self, paths):
        files = []
        for p in paths:
            if os.path.isdir(p):
                files += sorted(os.path.join(p, f) for f in os.listdir(p)
                                if os.path.splitext(f)[1].lower() in IMAGE_EXTS)
            else:
                files.append(p)
        self.add(files)

    def add(self, paths):
        if not paths:
            return []
        media.settings().setValue("last_dir", os.path.dirname(paths[0]))
        need = [p for p in paths if cv.needs_camera_pack(p)]
        if need and self.api is not None:
            # HEIC / RAW need a one-time download; queue the files once it's there
            def then(ok):
                if ok:
                    media.register_heif()
                self._add_now(paths)
            if QMessageBox.question(self, "HEIC / camera RAW", "Reading HEIC and camera RAW files needs a "
                                    "one-time download (about 8 MB). Download it now?") == \
                    QMessageBox.StandardButton.Yes:
                self.api.ensure_runtime("camera-formats", then, "HEIC + RAW support")
                return []
        return self._add_now(paths)

    def _add_now(self, paths):
        added = self.queue.add(paths, os.path.basename, self)
        if added and not self.from_manual:
            name = cv.EXT_TO_FORMAT.get(os.path.splitext(added[0])[1].lower().lstrip("."))
            if name:
                self.from_combo.setCurrentText(name)
        return added

    # -- converting (decode in memory; writing happens when you save)
    def _to_changed(self, name):
        q = cv.OUTPUT_FORMATS.get(name, {}).get("quality")
        for w in (self.quality, self.quality_label):
            w.setVisible(q is not None)
        if q:
            self.quality.setValue(q)

    def _update(self):
        self.status.setText(self.queue.summary())
        self.convert_btn.setEnabled(bool(self.queue.pending()))
        self.all_btn.setEnabled(bool(self.queue.results()))

    def convert(self):
        paths = self.queue.pending()
        if not paths:
            media.error(self, "No files", "No files have been added yet.")
            return
        for p in paths:
            self.queue.start(p)
            media.run(lambda _j, src: cv.decode(src), p,
                      done=lambda d, p=p: self.queue.finish(p, d, "Converted" if len(d["frames"]) == 1 else
                                                            f"Converted · {len(d['frames'])} frames"),
                      failed=lambda m, p=p: self.queue.fail(p, m))

    # -- saving
    def out_name(self, src, folder=None):
        ext = cv.OUTPUT_FORMATS[self.to_combo.currentText()]["ext"]
        return os.path.join(folder or os.path.dirname(src), os.path.splitext(os.path.basename(src))[0] + ext)

    def _write(self, src, dest):
        d = self.queue.results().get(src)
        if d is None:
            return False
        try:
            cv.write(d, dest, self.to_combo.currentText(), self.resize.spec(), self.quality.value())
        except Exception as e:  # noqa: BLE001
            media.error(self, "Save failed", f"{os.path.basename(src)}: {e}")
            return False
        self.queue.flash(src)
        return True

    def save_one(self, src):
        dest = self.out_name(src)
        if os.path.abspath(dest) == os.path.abspath(src):
            dest = media.unique_path(dest)
        if self._write(src, dest):
            self._saved([dest], [src])

    def save_one_to(self, src):
        fmt = cv.OUTPUT_FORMATS[self.to_combo.currentText()]
        dest = media.ask_save_path(self, "Save Image As", self.out_name(src),
                                   f"{fmt['pil']} image (*{fmt['ext']})")
        if dest and self._write(src, dest):
            self._saved([dest], [src])

    def save_all(self, folder):
        results = self.queue.results()
        if not results:
            media.error(self, "Nothing to save", "No files have finished converting yet.")
            return
        saved, originals, failed = [], [], 0
        for src in results:
            dest = self.out_name(src, folder)
            if os.path.abspath(dest) == os.path.abspath(src):
                dest = media.unique_path(dest)
            if self._write(src, dest):
                saved.append(dest)
                originals.append(src)
            else:
                failed += 1
        msg = f"Saved {len(saved)} file(s)" + (f", {failed} failed" if failed else "")
        self.status.setText(msg)
        self._saved(saved, originals)

    def save_all_to(self):
        if not self.queue.results():
            media.error(self, "Nothing to save", "No files have finished converting yet.")
            return
        d = QFileDialog.getExistingDirectory(self, "Choose where to save your files", self._start_dir())
        if d:
            self.save_all(d)

    def _saved(self, saved, originals):
        if self.api and saved:
            self.api.status(f"Saved {len(saved)} file(s)")
        media.after_save(self, saved, [o for o, s in zip(originals, saved) if os.path.abspath(o) != os.path.abspath(s)])

    def open_in_lumen(self, src):
        d = self.queue.results().get(src)
        if d is None or self.api is None:
            return
        frames = d["frames"]
        spec = self.resize.spec()
        if spec:
            frames = [media.resize_to_spec(f, spec) for f in frames]
        name = os.path.splitext(os.path.basename(src))[0]
        if len(frames) > 1:
            self.api.open_layers([media.pil_to_qimage(f) for f in frames], name)
        else:
            self.api.open_image(media.pil_to_qimage(frames[0]), name)


def register(api):
    page = BatchConverterPage(api)
    api.add_workspace("Batch Converter", page, icon="convert")
    api.add_menu_action("Plugins", "Batch Converter", lambda: api.show_workspace(page), needs_document=False)
    register.workspace = page

    # Teach Lumen itself to open HEIC / HEIF / AVIF / camera RAW and to save GIF / AVIF / ICO
    def lumen_reader(path):
        if cv.needs_camera_pack(path):
            def then(ok):
                if ok:
                    media.register_heif()
                    api.window().open_path(path)
            api.ensure_runtime("camera-formats", then, "HEIC + RAW support")
            raise media.Deferred()
        return cv.read_for_lumen(path)

    api.add_file_reader(sorted(media.HEIF_EXTS), "HEIC / HEIF photos", lumen_reader)
    api.add_file_reader(sorted(media.RAW_EXTS), "Camera RAW", lumen_reader)
    if media.avif_supported():
        api.add_file_reader([".avif"], "AVIF", lumen_reader)
        api.add_file_writer("avif", "AVIF", cv.writer("AVIF"))
    api.add_file_writer("gif", "GIF", cv.writer("GIF"))
    api.add_file_writer("ico", "Windows Icon", cv.writer("ICO"))
    if media.heif_supported():
        media.register_heif()
