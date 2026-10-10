"""Dialogs: New Document, Image Size, Canvas Size, Text entry, Export quality."""
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QGuiApplication
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSpinBox,
                             QComboBox, QPushButton, QLineEdit, QToolButton, QCheckBox, QPlainTextEdit,
                             QSlider, QWidget, QListWidget, QListWidgetItem, QButtonGroup, QFrame)

from . import icons, theme

PRESETS = [
    ("Custom", None),
    ("Default Lumen Size", (1920, 1080)),
    ("HD 1280 × 720", (1280, 720)),
    ("Full HD 1920 × 1080", (1920, 1080)),
    ("4K UHD 3840 × 2160", (3840, 2160)),
    ("Instagram Post 1080 × 1080", (1080, 1080)),
    ("Instagram Story 1080 × 1920", (1080, 1920)),
    ("YouTube Thumbnail 1280 × 720", (1280, 720)),
    ("Twitter / X Header 1500 × 500", (1500, 500)),
    ("Discord Banner 960 × 540", (960, 540)),
    ("Discord Emoji 128 × 128", (128, 128)),
    ("A4 @ 300 ppi 2480 × 3508", (2480, 3508)),
    ("Icon 512 × 512", (512, 512)),
]


def _spin(lo, hi, val, suffix="", width=90):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setSuffix(suffix)
    s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    s.setFixedWidth(width)
    return s


def _buttons(dlg, ok_text="OK"):
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dlg.reject)
    ok = QPushButton(ok_text)
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    return row, ok


def _heading(text):
    h = QLabel(text)
    h.setObjectName("Heading")
    return h


class NewDocumentDialog(QDialog):
    def __init__(self, ctx, parent=None, clipboard_size=None):
        super().__init__(parent)
        self.setWindowTitle("New Document")
        self.ctx = ctx
        self.setMinimumWidth(640)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # presets list (left)
        left = QWidget()
        left.setStyleSheet(f"background: {theme.BG_DARK};")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 16, 8, 16)
        lab = QLabel("PRESETS")
        lab.setObjectName("Dim")
        ll.addWidget(lab)
        self.presets = QListWidget()
        self.presets.setStyleSheet(f"background: {theme.BG_DARK};")
        self.presets.setFixedWidth(230)
        items = list(PRESETS[1:])
        if clipboard_size:
            items.insert(0, (f"Clipboard {clipboard_size[0]} × {clipboard_size[1]}", clipboard_size))
        self._preset_sizes = []
        for name, size in items:
            self.presets.addItem(QListWidgetItem(name))
            self._preset_sizes.append(size)
        self.presets.currentRowChanged.connect(self._preset_chosen)
        ll.addWidget(self.presets, 1)
        outer.addWidget(left)

        # details (right)
        right = QVBoxLayout()
        right.setContentsMargins(20, 16, 20, 16)
        right.setSpacing(10)
        right.addWidget(_heading("Preset Details"))
        self.name = QLineEdit(f"Untitled-{_next_untitled()}")
        right.addWidget(self.name)
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(10)
        w0, h0 = clipboard_size or (int(ctx.settings.value("new/w", 1920)), int(ctx.settings.value("new/h", 1080)))
        self.w = _spin(1, 30000, w0, " px")
        self.h = _spin(1, 30000, h0, " px")
        self.dpi = _spin(1, 2400, int(ctx.settings.value("new/dpi", 72)), " ppi")
        self.orient = QToolButton()
        self.orient.setText("⇄")
        self.orient.setToolTip("Swap width and height")
        self.orient.clicked.connect(self._swap)
        self.bg = QComboBox()
        self.bg.addItems(["White", "Black", "Background Color", "Transparent"])
        self.bg.setCurrentIndex(int(ctx.settings.value("new/bg", 0)))
        for r, (label, w) in enumerate((("Width", self.w), ("Height", self.h), ("Resolution", self.dpi),
                                        ("Background Contents", self.bg))):
            l = QLabel(label)
            l.setObjectName("Dim")
            grid.addWidget(l, r, 0)
            grid.addWidget(w, r, 1)
        grid.addWidget(self.orient, 0, 2, 2, 1)
        grid.setColumnStretch(3, 1)
        right.addLayout(grid)
        right.addStretch(1)
        row, ok = _buttons(self, "Create")
        right.addLayout(row)
        outer.addLayout(right, 1)
        self.w.valueChanged.connect(self._custom)
        self.h.valueChanged.connect(self._custom)

    def _preset_chosen(self, row):
        size = self._preset_sizes[row] if 0 <= row < len(self._preset_sizes) else None
        if size:
            self.w.blockSignals(True)
            self.h.blockSignals(True)
            self.w.setValue(size[0])
            self.h.setValue(size[1])
            self.w.blockSignals(False)
            self.h.blockSignals(False)

    def _custom(self):
        self.presets.blockSignals(True)
        self.presets.clearSelection()
        self.presets.setCurrentRow(-1)
        self.presets.blockSignals(False)

    def _swap(self):
        w, h = self.w.value(), self.h.value()
        self.w.setValue(h)
        self.h.setValue(w)

    def values(self):
        s = self.ctx.settings
        s.setValue("new/w", self.w.value())
        s.setValue("new/h", self.h.value())
        s.setValue("new/dpi", self.dpi.value())
        s.setValue("new/bg", self.bg.currentIndex())
        fill = [QColor("white"), QColor("black"), self.ctx.bg, None][self.bg.currentIndex()]
        return self.name.text().strip() or "Untitled", self.w.value(), self.h.value(), self.dpi.value(), fill


