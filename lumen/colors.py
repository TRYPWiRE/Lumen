"""Colour picking UI: spectrum, picker dialog, foreground/background chips, swatches."""
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF, QRect, QSize, QPoint
from PyQt6.QtGui import (QPainter, QColor, QLinearGradient, QPen, QPixmap, QBrush, QIntValidator,
                         QRegularExpressionValidator)
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
                             QSpinBox, QDialog, QPushButton, QSizePolicy, QToolButton, QMenu)

from . import icons, theme


def _chk(size=6):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    p.fillRect(0, 0, size, size, QColor("#c8c8c8"))
    p.fillRect(size, size, size, size, QColor("#c8c8c8"))
    p.end()
    return QBrush(pm)


class SVSquare(QWidget):
    changed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.h, self.s, self.v = 0.0, 1.0, 1.0
        self._cache = None
        self._cache_key = None
        self.setMinimumSize(120, 100)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_hsv(self, h, s, v):
        self.h, self.s, self.v = h, s, v
        self.update()

    def _bg(self):
        key = (round(self.h, 4), self.width(), self.height())
        if key != self._cache_key:
            pm = QPixmap(self.size())
            p = QPainter(pm)
            r = QRectF(pm.rect())
            p.fillRect(r, QColor.fromHsvF(self.h, 1, 1))
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, QColor(255, 255, 255, 255))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(r, g)
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 255))
            p.fillRect(r, g)
            p.end()
            self._cache, self._cache_key = pm, key
        return self._cache

    def paintEvent(self, ev):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = self.s * (self.width() - 1)
        y = (1 - self.v) * (self.height() - 1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("black"), 1))
        p.drawEllipse(QPointF(x, y), 6, 6)
        p.setPen(QPen(QColor("white"), 1.5))
        p.drawEllipse(QPointF(x, y), 5, 5)

    def _set_from(self, pos):
        s = min(1.0, max(0.0, pos.x() / max(1, self.width() - 1)))
        v = 1.0 - min(1.0, max(0.0, pos.y() / max(1, self.height() - 1)))
        self.s, self.v = s, v
        self.update()
        self.changed.emit(s, v)

    def mousePressEvent(self, ev):
        self._set_from(ev.position())

    def mouseMoveEvent(self, ev):
        if ev.buttons():
            self._set_from(ev.position())


class HueBar(QWidget):
    changed = pyqtSignal(float)

    def __init__(self, vertical=True, parent=None):
        super().__init__(parent)
        self.vertical = vertical
        self.h = 0.0
        if vertical:
            self.setFixedWidth(18)
        else:
            self.setFixedHeight(14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_hue(self, h):
        self.h = h
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(3 if self.vertical else 0, 0 if self.vertical else 2,
                                         -3 if self.vertical else 0, 0 if self.vertical else -2)
        g = QLinearGradient(r.topLeft(), r.bottomLeft() if self.vertical else r.topRight())
        for i in range(7):
            t = i / 6
            g.setColorAt(t, QColor.fromHsvF(((1 - t) if self.vertical else t) % 1.0, 1, 1))
        p.fillRect(r, g)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("black"), 1))
        p.setBrush(QColor("white"))
        if self.vertical:
            y = (1 - self.h) * (self.height() - 1)
            p.drawPolygon([QPointF(0, y - 4), QPointF(5, y), QPointF(0, y + 4)])
            w = self.width()
            p.drawPolygon([QPointF(w, y - 4), QPointF(w - 5, y), QPointF(w, y + 4)])
        else:
            x = self.h * (self.width() - 1)
            p.drawRect(QRectF(x - 2.5, 0.5, 5, self.height() - 1))

    def _set_from(self, pos):
        if self.vertical:
            h = 1.0 - min(1.0, max(0.0, pos.y() / max(1, self.height() - 1)))
        else:
            h = min(1.0, max(0.0, pos.x() / max(1, self.width() - 1)))
        self.h = min(h, 0.9999)
        self.update()
        self.changed.emit(self.h)

    def mousePressEvent(self, ev):
        self._set_from(ev.position())

    def mouseMoveEvent(self, ev):
        if ev.buttons():
            self._set_from(ev.position())


