"""Document model: pixels, selection, floating selection and undo history."""
import os
from PyQt6.QtCore import QObject, pyqtSignal, QRect, QRectF, QPoint, QPointF, Qt, QSize
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QColor, QUndoStack, QUndoCommand

from . import imageops
from .imageops import PREMUL


class RegionCommand(QUndoCommand):
    """Replaces the pixels of one rectangle (before/after snapshots)."""

    def __init__(self, doc, text, rect, before, after, sel_before=None, sel_after=None):
        super().__init__(text)
        self.doc, self.rect, self.before, self.after = doc, QRect(rect), before, after
        self.sel_before, self.sel_after = sel_before, sel_after

    def _put(self, img, sel):
        p = QPainter(self.doc.image)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(self.rect.topLeft(), img)
        p.end()
        if sel is not None:
            self.doc._set_selection_raw(sel)
        self.doc.changed.emit(self.rect)

    def redo(self):
        self._put(self.after, self.sel_after)

    def undo(self):
        self.doc.cancel_floating(silent=True)
        self._put(self.before, self.sel_before)


class ImageCommand(QUndoCommand):
    """Replaces the whole image (resize, rotate, crop...)."""

    def __init__(self, doc, text, before, after, sel_before, sel_after):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after
        self.sel_before, self.sel_after = sel_before, sel_after

    def redo(self):
        self.doc._swap_image(self.after, self.sel_after)

    def undo(self):
        self.doc.cancel_floating(silent=True)
        self.doc._swap_image(self.before, self.sel_before)


class SelectionCommand(QUndoCommand):
    def __init__(self, doc, text, before, after):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after

    def redo(self):
        self.doc._set_selection_raw(self.after)

    def undo(self):
        self.doc.cancel_floating(silent=True)
        self.doc._set_selection_raw(self.before)


class Floating:
    """Pixels lifted off the canvas (paste or move) that haven't been committed."""

    def __init__(self, image, pos, origin_image, label, source_rect=QRect(), sel_before=None):
        self.image = image          # premultiplied pixels
        self.pos = QPoint(pos)      # top-left in document space
        self.origin = origin_image  # full document snapshot before the lift
        self.label = label          # history label used on commit
        self.source_rect = QRect(source_rect)
        self.sel_before = sel_before

    def rect(self):
        return QRect(self.pos, self.image.size())


