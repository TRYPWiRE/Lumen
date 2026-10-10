"""Editing tools. Each tool receives mouse events in image coordinates."""
import math
import numpy as np
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, QLineF, QSize
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QPainterPath, QCursor, QFont,
                         QFontMetricsF, QLinearGradient, QRadialGradient, QImage, QPolygonF)
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QCheckBox, QComboBox, QFontComboBox,
                             QToolButton, QSpinBox, QButtonGroup, QPushButton)

from . import icons, imageops
from .widgets import labeled_spin, separator, Swatch, icon_button

LEFT = Qt.MouseButton.LeftButton
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier
CTRL = Qt.KeyboardModifier.ControlModifier


def constrain_45(a: QPointF, b: QPointF) -> QPointF:
    d = b - a
    ang = math.atan2(d.y(), d.x())
    step = math.pi / 4
    ang = round(ang / step) * step
    length = math.hypot(d.x(), d.y())
    return QPointF(a.x() + math.cos(ang) * length, a.y() + math.sin(ang) * length)


def drag_rect(a: QPointF, b: QPointF, square=False, centred=False) -> QRectF:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    if square:
        s = max(abs(dx), abs(dy))
        dx = math.copysign(s, dx if dx else 1)
        dy = math.copysign(s, dy if dy else 1)
    if centred:
        return QRectF(a.x() - dx, a.y() - dy, 2 * dx, 2 * dy).normalized()
    return QRectF(a.x(), a.y(), dx, dy).normalized()


class Tool:
    name = ""
    title = ""
    icon = ""
    key = ""
    hint = ""
    brush_outline = False
    alt_picks = False
    hover_overlay = False
    defaults = {}

    def __init__(self, ctx):
        self.ctx = ctx
        self.active = False
        self.opts = {}
        for k, v in self.defaults.items():
            stored = ctx.settings.value(f"tools/{self.name}/{k}", v)
            try:
                self.opts[k] = type(v)(stored) if not isinstance(v, bool) else stored in (True, "true", 1, "1")
            except (TypeError, ValueError):
                self.opts[k] = v
        self._options = None
        self._controls = {}

    # -- options -----------------------------------------------------------
    def set_opt(self, key, value):
        self.opts[key] = value
        self.ctx.settings.setValue(f"tools/{self.name}/{key}", value)
        ctl = self._controls.get(key)
        if isinstance(ctl, QSpinBox) and ctl.value() != value:
            ctl.blockSignals(True)
            ctl.setValue(value)
            ctl.blockSignals(False)
        cv = self.ctx.current_canvas()
        if cv:
            cv.viewport().update()

    def options_widget(self):
        if self._options is None:
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            self.build_options(lay)
            if self.hint:
                h = QLabel(self.hint)
                h.setObjectName("Dim")
                lay.addSpacing(8)
                lay.addWidget(h)
            lay.addStretch(1)
            self._options = w
        return self._options

    def build_options(self, lay):
        pass

    def spin(self, lay, key, label, lo, hi, suffix=""):
        w, s = labeled_spin(label, lo, hi, int(self.opts[key]), suffix)
        s.valueChanged.connect(lambda v, k=key: self.set_opt(k, v))
        self._controls[key] = s
        lay.addWidget(w)
        return s

    def check(self, lay, key, label):
        c = QCheckBox(label)
        c.setChecked(bool(self.opts[key]))
        c.toggled.connect(lambda v, k=key: self.set_opt(k, v))
        lay.addWidget(c)
        return c

    def combo(self, lay, key, label, items):
        if label:
            lab = QLabel(label)
            lab.setObjectName("Dim")
            lay.addWidget(lab)
        cb = QComboBox()
        cb.addItems(items)
        cb.setCurrentIndex(int(self.opts[key]))
        cb.currentIndexChanged.connect(lambda i, k=key: self.set_opt(k, i))
        lay.addWidget(cb)
        return cb

    # -- behaviour ---------------------------------------------------------
    def cursor(self, canvas):
        return QCursor(Qt.CursorShape.CrossCursor)

    def activate(self, canvas):
        pass

    def deactivate(self, canvas):
        pass

    def press(self, canvas, pt, ev):
        pass

    def move(self, canvas, pt, ev):
        pass

    def release(self, canvas, pt, ev):
        pass

    def paint_overlay(self, p, canvas):
        pass

    def key_press(self, canvas, ev):
        return False