_untitled = [0]


def _next_untitled():
    from .document import Document
    return Document._counter + 1


class LinkButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(True)
        self.setIcon(icons.icon("link"))
        self.setToolTip("Constrain proportions")
        self.setFixedSize(26, 54)


class ImageSizeDialog(QDialog):
    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Size")
        self.ow, self.oh = w, h
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        lay.addWidget(_heading("Image Size"))
        self.info = QLabel()
        self.info.setObjectName("Dim")
        lay.addWidget(self.info)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self.units = QComboBox()
        self.units.addItems(["Pixels", "Percent"])
        self.w = _spin(1, 30000, w)
        self.h = _spin(1, 30000, h)
        self.link = LinkButton()
        grid.addWidget(QLabel("Width:"), 0, 0)
        grid.addWidget(self.w, 0, 1)
        grid.addWidget(QLabel("Height:"), 1, 0)
        grid.addWidget(self.h, 1, 1)
        grid.addWidget(self.link, 0, 2, 2, 1)
        grid.addWidget(self.units, 0, 3)
        grid.setColumnStretch(4, 1)
        lay.addLayout(grid)
        r = QHBoxLayout()
        r.addWidget(QLabel("Resample:"))
        self.method = QComboBox()
        self.method.addItems(["Automatic (smooth)", "Nearest Neighbor (hard edges)"])
        r.addWidget(self.method, 1)
        lay.addLayout(r)
        row, ok = _buttons(self)
        lay.addLayout(row)
        self._busy = False
        self.w.valueChanged.connect(lambda: self._linked("w"))
        self.h.valueChanged.connect(lambda: self._linked("h"))
        self.units.currentIndexChanged.connect(self._units)
        self._update_info()

    def _px(self):
        if self.units.currentIndex() == 1:
            return max(1, round(self.ow * self.w.value() / 100)), max(1, round(self.oh * self.h.value() / 100))
        return self.w.value(), self.h.value()

    def _linked(self, which):
        if self._busy:
            return
        self._busy = True
        if self.link.isChecked():
            if self.units.currentIndex() == 1:
                (self.h if which == "w" else self.w).setValue((self.w if which == "w" else self.h).value())
            elif which == "w":
                self.h.setValue(max(1, round(self.w.value() * self.oh / self.ow)))
            else:
                self.w.setValue(max(1, round(self.h.value() * self.ow / self.oh)))
        self._busy = False
        self._update_info()

    def _units(self, i):
        self._busy = True
        if i == 1:
            self.w.setSuffix(" %")
            self.h.setSuffix(" %")
            self.w.setValue(100)
            self.h.setValue(100)
        else:
            self.w.setSuffix("")
            self.h.setSuffix("")
            self.w.setValue(self.ow)
            self.h.setValue(self.oh)
        self._busy = False
        self._update_info()

    def _update_info(self):
        w, h = self._px()
        mb = w * h * 4 / (1024 * 1024)
        self.info.setText(f"New size: {w} × {h} px ({mb:.1f} MB)   ·   was {self.ow} × {self.oh} px")

    def values(self):
        w, h = self._px()
        return w, h, self.method.currentIndex() == 0


