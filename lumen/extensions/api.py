"""The object passed to an extension's register(api). Keep this stable: extensions depend on it.

    def register(api):
        api.add_filter("Filter/Blur", "Gaussian Blur…", my_blur_fn, params=[...])
        api.add_menu_action("Image/Adjustments", "Do Thing", callback, shortcut="Ctrl+Alt+T")
        api.add_tool(MyToolClass)                 # subclass of api.Tool
        api.add_panel("My Panel", widget)
"""
from PyQt6.QtGui import QAction, QKeySequence

from .. import __version__, imageops
from ..tools import Tool


API_VERSION = 1


class ExtensionAPI:
    API_VERSION = API_VERSION
    Tool = Tool                 # base class for extension tools
    imageops = imageops         # numpy <-> QImage helpers

    def __init__(self, window, ext):
        self._w = window
        self.ext = ext
        self.id = ext.id if ext else "test"
        self.app_version = __version__
        self.ctx = window.ctx

    # ------------------------------------------------------------ documents
    def current_document(self):
        return self._w.current_doc()

    def current_canvas(self):
        return self._w.current_canvas()

    def status(self, message, ms=4000):
        self._w.statusBar().showMessage(message, ms)

    def setting(self, key, default=None):
        return self.ctx.settings.value(f"ext/{self.id}/{key}", default)

    def set_setting(self, key, value):
        self.ctx.settings.setValue(f"ext/{self.id}/{key}", value)

    # ------------------------------------------------------------ menus
    def menu(self, path):
        """'Filter/Blur' -> the Blur submenu of the Filter menu (created if needed)."""
        return self._w.menu_path(path)

    def add_menu_action(self, path, text, callback, shortcut=None, needs_document=True):
        a = QAction(text, self._w)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda *_: callback())
        a.setProperty("needs_document", needs_document)
        a.setProperty("extension", self.id)
        self.menu(path).addAction(a)
        self._w.addAction(a)
        self._w.register_extension_action(a)
        return a

    def add_filter(self, path, text, fn, params=None, shortcut=None):
        """fn(QImage, **params) -> QImage. With params, a dialog with live preview is shown.
        params: list of dicts {key, label, min, max, default, suffix?, decimals?}"""
        from .ui import run_filter

        def go():
            run_filter(self._w, text.rstrip("…. "), fn, params or [])
        return self.add_menu_action(path, text, go, shortcut)

    # ------------------------------------------------------------ tools / panels
    def add_tool(self, tool_cls, group=None):
        """Register a Tool subclass. group: an existing toolbox group id (e.g. 'brush') or None for a new slot."""
        return self._w.register_tool(tool_cls, group)

    def add_panel(self, title, widget):
        return self._w.register_panel(title, widget)