# =================================================================== painting
class StrokeTool(Tool):
    brush_outline = True
    alt_picks = True
    pencil = False
    erase = False
    defaults = {"size": 20, "hardness": 100, "opacity": 100}

    def __init__(self, ctx):
        super().__init__(ctx)
        self._last_end = {}

    def cursor(self, canvas):
        return QCursor(Qt.CursorShape.BlankCursor)

    def build_options(self, lay):
        self.spin(lay, "size", "Size", 1, 2500, " px")
        if not self.pencil:
            self.spin(lay, "hardness", "Hardness", 0, 100, "%")
        lay.addWidget(separator())
        self.spin(lay, "opacity", "Opacity", 1, 100, "%")

    def _color(self, doc):
        if self.erase:
            return doc.bg_color if not doc.transparent else QColor(0, 0, 0)
        return self.ctx.fg

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        doc = cv.doc
        doc.commit_floating()
        self.cv, self.doc = cv, doc
        self.active = True
        self.working = doc.image.copy()
        self.mask = np.zeros((doc.height, doc.width), np.uint8)
        hard = self.opts["hardness"] / 100.0 if not self.pencil else 1.0
        self.stamp = imageops.make_stamp(self.opts["size"], hard, self.pencil)
        self.spacing = max(1.0, self.opts["size"] * (0.25 if self.pencil else 0.1))
        self.color = self._color(doc)
        self.opacity = self.opts["opacity"] / 100.0
        self.dirty = QRect()
        self.pending = QRect()
        self.gap = 0.0
        last = self._last_end.get(id(doc))
        if ev.modifiers() & SHIFT and last is not None:
            self._dab(last)
            self._segment(last, pt)
        else:
            self._dab(pt)
        self.last = pt
        self._flush()

    def move(self, cv, pt, ev):
        if not self.active:
            return
        self._segment(self.last, pt)
        self.last = pt
        self._flush()

    def release(self, cv, pt, ev):
        if not self.active or ev.button() != LEFT:
            return
        self.active = False
        self._last_end[id(self.doc)] = QPointF(self.last)
        self.doc.preview = None
        if not self.dirty.isEmpty():
            self.doc.apply_patch(self.title, self.dirty, self.working.copy(self.dirty))
        else:
            self.doc.changed.emit(QRect())
        self.working = None
        self.mask = None

    def _segment(self, a, b):
        d = math.hypot(b.x() - a.x(), b.y() - a.y())
        if d < 1e-6:
            return
        travel = 0.0
        nxt = self.spacing - self.gap
        while travel + nxt <= d:
            travel += nxt
            t = travel / d
            self._dab(QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t))
            nxt = self.spacing
        self.gap = self.spacing - (nxt - (d - travel))

    def _dab(self, c):
        st = self.stamp
        n = st.shape[0]
        x0 = int(math.floor(c.x() - n / 2.0 + 0.5))
        y0 = int(math.floor(c.y() - n / 2.0 + 0.5))
        h, w = self.mask.shape
        ax0, ay0 = max(0, x0), max(0, y0)
        ax1, ay1 = min(w, x0 + n), min(h, y0 + n)
        if ax0 >= ax1 or ay0 >= ay1:
            return
        region = self.mask[ay0:ay1, ax0:ax1]
        np.maximum(region, st[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0], out=region)
        self.pending = self.pending.united(QRect(ax0, ay0, ax1 - ax0, ay1 - ay0))

    def _flush(self):
        r = self.pending.intersected(self.doc.rect())
        self.pending = QRect()
        if r.isEmpty():
            return
        self.dirty = self.dirty.united(r)
        layer = imageops.colorize(self.mask[r.top():r.bottom() + 1, r.left():r.right() + 1],
                                  self.color, self.opacity)
        p = QPainter(self.working)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawImage(r.topLeft(), self.doc.image, r)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self.doc.clip(p)
        if self.erase and self.doc.transparent:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        p.drawImage(r.topLeft(), layer)
        p.end()
        self.doc.set_preview(self.working, r)

    def key_press(self, canvas, ev):
        k = ev.key()
        if k in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            s = self.opts["size"]
            step = 1 if s < 10 else 5 if s < 50 else 10 if s < 100 else 25 if s < 300 else 50
            s = s + step if k == Qt.Key.Key_BracketRight else s - step
            self.set_opt("size", max(1, min(2500, s)))
            return True
        return False


class BrushTool(StrokeTool):
    name, title, icon, key = "brush", "Brush Tool", "brush", "B"
    defaults = {"size": 20, "hardness": 0, "opacity": 100}


class PencilTool(StrokeTool):
    name, title, icon, key = "pencil", "Pencil Tool", "pencil", "B"
    pencil = True
    defaults = {"size": 1, "opacity": 100}


class EraserTool(StrokeTool):
    name, title, icon, key = "eraser", "Eraser Tool", "eraser", "E"
    erase = True
    alt_picks = False
    defaults = {"size": 30, "hardness": 100, "opacity": 100}


class BucketTool(Tool):
    name, title, icon, key = "bucket", "Paint Bucket Tool", "bucket", "G"
    alt_picks = True
    defaults = {"tolerance": 32, "opacity": 100, "contiguous": True}

    def cursor(self, canvas):
        return icons.tool_cursor("bucket", (20, 19))

    def build_options(self, lay):
        self.spin(lay, "opacity", "Opacity", 1, 100, "%")
        self.spin(lay, "tolerance", "Tolerance", 0, 255)
        self.check(lay, "contiguous", "Contiguous")

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        x, y = math.floor(pt.x()), math.floor(pt.y())
        doc = cv.doc
        if not doc.rect().contains(x, y):
            return
        doc.commit_floating()
        fill_at(doc, x, y, self.ctx.fg, self.opts["tolerance"], self.opts["contiguous"],
                self.opts["opacity"] / 100.0)


