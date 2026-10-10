"""The zoomable, scrollable document view."""
import math
from PyQt6.QtCore import Qt, QEvent, QRect, QRectF, QPoint, QPointF, pyqtSignal, QTimer
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QPixmap, QTransform, QCursor,
                         QPainterPath, QMouseEvent)
from PyQt6.QtWidgets import QAbstractScrollArea

from . import theme

ZOOM_STEPS = [1 / 32, 1 / 24, 1 / 16, 1 / 12, 1 / 8, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 1.0,
              1.5, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 32]
PAD = 60


def _checker():
    pm = QPixmap(16, 16)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor("#cccccc"))
    p.fillRect(8, 8, 8, 8, QColor("#cccccc"))
    p.end()
    return pm


class Canvas(QAbstractScrollArea):
    zoomChanged = pyqtSignal(float)
    cursorMoved = pyqtSignal(object)   # QPoint (image coords) or None
    viewChanged = pyqtSignal()

    def __init__(self, doc, ctx, parent=None):
        super().__init__(parent)
        self.doc, self.ctx = doc, ctx
        self.zoom = 1.0
        self._checker = QBrush(_checker())
        self._pan_from = None
        self._space = False
        self._auto_fit = True   # keep re-fitting on resize until the user zooms
        self.mouse_view = None       # last mouse position in view coords
        self._ant_offset = 0.0
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        vp = self.viewport()
        vp.setMouseTracking(True)
        vp.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        vp.setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        doc.changed.connect(self._doc_changed)
        doc.sizeChanged.connect(self._size_changed)
        doc.selectionChanged.connect(self.viewport().update)
        self._ants = QTimer(self)
        self._ants.setInterval(110)
        self._ants.timeout.connect(self._tick_ants)
        self._ants.start()
        self.setAcceptDrops(False)

    # ----------------------------------------------------------- geometry
    def tool(self):
        if self._space or self._pan_from is not None:
            return self.ctx.tools.get("hand")
        return self.ctx.tool

    def origin(self):
        vw, vh = self.viewport().width(), self.viewport().height()
        iw, ih = self.doc.width * self.zoom, self.doc.height * self.zoom
        ox = (vw - iw) / 2 if iw <= vw else PAD - self.horizontalScrollBar().value()
        oy = (vh - ih) / 2 if ih <= vh else PAD - self.verticalScrollBar().value()
        return QPointF(math.floor(ox), math.floor(oy))

    def transform(self) -> QTransform:
        o = self.origin()
        return QTransform(self.zoom, 0, 0, self.zoom, o.x(), o.y())

    def img_to_view(self, pt: QPointF) -> QPointF:
        o = self.origin()
        return QPointF(o.x() + pt.x() * self.zoom, o.y() + pt.y() * self.zoom)

    def view_to_img(self, pt: QPointF) -> QPointF:
        o = self.origin()
        return QPointF((pt.x() - o.x()) / self.zoom, (pt.y() - o.y()) / self.zoom)

    def img_rect_to_view(self, r: QRectF) -> QRectF:
        return self.transform().mapRect(QRectF(r))

    def _update_scrollbars(self):
        vw, vh = self.viewport().width(), self.viewport().height()
        iw, ih = self.doc.width * self.zoom, self.doc.height * self.zoom
        for sb, content, view in ((self.horizontalScrollBar(), iw, vw), (self.verticalScrollBar(), ih, vh)):
            sb.blockSignals(True)
            if content <= view:
                sb.setRange(0, 0)
            else:
                sb.setRange(0, int(math.ceil(content + 2 * PAD - view)))
                sb.setPageStep(view)
                sb.setSingleStep(max(1, view // 20))
            sb.blockSignals(False)

    def set_zoom(self, z, anchor: QPointF = None, user=True):
        if user:
            self._auto_fit = False
        z = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], z))
        if anchor is None:
            anchor = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        img_pt = self.view_to_img(anchor)
        self.zoom = z
        self._update_scrollbars()
        for sb, ip, a in ((self.horizontalScrollBar(), img_pt.x(), anchor.x()),
                          (self.verticalScrollBar(), img_pt.y(), anchor.y())):
            if sb.maximum() > 0:
                sb.blockSignals(True)
                sb.setValue(int(round(PAD + ip * z - a)))
                sb.blockSignals(False)
        self.viewport().update()
        self.zoomChanged.emit(self.zoom)
        self.viewChanged.emit()

    def zoom_step(self, direction, anchor=None):
        z = self.zoom
        if direction > 0:
            nxt = [s for s in ZOOM_STEPS if s > z + 1e-6]
            self.set_zoom(nxt[0] if nxt else ZOOM_STEPS[-1], anchor)
        else:
            prv = [s for s in ZOOM_STEPS if s < z - 1e-6]
            self.set_zoom(prv[-1] if prv else ZOOM_STEPS[0], anchor)

    def fit_to_screen(self, user=True):
        vw, vh = self.viewport().width(), self.viewport().height()
        if vw < 10 or vh < 10:
            return
        z = min((vw - 48) / self.doc.width, (vh - 48) / self.doc.height)
        self.set_zoom(max(ZOOM_STEPS[0], z), user=user)

    def auto_zoom(self):
        """100% if the image fits, otherwise fit on screen (what a new/opened image starts at)."""
        vw, vh = self.viewport().width(), self.viewport().height()
        if self.doc.width > vw - 48 or self.doc.height > vh - 48:
            self.fit_to_screen(user=False)
        else:
            self.set_zoom(1.0, user=False)

    def actual_pixels(self):
        self.set_zoom(1.0)

    def center_on(self, img_pt: QPointF):
        cur = self.view_to_img(QPointF(self.viewport().width() / 2, self.viewport().height() / 2))
        self.pan_by(QPointF((cur.x() - img_pt.x()) * self.zoom, (cur.y() - img_pt.y()) * self.zoom))

    def pan_by(self, delta: QPointF):
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(int(h.value() - delta.x()))
        v.setValue(int(v.value() - delta.y()))

    def visible_image_rect(self) -> QRectF:
        tl = self.view_to_img(QPointF(0, 0))
        br = self.view_to_img(QPointF(self.viewport().width(), self.viewport().height()))
        return QRectF(tl, br).intersected(QRectF(self.doc.rect()))

    # ----------------------------------------------------------- slots
    def _scrolled(self):
        self.viewport().update()
        self.viewChanged.emit()

    def _size_changed(self):
        self.auto_zoom()
        self._update_scrollbars()
        self.viewport().update()
        self.viewChanged.emit()

    def _doc_changed(self, rect: QRect):
        if rect.isEmpty():
            self.viewport().update()
        else:
            self.viewport().update(self.img_rect_to_view(QRectF(rect)).toAlignedRect().adjusted(-2, -2, 2, 2))

    def _tick_ants(self):
        if self.doc.has_selection() or self.doc.floating or self.doc.editing_text is not None:
            self._ant_offset = (self._ant_offset + 1) % 8
            self.viewport().update()

    # ----------------------------------------------------------- painting
    def paintEvent(self, ev):
        p = QPainter(self.viewport())
        er = QRectF(ev.rect())
        p.fillRect(er, QColor(theme.PASTEBOARD))
        o = self.origin()
        z = self.zoom
        target = QRectF(o.x(), o.y(), self.doc.width * z, self.doc.height * z)

        # soft drop shadow
        p.setPen(Qt.PenStyle.NoPen)
        for i, a in ((6, 10), (4, 18), (2, 34), (1, 60)):
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRect(target.adjusted(-i, -i + 1, i, i + 1))

        vis = target.intersected(er)
        if not vis.isEmpty():
            p.setBrushOrigin(target.topLeft())
            p.fillRect(vis, self._checker)
            src = QRectF((vis.x() - o.x()) / z, (vis.y() - o.y()) / z, vis.width() / z, vis.height() / z)
            src = src.toAlignedRect().adjusted(-1, -1, 1, 1).intersected(self.doc.rect())
            p.save()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, z < 1)
            p.translate(o)
            p.scale(z, z)
            p.drawImage(QRectF(src), self.doc.composite(), QRectF(src))
            p.restore()

            if z >= 8:
                self._draw_pixel_grid(p, vis, o, z)

        tr = self.transform()
        if self.doc.has_selection():
            self._draw_ants(p, tr.map(self.doc.selection))

        tool = self.tool()
        if tool is not None:
            p.save()
            tool.paint_overlay(p, self)
            p.restore()
        for fn in list(getattr(self.ctx, "canvas_overlays", [])):   # extension overlays
            p.save()
            try:
                fn(p, self)
            except Exception as e:  # never let an extension break painting
                self.ctx.status.emit(f"Canvas overlay error: {e}")
            p.restore()
            if self.mouse_view is not None and getattr(tool, "brush_outline", False):
                self._draw_brush_cursor(p, tool)
        p.end()

    def _draw_pixel_grid(self, p, vis, o, z):
        pen = QPen(QColor(128, 128, 128, 70))
        pen.setCosmetic(True)
        p.setPen(pen)
        x0 = math.floor((vis.left() - o.x()) / z)
        x1 = math.ceil((vis.right() - o.x()) / z)
        y0 = math.floor((vis.top() - o.y()) / z)
        y1 = math.ceil((vis.bottom() - o.y()) / z)
        for x in range(x0, x1 + 1):
            vx = o.x() + x * z
            p.drawLine(QPointF(vx, vis.top()), QPointF(vx, vis.bottom()))
        for y in range(y0, y1 + 1):
            vy = o.y() + y * z
            p.drawLine(QPointF(vis.left(), vy), QPointF(vis.right(), vy))

    def _draw_ants(self, p, path: QPainterPath):
        p.setBrush(Qt.BrushStyle.NoBrush)
        white = QPen(QColor(255, 255, 255), 1)
        white.setCosmetic(True)
        p.setPen(white)
        p.drawPath(path)
        black = QPen(QColor(0, 0, 0), 1)
        black.setCosmetic(True)
        black.setDashPattern([4, 4])
        black.setDashOffset(self._ant_offset)
        p.setPen(black)
        p.drawPath(path)

    def _draw_brush_cursor(self, p, tool):
        size = max(1.0, tool.opts.get("size", 1)) * self.zoom
        c = self.mouse_view
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if size >= 5:
            for col, w in ((QColor(0, 0, 0, 160), 3), (QColor(255, 255, 255, 230), 1)):
                p.setPen(QPen(col, w))
                p.drawEllipse(c, size / 2, size / 2)
        # small cross-hair in the centre
        for col, w in ((QColor(0, 0, 0, 160), 3), (QColor(255, 255, 255, 230), 1)):
            p.setPen(QPen(col, w))
            p.drawLine(c + QPointF(-4, 0), c + QPointF(4, 0))
            p.drawLine(c + QPointF(0, -4), c + QPointF(0, 4))

    # ----------------------------------------------------------- input
    def refresh_cursor(self):
        tool = self.tool()
        if tool is None:
            return
        if self._pan_from is not None:
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.viewport().setCursor(tool.cursor(self))
        self.viewport().update()

    def _img_pos(self, ev) -> QPointF:
        return self.view_to_img(ev.position())

    def mousePressEvent(self, ev: QMouseEvent):
        self.setFocus()
        if ev.button() == Qt.MouseButton.MiddleButton or (
                ev.button() == Qt.MouseButton.LeftButton and (self._space or self.ctx.tool is self.ctx.tools.get("hand"))):
            self._pan_from = ev.position()
            self.refresh_cursor()
            return
        tool = self.tool()
        if tool is not None:
            if ev.button() == Qt.MouseButton.LeftButton and (ev.modifiers() & Qt.KeyboardModifier.AltModifier) \
                    and getattr(tool, "alt_picks", False):
                self._pick_color(self._img_pos(ev))
                return
            tool.press(self, self._img_pos(ev), ev)

    def mouseMoveEvent(self, ev: QMouseEvent):
        self.mouse_view = ev.position()
        ip = self._img_pos(ev)
        self.cursorMoved.emit(QPoint(math.floor(ip.x()), math.floor(ip.y())))
        if self._pan_from is not None:
            d = ev.position() - self._pan_from
            self._pan_from = ev.position()
            self.pan_by(d)
            return
        tool = self.tool()
        if tool is not None:
            if ev.buttons() & Qt.MouseButton.LeftButton and (ev.modifiers() & Qt.KeyboardModifier.AltModifier) \
                    and getattr(tool, "alt_picks", False) and not getattr(tool, "active", False):
                self._pick_color(ip)
                return
            tool.move(self, ip, ev)
        if getattr(tool, "brush_outline", False) or getattr(tool, "hover_overlay", False):
            self.viewport().update()

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if self._pan_from is not None and ev.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._pan_from = None
            self.refresh_cursor()
            return
        tool = self.tool()
        if tool is not None:
            tool.release(self, self._img_pos(ev), ev)

    def mouseDoubleClickEvent(self, ev):
        tool = self.tool()
        if tool is not None and hasattr(tool, "double_click"):
            tool.double_click(self, self._img_pos(ev), ev)
        else:
            self.mousePressEvent(ev)

    def leaveEvent(self, ev):
        self.mouse_view = None
        self.cursorMoved.emit(None)
        self.viewport().update()
        super().leaveEvent(ev)

    def wheelEvent(self, ev):
        mods = ev.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            dy = ev.angleDelta().y() or ev.angleDelta().x()
            if dy:
                self.zoom_step(1 if dy > 0 else -1, ev.position())
            ev.accept()
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            h = self.horizontalScrollBar()
            h.setValue(h.value() - ev.angleDelta().y())
            ev.accept()
            return
        super().wheelEvent(ev)

    def event(self, ev):
        # While typing on the canvas, letters must reach the Type tool instead of tool shortcuts.
        if ev.type() == QEvent.Type.ShortcutOverride:
            tool = self.ctx.tool
            if tool is not None and getattr(tool, "wants_key", None) and tool.wants_key(self, ev):
                ev.accept()
                return True
        return super().event(ev)

    def inputMethodEvent(self, ev):
        tool = self.ctx.tool
        if tool is not None and hasattr(tool, "input_method"):
            tool.input_method(self, ev)
            return
        super().inputMethodEvent(ev)

    def keyPressEvent(self, ev):
        tool = self.ctx.tool
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            if not getattr(tool, "active", False) and not getattr(tool, "captures_space", False):
                self._space = True
                self.refresh_cursor()
                return
        tool = self.tool()
        if tool is not None and tool.key_press(self, ev):
            return
        if self._opacity_key(ev):
            return
        super().keyPressEvent(ev)

    def _opacity_key(self, ev):
        """Photoshop: number keys set opacity (tool opacity for painting tools, else layer opacity).
        1 = 10% … 0 = 100%; two quick digits give an exact value (e.g. 4 then 5 = 45%)."""
        if ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier or not ev.text().isdigit():
            return False
        import time
        d = int(ev.text())
        now = time.monotonic()
        last = getattr(self, "_digit", None)
        if last is not None and now - last[1] < 0.6:
            value = last[0] * 10 + d
            self._digit = None
            value = 100 if value == 0 else value
        else:
            value = 100 if d == 0 else d * 10
            self._digit = (d, now)
        tool = self.ctx.tool
        if tool is not None and "opacity" in tool.opts and getattr(tool, "brush_outline", False):
            tool.set_opt("opacity", value)
            self.ctx.status.emit(f"{tool.title}: opacity {value}%")
        else:
            L = self.doc.active
            if L is not None and not L.background:
                self.doc.set_props(L, "Opacity Change", merge_key="opacity", opacity=value)
        return True

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat() and self._space:
            self._space = False
            self.refresh_cursor()
            return
        super().keyReleaseEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._viewport_resized()

    def viewportEvent(self, ev):
        if ev.type() == QEvent.Type.Resize:
            self._viewport_resized()
        return super().viewportEvent(ev)

    def _viewport_resized(self):
        self._update_scrollbars()
        if self._auto_fit and self.viewport().width() > 50:
            self.auto_zoom()
        self.viewChanged.emit()

    def _pick_color(self, ip: QPointF):
        x, y = math.floor(ip.x()), math.floor(ip.y())
        if self.doc.rect().contains(x, y):
            from . import imageops
            c = imageops.sample(self.doc.composite(), x, y, 1)
            if c.alpha() > 0:
                self.ctx.set_fg(c)
