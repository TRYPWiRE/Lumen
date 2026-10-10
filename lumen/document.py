"""Document model: layers, selection, floating pixels and undo history."""
import os
from PyQt6.QtCore import QObject, pyqtSignal, QRect, QRectF, QPoint, QSize, Qt
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QColor, QUndoStack, QUndoCommand

from . import imageops
from .imageops import PREMUL
from .layers import Layer, TextData, apply_alpha_lock, draw_layer, flatten


class LayerBlocked(Exception):
    """Raised when the active layer can't take the requested edit (locked, type layer…)."""


# =========================================================================== commands
class PixelsCommand(QUndoCommand):
    """Replace pixels of one layer inside a document rect."""

    def __init__(self, doc, text, layer, rect, before, after, sel_before=None, sel_after=None):
        super().__init__(text)
        self.doc, self.layer, self.rect = doc, layer, QRect(rect)
        self.before, self.after = before, after
        self.sel_before, self.sel_after = sel_before, sel_after

    def _put(self, img, sel):
        self.layer.put_region(self.rect, img)
        if sel is not None:
            self.doc._set_selection_raw(sel)
        self.doc._layer_pixels_changed(self.layer, self.rect)

    def redo(self):
        self._put(self.after, self.sel_after)

    def undo(self):
        self.doc._abort_transient()
        self._put(self.before, self.sel_before)


class LayerStateCommand(QUndoCommand):
    """Swap a layer's whole pixel buffer / offset / text (transforms, rasterize, text edits)."""

    def __init__(self, doc, text, layer, before, after):
        super().__init__(text)
        self.doc, self.layer, self.before, self.after = doc, layer, before, after

    @staticmethod
    def capture(layer):
        return (layer.image.copy(), layer.offset.__class__(layer.offset),
                layer.text.copy() if layer.text else None)

    def _apply(self, state):
        old = self.layer.rect()
        img, off, txt = state
        self.layer.image, self.layer.offset = img.copy(), off.__class__(off)
        self.layer.text = txt.copy() if txt else None
        self.layer.touch()
        self.doc._layer_pixels_changed(self.layer, old.united(self.layer.rect()))
        self.doc.layersChanged.emit()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self.doc._abort_transient()
        self._apply(self.before)


class MoveLayerCommand(QUndoCommand):
    def __init__(self, doc, layer, dx, dy, text="Move"):
        super().__init__(text)
        self.doc, self.layer, self.dx, self.dy = doc, layer, dx, dy

    def _move(self, dx, dy):
        old = self.layer.rect()
        self.layer.translate(dx, dy)
        self.doc._layer_pixels_changed(self.layer, old.united(self.layer.rect()))

    def redo(self):
        self._move(self.dx, self.dy)

    def undo(self):
        self.doc._abort_transient()
        self._move(-self.dx, -self.dy)


class PropsCommand(QUndoCommand):
    """Change layer properties (name, opacity, blend, visibility, locks…). Merges slider drags."""
    MERGE_ID = 4711

    def __init__(self, doc, layer, text, before, after, merge_key=None):
        super().__init__(text)
        self.doc, self.layer, self.before, self.after = doc, layer, before, after
        self.merge_key = merge_key

    def id(self):
        return self.MERGE_ID if self.merge_key else -1

    def mergeWith(self, other):
        if other.merge_key and other.merge_key == self.merge_key and other.layer is self.layer:
            self.after = other.after
            return True
        return False

    def _apply(self, values):
        for k, v in values.items():
            setattr(self.layer, k, v)
        self.layer.touch()
        self.doc._layer_pixels_changed(self.layer, self.layer.rect())
        self.doc.layersChanged.emit()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self.doc._abort_transient()
        self._apply(self.before)


