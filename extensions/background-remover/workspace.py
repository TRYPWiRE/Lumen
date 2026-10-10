"""Background Remover workspace tab."""
import os

from PyQt6.QtCore import Qt, QPointF, QSize
from PyQt6.QtGui import QImage, QImageReader
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QLabel, QComboBox,
                             QProgressBar, QSlider, QCheckBox, QScrollArea, QFrame, QSplitter, QFileDialog,
                             QMessageBox, QToolButton, QButtonGroup, QGridLayout)

from . import ai
from .cutout import Cutout, CutoutCanvas

WAND, ERASE, RESTORE = "wand", "erase", "restore"


class BackgroundRemoverWorkspace(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.cut = None
        self.origin = None            # ("file", path) or ("layer", doc, layer, rect)
        self.tool = WAND
        self._last = None
        self._task = None
        self.models_dir = api.data_dir("models")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(12)
        pl.addWidget(self._source_group())
        pl.addWidget(self._ai_group())
        pl.addWidget(self._tools_group())
        pl.addWidget(self._edges_group())
        pl.addWidget(self._output_group())
        pl.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(panel)
        sa.setMinimumWidth(320)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setMaximumWidth(420)
        split.addWidget(sa)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.canvas = CutoutCanvas()
        self.canvas.pressed.connect(self._pressed)
        self.canvas.dragged.connect(self._dragged)
        self.canvas.released.connect(self._released)
        self.canvas.viewChanged.connect(self._zoom_label)
        rl.addWidget(self.canvas, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 6)
        for text, tip, fn in (("−", "Zoom out", lambda: self.canvas.zoom_by(0.8)),
                              ("+", "Zoom in", lambda: self.canvas.zoom_by(1.25))):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setFixedSize(28, 26)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.zoom_lbl = QLabel("—")
        self.zoom_lbl.setMinimumWidth(50)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.zoom_lbl)
        fit = QPushButton("Fit")
        fit.setObjectName("Flat")
        fit.clicked.connect(self.canvas.reset_view)
        bar.addWidget(fit)
        self.status = QLabel("Scroll to zoom where the cursor is · right-drag to move around")
        self.status.setObjectName("Dim")
        bar.addWidget(self.status, 1)
        rl.addLayout(bar)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        root.addWidget(split)
        self._update()

    # ------------------------------------------------------------ panel groups
    def _group(self, title):
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        lay.setSpacing(8)
        return box, lay

    def _source_group(self):
        box, lay = self._group("Image")
        row = QHBoxLayout()
        b = QPushButton("Open Image…")
        b.setObjectName("Primary")
        b.clicked.connect(self.open_file)
        row.addWidget(b)
        self.from_layer_btn = QPushButton("Use Active Layer")
        self.from_layer_btn.setObjectName("Flat")
        self.from_layer_btn.setToolTip("Bring the active layer of the current Lumen document here")
        self.from_layer_btn.clicked.connect(self.from_active_layer)
        row.addWidget(self.from_layer_btn)
        lay.addLayout(row)
        self.file_lbl = QLabel("No image yet")
        self.file_lbl.setObjectName("Dim")
        self.file_lbl.setWordWrap(True)
        lay.addWidget(self.file_lbl)
        return box

    def _ai_group(self):
        box, lay = self._group("Remove the background for me")
        self.model = QComboBox()
        self.model.addItems(list(ai.MODELS))
        self.model.setCurrentIndex(int(self.api.setting("model", 0) or 0))
        self.model.currentIndexChanged.connect(lambda i: self.api.set_setting("model", i))
        self.model.setToolTip("Balanced is quick and small. Best quality is slower but cleaner.\n"
                              "People / characters is trained on human subjects.")
        lay.addWidget(self.model)
        self.ai_btn = QPushButton("AI: Find the Subject and Cut It Out")
        self.ai_btn.setObjectName("Primary")
        self.ai_btn.setMinimumHeight(34)
        self.ai_btn.clicked.connect(self.run_ai)
        lay.addWidget(self.ai_btn)
        self.ai_prog = QProgressBar()
        self.ai_prog.setFixedHeight(6)
        self.ai_prog.setTextVisible(False)
        self.ai_prog.hide()
        lay.addWidget(self.ai_prog)
        hint = QLabel("Looks at the picture to find the subject, so it copes with busy backgrounds. "
                      "The model downloads the first time you use it, then works offline.")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.edges_btn = QPushButton("Or: Clear the Background from the Edges")
        self.edges_btn.setObjectName("Flat")
        self.edges_btn.setToolTip("Clears everything connected to the four corners that matches their colour.\n"
                                  "Best for plain or flat backgrounds.")
        self.edges_btn.clicked.connect(self.clear_edges)
        lay.addWidget(self.edges_btn)
        return box

    def _tools_group(self):
        box, lay = self._group("Touch up by hand")
        row = QHBoxLayout()
        self.tool_grp = QButtonGroup(self)
        from lumen import icons
        for i, (tool, icon, text, tip) in enumerate((
                (WAND, "wand", "Magic Wand", "Click a colour to clear it"),
                (ERASE, "eraser", "Erase", "Brush away what's left"),
                (RESTORE, "restore", "Restore", "Brush back parts that were removed by mistake"))):
            b = QToolButton()
            b.setIcon(icons.icon(icon, 18))
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setObjectName("ModeButton")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setMinimumSize(QSize(82, 48))
            self.tool_grp.addButton(b, i)
            row.addWidget(b)
        self.tool_grp.idClicked.connect(lambda i: self.set_tool((WAND, ERASE, RESTORE)[i]))
        lay.addLayout(row)
        grid = QGridLayout()
        self.tol = QSlider(Qt.Orientation.Horizontal)
        self.tol.setRange(0, 128)
        self.tol.setValue(int(self.api.setting("tolerance", 32) or 32))
        self.tol_lbl = QLabel(str(self.tol.value()))
        self.tol.valueChanged.connect(lambda v: (self.tol_lbl.setText(str(v)), self.api.set_setting("tolerance", v)))
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(2, 300)
        self.size.setValue(int(self.api.setting("brush", 30) or 30))
        self.size_lbl = QLabel(str(self.size.value()))
        self.size.valueChanged.connect(lambda v: (self.size_lbl.setText(str(v)), self.api.set_setting("brush", v),
                                                  self._brush_outline()))
        for r, (label, sl, lbl) in enumerate((("Tolerance", self.tol, self.tol_lbl), ("Brush size", self.size, self.size_lbl))):
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(sl, r, 1)
            lbl.setMinimumWidth(30)
            grid.addWidget(lbl, r, 2)
        lay.addLayout(grid)
        self.contig = QCheckBox("Only clear the area I click on")
        self.contig.setChecked(True)
        lay.addWidget(self.contig)
        row = QHBoxLayout()
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setObjectName("Flat")
        self.undo_btn.clicked.connect(self.undo)
        self.reset_btn = QPushButton("Start Over")
        self.reset_btn.setObjectName("Flat")
        self.reset_btn.clicked.connect(self.reset)
        row.addWidget(self.undo_btn)
        row.addWidget(self.reset_btn)
        lay.addLayout(row)
        return box

    def _edges_group(self):
        box, lay = self._group("Tidy up the edges")
        grid = QGridLayout()
        self.edge_btns = []
        for i, (text, tip, fn) in enumerate((
                ("Soften", "Feather the edge slightly", lambda c: c.soften()),
                ("Tighten", "Shrink the cut-out by 1 px (removes halos)", lambda c: c.tighten()),
                ("Grow", "Expand the cut-out by 1 px", lambda c: c.grow()))):
            b = QPushButton(text)
            b.setObjectName("Flat")
            b.setToolTip(tip)
            b.clicked.connect(lambda _, f=fn: self._edit(f))
            grid.addWidget(b, 0, i)
            self.edge_btns.append(b)
        lay.addLayout(grid)
        self.trim = QCheckBox("Trim to the subject when exporting")
        self.trim.setToolTip("Crop away the empty space around the cut-out")
        lay.addWidget(self.trim)
        return box

    def _output_group(self):
        box, lay = self._group("Use the result")
        self.to_layer_btn = QPushButton("Add to Lumen as New Layer")
        self.to_layer_btn.setObjectName("Primary")
        self.to_layer_btn.clicked.connect(self.add_as_layer)
        lay.addWidget(self.to_layer_btn)
        self.apply_btn = QPushButton("Apply to the Original Layer")
        self.apply_btn.setObjectName("Flat")
        self.apply_btn.setToolTip("Replace the layer this came from with the cut-out (undoable in Lumen)")
        self.apply_btn.clicked.connect(self.apply_to_layer)
        lay.addWidget(self.apply_btn)
        self.open_btn = QPushButton("Open as New Document")
        self.open_btn.setObjectName("Flat")
        self.open_btn.clicked.connect(self.open_document)
        lay.addWidget(self.open_btn)
        row = QHBoxLayout()
        self.fmt = QComboBox()
        self.fmt.addItems(["PNG", "WebP"])
        row.addWidget(self.fmt)
        self.save_btn = QPushButton("Save Image…")
        self.save_btn.setObjectName("Flat")
        self.save_btn.clicked.connect(self.save)
        row.addWidget(self.save_btn, 1)
        lay.addLayout(row)
        return box

    # ------------------------------------------------------------ state
    def _update(self):
        has = self.cut is not None
        for w in [self.ai_btn, self.edges_btn, self.undo_btn, self.reset_btn, self.to_layer_btn, self.open_btn,
                  self.save_btn] + self.edge_btns:
            w.setEnabled(has and self._task is None)
        self.undo_btn.setEnabled(has and bool(self.cut.history))
        self.apply_btn.setEnabled(has and self.origin is not None and self.origin[0] == "layer")
        self.from_layer_btn.setEnabled(self.api.active_layer() is not None)

    def _refresh(self, reset=False):
        if self.cut is not None:
            self.canvas.set_image(self.cut.result(), reset)
        self._update()

    def _zoom_label(self):
        self.zoom_lbl.setText(f"{self.canvas.zoom * 100:.0f}%")

    def set_status(self, text):
        self.status.setText(text)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._update()

    # ------------------------------------------------------------ loading
    def load_image(self, img: QImage, label, origin):
        if img is None or img.isNull():
            return False
        self.cut = Cutout(img, self.api.imageops)
        self.origin = origin
        self.file_lbl.setText(label)
        self._refresh(reset=True)
        self.set_status("Click the background with the Magic Wand, or let the AI find the subject.")
        return True

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", self.api.setting("dir", os.path.expanduser("~")),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff)")
        if not path:
            return
        self.api.set_setting("dir", os.path.dirname(path))
        r = QImageReader(path)
        r.setAutoTransform(True)
        img = r.read()
        if img.isNull():
            QMessageBox.warning(self, "Background Remover", f"Couldn't open that image.\n\n{r.errorString()}")
            return
        self.load_image(img, os.path.basename(path), ("file", path))

    def from_active_layer(self):
        doc = self.api.current_document()
        L = doc.active if doc else None
        if L is None:
            return False
        r = L.rect().intersected(doc.rect()) if not L.background else doc.rect()
        if r.isEmpty():
            return False
        return self.load_image(L.region(r), f"Layer “{L.name}” from {doc.name}", ("layer", doc, L, r))

    # ------------------------------------------------------------ tools
    def set_tool(self, t):
        self.tool = t
        self._brush_outline()

    def _brush_outline(self):
        self.canvas.brush_radius = self.size.value() / 2 if self.tool in (ERASE, RESTORE) else 0
        self.canvas.update()

    def _pressed(self, pt):
        if self.cut is None:
            return
        if self.tool == WAND:
            n = self.cut.wand(int(pt.x()), int(pt.y()), self.tol.value(), self.contig.isChecked())
            self.set_status(f"Cleared {n:,} pixels." if n else "Nothing to clear there.")
            self._refresh()
            return
        self.cut.push()
        self._last = pt
        self.cut.brush(pt, pt, self.size.value() / 2, self.tool == RESTORE)
        self._refresh()

    def _dragged(self, pt):
        if self.cut is None or self.tool == WAND or self._last is None:
            return
        self.cut.brush(self._last, pt, self.size.value() / 2, self.tool == RESTORE)
        self._last = pt
        self._refresh()

    def _released(self):
        self._last = None

    def _edit(self, fn):
        if self.cut is not None:
            fn(self.cut)
            self._refresh()

    def undo(self):
        if self.cut is not None and self.cut.undo():
            self._refresh()

    def reset(self):
        if self.cut is not None:
            self.cut.reset()
            self._refresh()

    def clear_edges(self):
        if self.cut is None:
            return
        n = self.cut.clear_edges(self.tol.value())
        self.set_status(f"Cleared {n:,} background pixels from the edges." if n else
                        "The corners don't share a plain background — try the AI or the Magic Wand.")
        self._refresh()

    # ------------------------------------------------------------ AI
    def run_ai(self):
        if self.cut is None or self._task is not None:
            return
        from lumen import net
        name = ai.MODELS[self.model.currentText()]
        folder = self.models_dir
        img = self.cut.source

        def job(progress=None, cancelled=None):
            path = ai.download_model(folder, name, progress, cancelled)
            return ai.subject_alpha(img, path)
        self._task = net.Task(job, with_progress=True)
        self._task.progress.connect(self._ai_progress)
        self._task.succeeded.connect(self._ai_done)
        self._task.failed.connect(self._ai_failed)
        self.ai_btn.setText("Working…")
        self.ai_prog.setRange(0, 0)
        self.ai_prog.show()
        self.set_status("Downloading the model…" if not ai.have_model(folder, name) else "Finding the subject…")
        self._update()
        self._task.start()

    def _ai_progress(self, done, total):
        if total:
            self.ai_prog.setRange(0, 100)
            self.ai_prog.setValue(int(done * 100 / total))
            self.set_status(f"Downloading the model… {done / 1048576:.1f} of {total / 1048576:.0f} MB")

    def _ai_finish(self):
        self._task = None
        self.ai_btn.setText("AI: Find the Subject and Cut It Out")
        self.ai_prog.hide()
        self._update()

    def _ai_done(self, mask):
        self._ai_finish()
        if self.cut is None or mask.shape != self.cut.alpha.shape:
            return
        self.cut.apply_mask(mask)
        self.set_status("Subject found. Touch up with Erase / Restore if needed.")
        self._refresh()

    def _ai_failed(self, msg):
        self._ai_finish()
        QMessageBox.warning(self, "Background Remover", f"The AI cut-out didn't work.\n\n{msg}")

    # ------------------------------------------------------------ output
    def result(self):
        crop = self.cut.bounds() if self.trim.isChecked() else None
        return self.cut.result(crop), crop

    def add_as_layer(self):
        if self.cut is None:
            return
        img, _ = self.result()
        name = (self.origin[2].name if self.origin and self.origin[0] == "layer" else
                os.path.splitext(self.file_lbl.text())[0]) + " cut-out"
        self.api.add_image_as_layer(img, name[:60])
        self.set_status("Added to Lumen as a new layer.")

    def apply_to_layer(self):
        if self.cut is None or not self.origin or self.origin[0] != "layer":
            return False
        _, doc, L, r = self.origin
        if L not in doc.layers:
            QMessageBox.information(self, "Background Remover", "That layer no longer exists.")
            return False
        doc.undo.beginMacro("Remove Background")
        try:
            if L.background:
                doc.background_to_layer(L)
            doc.apply_patch("Remove Background", r, self.cut.result(), layer=L)
        finally:
            doc.undo.endMacro()
        self.set_status(f"Applied to “{L.name}”.")
        return True

    def open_document(self):
        if self.cut is not None:
            img, _ = self.result()
            self.api.open_image(img, "Cut-out")

    def save(self):
        if self.cut is None:
            return
        ext = ".png" if self.fmt.currentText() == "PNG" else ".webp"
        base = os.path.splitext(self.file_lbl.text().split("“")[-1].split("”")[0])[0] or "cutout"
        path, _ = QFileDialog.getSaveFileName(self, "Save Cut-out",
                                              os.path.join(self.api.setting("dir", os.path.expanduser("~")),
                                                           base + "-cutout" + ext),
                                              f"{self.fmt.currentText()} (*{ext})")
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        img, _ = self.result()
        if img.convertToFormat(QImage.Format.Format_ARGB32).save(path, quality=95):
            self.set_status(f"Saved {os.path.basename(path)}")
        else:
            QMessageBox.warning(self, "Background Remover", "Couldn't save the image.")
