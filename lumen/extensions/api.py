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

    Workspaces (API 3):
        api.add_workspace("My Tool", widget)      # adds a top tab next to "Lumen"
        api.add_image_as_layer(qimage, "Name")    # hand pictures back to Lumen
        api.ask_params("Title", params, preview)  # settings dialog with live preview
"""
from PyQt6.QtGui import QAction, QKeySequence

from .. import __version__, imageops
from ..tools import Tool


API_VERSION = 3


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

    def add_filter(self, path, text, fn, params=None, shortcut=None, dialog_hook=None):
        """fn(QImage, **params) -> QImage. With params, a dialog with live preview is shown.
        params: list of dicts {key, label, default, type?} — see ui.ParamsDialog for the types.
        dialog_hook(dialog) can add custom widgets (dialog.extra layout, dialog.extra_values)."""
        from .ui import run_filter

        def go():
            run_filter(self._w, text.rstrip("…. "), fn, params or [], dialog_hook)
        return self.add_menu_action(path, text, go, shortcut)

    def ask_params(self, title, params, preview=None, ok_text="OK"):
        """Show a settings dialog. preview(values or None) is called live. Returns values or None."""
        from .ui import ParamsDialog
        dlg = ParamsDialog(self._w, title, params, on_change=preview, ok_text=ok_text)
        return dlg.values() if dlg.exec() else None

    # ------------------------------------------------------------ workspaces (API 3)
    def add_workspace(self, title, widget, icon=None):
        """Add a top-level tab next to "Lumen" (e.g. a browser or a dedicated tool)."""
        return self._w.register_workspace(title, widget, icon)

    def show_workspace(self, widget):
        self._w.show_workspace(widget)

    def show_lumen(self):
        self._w.show_workspace(0)

    def add_image_as_layer(self, image, name=None, show=False):
        """Place an image in the current document as a new layer (opens a new document if none)."""
        return self._w.add_image_as_layer(image, name, show)

    def open_image(self, image, name=None):
        """Open an image as a new document and switch to Lumen."""
        return self._w.open_image_document(image, name)

    def data_dir(self, sub=""):
        """A folder this extension can keep files in (models, caches…)."""
        import os
        from .. import config
        d = os.path.join(config.data_dir(), "ext-data", self.id, sub)
        os.makedirs(d, exist_ok=True)
        return d

    def window(self):
        return self._w

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