def fill_at(doc, x, y, color, tolerance=32, contiguous=True, opacity=1.0):
    mask = imageops.flood_mask(doc.image, x, y, tolerance, contiguous)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return
    rect = QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))
    layer = imageops.mask_to_image(mask[rect.top():rect.bottom() + 1, rect.left():rect.right() + 1],
                                   color, opacity)
    doc.apply_region("Paint Bucket", rect, lambda p: p.drawImage(rect.topLeft(), layer))


class GradientTool(Tool):
    name, title, icon, key = "gradient", "Gradient Tool", "gradient", "G"
    defaults = {"kind": 0, "mode": 0, "opacity": 100, "reverse": False}

    def build_options(self, lay):
        self.combo(lay, "mode", "", ["Foreground to Background", "Foreground to Transparent"])
        self.combo(lay, "kind", "", ["Linear", "Radial"])
        lay.addWidget(separator())
        self.spin(lay, "opacity", "Opacity", 1, 100, "%")
        self.check(lay, "reverse", "Reverse")

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        cv.doc.commit_floating()
        self.active = True
        self.a = self.b = pt

    def move(self, cv, pt, ev):
        if self.active:
            self.b = constrain_45(self.a, pt) if ev.modifiers() & SHIFT else pt
            cv.viewport().update()

    def release(self, cv, pt, ev):
        if not self.active:
            return
        self.active = False
        cv.viewport().update()
        if QLineF(self.a, self.b).length() * cv.zoom < 2:
            return
        apply_gradient(cv.doc, self.a, self.b, self.ctx.fg, self.ctx.bg, self.opts)

    def paint_overlay(self, p, cv):
        if not self.active:
            return
        a, b = cv.img_to_view(self.a), cv.img_to_view(self.b)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for col, w in ((QColor(0, 0, 0, 170), 3), (QColor("white"), 1)):
            p.setPen(QPen(col, w))
            p.drawLine(a, b)
        p.setBrush(QColor("white"))
        p.setPen(QPen(QColor(0, 0, 0, 170), 1))
        p.drawEllipse(a, 3.5, 3.5)
        p.drawEllipse(b, 3.5, 3.5)


def apply_gradient(doc, a, b, fg, bg, opts):
    c0, c1 = QColor(fg), QColor(bg)
    if opts.get("mode", 0) == 1:
        c1 = QColor(fg)
        c1.setAlpha(0)
    if opts.get("reverse"):
        c0, c1 = c1, c0
    if opts.get("kind", 0) == 1:
        g = QRadialGradient(a, QLineF(a, b).length())
    else:
        g = QLinearGradient(a, b)
    g.setColorAt(0, c0)
    g.setColorAt(1, c1)
    rect = doc.selection_bounds() if doc.has_selection() else doc.rect()

    def paint(p):
        p.setOpacity(opts.get("opacity", 100) / 100.0)
        p.fillRect(rect, QBrush(g))
    doc.apply_region("Gradient", rect, paint)


