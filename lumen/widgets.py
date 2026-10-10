"""Small reusable widgets for the options bar and panels."""
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QSize
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import (QLabel, QSpinBox, QWidget, QHBoxLayout, QFrame, QToolButton,
                             QSizePolicy)


class ScrubLabel(QLabel):
    """Label you can drag left/right to change the linked spin box (like Photoshop)."""

    def __init__(self, text, spin: QSpinBox, parent=None):
        super().__init__(text, parent)
        self.spin = spin
        self._x = None
        self._start = 0
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._x = ev.position().x()
            self._start = self.spin.value()

    def mouseMoveEvent(self, ev):
        if self._x is not None:
            dx = ev.position().x() - self._x
            step = 1 if not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 10
            self.spin.setValue(int(self._start + dx / 2 * step))

    def mouseReleaseEvent(self, ev):
        self._x = None


def labeled_spin(label, lo, hi, value, suffix="", width=62):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    spin = QSpinBox()
    spin.setRange(lo, hi)
    spin.setValue(value)
    spin.setSuffix(suffix)
    spin.setFixedWidth(width)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight)
    lab = ScrubLabel(label, spin)
    lab.setObjectName("Dim")
    lay.addWidget(lab)
    lay.addWidget(spin)
    return w, spin


def separator():
    f = QFrame()
    f.setObjectName("OptSep")
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedHeight(22)
    return f


class Swatch(QWidget):
    """Flat colour chip."""
    clicked = pyqtSignal()

    def __init__(self, color=QColor("black"), size=16, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, c):
        self.color = QColor(c)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), self.color)
        p.setPen(QPen(QColor("#777"), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, ev):
        self.clicked.emit()


def icon_button(icon, tip, checkable=False, size=26):
    b = QToolButton()
    b.setIcon(icon)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setIconSize(QSize(18, 18))
    b.setFixedSize(size, size)
    return b
