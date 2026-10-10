"""The object passed to an extension's register(api). Keep this stable: extensions depend on it.

    def register(api):
        api.add_filter("Filter/Blur", "Gaussian Blur…", my_blur_fn, params=[...])
        api.add_menu_action("Image/Adjustments", "Do Thing", callback, shortcut="Ctrl+Alt+T")
        api.add_tool(MyToolClass)                 # subclass of api.Tool
        api.add_panel("My Panel", widget)

    Layers (API 2):
        doc = api.current_document()
        doc.layers / doc.active                   # bottom → top list, active layer
        api.new_layer("Glow", image, QPoint(x, y))
        api.layer_image(layer)                    # canvas-sized copy of a layer's pixels
        api.set_layer_image(layer, image, "My Effect")    # undoable
        api.composite()                           # flattened image of the visible layers
        api.add_canvas_overlay(fn)                # fn(painter, canvas) draws on top of the canvas
        api.on("layers_changed", fn) / api.on("document_changed", fn) / api.on("tool_changed", fn)
"""
from PyQt6.QtGui import QAction, QKeySequence

from .. import __version__, imageops
from ..tools import Tool


API_VERSION = 2


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

    # ------------------------------------------------------------ layers (API 2)
    def layers(self):
        d = self.current_document()
        return list(d.layers) if d else []

    def active_layer(self):
        d = self.current_document()
        return d.active if d else None

    def new_layer(self, name=None, image=None, offset=None, label="New Layer"):
        from PyQt6.QtCore import QPoint
        d = self.current_document()
        if d is None:
            return None
        return d.add_layer(name, imageops.to_working(image) if image is not None else None,
                           offset or QPoint(0, 0), text=label)

    def layer_image(self, layer=None):
        d = self.current_document()
        return d.layer_pixels(layer) if d else None

    def set_layer_image(self, layer, image, label="Extension"):
        """Replace a layer's pixels with a canvas-sized image, as one undoable step."""
        d = self.current_document()
        if d is None:
            return False
        img = imageops.to_working(image)
        r = d.rect()
        if img.size() != r.size():
            raise ValueError("set_layer_image expects a canvas-sized image")
        d.apply_patch(label, r, img, layer=layer or d.active)
        return True

    def composite(self):
        d = self.current_document()
        return d.flattened() if d else None

    def add_canvas_overlay(self, fn):
        """fn(painter, canvas): draw extra UI on the canvas. canvas.img_to_view() maps document → screen."""
        self.ctx.canvas_overlays.append(fn)
        cv = self.current_canvas()
        if cv:
            cv.viewport().update()
        return fn

    def remove_canvas_overlay(self, fn):
        if fn in self.ctx.canvas_overlays:
            self.ctx.canvas_overlays.remove(fn)

    def refresh_canvas(self):
        cv = self.current_canvas()
        if cv:
            cv.viewport().update()

    def on(self, event, fn):
        """Subscribe to 'layers_changed', 'document_changed' (pixels) or 'tool_changed'."""
        self._w.ext_events.setdefault(event, []).append(fn)
        return fn