class AnchorGrid(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(84, 84)
        self.anchor = (1, 1)

    def paintEvent(self, ev):
        p = QPainter(self)
        for r in range(3):
            for c in range(3):
                rect = QRect(c * 28 + 2, r * 28 + 2, 24, 24)
                sel = (c, r) == self.anchor
                p.fillRect(rect, QColor(theme.ACCENT if sel else "#454545"))
                p.setPen(QColor("#222"))
                p.drawRect(rect.adjusted(0, 0, -1, -1))

    def mousePressEvent(self, ev):
        c, r = int(ev.position().x() // 28), int(ev.position().y() // 28)
        self.anchor = (min(2, max(0, c)), min(2, max(0, r)))
        self.update()


class CanvasSizeDialog(QDialog):
    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Canvas Size")
        self.ow, self.oh = w, h
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        lay.addWidget(_heading("Canvas Size"))
        cur = QLabel(f"Current size: {w} × {h} px")
        cur.setObjectName("Dim")
        lay.addWidget(cur)
        grid = QGridLayout()
        self.w = _spin(-30000, 30000, w, " px")
        self.h = _spin(-30000, 30000, h, " px")
        self.rel = QCheckBox("Relative")
        self.rel.toggled.connect(self._rel)
        grid.addWidget(QLabel("Width:"), 0, 0)
        grid.addWidget(self.w, 0, 1)
        grid.addWidget(QLabel("Height:"), 1, 0)
        grid.addWidget(self.h, 1, 1)
        grid.addWidget(self.rel, 2, 1)
        grid.addWidget(QLabel("Anchor:"), 3, 0, Qt.AlignmentFlag.AlignTop)
        self.anchor = AnchorGrid()
        grid.addWidget(self.anchor, 3, 1)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        r = QHBoxLayout()
        r.addWidget(QLabel("Canvas extension colour:"))
        self.ext = QComboBox()
        self.ext.addItems(["Background", "Foreground", "White", "Black", "Transparent"])
        r.addWidget(self.ext, 1)
        lay.addLayout(r)
        row, ok = _buttons(self)
        lay.addLayout(row)

    def _rel(self, on):
        if on:
            self.w.setValue(0)
            self.h.setValue(0)
        else:
            self.w.setValue(self.ow)
            self.h.setValue(self.oh)

    def values(self):
        w, h = self.w.value(), self.h.value()
        if self.rel.isChecked():
            w, h = self.ow + w, self.oh + h
        return max(1, w), max(1, h), self.anchor.anchor, self.ext.currentIndex()


class TextDialog(QDialog):
    textChanged = pyqtSignal(str)

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Type")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(_heading("Enter text"))
        tip = QLabel("Preview updates on the canvas as you type. Ctrl+Enter to commit.")
        tip.setObjectName("Dim")
        lay.addWidget(tip)
        self.edit = QPlainTextEdit()
        self.edit.setMinimumSize(360, 110)
        f = tool.font()
        f.setPixelSize(16)
        self.edit.setFont(f)
        self.edit.textChanged.connect(lambda: self.textChanged.emit(self.edit.toPlainText()))
        lay.addWidget(self.edit)
        row, ok = _buttons(self, "Commit")
        lay.addLayout(row)
        ok.setDefault(False)
        ok.setAutoDefault(False)
        ok.setObjectName("Primary")

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.accept()
            return
        super().keyPressEvent(ev)

    def text(self):
        return self.edit.toPlainText()


class QualityDialog(QDialog):
    def __init__(self, fmt, parent=None, value=90):
        super().__init__(parent)
        self.setWindowTitle(f"{fmt} Options")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(_heading(f"{fmt} Options"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Quality:"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(value)
        self.spin = _spin(1, 100, value, "", 54)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        lay.addLayout(row)
        b, ok = _buttons(self)
        lay.addLayout(b)
        self.setMinimumWidth(360)

    def value(self):
        return self.spin.value()
