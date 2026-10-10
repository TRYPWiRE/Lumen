"""Right-hand panels: Navigator, Info, History, and the panel-group container."""
import math
from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QUndoGroup
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QTabWidget,
                             QGridLayout, QToolButton, QUndoView)

from . import icons, theme, imageops


class PanelGroup(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelGroup")
        self.setDocumentMode(False)
        self.setUsesScrollButtons(False)
        self.tabBar().setExpanding(False)


class NavigatorView(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setMinimumHeight(120)
        self._thumb = None
        self._dirty = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def invalidate(self):
        self._dirty = True
        self.update()

    def _layout(self):
        cv = self.panel.canvas
        if not cv:
            return None
        w, h = self.width() - 16, self.height() - 16
        s = min(w / cv.doc.width, h / cv.doc.height)
        tw, th = cv.doc.width * s, cv.doc.height * s
        return QRectF((self.width() - tw) / 2, (self.height() - th) / 2, tw, th), s

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        lay = self._layout()
        if not lay:
            return
        r, s = lay
        cv = self.panel.canvas
        if self._dirty or self._thumb is None or self._thumb.size() != r.size().toSize():
            self._thumb = cv.doc.flattened().scaled(r.size().toSize(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation)
            self._dirty = False
        p.fillRect(r, QColor("white"))
        p.drawImage(r.topLeft(), self._thumb)
        vis = cv.visible_image_rect()
        vr = QRectF(r.x() + vis.x() * s, r.y() + vis.y() * s, vis.width() * s, vis.height() * s)
        p.setPen(QPen(QColor("#ff3b30"), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(vr.adjusted(0.5, 0.5, -0.5, -0.5))

    def _go(self, pos):
        lay = self._layout()
        if not lay:
            return
        r, s = lay
        self.panel.canvas.center_on(QPointF((pos.x() - r.x()) / s, (pos.y() - r.y()) / s))

    def mousePressEvent(self, ev):
        self._go(ev.position())

    def mouseMoveEvent(self, ev):
        if ev.buttons():
            self._go(ev.position())


class NavigatorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(4)
        self.view = NavigatorView(self)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        self.pct = QLabel("100%")
        self.pct.setFixedWidth(52)
        row.addWidget(self.pct)
        out = QToolButton()
        out.setIcon(icons.icon("zoom_out"))
        out.setIconSize(QSize(14, 14))
        out.clicked.connect(lambda: self.canvas and self.canvas.zoom_step(-1))
        row.addWidget(out)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self._slid)
        row.addWidget(self.slider, 1)
        inn = QToolButton()
        inn.setIcon(icons.icon("zoom_in"))
        inn.setIconSize(QSize(14, 14))
        inn.clicked.connect(lambda: self.canvas and self.canvas.zoom_step(1))
        row.addWidget(inn)
        lay.addLayout(row)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(150)
        self._thumb_timer.timeout.connect(self.view.invalidate)

    def set_canvas(self, cv):
        if self.canvas:
            for sig, slot in ((self.canvas.viewChanged, self.view.update),
                              (self.canvas.zoomChanged, self._zoom),
                              (self.canvas.doc.changed, self._doc_changed),
                              (self.canvas.doc.sizeChanged, self.view.invalidate)):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self.canvas = cv
        if cv:
            cv.viewChanged.connect(self.view.update)
            cv.zoomChanged.connect(self._zoom)
            cv.doc.changed.connect(self._doc_changed)
            cv.doc.sizeChanged.connect(self.view.invalidate)
            self._zoom(cv.zoom)
        self.view.invalidate()

    def _doc_changed(self, *_):
        self._thumb_timer.start()

    @staticmethod
    def _z_to_slider(z):
        return int(round((math.log2(z) + 5) / 10 * 1000))

    def _zoom(self, z):
        self.pct.setText(f"{z * 100:.4g}%")
        self.slider.blockSignals(True)
        self.slider.setValue(self._z_to_slider(z))
        self.slider.blockSignals(False)

    def _slid(self, v):
        if self.canvas:
            self.canvas.set_zoom(2 ** (v / 1000 * 10 - 5))


class InfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = None
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.vals = {}
        rows = [("R", 0, 0), ("G", 1, 0), ("B", 2, 0), ("A", 3, 0),
                ("X", 0, 2), ("Y", 1, 2), ("W", 2, 2), ("H", 3, 2)]
        for key, r, c in rows:
            lab = QLabel(key + ":")
            lab.setObjectName("Dim")
            grid.addWidget(lab, r, c)
            v = QLabel("")
            v.setMinimumWidth(48)
            grid.addWidget(v, r, c + 1)
            self.vals[key] = v
        self.swatch = QLabel()
        self.swatch.setFixedSize(26, 26)
        grid.addWidget(self.swatch, 0, 4, 2, 1)
        self.doc_label = QLabel("")
        self.doc_label.setObjectName("Dim")
        grid.addWidget(self.doc_label, 5, 0, 1, 5)
        grid.setRowStretch(6, 1)
        grid.setColumnStretch(5, 1)

    def set_canvas(self, cv):
        if self.canvas:
            try:
                self.canvas.cursorMoved.disconnect(self.cursor)
                self.canvas.doc.selectionChanged.disconnect(self.selection)
                self.canvas.doc.sizeChanged.disconnect(self.selection)
            except (TypeError, RuntimeError):
                pass
        self.canvas = cv
        if cv:
            cv.cursorMoved.connect(self.cursor)
            cv.doc.selectionChanged.connect(self.selection)
            cv.doc.sizeChanged.connect(self.selection)
        self.cursor(None)
        self.selection()

    def cursor(self, pt):
        cv = self.canvas
        if cv is None or pt is None or not cv.doc.rect().contains(pt):
            for k in "RGBAXY":
                self.vals[k].setText("")
            self.swatch.setStyleSheet("")
            return
        c = cv.doc.display_image().pixelColor(pt)
        self.vals["R"].setText(str(c.red()))
        self.vals["G"].setText(str(c.green()))
        self.vals["B"].setText(str(c.blue()))
        self.vals["A"].setText(str(c.alpha()))
        self.vals["X"].setText(str(pt.x()))
        self.vals["Y"].setText(str(pt.y()))
        self.swatch.setStyleSheet(f"background: {c.name()}; border: 1px solid #111;")

    def selection(self):
        cv = self.canvas
        if not cv:
            self.vals["W"].setText("")
            self.vals["H"].setText("")
            self.doc_label.setText("")
            return
        r = cv.doc.selection_bounds()
        self.vals["W"].setText(str(r.width()) if not r.isEmpty() else "")
        self.vals["H"].setText(str(r.height()) if not r.isEmpty() else "")
        self.doc_label.setText(f"Document: {cv.doc.width} × {cv.doc.height} px")


class HistoryPanel(QWidget):
    def __init__(self, group: QUndoGroup, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = QUndoView(group)
        self.view.setCleanIcon(icons.icon("check"))
        lay.addWidget(self.view)