class ColorPicker(QWidget):
    """Spectrum + numeric fields. Keeps its own HSV so hue survives greys."""
    colorChanged = pyqtSignal(QColor)

    def __init__(self, color=QColor("black"), compact=False, parent=None):
        super().__init__(parent)
        self._h = self._s = self._v = 0.0
        self._busy = False
        self.square = SVSquare()
        self.hue = HueBar(vertical=True)
        self.square.changed.connect(self._sv_changed)
        self.hue.changed.connect(self._hue_changed)

        self.hex = QLineEdit()
        self.hex.setValidator(QRegularExpressionValidator(QRegularExpression("#?[0-9A-Fa-f]{0,6}")))
        self.hex.setFixedWidth(74)
        self.hex.editingFinished.connect(self._hex_edited)
        self.spins = {}
        for key, hi in (("H", 360), ("S", 100), ("B", 100), ("R", 255), ("G", 255), ("Bl", 255)):
            s = QSpinBox()
            s.setRange(0, hi)
            s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            s.setFixedWidth(48)
            s.setAlignment(Qt.AlignmentFlag.AlignRight)
            s.valueChanged.connect(lambda _, k=key: self._spin_changed(k))
            self.spins[key] = s

        if compact:
            outer = QVBoxLayout(self)
            outer.setContentsMargins(10, 10, 10, 10)
            outer.setSpacing(8)
            top = QHBoxLayout()
            top.setSpacing(6)
            top.addWidget(self.square, 1)
            top.addWidget(self.hue)
            outer.addLayout(top, 1)
            row = QHBoxLayout()
            row.setSpacing(4)
            for key, label in (("R", "R"), ("G", "G"), ("Bl", "B")):
                lab = QLabel(label)
                lab.setObjectName("Dim")
                row.addWidget(lab)
                self.spins[key].setFixedWidth(40)
                row.addWidget(self.spins[key])
            row.addStretch(1)
            row.addWidget(self.hex)
            outer.addLayout(row)
            for k in ("H", "S", "B"):
                self.spins[k].hide()
        else:
            outer = QHBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(10)
            self.square.setFixedSize(256, 256)
            self.hue.setFixedHeight(256)
            outer.addWidget(self.square)
            outer.addWidget(self.hue)
            self.fields = QGridLayout()
            self.fields.setHorizontalSpacing(6)
            self.fields.setVerticalSpacing(5)
            rows = (("H", "H:", "°"), ("S", "S:", "%"), ("B", "B:", "%"), (None, "", ""),
                    ("R", "R:", ""), ("G", "G:", ""), ("Bl", "B:", ""))
            for i, (k, lab, unit) in enumerate(rows):
                if k is None:
                    self.fields.setRowMinimumHeight(i, 8)
                    continue
                self.fields.addWidget(QLabel(lab), i, 0)
                self.fields.addWidget(self.spins[k], i, 1)
                u = QLabel(unit)
                u.setObjectName("Dim")
                self.fields.addWidget(u, i, 2)
            self.fields.addWidget(QLabel("#"), 8, 0)
            self.fields.addWidget(self.hex, 8, 1, 1, 2)
            self.fields.setRowStretch(9, 1)
            self.fields_holder = QVBoxLayout()
            self.fields_holder.addLayout(self.fields)
            outer.addLayout(self.fields_holder)
        self.set_color(color)

    # ------------------------------------------------------------------
    def color(self) -> QColor:
        return QColor.fromHsvF(self._h, self._s, self._v)

    def set_color(self, c: QColor, emit=False):
        c = QColor(c)
        h, s, v, _ = c.getHsvF()
        if h < 0:  # achromatic: keep current hue
            h = self._h
        self._h, self._s, self._v = h, s, v
        self._sync(exclude=None)
        if emit:
            self.colorChanged.emit(self.color())

    def _sync(self, exclude):
        self._busy = True
        self.square.set_hsv(self._h, self._s, self._v)
        self.hue.set_hue(self._h)
        c = self.color()
        vals = {"H": round(self._h * 360) % 360, "S": round(self._s * 100), "B": round(self._v * 100),
                "R": c.red(), "G": c.green(), "Bl": c.blue()}
        for k, v in vals.items():
            if k != exclude:
                self.spins[k].setValue(v)
        if exclude != "hex":
            self.hex.setText(c.name()[1:].upper())
        self._busy = False

    def _emit(self):
        self.colorChanged.emit(self.color())

    def _sv_changed(self, s, v):
        self._s, self._v = s, v
        self._sync("sv")
        self._emit()

    def _hue_changed(self, h):
        self._h = h
        self._sync("hue")
        self._emit()

    def _spin_changed(self, key):
        if self._busy:
            return
        if key in ("H", "S", "B"):
            self._h = (self.spins["H"].value() % 360) / 360.0
            self._s = self.spins["S"].value() / 100.0
            self._v = self.spins["B"].value() / 100.0
        else:
            c = QColor(self.spins["R"].value(), self.spins["G"].value(), self.spins["Bl"].value())
            h, s, v, _ = c.getHsvF()
            if h >= 0:
                self._h = h
            self._s, self._v = s, v
        self._sync(key)
        self._emit()

    def _hex_edited(self):
        t = self.hex.text().strip().lstrip("#")
        if len(t) == 3:
            t = "".join(ch * 2 for ch in t)
        if len(t) == 6:
            self.set_color(QColor("#" + t), emit=True)
        else:
            self._sync(None)


