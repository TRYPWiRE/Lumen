"""Photoshop-style Layers panel."""
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QFont, QImage, QFontMetrics
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QToolButton, QScrollArea,
                             QLineEdit, QMenu, QFrame, QSizePolicy)

from . import icons, theme
from .layers import BLEND_MODES, BLEND_LABELS
from .widgets import labeled_spin

ROW_H = 40
EYE_W = 30
THUMB = 30


def _checker_brush(size=4):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    p.fillRect(0, 0, size, size, QColor("#cccccc"))
    p.fillRect(size, size, size, size, QColor("#cccccc"))
    p.end()
    return QBrush(pm)


class LayerList(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._thumbs = {}
        self._press = None
        self._drag_to = None
        self._editor = None
        self._checker = _checker_brush()

    # ------------------------------------------------------------ geometry
    def doc(self):
        return self.panel.doc

    def rows(self):
        d = self.doc()
        return list(reversed(d.layers)) if d else []

    def sizeHint(self):
        return QSize(220, max(ROW_H, len(self.rows()) * ROW_H))

    def refresh(self):
        self.setMinimumHeight(max(ROW_H, len(self.rows()) * ROW_H))
        self.update()

    def row_at(self, y):
        i = int(y // ROW_H)
        rows = self.rows()
        return (i, rows[i]) if 0 <= i < len(rows) else (None, None)

    def thumb_rect(self, i):
        return QRect(EYE_W + 8, i * ROW_H + (ROW_H - THUMB) // 2, THUMB, THUMB)

    def name_rect(self, i):
        x = EYE_W + 8 + THUMB + 8
        return QRect(x, i * ROW_H, self.width() - x - 28, ROW_H)

    # ------------------------------------------------------------ painting
    def thumbnail(self, L):
        d = self.doc()
        key = (L.uid, L.version, d.width, d.height, id(L.display()))
        pm = self._thumbs.get(L.uid)
        if pm is not None and pm[0] == key:
            return pm[1]
        s = min(THUMB / d.width, THUMB / d.height)
        w, h = max(1, round(d.width * s)), max(1, round(d.height * s))
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.fillRect(img.rect(), self._checker)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.scale(s, s)
        p.drawImage(L.offset, L.display())
        p.end()
        pm = QPixmap.fromImage(img)
        self._thumbs[L.uid] = (key, pm)
        return pm

    def paintEvent(self, ev):
        p = QPainter(self)
        C = theme.C
        p.fillRect(self.rect(), QColor(C["window"]))
        d = self.doc()
        if not d:
            return
        f = self.font()
        italic = QFont(f)
        italic.setItalic(True)
        for i, L in enumerate(self.rows()):
            r = QRect(0, i * ROW_H, self.width(), ROW_H)
            active = L is d.active
            if active:
                p.fillRect(r, QColor(C["selection"]))
            p.setPen(QColor(C["border"]))
            p.drawLine(r.bottomLeft(), r.bottomRight())
            p.drawLine(EYE_W, r.top(), EYE_W, r.bottom())
            # eye
            if L.visible:
                p.drawPixmap(EYE_W // 2 - 8, r.top() + ROW_H // 2 - 8, icons.pixmap("eye", 16, QColor(C["icon"])))
            # thumbnail
            tr = self.thumb_rect(i)
            if L.is_text:
                p.fillRect(tr, QColor("#dadada"))
                tf = QFont(f)
                tf.setPixelSize(20)
                tf.setBold(True)
                p.setFont(tf)
                p.setPen(QColor("#2b2b2b"))
                p.drawText(tr, Qt.AlignmentFlag.AlignCenter, "T")
                p.setFont(f)
            else:
                pm = self.thumbnail(L)
                pr = QRect(0, 0, pm.width(), pm.height())
                pr.moveCenter(tr.center())
                p.drawPixmap(pr.topLeft(), pm)
                tr = pr
            p.setPen(QPen(QColor(C["text_strong"] if active else C["border"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(tr.adjusted(-1, -1, 0, 0))
            # name
            nr = self.name_rect(i)
            p.setFont(italic if L.background else f)
            p.setPen(QColor(C["text_strong"] if active else C["text"]) if L.visible else QColor(C["text_dim"]))
            name = QFontMetrics(p.font()).elidedText(L.name, Qt.TextElideMode.ElideRight, nr.width())
            p.drawText(nr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            p.setFont(f)
            # lock
            if L.background or L.lock_all or L.lock_alpha or L.lock_pixels or L.lock_position:
                full = L.background or L.lock_all
                col = QColor(C["icon"]) if full else QColor(C["text_dim"])
                p.drawPixmap(self.width() - 22, r.top() + ROW_H // 2 - 7, icons.pixmap("lock", 14, col))
        # drop indicator
        if self._drag_to is not None:
            y = self._drag_to * ROW_H
            p.setPen(QPen(QColor(C["accent"]), 2))
            p.drawLine(0, y, self.width(), y)

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        d = self.doc()
        if not d:
            return
        self._close_editor(commit=True)
        i, L = self.row_at(ev.position().y())
        if L is None:
            return
        pos = ev.position().toPoint()
        if ev.button() == Qt.MouseButton.RightButton:
            d.set_active(L)
            self.panel.context_menu(L, ev.globalPosition().toPoint())
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if pos.x() < EYE_W:
            if ev.modifiers() & Qt.KeyboardModifier.AltModifier:
                d.solo(L)
            else:
                d.toggle_visible(L)
            return
        if self.thumb_rect(i).adjusted(-2, -2, 2, 2).contains(pos) and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            d.select_layer_pixels(L)
            return
        d.set_active(L)
        self._press = (pos, L)

    def mouseMoveEvent(self, ev):
        if self._press is None or not (ev.buttons() & Qt.MouseButton.LeftButton):
            return
        start, L = self._press
        if (ev.position().toPoint() - start).manhattanLength() < 6 or L.background:
            return
        n = len(self.rows())
        self._drag_to = max(0, min(n, int(round(ev.position().y() / ROW_H))))
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._press is not None and self._drag_to is not None:
            _, L = self._press
            d = self.doc()
            n = len(d.layers)
            # drop slot k (from the top) means "above the row k" → stack index n - k
            target = n - self._drag_to
            cur = d.layers.index(L)
            if target > cur:
                target -= 1
            d.move_layer_to(L, target)
        self._press = None
        self._drag_to = None
        self.update()

    def mouseDoubleClickEvent(self, ev):
        i, L = self.row_at(ev.position().y())
        if L is None or ev.position().x() < EYE_W:
            return
        pos = ev.position().toPoint()
        d = self.doc()
        if L.background:
            d.background_to_layer(L)
            return
        if self.thumb_rect(i).adjusted(-2, -2, 2, 2).contains(pos) and L.is_text:
            self.panel.edit_text_requested(L)
            return
        self.start_rename(i, L)

    # ------------------------------------------------------------ rename
    def start_rename(self, i, L):
        self._close_editor(commit=False)
        e = QLineEdit(L.name, self)
        e.setGeometry(self.name_rect(i).adjusted(-4, 8, 0, -8))
        e.selectAll()
        e.show()
        e.setFocus()
        e.editingFinished.connect(lambda: self._close_editor(commit=True))
        self._editor = (e, L)

    def _close_editor(self, commit):
        if not self._editor:
            return
        e, L = self._editor
        self._editor = None
        if commit and self.doc():
            self.doc().rename_layer(L, e.text())
        e.deleteLater()
        self.update()


class LayersPanel(QWidget):
    editTextRequested = pyqtSignal(object)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.doc = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(5)
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        self.blend = QComboBox()
        self.blend.setToolTip("Set the blending mode for the layer")
        for m in BLEND_MODES:
            if m is None:
                self.blend.insertSeparator(self.blend.count())
            else:
                self.blend.addItem(m[1], m[0])
        self.blend.setMaxVisibleItems(40)
        self.blend.activated.connect(self._blend_chosen)
        r1.addWidget(self.blend, 1)
        w, self.opacity = labeled_spin("Opacity:", 0, 100, 100, "%", 58)
        self.opacity.valueChanged.connect(lambda v: self._prop("opacity", v, "Opacity Change"))
        r1.addWidget(w)
        tl.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(3)
        lab = QLabel("Lock:")
        lab.setObjectName("Dim")
        r2.addWidget(lab)
        self.locks = {}
        for key, ic, tip in (("lock_alpha", "lock_alpha", "Lock transparent pixels"),
                             ("lock_pixels", "lock_pixels", "Lock image pixels"),
                             ("lock_position", "lock_position", "Lock position"),
                             ("lock_all", "lock", "Lock all")):
            b = QToolButton()
            b.setIcon(icons.icon(ic, 16))
            b.setIconSize(QSize(14, 14))
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setFixedSize(24, 22)
            b.toggled.connect(lambda on, k=key: self._lock(k, on))
            r2.addWidget(b)
            self.locks[key] = b
        r2.addStretch(1)
        w, self.fill = labeled_spin("Fill:", 0, 100, 100, "%", 58)
        self.fill.valueChanged.connect(lambda v: self._prop("fill", v, "Fill Opacity Change"))
        r2.addWidget(w)
        tl.addLayout(r2)
        lay.addWidget(top)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #232323;")
        lay.addWidget(sep)

        self.list = LayerList(self)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(self.list)
        lay.addWidget(sa, 1)

        bottom = QFrame()
        bottom.setObjectName("PanelFooter")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(6, 3, 6, 3)
        bl.addStretch(1)
        for ic, tip, slot in (("new_layer", "Create a new layer (Shift+Ctrl+Alt+N)", lambda: self.doc and self.doc.add_layer()),
                              ("trash", "Delete layer", lambda: self.doc and self.doc.delete_layer())):
            b = QToolButton()
            b.setIcon(icons.icon(ic, 18))
            b.setIconSize(QSize(16, 16))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bl.addWidget(b)
        lay.addWidget(bottom)
        self._busy = False
        self.set_document(None)

    # ------------------------------------------------------------ document binding
    def set_document(self, doc):
        if self.doc is not None:
            for sig in (self.doc.layersChanged, self.doc.activeLayerChanged):
                try:
                    sig.disconnect(self.refresh)
                except (TypeError, RuntimeError):
                    pass
        self.doc = doc
        if doc is not None:
            doc.layersChanged.connect(self.refresh)
            doc.activeLayerChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self._busy = True
        d = self.doc
        L = d.active if d else None
        enabled = L is not None
        for w in [self.blend, self.opacity, self.fill] + list(self.locks.values()):
            w.setEnabled(enabled and not L.background)
        if L is not None:
            self.blend.setCurrentIndex(max(0, self.blend.findData(L.blend)))
            self.opacity.setValue(L.opacity)
            self.fill.setValue(L.fill)
            for k, b in self.locks.items():
                b.setChecked(bool(getattr(L, k)))
            if L.background:
                self.locks["lock_all"].setChecked(True)
        self._busy = False
        self.list.refresh()

    # ------------------------------------------------------------ edits
    def _prop(self, key, value, text):
        if self._busy or not self.doc:
            return
        self.doc.set_props(self.doc.active, text, merge_key=key, **{key: value})

    def _blend_chosen(self, i):
        if self.doc and not self._busy:
            key = self.blend.itemData(i)
            if key:
                self.doc.set_props(self.doc.active, "Blending Change", blend=key)

    def _lock(self, key, on):
        if self._busy or not self.doc:
            return
        self.doc.set_props(self.doc.active, "Lock Layer" if on else "Unlock Layer", **{key: on})

    def edit_text_requested(self, L):
        self.editTextRequested.emit(L)

    def context_menu(self, L, pos):
        w = self.window
        m = QMenu(self)
        if L.background:
            m.addAction("Layer from Background…", lambda: self.doc.background_to_layer(L))
        m.addAction("Duplicate Layer", w.A["dup_layer"].trigger)
        m.addAction("Delete Layer", w.A["del_layer"].trigger)
        m.addAction("Rename Layer", lambda: self.list.start_rename(self.list.rows().index(L), L))
        m.addSeparator()
        if L.is_text:
            m.addAction("Rasterize Type", lambda: self.doc.rasterize_layer(L))
            m.addSeparator()
        m.addAction("Select Pixels", lambda: self.doc.select_layer_pixels(L))
        m.addSeparator()
        m.addAction("Merge Down", w.A["merge_down"].trigger).setEnabled(self.doc.layers.index(L) > 0)
        m.addAction("Merge Visible", w.A["merge_visible"].trigger)
        m.addAction("Flatten Image", w.A["flatten"].trigger)
        m.exec(pos)