class Document(QObject):
    changed = pyqtSignal(QRect)        # pixels changed (empty rect == everything)
    sizeChanged = pyqtSignal()
    selectionChanged = pyqtSignal()
    titleChanged = pyqtSignal()

    _counter = 0

    def __init__(self, image: QImage, path=None, name=None, transparent=None, dpi=72):
        super().__init__()
        self.image = imageops.to_working(image).copy()
        self.path = path
        if name is None:
            if path:
                name = os.path.basename(path)
            else:
                Document._counter += 1
                name = f"Untitled-{Document._counter}"
        self.name = name
        self.dpi = dpi
        self.transparent = image.hasAlphaChannel() if transparent is None else transparent
        self.selection = QPainterPath()
        self.floating = None
        self.preview = None   # temporary image shown instead of `image` while a tool works
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self._clean_changed)
        self.bg_color = QColor("white")  # set by the app: colour revealed when erasing/clearing

    def _clean_changed(self, _clean):
        self.titleChanged.emit()

    # ------------------------------------------------------------ basics
    @property
    def width(self):
        return self.image.width()

    @property
    def height(self):
        return self.image.height()

    def rect(self):
        return self.image.rect()

    def modified(self):
        return not self.undo.isClean()

    def display_image(self):
        return self.preview if self.preview is not None else self.image

    def set_preview(self, img, rect=QRect()):
        self.preview = img
        self.changed.emit(rect)

    def has_selection(self):
        return not self.selection.isEmpty()

    def selection_bounds(self) -> QRect:
        if self.selection.isEmpty():
            return QRect()
        return self.selection.boundingRect().toAlignedRect().intersected(self.rect())

    def clip(self, p: QPainter):
        if not self.selection.isEmpty():
            p.setClipPath(self.selection)

    # ------------------------------------------------------------ edits
    def apply_patch(self, text, rect: QRect, after: QImage):
        """Commit `after` (already rendered) into rect as one history step."""
        rect = QRect(rect).intersected(self.rect())
        if rect.isEmpty():
            return
        if after.size() != rect.size():
            after = after.copy(QRect(QPoint(0, 0), rect.size()))
        before = self.image.copy(rect)
        self.undo.push(RegionCommand(self, text, rect, before, after))

    def apply_region(self, text, rect: QRect, paint_fn, clip=True):
        """Run paint_fn(painter) on the image inside rect as one history step."""
        self.commit_floating()
        rect = QRect(rect).intersected(self.rect())
        if rect.isEmpty():
            return False
        before = self.image.copy(rect)
        work = self.image.copy(rect)
        p = QPainter(work)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-rect.x(), -rect.y())
        if clip:
            self.clip(p)
        paint_fn(p)
        p.end()
        self.undo.push(RegionCommand(self, text, rect, before, work))
        return True

    def replace_image(self, text, new_image: QImage, new_selection=None):
        self.commit_floating()
        sel_after = QPainterPath() if new_selection is None else new_selection
        self.undo.push(ImageCommand(self, text, self.image.copy(), imageops.to_working(new_image).copy(),
                                    QPainterPath(self.selection), sel_after))

    def _swap_image(self, img, sel):
        old = self.image.size()
        self.image = img.copy()
        self.preview = None
        self._set_selection_raw(sel)
        if old != img.size():
            self.sizeChanged.emit()
        self.changed.emit(QRect())

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

    # ------------------------------------------------------------ floating
    def lift_selection(self, label="Move"):
        """Cut the selected pixels into a floating piece the Move tool can drag."""
        if self.floating or not self.has_selection():
            return self.floating is not None
        rect = self.selection_bounds()
        if rect.isEmpty():
            return False
        origin = self.image.copy()
        piece = imageops.masked_copy(self.image, self.selection)
        p = QPainter(self.image)
        p.setClipPath(self.selection)
        if self.transparent:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(rect, Qt.GlobalColor.transparent)
        else:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(rect, self.bg_color)
        p.end()
        self.floating = Floating(piece, rect.topLeft(), origin, label, rect, QPainterPath(self.selection))
        self.changed.emit(QRect())
        return True

    def paste_floating(self, img: QImage, pos: QPoint, label="Paste"):
        self.commit_floating()
        img = imageops.to_working(img).copy()
        self.floating = Floating(img, pos, self.image.copy(), label, QRect(), QPainterPath(self.selection))
        sel = QPainterPath()
        sel.addRect(QRectF(QRect(pos, img.size())))
        self._set_selection_raw(sel)
        self.changed.emit(QRect())

    def move_floating(self, dx, dy):
        if not self.floating:
            return
        self.floating.pos += QPoint(dx, dy)
        self.selection.translate(dx, dy)
        self.selectionChanged.emit()
        self.changed.emit(QRect())

    def commit_floating(self):
        f = self.floating
        if not f:
            return
        self.floating = None
        dest = f.rect()
        p = QPainter(self.image)
        p.drawImage(dest.topLeft(), f.image)
        p.end()
        region = dest.united(f.source_rect) if not f.source_rect.isEmpty() else dest
        region = region.intersected(self.rect())
        if region.isEmpty():  # dragged completely off-canvas
            region = f.source_rect.intersected(self.rect())
        if region.isEmpty():
            self.image = f.origin
            self.changed.emit(QRect())
            return
        before = f.origin.copy(region)
        after = self.image.copy(region)
        self.undo.push(RegionCommand(self, f.label, region, before, after,
                                     f.sel_before, QPainterPath(self.selection)))

    def cancel_floating(self, silent=False):
        f = self.floating
        if not f:
            return False
        self.floating = None
        self.image = f.origin
        self._set_selection_raw(f.sel_before)
        if not silent:
            self.changed.emit(QRect())
        return True

    # ------------------------------------------------------------ helpers
    def clear_selection_pixels(self, text="Clear"):
        if not self.has_selection():
            return
        rect = self.selection_bounds()

        def paint(p):
            if self.transparent:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                p.fillRect(rect, Qt.GlobalColor.transparent)
            else:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                p.fillRect(rect, self.bg_color)
        self.apply_region(text, rect, paint)

    def fill(self, color: QColor, text="Fill"):
        rect = self.selection_bounds() if self.has_selection() else self.rect()
        self.apply_region(text, rect, lambda p: p.fillRect(rect, color))

    def filter_region(self, text, fn):
        """Apply fn(QImage)->QImage to the selection (or whole image)."""
        self.commit_floating()
        rect = self.selection_bounds() if self.has_selection() else self.rect()
        if rect.isEmpty():
            return
        processed = imageops.to_working(fn(self.image.copy(rect)))

        def paint(p):
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(rect.topLeft(), processed)
        self.apply_region(text, rect, paint, clip=True)

    def flattened(self) -> QImage:
        """The image as it would be saved (commits nothing, includes floating)."""
        if not self.floating:
            return self.image
        out = self.image.copy()
        p = QPainter(out)
        p.drawImage(self.floating.pos, self.floating.image)
        p.end()
        return out