class StackCommand(QUndoCommand):
    """Replace the layer list (add, delete, duplicate, reorder, merge, flatten)."""

    def __init__(self, doc, text, before, after, active_before, active_after):
        super().__init__(text)
        self.doc = doc
        self.before, self.after = list(before), list(after)
        self.ab, self.aa = active_before, active_after

    def _apply(self, layers, active):
        self.doc.layers = list(layers)
        self.doc._active = active if active in layers else (layers[-1] if layers else None)
        self.doc._full_change()
        self.doc.layersChanged.emit()
        self.doc.activeLayerChanged.emit()

    def redo(self):
        self._apply(self.after, self.aa)

    def undo(self):
        self.doc._abort_transient()
        self._apply(self.before, self.ab)


class DocStateCommand(QUndoCommand):
    """Whole-document change (crop, image/canvas size, rotate)."""

    def __init__(self, doc, text, before, after):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after

    def redo(self):
        self.doc._restore_state(self.after)

    def undo(self):
        self.doc._abort_transient()
        self.doc._restore_state(self.before)


class SelectionCommand(QUndoCommand):
    def __init__(self, doc, text, before, after):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after

    def redo(self):
        self.doc._set_selection_raw(self.after)

    def undo(self):
        self.doc._abort_transient()
        self.doc._set_selection_raw(self.before)


# =========================================================================== floating pixels
class Floating:
    """Selected pixels lifted off a layer by the Move tool (not yet committed)."""

    def __init__(self, doc, layer, label):
        self.doc, self.layer, self.label = doc, layer, label
        self.origin = (layer.image.copy(), QPoint(layer.offset))
        self.sel_before = QPainterPath(doc.selection)
        self.source_rect = doc.selection_bounds()
        self.image = imageops.masked_copy(layer.region(doc.rect()), doc.selection)
        self.pos = self.source_rect.topLeft()
        # cut the hole
        hole = layer.region(self.source_rect)
        p = QPainter(hole)
        p.translate(-self.source_rect.topLeft())
        p.setClipPath(doc.selection)
        if layer.background:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.source_rect, doc.bg_color)
        else:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(self.source_rect, Qt.GlobalColor.transparent)
        p.end()
        layer.put_region(self.source_rect, hole)
        self.base = layer.image          # layer without the lifted pixels
        layer.preview = None
        self._refresh(QRect())

    def rect(self):
        return QRect(self.pos, self.image.size())

    def _refresh(self, old_rect):
        L = self.layer
        L.ensure_covers(self.rect().intersected(self.doc.rect()))
        self.base = L.image
        pv = L.image.copy()
        p = QPainter(pv)
        p.drawImage(self.pos - L.offset, self.image)
        p.end()
        L.preview = pv
        self.doc.invalidate(old_rect.united(self.rect()))

    def move(self, dx, dy):
        old = self.rect()
        self.pos += QPoint(dx, dy)
        self._refresh(old)