class ColorPickerDialog(QDialog):
    def __init__(self, color, title="Color Picker (Foreground Color)", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.original = QColor(color)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        head = QLabel(title)
        head.setObjectName("Heading")
        lay.addWidget(head)
        body = QHBoxLayout()
        self.picker = ColorPicker(color, compact=False)
        body.addWidget(self.picker)
        side = QVBoxLayout()
        side.setSpacing(4)
        lab_new = QLabel("new")
        lab_new.setObjectName("Dim")
        lab_new.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(lab_new)
        self.preview = QLabel()
        self.preview.setFixedSize(70, 100)
        side.addWidget(self.preview)
        lab_cur = QLabel("current")
        lab_cur.setObjectName("Dim")
        lab_cur.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(lab_cur)
        side.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        side.addWidget(ok)
        side.addWidget(cancel)
        body.addLayout(side)
        lay.addLayout(body)
        self.picker.colorChanged.connect(self._preview)
        self._preview()

    def _preview(self, *_):
        pm = QPixmap(70, 100)
        p = QPainter(pm)
        p.fillRect(0, 0, 70, 50, self.picker.color())
        p.fillRect(0, 50, 70, 50, self.original)
        p.setPen(QColor("#111"))
        p.drawRect(0, 0, 69, 99)
        p.end()
        self.preview.setPixmap(pm)

    def color(self):
        return self.picker.color()


def pick_color(parent, color, title):
    dlg = ColorPickerDialog(color, title, parent)
    if dlg.exec():
        return dlg.color()
    return None


class FgBgWidget(QWidget):
    """The overlapping foreground/background chips at the bottom of the toolbox."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setFixedSize(42, 42)
        ctx.colorsChanged.connect(self.update)
        self.setToolTip("Foreground / background colour\nX: swap · D: default black & white")

    def _fg_rect(self):
        return QRect(3, 3, 21, 21)

    def _bg_rect(self):
        return QRect(15, 15, 21, 21)

    def paintEvent(self, ev):
        p = QPainter(self)
        for r, c in ((self._bg_rect(), self.ctx.bg), (self._fg_rect(), self.ctx.fg)):
            p.fillRect(r, c)
            p.setPen(QPen(QColor("#111"), 1))
            p.drawRect(r.adjusted(0, 0, -1, -1))
            p.setPen(QPen(QColor("#888"), 1))
            p.drawRect(r.adjusted(1, 1, -2, -2))
        p.drawPixmap(27, 0, icons.pixmap("swap", 13))
        p.drawPixmap(0, 28, icons.pixmap("default_colors", 13))

    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        if QRect(26, 0, 16, 14).contains(pos):
            self.ctx.swap_colors()
        elif QRect(0, 27, 14, 15).contains(pos):
            self.ctx.default_colors()
        elif self._fg_rect().contains(pos):
            c = pick_color(self.window(), self.ctx.fg, "Color Picker (Foreground Color)")
            if c is not None:
                self.ctx.set_fg(c)
        elif self._bg_rect().contains(pos):
            c = pick_color(self.window(), self.ctx.bg, "Color Picker (Background Color)")
            if c is not None:
                self.ctx.set_bg(c)


class ColorPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.target = "fg"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.chips = _PanelChips(self)
        lay.addWidget(self.chips, 0, Qt.AlignmentFlag.AlignTop)
        self.picker = ColorPicker(ctx.fg, compact=True)
        lay.addWidget(self.picker, 1)
        self.picker.colorChanged.connect(self._picked)
        ctx.colorsChanged.connect(self._ctx_changed)

    def _picked(self, c):
        (self.ctx.set_fg if self.target == "fg" else self.ctx.set_bg)(c)

    def _ctx_changed(self):
        c = self.ctx.fg if self.target == "fg" else self.ctx.bg
        if c != self.picker.color():
            self.picker.blockSignals(True)
            self.picker.set_color(c)
            self.picker.blockSignals(False)
        self.chips.update()

    def set_target(self, t):
        self.target = t
        self._ctx_changed()


class _PanelChips(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setFixedSize(52, 54)
        self.setToolTip("Click a chip to choose which colour the spectrum edits")

    def paintEvent(self, ev):
        p = QPainter(self)
        ctx = self.panel.ctx
        fg, bg = QRect(10, 12, 22, 22), QRect(22, 24, 22, 22)
        for r, c, t in ((bg, ctx.bg, "bg"), (fg, ctx.fg, "fg")):
            p.fillRect(r, c)
            sel = self.panel.target == t
            p.setPen(QPen(QColor(theme.ACCENT if sel else "#111"), 2 if sel else 1))
            p.drawRect(r.adjusted(0, 0, -1, -1))

    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        if QRect(10, 12, 22, 22).contains(pos):
            self.panel.set_target("fg")
        elif QRect(22, 24, 22, 22).contains(pos):
            self.panel.set_target("bg")


DEFAULT_SWATCHES = [
    "#ffffff", "#e6e6e6", "#cccccc", "#b3b3b3", "#999999", "#808080", "#666666", "#4d4d4d",
    "#333333", "#1a1a1a", "#000000",
    "#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff",
    "#ed1c24", "#f26522", "#f7941d", "#fff200", "#8dc63f", "#39b54a", "#00a651", "#00a99d",
    "#00aeef", "#0072bc", "#0054a6", "#2e3192", "#662d91", "#92278f", "#ec008c", "#ed145b",
    "#f69679", "#f9ad81", "#fdc68a", "#fff799", "#c4df9b", "#a3d39c", "#82ca9c", "#7accc8",
    "#6dcff6", "#7da7d9", "#8393ca", "#8781bd", "#a187be", "#bd8cbf", "#f49ac1", "#f5989d",
    "#9e0b0f", "#a0410d", "#a3620a", "#aba000", "#598527", "#1a7b30", "#007236", "#00746b",
    "#0076a3", "#004b80", "#003471", "#1b1464", "#440e62", "#630460", "#9e005d", "#9e0039",
    "#c69c6d", "#a67c52", "#8c6239", "#754c24", "#603913", "#3c2415",
]


class SwatchGrid(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.cell = 17
        self.gap = 3
        custom = ctx.settings.value("swatches/custom", [])
        if isinstance(custom, str):
            custom = [custom]
        self.custom = [c for c in (custom or []) if QColor(c).isValid()]
        self.setMouseTracking(True)
        self.setMinimumHeight(60)

    def colors(self):
        return DEFAULT_SWATCHES + self.custom

    def _cols(self):
        return max(1, (self.width() - 2 * 8 + self.gap) // (self.cell + self.gap))

    def heightForWidth(self, w):
        cols = max(1, (w - 16 + self.gap) // (self.cell + self.gap))
        rows = -(-len(self.colors()) // cols)
        return 16 + rows * (self.cell + self.gap)

    def hasHeightForWidth(self):
        return True

    def _rect(self, i):
        cols = self._cols()
        r, c = divmod(i, cols)
        return QRect(8 + c * (self.cell + self.gap), 8 + r * (self.cell + self.gap), self.cell, self.cell)

    def _index_at(self, pos):
        for i in range(len(self.colors())):
            if self._rect(i).contains(pos):
                return i
        return -1

    def paintEvent(self, ev):
        p = QPainter(self)
        for i, c in enumerate(self.colors()):
            r = self._rect(i)
            p.fillRect(r, QColor(c))
            p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawRect(r.adjusted(0, 0, -1, -1))

    def mouseMoveEvent(self, ev):
        i = self._index_at(ev.position().toPoint())
        self.setToolTip(self.colors()[i].upper() if i >= 0 else "")

    def mousePressEvent(self, ev):
        i = self._index_at(ev.position().toPoint())
        if i < 0:
            return
        col = QColor(self.colors()[i])
        if ev.button() == Qt.MouseButton.RightButton and i >= len(DEFAULT_SWATCHES):
            m = QMenu(self)
            act = m.addAction("Delete Swatch")
            if m.exec(ev.globalPosition().toPoint()) == act:
                del self.custom[i - len(DEFAULT_SWATCHES)]
                self._save()
            return
        if ev.modifiers() & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier):
            self.ctx.set_bg(col)
        else:
            self.ctx.set_fg(col)

    def add_current(self):
        self.custom.append(self.ctx.fg.name())
        self._save()

    def _save(self):
        self.ctx.settings.setValue("swatches/custom", self.custom)
        self.updateGeometry()
        self.update()


class SwatchesPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.grid = SwatchGrid(ctx)
        lay.addWidget(self.grid, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 4)
        tip = QLabel("Click: foreground · Alt+click: background")
        tip.setObjectName("Dim")
        bar.addWidget(tip)
        bar.addStretch(1)
        add = QToolButton()
        add.setIcon(icons.icon("plus"))
        add.setToolTip("Add the foreground colour as a swatch")
        add.clicked.connect(self.grid.add_current)
        bar.addWidget(add)
        lay.addLayout(bar)
