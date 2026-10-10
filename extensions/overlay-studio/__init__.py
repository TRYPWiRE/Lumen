"""Overlay Studio for Lumen: put one image (still or animated) over another and export it."""
import os
import threading

from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, QElapsedTimer, QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QColor, QPen, QPixmap, QImage, QPainter, QBrush
from PyQt6.QtWidgets import (QHBoxLayout, QVBoxLayout, QGridLayout, QWidget, QFileDialog, QLabel, QSpinBox,
                             QSlider, QCheckBox, QComboBox, QFrame, QGraphicsScene, QGraphicsView,
                             QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsItem, QScrollArea)

from lumen import media, theme
from . import compose as C


class Slot(QFrame):
    """Import box for one layer: thumbnail, name, Import / From Lumen / Clear. Accepts drag-and-drop."""

    def __init__(self, title, page, role):
        super().__init__()
        self.page, self.role = page, role
        self.setAcceptDrops(True)
        self.setObjectName("Slot")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)
        self.thumb = QLabel("＋")
        self.thumb.setFixedSize(64, 64)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        h = QLabel(title)
        h.setStyleSheet("font-weight: 700;")
        col.addWidget(h)
        self.name = media.dim("Drop an image here or click Import")
        col.addWidget(self.name)
        row = QHBoxLayout()
        imp = media.primary("Import…")
        imp.setStyleSheet("QPushButton { padding: 4px 10px; min-width: 0; }")
        imp.clicked.connect(lambda: page.pick(role))
        row.addWidget(imp)
        lum = media.button("From Lumen", "Use the picture open in Lumen", small=True)
        lum.clicked.connect(lambda: page.from_lumen(role))
        row.addWidget(lum)
        self.clear_btn = media.button("Clear", small=True)
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(lambda: page.clear(role))
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        col.addLayout(row)
        lay.addLayout(col, 1)
        self._restyle()
        theme.notifier.changed.connect(self._restyle)

    def _restyle(self, *_):
        c = theme.C
        self.setStyleSheet(f"QFrame#Slot {{ border: 1px dashed {c['separator']}; border-radius: 8px; }}")
        self.thumb.setStyleSheet(f"background: {c['pasteboard']}; border-radius: 6px; font-size: 22px; "
                                 f"color: {c['text_dim']};")

    def set_layer(self, layer):
        if layer is None:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("＋")
            self.name.setText("Drop an image here or click Import")
            self.clear_btn.setEnabled(False)
            return
        self.thumb.setPixmap(layer.pixmaps[0].scaled(58, 58, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        w, h = layer.size
        extra = f"  •  {len(layer.frames)} frames" if layer.animated else ""
        self.name.setText(f"{layer.name}\n{w} × {h}{extra}")
        self.clear_btn.setEnabled(True)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() or ev.mimeData().hasImage():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        m = ev.mimeData()
        if m.hasUrls() and m.urls()[0].isLocalFile():
            self.page.load_path(self.role, m.urls()[0].toLocalFile())
            ev.acceptProposedAction()
        elif m.hasImage():
            self.page.load_image(self.role, QImage(m.imageData()), "dropped image")
            ev.acceptProposedAction()


class Forefront(QGraphicsPixmapItem):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move • Arrow keys nudge (Shift = 10 px)")

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene() is not None:
            return self.page.clamp(value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.page.fg_moved()
        return super().itemChange(change, value)

    def keyPressEvent(self, ev):
        step = 10 if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        d = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0), Qt.Key.Key_Up: (0, -step),
             Qt.Key.Key_Down: (0, step)}.get(ev.key())
        if d is None:
            return super().keyPressEvent(ev)
        self.setPos(self.pos() + QPointF(*d))


class Preview(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(320, 260)
        self.restyle()

    def restyle(self, *_):
        self.setBackgroundBrush(QColor(theme.C["pasteboard"]))

    def fit(self):
        r = self.sceneRect()
        if not r.isEmpty():
            pad = max(r.width(), r.height()) * 0.03
            self.fitInView(r.adjusted(-pad, -pad, pad, pad), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.fit()


class OverlayPage(media.ToolPage):
    def __init__(self, api):
        super().__init__("Overlay Studio", "Put one image over another - animation is kept.", "overlay", api)
        self.bg = self.fg = None
        self.bg_item = self.fg_item = None
        self.anchor = ("c", "m")
        self.fg_pos = None
        self._programmatic = self._syncing = False
        self._tokens = {"bg": 0, "fg": 0}
        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        root = QHBoxLayout()
        root.setSpacing(16)
        panel = QVBoxLayout()
        panel.setSpacing(12)
        lg, ll = media.group("Layers")
        self.bg_slot = Slot("Background image", self, "bg")
        self.fg_slot = Slot("Forefront image", self, "fg")
        ll.addWidget(self.bg_slot)
        ll.addWidget(self.fg_slot)
        swap = media.button("⇅  Swap layers")
        swap.clicked.connect(self.swap)
        ll.addWidget(swap)
        panel.addWidget(lg)
        pg, pl = media.group("Position")
        grid = QGridLayout()
        self.preset_buttons = {}
        for i, (label, h, v) in enumerate(C.PRESETS):
            b = media.button(label)
            b.setCheckable(True)
            b.setStyleSheet("QPushButton { padding: 4px 6px; min-width: 0; }")
            b.clicked.connect(lambda _=False, a=(h, v): self.apply_preset(a))
            grid.addWidget(b, i // 3, i % 3)
            self.preset_buttons[(h, v)] = b
        pl.addLayout(grid)
        form = QGridLayout()
        form.addWidget(QLabel("Edge margin"), 0, 0)
        self.margin = QSpinBox()
        self.margin.setRange(0, 5000)
        self.margin.setValue(20)
        self.margin.setSuffix(" px")
        self.margin.valueChanged.connect(lambda _: self.anchor and self.apply_preset(self.anchor))
        form.addWidget(self.margin, 0, 1, 1, 3)
        form.addWidget(QLabel("X"), 1, 0)
        self.x_spin = QSpinBox()
        form.addWidget(self.x_spin, 1, 1)
        form.addWidget(QLabel("Y"), 1, 2, Qt.AlignmentFlag.AlignRight)
        self.y_spin = QSpinBox()
        form.addWidget(self.y_spin, 1, 3)
        for s in (self.x_spin, self.y_spin):
            s.setRange(-100000, 100000)
            s.setSuffix(" px")
            s.valueChanged.connect(self._spin_moved)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        pl.addLayout(form)
        self.keep_inside = QCheckBox("Keep forefront inside the background")
        self.keep_inside.setChecked(True)
        self.keep_inside.toggled.connect(lambda _: self._nudge_in())
        pl.addWidget(self.keep_inside)
        panel.addWidget(pg)
        sg, sl = media.group("Size && look")
        f2 = QGridLayout()
        f2.addWidget(QLabel("Scale"), 0, 0)
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(1, 400)
        self.scale_slider.setValue(100)
        f2.addWidget(self.scale_slider, 0, 1)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(1, 1000)
        self.scale_spin.setValue(100)
        self.scale_spin.setSuffix(" %")
        f2.addWidget(self.scale_spin, 0, 2)
        self.scale_slider.valueChanged.connect(self.scale_spin.setValue)
        self.scale_spin.valueChanged.connect(self._scale_changed)
        quick = QHBoxLayout()
        for label, frac in (("¼ width", 0.25), ("⅓ width", 1 / 3), ("½ width", 0.5), ("100%", None)):
            b = media.button(label)
            b.setStyleSheet("QPushButton { padding: 3px 6px; min-width: 0; }")
            b.clicked.connect(lambda _=False, f=frac: self.quick_scale(f))
            quick.addWidget(b)
        f2.addLayout(quick, 1, 1, 1, 2)
        f2.addWidget(QLabel("Opacity"), 2, 0)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        f2.addWidget(self.opacity, 2, 1)
        self.opacity_lbl = QLabel("100%")
        f2.addWidget(self.opacity_lbl, 2, 2)
        self.opacity.valueChanged.connect(self._opacity_changed)
        f2.setColumnStretch(1, 1)
        sl.addLayout(f2)
        panel.addWidget(sg)
        eg, el = media.group("Export")
        row = QHBoxLayout()
        self.fmt = QComboBox()
        self.fmt.addItems(media.animation_formats())
        self.fmt.currentTextChanged.connect(lambda _: self._info())
        row.addWidget(self.fmt, 1)
        self.save_btn = media.primary("Save Image…")
        self.save_btn.clicked.connect(self.save)
        row.addWidget(self.save_btn, 1)
        el.addLayout(row)
        self.lumen_btn = media.button("Open in Lumen", "Open the result in Lumen (animation frames become layers)")
        self.lumen_btn.clicked.connect(self.open_in_lumen)
        el.addWidget(self.lumen_btn)
        self.info = media.dim("")
        el.addWidget(self.info)
        panel.addWidget(eg)
        panel.addStretch(1)
        pw = QWidget()
        pw.setLayout(panel)
        pw.setFixedWidth(430)
        root.addWidget(pw)
        pv, pvl = media.group("Preview")
        head = QHBoxLayout()
        head.addWidget(media.dim("Drag the forefront to move it, or click it and use the arrow keys (Shift = 10 px)."),
                       1)
        self.status = media.dim("", wrap=False)
        head.addWidget(self.status)
        pvl.addLayout(head)
        self.scene = QGraphicsScene(self)
        self.view = Preview(self.scene)
        pvl.addWidget(self.view, 1)
        root.addWidget(pv, 1)
        self.body.addLayout(root, 1)
        theme.notifier.changed.connect(self._theme)
        self.rebuild()

    def _theme(self, *_):
        self.view.restyle()
        self.rebuild()

    # -- loading
    def files_dropped(self, paths):
        role = "bg" if self.bg is None else "fg"
        self.load_path(role, paths[0])

    def pick(self, role):
        path, _ = QFileDialog.getOpenFileName(self, "Choose background image" if role == "bg" else
                                              "Choose forefront image", media.settings().value("last_dir", ""),
                                              media.IMAGE_FILTER)
        if path:
            media.settings().setValue("last_dir", os.path.dirname(path))
            self.load_path(role, path)

    def load_path(self, role, path):
        def read():
            with open(path, "rb") as f:
                return f.read()
        self._load(role, read, os.path.basename(path))

    def load_image(self, role, qimg, name):
        pil = media.qimage_to_pil(qimg)
        self._load(role, lambda: pil, name)

    def from_lumen(self, role):
        img = self.lumen_image()
        if img is None:
            media.error(self, "Lumen", "Open or create an image in Lumen first.")
            return
        doc = self.api.current_document()
        self.load_image(role, img, getattr(doc, "name", "Lumen image"))

    def _load(self, role, fetch, name):
        self._tokens[role] += 1
        token = self._tokens[role]
        (self.bg_slot if role == "bg" else self.fg_slot).name.setText(f"Loading {name}…")

        def job(_j):
            return C.build_layer(fetch(), name)
        media.run(job, done=lambda layer: self._ready(role, token, layer),
                  failed=lambda m: self._load_failed(role, token, m))

    def _load_failed(self, role, token, msg):
        if token != self._tokens[role]:
            return
        (self.bg_slot if role == "bg" else self.fg_slot).set_layer(getattr(self, role))
        media.error(self, "Couldn't load image", msg)

    def _ready(self, role, token, layer):
        if token != self._tokens[role]:
            return
        layer.pixmaps = [QPixmap.fromImage(q) for q in layer.qimages]
        if role == "bg":
            self.bg = layer
            self.bg_slot.set_layer(layer)
        else:
            self.fg = layer
            self.fg_slot.set_layer(layer)
            self.fg_pos = None
            self.anchor = self.anchor or ("c", "m")
            self._auto_scale()
        self.status.setText(f"Loaded {layer.name}")
        self.rebuild()

    def clear(self, role):
        self._tokens[role] += 1
        setattr(self, role, None)
        (self.bg_slot if role == "bg" else self.fg_slot).set_layer(None)
        self.rebuild()

    def swap(self):
        self.bg, self.fg = self.fg, self.bg
        self.bg_slot.set_layer(self.bg)
        self.fg_slot.set_layer(self.fg)
        self.fg_pos = None
        self.anchor = self.anchor or ("c", "m")
        self._auto_scale()
        self.rebuild()

    def _auto_scale(self):
        pct = 100
        if self.bg and self.fg:
            bw, bh = self.bg.size
            fw, fh = self.fg.size
            if fw > bw or fh > bh:
                pct = max(1, int(min(bw / fw, bh / fh) * 50))
        self.scale_spin.setValue(pct)

    # -- scene
    def rebuild(self):
        self.timer.stop()
        self.bg_item = self.fg_item = None
        self.scene.clear()
        if not self.bg:
            t = self.scene.addText("Import a background image to start")
            t.setDefaultTextColor(QColor(theme.C["text_dim"]))
            self.scene.setSceneRect(QRectF(-200, -40, 600, 120))
            self.view.fit()
            self._controls()
            return
        w, h = self.bg.size
        rect = QRectF(0, 0, w, h)
        chk = QGraphicsRectItem(rect)
        chk.setBrush(QBrush(media.Checker.brush_pixmap(10)))
        chk.setPen(QPen(Qt.PenStyle.NoPen))
        self.scene.addItem(chk)
        self.bg_item = QGraphicsPixmapItem(self.bg.pixmaps[0])
        self.bg_item.setZValue(1)
        self.bg_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene.addItem(self.bg_item)
        outline = QGraphicsRectItem(rect)
        outline.setPen(QPen(QColor(theme.C["separator"])))
        outline.setZValue(3)
        self.scene.addItem(outline)
        if self.fg:
            self.fg_item = Forefront(self)
            self.fg_item.setPixmap(self.fg.pixmaps[0])
            self.fg_item.setScale(self.scale_spin.value() / 100)
            self.fg_item.setOpacity(self.opacity.value() / 100)
            self.fg_item.setZValue(2)
            self.scene.addItem(self.fg_item)
            if self.anchor is not None or self.fg_pos is None:
                self.apply_preset(self.anchor or ("c", "m"))
            else:
                self._move(*self.fg_pos)
            self.fg_item.setSelected(True)
        self.scene.setSceneRect(rect)
        self.view.fit()
        if self.bg.animated or (self.fg and self.fg.animated):
            self.timer.start()
        self._controls()

    def _tick(self):
        t = self.clock.elapsed()
        if self.bg_item is not None and self.bg.animated:
            self.bg_item.setPixmap(self.bg.pixmaps[self.bg.index_at(t)])
        if self.fg_item is not None and self.fg.animated:
            self.fg_item.setPixmap(self.fg.pixmaps[self.fg.index_at(t)])

    def _fg_size(self):
        w, h = self.fg.size
        s = self.scale_spin.value() / 100
        return w * s, h * s

    def clamp(self, value):
        x, y = round(value.x()), round(value.y())
        if self.keep_inside.isChecked() and self.bg and self.fg:
            bw, bh = self.bg.size
            fw, fh = self._fg_size()
            lx, hx = sorted((0, round(bw - fw)))
            ly, hy = sorted((0, round(bh - fh)))
            x, y = min(max(x, lx), hx), min(max(y, ly), hy)
        return QPointF(x, y)

    def _move(self, x, y):
        if self.fg_item is None:
            return
        self._programmatic = True
        try:
            self.fg_item.setPos(QPointF(x, y))
        finally:
            self._programmatic = False
        self.fg_moved(programmatic=True)

    def fg_moved(self, programmatic=None):
        if self.fg_item is None:
            return
        programmatic = self._programmatic if programmatic is None else programmatic
        pos = self.fg_item.pos()
        self.fg_pos = (pos.x(), pos.y())
        if not programmatic:
            self.anchor = None
        self._syncing = True
        self.x_spin.setValue(round(pos.x()))
        self.y_spin.setValue(round(pos.y()))
        self._syncing = False
        self._preset_buttons()
        self._info()

    def _spin_moved(self):
        if self._syncing or self.fg_item is None:
            return
        self.anchor = None
        self._move(self.x_spin.value(), self.y_spin.value())
        self._preset_buttons()

    def _nudge_in(self):
        if self.fg_item is not None:
            if self.anchor:
                self.apply_preset(self.anchor)
            else:
                self._move(*self.fg_pos)

    def apply_preset(self, anchor):
        self.anchor = anchor
        if not (self.bg and self.fg and self.fg_item is not None):
            self._preset_buttons()
            return
        bw, bh = self.bg.size
        fw, fh = self._fg_size()
        m = self.margin.value()
        h, v = anchor
        x = {"l": m, "c": (bw - fw) / 2, "r": bw - fw - m}[h]
        y = {"t": m, "m": (bh - fh) / 2, "b": bh - fh - m}[v]
        self._move(x, y)
        self.anchor = anchor
        self._preset_buttons()

    def _preset_buttons(self):
        for k, b in self.preset_buttons.items():
            b.setChecked(k == self.anchor)

    def quick_scale(self, frac):
        if not self.fg:
            return
        if frac is None:
            self.scale_spin.setValue(100)
        elif self.bg:
            self.scale_spin.setValue(max(1, round(self.bg.size[0] * frac / self.fg.size[0] * 100)))

    def _scale_changed(self, pct):
        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(min(pct, self.scale_slider.maximum()))
        self.scale_slider.blockSignals(False)
        if self.fg_item is None:
            return
        old = self.fg_item.scale()
        fw, fh = self.fg.size
        center = self.fg_item.pos() + QPointF(fw * old / 2, fh * old / 2)
        self.fg_item.setScale(pct / 100)
        if self.anchor:
            self.apply_preset(self.anchor)
        else:
            self._move(center.x() - fw * pct / 200, center.y() - fh * pct / 200)
        self._info()

    def _opacity_changed(self, v):
        self.opacity_lbl.setText(f"{v}%")
        if self.fg_item is not None:
            self.fg_item.setOpacity(v / 100)

    def _controls(self):
        has_fg = self.fg_item is not None
        for w in (self.x_spin, self.y_spin, self.scale_slider, self.scale_spin, self.opacity, self.margin,
                  *self.preset_buttons.values()):
            w.setEnabled(has_fg)
        self.save_btn.setEnabled(self.bg is not None)
        self.lumen_btn.setEnabled(self.bg is not None)
        self._preset_buttons()
        self._info()

    def _info(self):
        if not self.bg:
            self.info.setText("Output uses the background's size.")
            return
        w, h = self.bg.size
        parts = [f"Output: {w} × {h}"]
        if self.fg_item is not None:
            fw, fh = self._fg_size()
            parts.append(f"Forefront: {round(fw)} × {round(fh)}")
        if self.bg.animated or (self.fg is not None and self.fg.animated):
            parts.append("PNG saves a still of the first frame — choose GIF, WebP or AVIF to keep animation."
                         if self.fmt.currentText() == "PNG" else "Animation will be kept.")
        self.info.setText("\n".join(parts))

    # -- export
    def _render_args(self):
        fg = self.fg if self.fg_item is not None else None
        x, y = self.fg_pos if fg else (0, 0)
        return self.bg, fg, x, y, self.scale_spin.value() / 100, self.opacity.value() / 100

    def render(self, animate=True):
        bg, fg, x, y, s, o = self._render_args()
        return C.compose(bg, fg, x, y, s, o, animate)

    def save(self, path=None):
        if not self.bg:
            return
        fmt = self.fmt.currentText().lower()
        suffix = "." + fmt
        if path is None:
            base = os.path.splitext(self.bg.name)[0] or "overlay"
            default = os.path.join(media.settings().value("last_save_dir", os.path.expanduser("~")),
                                   f"{base}_overlay{suffix}")
            path = media.ask_save_path(self, "Save Overlay", default, f"{fmt.upper()} image (*{suffix})")
            if not path:
                return
        if not path.lower().endswith(suffix):
            path += suffix
        media.settings().setValue("last_save_dir", os.path.dirname(path))
        args = self._render_args()
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving…")
        self.status.setText("Rendering…")

        def job(_j):
            frames, durs = C.compose(*args, animate=(fmt != "png"))
            media.save_animation(frames, durs, path, fmt)
            return path

        def done(p):
            self.save_btn.setEnabled(True)
            self.save_btn.setText("Save Image…")
            self.status.setText(f"Saved {os.path.basename(p)}")
            self.last_saved = p
            media.after_save(self, [p], [])

        def failed(msg):
            self.save_btn.setEnabled(True)
            self.save_btn.setText("Save Image…")
            self.status.setText("")
            media.error(self, "Save failed", msg)
        return media.run(job, done=done, failed=failed)

    def open_in_lumen(self):
        if not self.bg or self.api is None:
            return
        frames, _ = self.render(animate=True)
        name = f"{os.path.splitext(self.bg.name)[0]} overlay"
        if len(frames) > 1:
            self.api.open_layers([media.pil_to_qimage(f) for f in frames], name)
        else:
            self.api.open_image(media.pil_to_qimage(frames[0]), name)

    def shutdown(self):
        super().shutdown()
        self.timer.stop()


def register(api):
    page = OverlayPage(api)
    api.add_workspace("Overlay Studio", page, icon="overlay")
    api.add_menu_action("Plugins", "Overlay Studio", lambda: api.show_workspace(page), needs_document=False)
    register.workspace = page
