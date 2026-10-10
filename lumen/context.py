"""Application-wide state shared by tools and panels (colours, settings)."""
import os
from PyQt6.QtCore import QObject, pyqtSignal, QSettings
from PyQt6.QtGui import QColor


class AppContext(QObject):
    colorsChanged = pyqtSignal()
    toolChanged = pyqtSignal(object)
    status = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._fg = QColor(0, 0, 0)
        self._bg = QColor(255, 255, 255)
        override = os.environ.get("LUMEN_SETTINGS")  # used by the test-suite so it never touches real prefs
        self.settings = QSettings(override, QSettings.Format.IniFormat) if override else QSettings("Lumen", "Lumen")
        self.window = None  # MainWindow, set later

    @property
    def fg(self):
        return QColor(self._fg)

    @property
    def bg(self):
        return QColor(self._bg)

    def set_fg(self, c):
        c = QColor(c)
        c.setAlpha(255)
        if c != self._fg:
            self._fg = c
            self.colorsChanged.emit()

    def set_bg(self, c):
        c = QColor(c)
        c.setAlpha(255)
        if c != self._bg:
            self._bg = c
            self.colorsChanged.emit()

    def swap_colors(self):
        self._fg, self._bg = self._bg, self._fg
        self.colorsChanged.emit()

    def default_colors(self):
        self._fg, self._bg = QColor(0, 0, 0), QColor(255, 255, 255)
        self.colorsChanged.emit()

    def current_canvas(self):
        return self.window.current_canvas() if self.window else None

    def current_doc(self):
        c = self.current_canvas()
        return c.doc if c else None