# =================================================================== shapes
class ShapeTool(Tool):
    alt_picks = True
    defaults = {"fill": True, "stroke": False, "width": 3}
    kind = "rect"

    def build_options(self, lay):
        if self.kind != "line":
            c = self.check(lay, "fill", "Fill")
            self.fill_swatch = Swatch(self.ctx.fg, 16)
            lay.addWidget(self.fill_swatch)
            lay.addSpacing(6)
            self.check(lay, "stroke", "Stroke")
            self.stroke_swatch = Swatch(self.ctx.bg, 16)
            lay.addWidget(self.stroke_swatch)
            self.spin(lay, "width", "", 1, 500, " px")
            self.ctx.colorsChanged.connect(self._sync_swatches)
            self.fill_swatch.setToolTip("Fill uses the foreground colour")
            self.stroke_swatch.setToolTip("Stroke uses the background colour")
        else:
            self.spin(lay, "width", "Weight", 1, 500, " px")

    def _sync_swatches(self):
        self.fill_swatch.set_color(self.ctx.fg)
        self.stroke_swatch.set_color(self.ctx.bg)

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        cv.doc.commit_floating()
        self.active = True
        self.a = self.b = pt
        self.mods = ev.modifiers()

    def move(self, cv, pt, ev):
        if self.active:
            self.b = pt
            self.mods = ev.modifiers()
            cv.viewport().update()

    def geometry(self):
        if self.kind == "line":
            b = constrain_45(self.a, self.b) if self.mods & SHIFT else self.b
            return QLineF(self.a, b)
        return drag_rect(self.a, self.b, bool(self.mods & SHIFT), bool(self.mods & ALT))

    def draw(self, p, geo):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.opts["width"]
        if self.kind == "line":
            pen = QPen(self.ctx.fg, w)
            pen.setCapStyle(Qt.PenCapStyle.SquareCap if w > 1 else Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawLine(geo)
            return
        p.setPen(QPen(self.ctx.bg, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap,
                      Qt.PenJoinStyle.MiterJoin) if self.opts["stroke"] else Qt.PenStyle.NoPen)
        p.setBrush(self.ctx.fg if self.opts["fill"] else Qt.BrushStyle.NoBrush)
        r = geo
        if self.opts["stroke"]:
            r = geo.adjusted(w / 2, w / 2, -w / 2, -w / 2)  # stroke inside, like Photoshop
        if self.kind == "rect":
            p.drawRect(r)
        else:
            p.drawEllipse(r)

    def release(self, cv, pt, ev):
        if not self.active:
            return
        self.active = False
        self.b = pt
        self.mods = ev.modifiers()
        geo = self.geometry()
        cv.viewport().update()
        if self.kind == "line":
            if geo.length() < 0.5:
                return
            w = self.opts["width"]
            bounds = QRectF(geo.p1(), geo.p2()).normalized().adjusted(-w, -w, w, w)
        else:
            if geo.width() < 1 or geo.height() < 1:
                return
            if not (self.opts["fill"] or self.opts["stroke"]):
                self.ctx.status.emit("Turn on Fill or Stroke in the options bar to draw a shape.")
                return
            bounds = geo.adjusted(-2, -2, 2, 2)
        cv.doc.apply_region(self.title.replace(" Tool", ""), bounds.toAlignedRect(), lambda p: self.draw(p, geo))

    def paint_overlay(self, p, cv):
        if not self.active:
            return
        p.setTransform(cv.transform())
        self.draw(p, self.geometry())


class RectTool(ShapeTool):
    name, title, icon, key, kind = "rect", "Rectangle Tool", "rect", "U", "rect"
    hint = "Shift: square · Alt: from centre"


class EllipseTool(ShapeTool):
    name, title, icon, key, kind = "ellipse", "Ellipse Tool", "ellipse", "U", "ellipse"
    hint = "Shift: circle · Alt: from centre"


class LineTool(ShapeTool):
    name, title, icon, key, kind = "line", "Line Tool", "line", "U", "line"
    defaults = {"width": 3}
    hint = "Shift: snap to 45°"


# =================================================================== selection
SEL_NEW, SEL_ADD, SEL_SUB, SEL_INT = range(4)


def combine_selection(doc, shape: QPainterPath, mode, label):
    cur = QPainterPath(doc.selection)
    if mode == SEL_NEW or cur.isEmpty():
        if mode == SEL_SUB or mode == SEL_INT:
            new = QPainterPath() if mode == SEL_INT else cur
        else:
            new = shape
    elif mode == SEL_ADD:
        new = cur.united(shape)
    elif mode == SEL_SUB:
        new = cur.subtracted(shape)
    else:
        new = cur.intersected(shape)
    doc.set_selection(new, label)


class SelectionTool(Tool):
    defaults = {"mode": 0}

    def build_options(self, lay):
        grp = QButtonGroup(lay.parentWidget() or None)
        for i, (ic, tip) in enumerate((("sel_new", "New selection"), ("sel_add", "Add to selection (Shift)"),
                                       ("sel_sub", "Subtract from selection (Alt)"),
                                       ("sel_int", "Intersect with selection (Shift+Alt)"))):
            b = icon_button(icons.icon(ic), tip, True, 26)
            b.setObjectName("ModeButton")
            b.setChecked(i == self.opts["mode"])
            grp.addButton(b, i)
            lay.addWidget(b)
        grp.idClicked.connect(lambda i: self.set_opt("mode", i))
        self._grp = grp
        lay.addWidget(separator())

    def mode_for(self, mods):
        s, a = bool(mods & SHIFT), bool(mods & ALT)
        if s and a:
            return SEL_INT
        if s:
            return SEL_ADD
        if a:
            return SEL_SUB
        return self.opts["mode"]


class MarqueeTool(SelectionTool):
    ellipse = False
    hint = "Shift: add/square · Alt: subtract · drag inside a selection to move it"

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        doc = cv.doc
        doc.commit_floating()
        self.active = True
        self.a = self.b = pt
        self.mods = ev.modifiers()
        self.mode = self.mode_for(ev.modifiers())
        self.moving = (self.mode == SEL_NEW and not (ev.modifiers() & (SHIFT | ALT)) and doc.has_selection()
                       and doc.selection.contains(pt))
        if self.moving:
            self.sel_start = QPainterPath(doc.selection)

    def move(self, cv, pt, ev):
        if not self.active:
            return
        self.b = pt
        self.mods = ev.modifiers()
        if self.moving:
            d = self.b - self.a
            moved = QPainterPath(self.sel_start)
            moved.translate(round(d.x()), round(d.y()))
            cv.doc._set_selection_raw(moved)
        cv.viewport().update()

    def shape_rect(self):
        square = bool(self.mods & SHIFT) and self.mode == SEL_NEW
        r = drag_rect(self.a, self.b, square, False)
        return QRectF(QPointF(round(r.left()), round(r.top())), QPointF(round(r.right()), round(r.bottom())))

    def release(self, cv, pt, ev):
        if not self.active:
            return
        self.active = False
        doc = cv.doc
        if self.moving:
            new = QPainterPath(doc.selection)
            doc._set_selection_raw(self.sel_start)
            if new != self.sel_start:
                doc.set_selection(new, "Move Selection")
            return
        r = self.shape_rect()
        if r.width() * cv.zoom < 2 and r.height() * cv.zoom < 2 or r.width() < 1 or r.height() < 1:
            if self.mode == SEL_NEW:
                doc.deselect()
            cv.viewport().update()
            return
        path = QPainterPath()
        if self.ellipse:
            path.addEllipse(r)
        else:
            path.addRect(r)
        combine_selection(doc, path, self.mode, self.title.replace(" Tool", ""))
        cv.viewport().update()

    def paint_overlay(self, p, cv):
        if not self.active or self.moving:
            return
        r = cv.img_rect_to_view(self.shape_rect())
        p.setBrush(Qt.BrushStyle.NoBrush)
        for col, dash in ((QColor("white"), None), (QColor("black"), [4, 4])):
            pen = QPen(col, 1)
            if dash:
                pen.setDashPattern(dash)
            p.setPen(pen)
            if self.ellipse:
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.drawEllipse(r)
            else:
                p.drawRect(r)


class RectMarqueeTool(MarqueeTool):
    name, title, icon, key = "marquee_rect", "Rectangular Marquee Tool", "marquee_rect", "M"


class EllipseMarqueeTool(MarqueeTool):
    name, title, icon, key = "marquee_ellipse", "Elliptical Marquee Tool", "marquee_ellipse", "M"
    ellipse = True


class LassoTool(SelectionTool):
    name, title, icon, key = "lasso", "Lasso Tool", "lasso", "L"
    hint = "Drag to draw a freehand selection"

    def cursor(self, canvas):
        return icons.tool_cursor("lasso", (7, 21))

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        cv.doc.commit_floating()
        self.active = True
        self.mode = self.mode_for(ev.modifiers())
        self.pts = [pt]

    def move(self, cv, pt, ev):
        if self.active:
            if QLineF(self.pts[-1], pt).length() * cv.zoom >= 1.5:
                self.pts.append(pt)
                cv.viewport().update()

    def release(self, cv, pt, ev):
        if not self.active:
            return
        self.active = False
        cv.viewport().update()
        if len(self.pts) < 3:
            if self.mode == SEL_NEW:
                cv.doc.deselect()
            return
        path = QPainterPath()
        path.addPolygon(QPolygonF(self.pts))
        path.closeSubpath()
        combine_selection(cv.doc, path, self.mode, "Lasso")

    def paint_overlay(self, p, cv):
        if not self.active or len(self.pts) < 2:
            return
        poly = cv.transform().map(QPolygonF(self.pts))
        for col, dash in ((QColor("white"), None), (QColor("black"), [4, 4])):
            pen = QPen(col, 1)
            if dash:
                pen.setDashPattern(dash)
            p.setPen(pen)
            p.drawPolyline(poly)


# =================================================================== move
class MoveTool(Tool):
    name, title, icon, key = "move", "Move Tool", "move", "V"
    hint = "Drag a selection to move its pixels · Arrow keys nudge · Enter applies · Esc cancels"

    def cursor(self, canvas):
        return QCursor(Qt.CursorShape.SizeAllCursor)

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        doc = cv.doc
        if not doc.floating:
            if not doc.has_selection():
                self.ctx.status.emit("Make a selection first, then drag it with the Move tool.")
                return
            doc.lift_selection("Move")
        self.active = True
        self.start = pt
        self.applied = QPoint(0, 0)

    def move(self, cv, pt, ev):
        if not self.active:
            return
        d = pt - self.start
        target = QPoint(round(d.x()), round(d.y()))
        step = target - self.applied
        if step.x() or step.y():
            cv.doc.move_floating(step.x(), step.y())
            self.applied = target

    def release(self, cv, pt, ev):
        self.active = False

    def deactivate(self, canvas):
        if canvas:
            canvas.doc.commit_floating()

    def key_press(self, cv, ev):
        k = ev.key()
        doc = cv.doc
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if k in arrows:
            if not doc.floating and not doc.lift_selection("Nudge"):
                return False
            dx, dy = arrows[k]
            n = 10 if ev.modifiers() & SHIFT else 1
            doc.move_floating(dx * n, dy * n)
            return True
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and doc.floating:
            doc.commit_floating()
            return True
        if k == Qt.Key.Key_Escape and doc.floating:
            doc.cancel_floating()
            return True
        return False


# =================================================================== crop
class CropTool(Tool):
    name, title, icon, key = "crop", "Crop Tool", "crop", "C"
    hover_overlay = True
    HANDLE = 7

    def __init__(self, ctx):
        super().__init__(ctx)
        self.rect = None
        self.drag = None

    def build_options(self, lay):
        self.size_label = QLabel("Drag over the image to set the crop area")
        self.size_label.setObjectName("Dim")
        lay.addWidget(self.size_label)
        lay.addWidget(separator())
        ok = icon_button(icons.icon("check"), "Commit crop (Enter)")
        cancel = icon_button(icons.icon("cancel"), "Cancel crop (Esc)")
        ok.clicked.connect(lambda: self.commit(self.ctx.current_canvas()))
        cancel.clicked.connect(lambda: self.cancel(self.ctx.current_canvas()))
        lay.addWidget(cancel)
        lay.addWidget(ok)

    def _update_label(self):
        if hasattr(self, "size_label"):
            if self.rect:
                r = self.rect.toAlignedRect()
                self.size_label.setText(f"W: {r.width()} px   H: {r.height()} px   ·   Enter to crop, Esc to cancel")
            else:
                self.size_label.setText("Drag over the image to set the crop area")

    def _handles(self, cv):
        r = cv.img_rect_to_view(self.rect)
        pts = {
            "tl": r.topLeft(), "t": QPointF(r.center().x(), r.top()), "tr": r.topRight(),
            "r": QPointF(r.right(), r.center().y()), "br": r.bottomRight(),
            "b": QPointF(r.center().x(), r.bottom()), "bl": r.bottomLeft(), "l": QPointF(r.left(), r.center().y()),
        }
        return pts

    def _hit(self, cv, vpos):
        if not self.rect:
            return None
        for name, hp in self._handles(cv).items():
            if abs(hp.x() - vpos.x()) <= self.HANDLE and abs(hp.y() - vpos.y()) <= self.HANDLE:
                return name
        if cv.img_rect_to_view(self.rect).contains(vpos):
            return "move"
        return None

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        cv.doc.commit_floating()
        hit = self._hit(cv, ev.position())
        self.active = True
        self.start = pt
        if hit:
            self.drag = hit
            self.orig = QRectF(self.rect)
        else:
            self.drag = "new"
            self.rect = QRectF(pt, pt)

    def move(self, cv, pt, ev):
        if not self.active:
            hit = self._hit(cv, ev.position())
            shapes = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                      "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                      "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                      "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                      "move": Qt.CursorShape.SizeAllCursor}
            cv.viewport().setCursor(QCursor(shapes.get(hit, Qt.CursorShape.CrossCursor)))
            return
        pt = QPointF(round(pt.x()), round(pt.y()))
        if self.drag == "new":
            self.rect = drag_rect(QPointF(round(self.start.x()), round(self.start.y())), pt,
                                  bool(ev.modifiers() & SHIFT))
        elif self.drag == "move":
            d = pt - QPointF(round(self.start.x()), round(self.start.y()))
            self.rect = self.orig.translated(d)
        else:
            r = QRectF(self.orig)
            if "l" in self.drag:
                r.setLeft(pt.x())
            if "r" in self.drag:
                r.setRight(pt.x())
            if "t" in self.drag:
                r.setTop(pt.y())
            if "b" in self.drag:
                r.setBottom(pt.y())
            self.rect = r.normalized()
        self._update_label()
        cv.viewport().update()

    def release(self, cv, pt, ev):
        if not self.active:
            return
        self.active = False
        if self.rect is not None and (self.rect.width() < 1 or self.rect.height() < 1):
            self.rect = None
        self._update_label()
        cv.viewport().update()

    def double_click(self, cv, pt, ev):
        if self.rect and cv.img_rect_to_view(self.rect).contains(ev.position()):
            self.commit(cv)

    def commit(self, cv):
        if cv is None or not self.rect:
            return
        r = self.rect.toAlignedRect()
        self.rect = None
        self._update_label()
        crop_document(cv.doc, r, "Crop")
        cv.viewport().update()

    def cancel(self, cv):
        self.rect = None
        self._update_label()
        if cv:
            cv.viewport().update()

    def deactivate(self, canvas):
        self.cancel(canvas)

    def key_press(self, cv, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.rect:
            self.commit(cv)
            return True
        if ev.key() == Qt.Key.Key_Escape and self.rect:
            self.cancel(cv)
            return True
        return False

    def paint_overlay(self, p, cv):
        if not self.rect:
            return
        r = cv.img_rect_to_view(self.rect)
        full = QPainterPath()
        full.addRect(QRectF(cv.viewport().rect()))
        hole = QPainterPath()
        hole.addRect(r)
        p.fillPath(full.subtracted(hole), QColor(0, 0, 0, 140))
        p.setBrush(Qt.BrushStyle.NoBrush)
        thirds = QPen(QColor(255, 255, 255, 110), 1)
        p.setPen(thirds)
        for i in (1, 2):
            x = r.left() + r.width() * i / 3
            y = r.top() + r.height() * i / 3
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(QColor("white"), 1))
        p.drawRect(r)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(QColor("white"))
        for hp in self._handles(cv).values():
            p.drawRect(QRectF(hp.x() - 4, hp.y() - 4, 8, 8))


def crop_document(doc, r: QRect, label="Crop"):
    if r.width() < 1 or r.height() < 1:
        return
    out = QImage(r.size(), imageops.PREMUL)
    out.fill(Qt.GlobalColor.transparent if doc.transparent else doc.bg_color)
    p = QPainter(out)
    p.drawImage(-r.topLeft(), doc.image)
    p.end()
    doc.replace_image(label, out)


# =================================================================== sampling
class EyedropperTool(Tool):
    name, title, icon, key = "eyedropper", "Eyedropper Tool", "eyedropper", "I"
    defaults = {"sample": 0}
    hint = "Click to set the foreground colour · Alt+click sets the background"
    SIZES = [1, 3, 5, 11, 31]

    def cursor(self, canvas):
        return icons.tool_cursor("eyedropper", (3, 21))

    def build_options(self, lay):
        self.combo(lay, "sample", "Sample Size:", ["Point Sample", "3 by 3 Average", "5 by 5 Average",
                                                   "11 by 11 Average", "31 by 31 Average"])

    def _pick(self, cv, pt, mods):
        x, y = math.floor(pt.x()), math.floor(pt.y())
        if not cv.doc.rect().contains(x, y):
            return
        c = imageops.sample(cv.doc.flattened(), x, y, self.SIZES[self.opts["sample"]])
        if c.alpha() == 0:
            return
        if mods & ALT:
            self.ctx.set_bg(c)
        else:
            self.ctx.set_fg(c)

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        self.active = True
        self.old = self.ctx.fg
        self._pick(cv, pt, ev.modifiers())
        cv.viewport().update()

    def move(self, cv, pt, ev):
        if self.active:
            self._pick(cv, pt, ev.modifiers())
            cv.viewport().update()

    def release(self, cv, pt, ev):
        self.active = False
        cv.viewport().update()

    def paint_overlay(self, p, cv):
        if not self.active or cv.mouse_view is None:
            return
        c = cv.mouse_view
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QPainterPath()
        outer.addEllipse(c, 48, 48)
        inner = QPainterPath()
        inner.addEllipse(c, 27, 27)
        ring = outer.subtracted(inner)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(ring, QColor(70, 70, 70))
        p.setClipPath(ring)
        rect = QRectF(c.x() - 45, c.y() - 45, 90, 90)
        p.setBrush(self.ctx.fg)
        p.drawPie(rect, 0, 180 * 16)
        p.setBrush(self.old)
        p.drawPie(rect, 180 * 16, 180 * 16)
        p.setClipping(False)
        p.setPen(QPen(QColor(70, 70, 70), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, 28.5, 28.5)


# =================================================================== text
class TextTool(Tool):
    name, title, icon, key = "text", "Horizontal Type Tool", "text", "T"
    defaults = {"family": "Segoe UI", "size": 48, "bold": False, "italic": False}
    hint = "Click on the image to place text"

    def cursor(self, canvas):
        return QCursor(Qt.CursorShape.IBeamCursor)

    def build_options(self, lay):
        fc = QFontComboBox()
        fc.setCurrentFont(QFont(self.opts["family"]))
        fc.setFixedWidth(170)
        fc.currentFontChanged.connect(lambda f: self.set_opt("family", f.family()))
        lay.addWidget(fc)
        self.spin(lay, "size", "", 1, 1000, " px")
        for key, label in (("bold", "B"), ("italic", "I")):
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setChecked(bool(self.opts[key]))
            f = b.font()
            f.setBold(key == "bold")
            f.setItalic(key == "italic")
            b.setFont(f)
            b.setFixedSize(26, 26)
            b.toggled.connect(lambda v, k=key: self.set_opt(k, v))
            lay.addWidget(b)
        lay.addWidget(separator())
        self.swatch = Swatch(self.ctx.fg, 18)
        self.swatch.setToolTip("Text uses the foreground colour")
        self.ctx.colorsChanged.connect(lambda: self.swatch.set_color(self.ctx.fg))
        lay.addWidget(self.swatch)

    def font(self):
        f = QFont(self.opts["family"])
        f.setPixelSize(max(1, int(self.opts["size"])))
        f.setBold(bool(self.opts["bold"]))
        f.setItalic(bool(self.opts["italic"]))
        return f

    def layout(self, pt, text):
        f = self.font()
        fm = QFontMetricsF(f)
        lines = text.split("\n")
        bounds = QRectF()
        y = pt.y()
        for ln in lines:
            br = fm.boundingRect(ln or " ").translated(pt.x(), y)
            bounds = bounds.united(br)
            y += fm.lineSpacing()
        return f, fm, lines, bounds.adjusted(-4, -4, 4, 4)

    def render(self, p, pt, text):
        f, fm, lines, _ = self.layout(pt, text)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(f)
        p.setPen(self.ctx.fg)
        y = pt.y()
        for ln in lines:
            p.drawText(QPointF(pt.x(), y), ln)
            y += fm.lineSpacing()

    def preview(self, doc, pt, text):
        img = doc.image.copy()
        if text:
            p = QPainter(img)
            doc.clip(p)
            self.render(p, pt, text)
            p.end()
        doc.set_preview(img)

    def commit_text(self, doc, pt, text):
        doc.preview = None
        if not text.strip():
            doc.changed.emit(QRect())
            return
        _, _, _, bounds = self.layout(pt, text)
        label = "Type: " + (text.split("\n")[0][:20] or "Text")
        doc.apply_region(label, bounds.toAlignedRect(), lambda p: self.render(p, pt, text))

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        from .dialogs import TextDialog
        doc = cv.doc
        doc.commit_floating()
        pt = QPointF(round(pt.x()), round(pt.y()))
        dlg = TextDialog(self, cv.window())
        dlg.textChanged.connect(lambda t: self.preview(doc, pt, t))
        if dlg.exec():
            self.commit_text(doc, pt, dlg.text())
        else:
            doc.set_preview(None)


# =================================================================== navigation
class HandTool(Tool):
    name, title, icon, key = "hand", "Hand Tool", "hand", "H"
    hint = "Tip: hold Space with any tool to pan"

    def cursor(self, canvas):
        return QCursor(Qt.CursorShape.OpenHandCursor)

    def build_options(self, lay):
        for text, fn in (("100%", "actual_pixels"), ("Fit Screen", "fit_to_screen")):
            b = QPushButton(text)
            b.setObjectName("Flat")
            b.clicked.connect(lambda _, f=fn: getattr(self.ctx.current_canvas(), f)() if self.ctx.current_canvas() else None)
            lay.addWidget(b)


class ZoomTool(Tool):
    name, title, icon, key = "zoom", "Zoom Tool", "zoom", "Z"
    defaults = {"out": False}
    hint = "Click to zoom in · Alt+click to zoom out"

    def cursor(self, canvas):
        return icons.tool_cursor("zoom_out" if self.opts["out"] else "zoom_in", (10, 10))

    def build_options(self, lay):
        grp = QButtonGroup(lay.parentWidget() or None)
        for i, (ic, tip) in enumerate((("zoom_in", "Zoom in"), ("zoom_out", "Zoom out (Alt)"))):
            b = icon_button(icons.icon(ic), tip, True)
            b.setObjectName("ModeButton")
            b.setChecked(i == int(self.opts["out"]))
            grp.addButton(b, i)
            lay.addWidget(b)
        grp.idClicked.connect(lambda i: (self.set_opt("out", bool(i)),
                                         self.ctx.current_canvas() and self.ctx.current_canvas().refresh_cursor()))
        self._grp = grp
        lay.addWidget(separator())
        for text, fn in (("100%", "actual_pixels"), ("Fit Screen", "fit_to_screen")):
            b = QPushButton(text)
            b.setObjectName("Flat")
            b.clicked.connect(lambda _, f=fn: getattr(self.ctx.current_canvas(), f)() if self.ctx.current_canvas() else None)
            lay.addWidget(b)

    def press(self, cv, pt, ev):
        if ev.button() != LEFT:
            return
        out = bool(self.opts["out"]) != bool(ev.modifiers() & ALT)
        cv.zoom_step(-1 if out else 1, ev.position())


# =================================================================== registry
TOOL_CLASSES = [MoveTool, RectMarqueeTool, EllipseMarqueeTool, LassoTool, CropTool, EyedropperTool,
                BrushTool, PencilTool, EraserTool, BucketTool, GradientTool, TextTool,
                RectTool, EllipseTool, LineTool, HandTool, ZoomTool]

# (group id, [tool names], separator-after)
TOOL_GROUPS = [
    ("move", ["move"], False),
    ("marquee", ["marquee_rect", "marquee_ellipse"], False),
    ("lasso", ["lasso"], False),
    ("crop", ["crop"], False),
    ("eyedropper", ["eyedropper"], True),
    ("brush", ["brush", "pencil"], False),
    ("eraser", ["eraser"], False),
    ("fill", ["bucket", "gradient"], True),
    ("text", ["text"], False),
    ("shape", ["rect", "ellipse", "line"], True),
    ("hand", ["hand"], False),
    ("zoom", ["zoom"], False),
]