# =========================================================================== document
class Document(QObject):
    changed = pyqtSignal(QRect)        # composite changed (empty rect == everything)
    sizeChanged = pyqtSignal()
    selectionChanged = pyqtSignal()
    titleChanged = pyqtSignal()
    layersChanged = pyqtSignal()        # list / properties / thumbnails
    activeLayerChanged = pyqtSignal()
    blocked = pyqtSignal(str)           # an edit was refused (message for the status bar)

    _counter = 0

    def __init__(self, image: QImage = None, path=None, name=None, transparent=None, dpi=72, size=None, layers=None):
        super().__init__()
        if layers is not None:
            self._size = QSize(size)
            self.layers = list(layers)
        else:
            img = imageops.to_working(image).copy()
            self._size = img.size()
            transparent = img.hasAlphaChannel() if transparent is None else transparent
            self.layers = [Layer("Layer 0" if transparent else "Background", img, background=not transparent)]
        self._active = self.layers[-1]
        self.path = path
        if name is None:
            if path:
                name = os.path.basename(path)
            else:
                Document._counter += 1
                name = f"Untitled-{Document._counter}"
        self.name = name
        self.dpi = dpi
        self.selection = QPainterPath()
        self.floating = None
        self.editing_text = None          # set by the Type tool while typing
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self._clean_changed)
        self.bg_color = QColor("white")   # set by the app: colour revealed when erasing the Background
        self.confirm = lambda kind, layer: True   # UI hook: ask before rasterizing a type layer, etc.
        self._comp = None
        self._dirty = QRect()
        self._layer_counter = 1

    def _clean_changed(self, _clean):
        self.titleChanged.emit()

    # ------------------------------------------------------------ basics
    @property
    def width(self):
        return self._size.width()

    @property
    def height(self):
        return self._size.height()

    def size(self):
        return QSize(self._size)

    def rect(self):
        return QRect(QPoint(0, 0), self._size)

    def modified(self):
        return not self.undo.isClean()

    @property
    def active(self) -> Layer:
        return self._active

    def set_active(self, layer):
        if layer is not self._active and layer in self.layers:
            self.commit_floating()
            self._active = layer
            self.activeLayerChanged.emit()
            self.layersChanged.emit()

    def background_layer(self):
        return next((L for L in self.layers if L.background), None)

    @property
    def transparent(self):
        """True when there's no Background layer (kept for older code)."""
        return self.background_layer() is None

    def next_layer_name(self, base="Layer"):
        names = {L.name for L in self.layers}
        n = 1
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    # ------------------------------------------------------------ compositing
    def invalidate(self, rect=QRect()):
        if rect.isEmpty():
            self._dirty = self.rect()
        else:
            self._dirty = self._dirty.united(rect.intersected(self.rect()))
        self.changed.emit(rect)

    def _full_change(self):
        self.invalidate(QRect())

    def composite(self) -> QImage:
        if self._comp is None or self._comp.size() != self._size:
            self._comp = QImage(self._size, PREMUL)
            self._dirty = self.rect()
        if not self._dirty.isEmpty():
            r = self._dirty
            self._dirty = QRect()
            p = QPainter(self._comp)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(r, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            for L in self.layers:
                if L.visible:
                    draw_layer(p, self._comp, L, r)
            p.end()
        return self._comp

    @property
    def image(self) -> QImage:
        """The flattened image (read-only view)."""
        return self.composite()

    def display_image(self):
        return self.composite()

    def flattened(self) -> QImage:
        return self.composite().copy()

    def _layer_pixels_changed(self, layer, rect):
        layer.touch()
        self.invalidate(rect)
        self.layersChanged.emit()

    # ------------------------------------------------------------ selection helpers
    def has_selection(self):
        return not self.selection.isEmpty()

    def selection_bounds(self) -> QRect:
        if self.selection.isEmpty():
            return QRect()
        return self.selection.boundingRect().toAlignedRect().intersected(self.rect())

    def clip(self, p: QPainter):
        if not self.selection.isEmpty():
            p.setClipPath(self.selection)

    # ------------------------------------------------------------ edit targets
    def paint_target(self, action="edit"):
        """Active layer ready for pixel edits, rasterizing a type layer if the user agrees."""
        L = self._active
        if L is None:
            raise LayerBlocked("There is no layer to edit.")
        if not L.visible:
            raise LayerBlocked(f"Could not {action} because the target layer is hidden.")
        if L.pixels_locked():
            raise LayerBlocked(f"Could not {action} because the layer is locked.")
        if L.is_text:
            if not self.confirm("rasterize", L):
                raise LayerBlocked(f"Could not {action}: the type layer must be rasterized first.")
            self.rasterize_layer(L)
        return L

    def try_target(self, action="edit"):
        try:
            return self.paint_target(action)
        except LayerBlocked as e:
            self.blocked.emit(str(e))
            return None

    # ------------------------------------------------------------ pixel edits on the active layer
    def apply_patch(self, text, rect: QRect, after: QImage, layer=None):
        """Commit `after` (already rendered, document rect) into the layer as one history step."""
        layer = layer or self._active
        rect = QRect(rect)
        if rect.isEmpty():
            return
        before = layer.region(rect)
        if after.size() != rect.size():
            after = after.copy(QRect(QPoint(0, 0), rect.size()))
        if layer.alpha_locked() and not layer.background:
            after = apply_alpha_lock(before, after)
        self.undo.push(PixelsCommand(self, text, layer, rect, before, after))

    def apply_region(self, text, rect: QRect, paint_fn, clip=True, layer=None, action=None):
        """Run paint_fn(painter, in document coords) on the active layer inside rect, as one step."""
        self.commit_floating()
        if layer is None:
            layer = self.try_target(action or text.lower())
            if layer is None:
                return False
        rect = QRect(rect).intersected(self.rect())
        if rect.isEmpty():
            return False
        before = layer.region(rect)
        work = before.copy()
        p = QPainter(work)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-rect.x(), -rect.y())
        if clip:
            self.clip(p)
        paint_fn(p)
        p.end()
        if layer.alpha_locked() and not layer.background:
            work = apply_alpha_lock(before, work)
        elif layer.background:   # the Background never has transparency
            flat = QImage(work.size(), PREMUL)
            flat.fill(self.bg_color)
            fp = QPainter(flat)
            fp.drawImage(0, 0, work)
            fp.end()
            work = flat
        self.undo.push(PixelsCommand(self, text, layer, rect, before, work))
        return True

    def clear_selection_pixels(self, text="Clear"):
        if not self.has_selection():
            return
        rect = self.selection_bounds()
        L = self.try_target("clear")
        if L is None:
            return

        def paint(p):
            if L.background:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                p.fillRect(rect, self.bg_color)
            else:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                p.fillRect(rect, Qt.GlobalColor.transparent)
        self.apply_region(text, rect, paint, layer=L)

    def fill(self, color: QColor, text="Fill"):
        rect = self.selection_bounds() if self.has_selection() else self.rect()
        self.apply_region(text, rect, lambda p: p.fillRect(rect, color))

    def filter_region(self, text, fn):
        """Apply fn(QImage)->QImage to the active layer inside the selection (or whole canvas)."""
        self.commit_floating()
        L = self.try_target("apply " + text)
        if L is None:
            return False
        rect = self.selection_bounds() if self.has_selection() else self.rect()
        if rect.isEmpty():
            return False
        processed = imageops.to_working(fn(L.region(rect)))

        def paint(p):
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(rect.topLeft(), processed)
        return self.apply_region(text, rect, paint, clip=True, layer=L)

    # ------------------------------------------------------------ live previews (filter dialogs)
    def preview_region(self, rect: QRect, img: QImage, layer=None):
        """Show `img` in place of the layer's pixels inside rect (clipped to the selection), without
        changing anything. clear_preview() removes it."""
        L = layer or self._active
        L.ensure_covers(rect)
        pv = L.image.copy()
        p = QPainter(pv)
        p.translate(-L.offset)
        self.clip(p)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(rect.topLeft(), img)
        p.end()
        L.preview = pv
        self.invalidate(rect)

    def clear_preview(self):
        for L in self.layers:
            if L.preview is not None and (self.floating is None or self.floating.layer is not L):
                L.preview = None
        self.invalidate(QRect())

    def set_preview(self, img, rect=QRect()):
        """Compatibility: canvas-sized preview of the active layer (None clears)."""
        if img is None:
            self.clear_preview()
        else:
            self.preview_region(self.rect(), img)

    def layer_pixels(self, layer=None) -> QImage:
        """Canvas-sized copy of a layer's pixels."""
        return (layer or self._active).region(self.rect())

    # ------------------------------------------------------------ layer stack
    def _push_stack(self, text, after, active_after):
        self.commit_floating()
        self.undo.push(StackCommand(self, text, self.layers, after, self._active, active_after))

    def _insert_index(self):
        return self.layers.index(self._active) + 1 if self._active in self.layers else len(self.layers)

    def add_layer(self, name=None, image=None, offset=QPoint(0, 0), text="New Layer", index=None, layer=None):
        L = layer or Layer(name or self.next_layer_name(), image, offset)
        if image is None and layer is None:
            L.image = QImage(1, 1, PREMUL)
            L.image.fill(Qt.GlobalColor.transparent)
            L.offset = QPoint(0, 0)
        idx = self._insert_index() if index is None else index
        after = self.layers[:idx] + [L] + self.layers[idx:]
        self._push_stack(text, after, L)
        return L

    def delete_layer(self, layer=None):
        layer = layer or self._active
        if layer not in self.layers or len(self.layers) == 1:
            self.blocked.emit("A document needs at least one layer.")
            return False
        idx = self.layers.index(layer)
        after = [L for L in self.layers if L is not layer]
        self._push_stack("Delete Layer", after, after[max(0, idx - 1)])
        return True

    def duplicate_layer(self, layer=None):
        layer = layer or self._active
        D = layer.clone()
        D.name = layer.name + " copy"
        D.background = False
        if layer.background:
            D.name = "Background copy"
        idx = self.layers.index(layer) + 1
        self._push_stack("Duplicate Layer", self.layers[:idx] + [D] + self.layers[idx:], D)
        return D

    def layer_via_copy(self, cut=False):
        """Ctrl+J / Shift+Ctrl+J: selected pixels (or whole layer) to a new layer."""
        self.commit_floating()
        src = self._active
        if not self.has_selection():
            return None if cut else self.duplicate_layer(src)
        r = self.selection_bounds()
        piece = imageops.masked_copy(src.region(self.rect()), self.selection)
        if piece.isNull() or not src.region(r).hasAlphaChannel():
            return None
        L = Layer(self.next_layer_name(), piece, r.topLeft())
        self.undo.beginMacro("Layer Via Cut" if cut else "Layer Via Copy")
        if cut:
            if src.is_text or src.pixels_locked():
                self.undo.endMacro()
                self.blocked.emit("Could not cut because the layer is locked.")
                return None
            self.clear_selection_pixels("Clear")
        idx = self.layers.index(src) + 1
        self._push_stack("New Layer", self.layers[:idx] + [L] + self.layers[idx:], L)
        self.undo.endMacro()
        return L

    def move_layer_to(self, layer, new_index, text="Layer Order"):
        layers = [L for L in self.layers if L is not layer]
        bg = self.background_layer()
        lo = 1 if bg is not None and bg is not layer else 0
        if layer.background:
            self.blocked.emit("The Background layer can't be moved. Convert it to a normal layer first.")
            return False
        new_index = max(lo, min(new_index, len(layers)))
        layers.insert(new_index, layer)
        if layers == self.layers:
            return False
        self._push_stack(text, layers, layer)
        return True

    def arrange(self, how):
        L = self._active
        i = self.layers.index(L)
        target = {"front": len(self.layers), "forward": i + 1, "backward": i - 1, "back": 0}[how]
        labels = {"front": "Bring to Front", "forward": "Bring Forward", "backward": "Send Backward",
                  "back": "Send to Back"}
        return self.move_layer_to(L, target, labels[how])

    def select_relative(self, step):
        i = self.layers.index(self._active) + step
        if 0 <= i < len(self.layers):
            self.set_active(self.layers[i])

    def set_props(self, layer, text, merge_key=None, **values):
        before = {k: getattr(layer, k) for k in values}
        if all(before[k] == v for k, v in values.items()):
            return
        self.undo.push(PropsCommand(self, layer, text, before, values, merge_key))

    def rename_layer(self, layer, name):
        name = name.strip()
        if name and name != layer.name:
            self.set_props(layer, "Rename Layer", name=name)

    def toggle_visible(self, layer):
        self.set_props(layer, "Show Layer" if not layer.visible else "Hide Layer", visible=not layer.visible)

    def solo(self, layer):
        """Alt+click on the eye: show only this layer (again to restore)."""
        others = [L for L in self.layers if L is not layer]
        self.undo.beginMacro("Show/Hide Layers")
        if any(L.visible for L in others) or not layer.visible:
            self._solo_memory = {L.uid: L.visible for L in others}
            if not layer.visible:
                self.set_props(layer, "Show Layer", visible=True)
            for L in others:
                if L.visible:
                    self.set_props(L, "Hide Layer", visible=False)
        else:
            memory = getattr(self, "_solo_memory", {})
            for L in others:
                if memory.get(L.uid, True):
                    self.set_props(L, "Show Layer", visible=True)
        self.undo.endMacro()

    def background_to_layer(self, layer=None, name="Layer 0"):
        layer = layer or self.background_layer()
        if layer is None or not layer.background:
            return
        self.set_props(layer, "Layer From Background", background=False, name=name)

    def layer_to_background(self, layer=None):
        layer = layer or self._active
        if self.background_layer() is not None or layer.is_text:
            return
        flat = QImage(self._size, PREMUL)
        flat.fill(self.bg_color)
        p = QPainter(flat)
        p.drawImage(layer.offset, layer.image)
        p.end()
        B = Layer("Background", flat, background=True)
        rest = [L for L in self.layers if L is not layer]
        self._push_stack("Background From Layer", [B] + rest, B)

    def rasterize_layer(self, layer=None):
        layer = layer or self._active
        if not layer.is_text:
            return
        before = LayerStateCommand.capture(layer)
        after = (layer.image.copy(), QPoint(layer.offset), None)
        self.undo.push(LayerStateCommand(self, "Rasterize Type", layer, before, after))

    def _merged_layer(self, group, name, background=False):
        """Pixel layer made by compositing `group` (bottom→top, all blend modes honoured)."""
        if background:
            return Layer(name, flatten(group, self._size, background_fill=self.bg_color), background=True)
        r = QRect()
        for L in group:
            r = r.united(L.rect())
        r = r.intersected(self.rect())
        if r.isEmpty():
            r = QRect(0, 0, 1, 1)
        return Layer(name, flatten(group, self._size, rect=r).copy(r), r.topLeft())

    def merge_down(self):
        self.commit_floating()
        L = self._active
        i = self.layers.index(L)
        if i == 0:
            return False
        below = self.layers[i - 1]
        if not below.visible or not L.visible:
            self.blocked.emit("Could not Merge Down because a layer is hidden.")
            return False
        base = below.clone()
        base.opacity, base.fill, base.blend = 100, 100, "norm"
        M = self._merged_layer([base, L], below.name, background=below.background)
        for k in ("opacity", "fill", "blend", "visible"):
            setattr(M, k, getattr(below, k))
        self._push_stack("Merge Down", self.layers[:i - 1] + [M] + self.layers[i + 1:], M)
        return True

    def merge_visible(self):
        vis = [L for L in self.layers if L.visible]
        if len(vis) < 2:
            return False
        has_bg = any(L.background for L in vis)
        target = vis[0]
        M = self._merged_layer(vis, "Background" if has_bg else target.name, background=has_bg)
        after = [L for L in self.layers if not L.visible or L is target]
        after[after.index(target)] = M
        self._push_stack("Merge Visible", after, M)
        return True

    def flatten_image(self):
        if len(self.layers) == 1 and self.layers[0].background:
            return False
        M = self._merged_layer([L for L in self.layers if L.visible], "Background", background=True)
        self._push_stack("Flatten Image", [M], M)
        return True

    # ------------------------------------------------------------ whole-document changes
    def _state(self):
        return (QSize(self._size), list(self.layers), self._active, QPainterPath(self.selection))

    def _restore_state(self, st):
        size, layers, active, sel = st
        old = QSize(self._size)
        self._size = QSize(size)
        self.layers = list(layers)
        self._active = active
        self._set_selection_raw(sel)
        self._comp = None
        if old != self._size:
            self.sizeChanged.emit()
        self._full_change()
        self.layersChanged.emit()
        self.activeLayerChanged.emit()

    def replace_state(self, text, size, layers, active=None, selection=None):
        self.commit_floating()
        idx = self.layers.index(self._active) if self._active in self.layers else len(layers) - 1
        active = active or layers[min(idx, len(layers) - 1)]
        after = (QSize(size), list(layers), active, selection if selection is not None else QPainterPath())
        self.undo.push(DocStateCommand(self, text, self._state(), after))

    def replace_image(self, text, new_image: QImage, new_selection=None):
        """Replace everything with one flat image (used by simple whole-image operations)."""
        img = imageops.to_working(new_image)
        B = Layer("Background", img, background=True) if self.background_layer() else Layer("Layer 0", img)
        self.replace_state(text, img.size(), [B], B, new_selection)

    # ------------------------------------------------------------ selection
    def _set_selection_raw(self, path):
        self.selection = QPainterPath(path) if path is not None else QPainterPath()
        self.selectionChanged.emit()

    def set_selection(self, path: QPainterPath, text="Selection"):
        self.commit_floating()
        clipped = QPainterPath()
        if path is not None and not path.isEmpty():
            full = QPainterPath()
            full.addRect(QRectF(self.rect()))
            clipped = path.intersected(full).simplified()
        if clipped.isEmpty() and self.selection.isEmpty():
            return
        if clipped == self.selection:
            return
        if clipped.isEmpty():
            text = "Deselect"
        self.undo.push(SelectionCommand(self, text, QPainterPath(self.selection), clipped))

    def select_all(self):
        p = QPainterPath()
        p.addRect(QRectF(self.rect()))
        self.set_selection(p, "Select All")

    def deselect(self):
        self.commit_floating()
        if self.has_selection():
            self.set_selection(QPainterPath(), "Deselect")

    def invert_selection(self):
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        self.set_selection(full.subtracted(self.selection), "Select Inverse")

    def select_layer_pixels(self, layer):
        """Ctrl+click a layer thumbnail: load its transparency as a selection."""
        reg = layer.region(self.rect())
        self.selection_from_mask(imageops.view(reg)[..., 3] >= 128, "Load Selection")

    def selection_from_mask(self, a, text="Selection"):
        """Select the True pixels of a canvas-sized boolean array."""
        import numpy as np
        path = QPainterPath()
        for y in np.flatnonzero(a.any(axis=1)):
            row = a[y]
            edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
            for s, e in zip(edges[::2], edges[1::2]):
                path.addRect(QRectF(int(s), int(y), int(e - s), 1))
        self.set_selection(path.simplified(), text)

    # ------------------------------------------------------------ floating (Move tool)
    def lift_selection(self, label="Move"):
        if self.floating:
            return True
        if not self.has_selection() or self.selection_bounds().isEmpty():
            return False
        L = self.try_target("use the Move tool")
        if L is None:
            return False
        self.floating = Floating(self, L, label)
        return True

    def move_floating(self, dx, dy):
        if not self.floating:
            return
        self.floating.move(dx, dy)
        self.selection.translate(dx, dy)
        self.selectionChanged.emit()

    def commit_floating(self):
        f = self.floating
        if not f:
            return
        self.floating = None
        L = f.layer
        L.preview = None
        dest = f.rect().intersected(self.rect())
        if not dest.isEmpty():
            p = QPainter(L.image)
            p.drawImage(f.pos - L.offset, f.image)
            p.end()
        region = dest.united(f.source_rect).intersected(self.rect())
        if region.isEmpty():
            return
        before = QImage(region.size(), PREMUL)
        before.fill(Qt.GlobalColor.transparent)
        p = QPainter(before)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(f.origin[1] - region.topLeft(), f.origin[0])
        p.end()
        after = L.region(region)
        self.undo.push(PixelsCommand(self, f.label, L, region, before, after,
                                     f.sel_before, QPainterPath(self.selection)))

    def cancel_floating(self, silent=False):
        f = self.floating
        if not f:
            return False
        self.floating = None
        L = f.layer
        L.image, L.offset = f.origin[0], f.origin[1]
        L.preview = None
        L.touch()
        self._set_selection_raw(f.sel_before)
        self.invalidate(QRect())
        return True

    def _abort_transient(self):
        """Undo/redo while something is mid-edit: drop the in-progress state."""
        self.cancel_floating(silent=True)
        if self.editing_text is not None:
            self.editing_text.abort()
