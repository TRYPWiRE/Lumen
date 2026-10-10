"""WebP to GIF for Lumen: batch-convert animated or still WebPs into GIFs."""
import os
import shutil

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QCheckBox, QWidget, QFileDialog, \
    QLabel

from lumen import media

QUALITY_DEFAULT, FRAMES_DEFAULT, WIDTH_DEFAULT = 80, 100, 400


def keep_every_for(frames_value):
    """10-100 % of frames kept → keep every Nth frame."""
    return 1 if frames_value >= 100 else max(1, round(100 / max(frames_value, 1)))


def build_gif_from_webp(source_path, output_path, quality, frames_value, width=None):
    """Every frame of a WebP → GIF. quality = palette size + dithering, frames_value thins the animation
    (durations stretched so the speed is kept), width rescales keeping the aspect ratio."""
    PIL = media.PIL
    frames, durations = [], []
    with PIL.Image.open(source_path) as im:
        had_alpha = media.has_transparency(im)
        for fr in PIL.ImageSequence.Iterator(im):
            frames.append(fr.convert("RGBA").copy())
            durations.append(fr.info.get("duration", 100) or 100)
    if not frames:
        raise RuntimeError("No frames could be read from this WebP.")
    keep = keep_every_for(frames_value)
    colors = max(8, round(8 + (quality / 100) * 248))
    dither = PIL.DITHER_FS if quality >= 35 else PIL.DITHER_NONE
    outs, durs = [], []
    for i, (f, d) in enumerate(zip(frames, durations)):
        if i % keep:
            continue
        if width:
            w, h = f.size
            f = f.resize((max(int(width), 1), max(int(round(h * width / w)), 1)), PIL.LANCZOS)
        outs.append(f)
        durs.append(d * keep)
    if not outs:
        raise RuntimeError("No frames left after applying the Frames setting.")
    media.save_gif(outs, durs, output_path, colors=colors, dither=dither, transparent=had_alpha)
    return output_path


def describe(path):
    PIL = media.PIL
    size = os.path.getsize(path)
    with PIL.Image.open(path) as im:
        w, h = im.size
        n = getattr(im, "n_frames", 1)
    return f"{os.path.basename(path)} — {w}×{h}, {n} frame{'s' if n != 1 else ''}, {media.format_size(size)}"


class WebpToGifPage(media.ToolPage):
    def __init__(self, api):
        super().__init__("WebP to GIF", "Convert WebP files - animated or still - into GIFs, in batches.", "webp",
                         api)
        self.previewed = None
        top = QHBoxLayout()
        self.open_btn = media.primary("Open WebP(s)…")
        self.open_btn.clicked.connect(self.choose)
        top.addWidget(self.open_btn)
        self.status = media.dim("")
        top.addWidget(self.status, 1)
        self.body.addLayout(top)
        self.queue = media.FileQueue([
            ("Show Preview", self.preview, "Play this GIF in the preview"),
            ("Save", self.save_one, "Saves next to the original WebP"),
            ("Save To…", self.save_one_to, "Choose a location and file name"),
            ("Open in Lumen", self.open_in_lumen, "Open the GIF's frames as layers in Lumen"),
        ])
        self.queue.changed.connect(self._update)
        self.body.addWidget(self.queue, 1)

        work = QHBoxLayout()
        work.setSpacing(16)
        left = QVBoxLayout()
        settings = QGroupBox("GIF Settings")
        g = QGridLayout(settings)
        g.setContentsMargins(14, 16, 14, 14)
        g.setColumnStretch(1, 1)
        self.quality, _ = media.slider_row(g, 0, "Quality", 1, 100, QUALITY_DEFAULT, "%")
        self.frames, _ = media.slider_row(g, 1, "Frames", 10, 100, FRAMES_DEFAULT, "%")
        self.width, self.width_label = media.slider_row(g, 2, "Width", 50, 1000, WIDTH_DEFAULT, " px")
        self.keep_width = QCheckBox("Keep original")
        self.keep_width.setChecked(True)
        self.keep_width.toggled.connect(self._keep_width)
        g.addWidget(self.keep_width, 2, 3)
        g.addWidget(media.dim("These settings apply to every file when you press Convert or a Target Size."),
                    3, 0, 1, 4)
        left.addWidget(settings)
        self.convert_btn = media.primary("Convert")
        self.convert_btn.setMinimumHeight(36)
        self.convert_btn.clicked.connect(self.convert)
        left.addWidget(self.convert_btn)
        self.targets = media.TargetSizeBox(discord=False, columns=5)
        self.targets.chosen.connect(lambda b, _sq: self.convert(target=b))
        left.addWidget(self.targets)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        work.addWidget(lw, 1)
        pv, pl = media.group("Preview")
        self.caption = media.dim("Nothing previewed yet")
        pl.addWidget(self.caption)
        self.view = media.AnimationView('Press “Show Preview” on a finished file')
        self.view.setMinimumHeight(260)
        pl.addWidget(self.view, 1)
        pv.setMinimumWidth(360)
        work.addWidget(pv, 1)
        self.body.addLayout(work)

        foot = QHBoxLayout()
        clear = media.button("Clear Completed", "Remove finished / failed files from Completed")
        clear.clicked.connect(self.clear)
        foot.addWidget(clear)
        foot.addStretch(1)
        self.save_all_btn = media.primary("Save All")
        self.save_all_btn.setToolTip("Saves every finished GIF next to its WebP")
        self.save_all_btn.clicked.connect(self.save_all)
        foot.addWidget(self.save_all_btn)
        self.body.addLayout(foot)
        self._keep_width(True)
        self._update()

    # -- files
    def files_dropped(self, paths):
        self.add([p for p in paths if p.lower().endswith(".webp")] or paths)

    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose WebP image(s)", media.settings().value("last_dir", ""),
                                                "WebP images (*.webp);;All files (*)")
        if paths:
            media.settings().setValue("last_dir", os.path.dirname(paths[0]))
            self.add(paths)

    def add(self, paths):
        return self.queue.add(paths, describe, self)

    def _keep_width(self, on):
        self.width.setEnabled(not on)
        self.width_label.setText("Original" if on else f"{self.width.value()} px")

    def _update(self):
        self.status.setText(self.queue.summary())
        has = bool(self.queue.pending())
        self.convert_btn.setEnabled(has)
        self.targets.setEnabled(has)
        self.save_all_btn.setEnabled(bool(self.queue.results()))

    # -- converting
    def convert(self, target=None):
        paths = self.queue.pending()
        if not paths:
            media.error(self, "No files", "Add some WebP files first.")
            return
        quality, frames = self.quality.value(), self.frames.value()
        width = None if self.keep_width.isChecked() else self.width.value()

        def job(j, src):
            out = media.temp_path(".gif")
            if target is None:
                build_gif_from_webp(src, out, quality, frames, width)
                return out, quality, True
            used = 1
            for q in range(100, 0, -10):
                build_gif_from_webp(src, out, q, frames, width)
                used = q
                if os.path.getsize(out) <= target:
                    return out, q, True
            return out, used, False

        for p in paths:
            self.queue.start(p)
            original = os.path.getsize(p)
            media.run(job, p, done=lambda r, p=p, o=original: self._done(p, r, o),
                      failed=lambda m, p=p: self.queue.fail(p, m))

    def _done(self, src, result, original):
        out, q, met = result
        size = os.path.getsize(out)
        pct = 100 * (1 - size / original) if original else 0
        status = f"{media.format_size(size)} ({abs(pct):.0f}% {'smaller' if pct >= 0 else 'larger'})"
        self.queue.finish(src, out, status)
        if not met:
            media.error(self, "Couldn't fully meet target", f"{os.path.basename(src)}: even at the lowest quality "
                        f"the GIF is {media.format_size(size)}, which is still over the target. Try fewer frames or "
                        "a smaller width.")

    # -- results
    def preview(self, src):
        out = self.queue.results().get(src)
        if out:
            self.view.load_file(out)
            self.caption.setText(f"Preview: {os.path.basename(src)} → GIF, {media.format_size(os.path.getsize(out))}")
            self.previewed = src

    @staticmethod
    def default_out(src):
        return os.path.splitext(src)[0] + ".gif"

    def _save(self, src, dest):
        out = self.queue.results().get(src)
        if not out:
            return False
        try:
            shutil.copyfile(out, dest)
        except OSError as e:
            media.error(self, "Save failed", str(e))
            return False
        self.queue.flash(src)
        return True

    def save_one(self, src):
        dest = self.default_out(src)
        if self._save(src, dest):
            media.after_save(self, [dest], [src])

    def save_one_to(self, src):
        dest = media.ask_save_path(self, "Save GIF As", self.default_out(src), "GIF image (*.gif)")
        if dest and self._save(src, dest):
            media.after_save(self, [dest], [src])

    def save_all(self):
        saved, originals = [], []
        for src in self.queue.results():
            dest = self.default_out(src)
            if self._save(src, dest):
                saved.append(dest)
                originals.append(src)
        if self.api:
            self.api.status(f"Saved {len(saved)} GIF(s)")
        media.after_save(self, saved, originals)

    def open_in_lumen(self, src):
        out = self.queue.results().get(src)
        if out and self.api:
            frames, _ = media.read_frames(out)
            self.api.open_layers([media.pil_to_qimage(f) for f in frames], os.path.splitext(os.path.basename(src))[0])

    def clear(self):
        gone = self.queue.clear_completed()
        if self.previewed in gone:
            self.view.clear('Press “Show Preview” on a finished file')
            self.caption.setText("Nothing previewed yet")


def register(api):
    page = WebpToGifPage(api)
    api.add_workspace("WebP to GIF", page, icon="webp")
    api.add_menu_action("Plugins", "WebP to GIF", lambda: api.show_workspace(page), needs_document=False)
    register.workspace = page
