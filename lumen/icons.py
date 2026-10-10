"""Vector icons drawn at runtime with QPainter (no image files needed)."""
import math
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize
from PyQt6.QtGui import (QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath,
                         QLinearGradient, QCursor, QFont, QBrush, QPolygonF, QIconEngine)

ICON_COLOR = QColor("#c9c9c9")      # kept for old extensions; real colours come from the theme
ICON_ACTIVE = QColor("#ffffff")
_cache = {}
_pm_cache = {}


def _pen(c, w=1.5):
    pen = QPen(c, w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _poly(*pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


# ---------------------------------------------------------------- drawings
# Each function draws into a 24x24 logical space using colour c.

def d_move(p, c):
    p.setPen(_pen(c, 1.6))
    p.drawLine(QPointF(12, 3), QPointF(12, 21))
    p.drawLine(QPointF(3, 12), QPointF(21, 12))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for poly in (_poly((12, 1.5), (9, 5.5), (15, 5.5)), _poly((12, 22.5), (9, 18.5), (15, 18.5)),
                 _poly((1.5, 12), (5.5, 9), (5.5, 15)), _poly((22.5, 12), (18.5, 9), (18.5, 15))):
        p.drawPolygon(poly)


def d_marquee_rect(p, c):
    pen = _pen(c, 1.5)
    pen.setDashPattern([2.0, 1.6])
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)
    p.drawRect(QRectF(4, 5, 16, 14))


def d_marquee_ellipse(p, c):
    pen = _pen(c, 1.5)
    pen.setDashPattern([2.0, 1.6])
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)
    p.drawEllipse(QRectF(3.5, 5, 17, 14))


def d_lasso(p, c):
    p.setPen(_pen(c, 1.5))
    p.drawEllipse(QRectF(4, 3.5, 17, 11))
    path = QPainterPath(QPointF(8, 13.5))
    path.cubicTo(QPointF(5, 16), QPointF(9, 18), QPointF(7, 21))
    p.drawPath(path)
    p.setBrush(c)
    p.drawEllipse(QPointF(7.5, 14.5), 1.6, 1.6)


def d_crop(p, c):
    p.setPen(_pen(c, 1.8))
    p.drawPolyline(_poly((7, 2.5), (7, 17), (21.5, 17)))
    p.drawPolyline(_poly((2.5, 7), (17, 7), (17, 21.5)))


def d_eyedropper(p, c):
    p.save()
    p.translate(12, 12)
    p.rotate(45)
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(-2, -3, 4, 13), 1, 1)          # glass tube
    p.drawLine(QPointF(0, 10), QPointF(0, 12.5))          # tip
    p.setBrush(c)
    p.drawRoundedRect(QRectF(-3.5, -6, 7, 3), 1, 1)       # collar
    p.drawEllipse(QRectF(-2.6, -11.5, 5.2, 6))            # bulb
    p.restore()


def d_brush(p, c):
    p.save()
    p.translate(12, 12)
    p.rotate(45)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(-1.6, -12, 3.2, 12), 1.5, 1.5)   # handle
    p.drawRect(QRectF(-2.3, -1, 4.6, 2.5))                    # ferrule
    path = QPainterPath(QPointF(-2.6, 2))
    path.cubicTo(QPointF(-3.5, 7), QPointF(-1, 10), QPointF(0, 12))
    path.cubicTo(QPointF(1, 10), QPointF(3.5, 7), QPointF(2.6, 2))
    path.closeSubpath()
    p.drawPath(path)
    p.restore()


def d_pencil(p, c):
    p.save()
    p.translate(12, 12)
    p.rotate(45)
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(_poly((-2.8, -11), (2.8, -11), (2.8, 5), (0, 11), (-2.8, 5)))
    p.drawLine(QPointF(-2.8, -7.5), QPointF(2.8, -7.5))
    p.setBrush(c)
    p.drawPolygon(_poly((-1.1, 8.3), (1.1, 8.3), (0, 11)))
    p.restore()


def d_eraser(p, c):
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(-9, -4.5, 18, 9), 1.5, 1.5)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(-9, -4.5, 7, 9), 1.5, 1.5)
    p.restore()
    p.setPen(_pen(c, 1.2))
    p.drawLine(QPointF(9, 21), QPointF(21, 21))


def d_bucket(p, c):
    p.save()
    p.translate(11, 12)
    p.rotate(-40)
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(-6, -5, 12, 12), 1.5, 1.5)
    p.drawArc(QRectF(-4, -10, 8, 9), 0, 180 * 16)
    p.restore()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    path = QPainterPath(QPointF(19.5, 12))
    path.cubicTo(QPointF(17, 16), QPointF(17.5, 19), QPointF(19.5, 19))
    path.cubicTo(QPointF(21.5, 19), QPointF(22, 16), QPointF(19.5, 12))
    p.drawPath(path)


def d_gradient(p, c):
    g = QLinearGradient(3, 0, 21, 0)
    g.setColorAt(0, c)
    t = QColor(c)
    t.setAlpha(0)
    g.setColorAt(1, t)
    p.setPen(_pen(c, 1.2))
    p.setBrush(QBrush(g))
    p.drawRect(QRectF(3, 6, 18, 12))


def d_text(p, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(4.5, 3.5, 15, 2.6))
    p.drawRect(QRectF(10.6, 3.5, 2.8, 17))
    p.drawRect(QRectF(8, 18.6, 8, 1.9))
    p.drawRect(QRectF(4.5, 3.5, 1.9, 4.5))
    p.drawRect(QRectF(17.6, 3.5, 1.9, 4.5))


def d_rect(p, c):
    p.setPen(_pen(c, 1.6))
    p.drawRect(QRectF(4, 5, 16, 14))


def d_ellipse(p, c):
    p.setPen(_pen(c, 1.6))
    p.drawEllipse(QRectF(3.5, 5, 17, 14))


def d_line(p, c):
    p.setPen(_pen(c, 1.8))
    p.drawLine(QPointF(4, 20), QPointF(20, 4))


def d_hand(p, c):
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    # four fingers
    xs = [7.0, 10.0, 13.0, 16.0]
    tops = [7.0, 4.0, 4.5, 7.0]
    path.moveTo(5.5, 13)
    for x, t in zip(xs, tops):
        path.lineTo(x - 1.4, t + 1.4)
        path.arcTo(QRectF(x - 1.4, t, 2.8, 2.8), 180, -180)
        path.lineTo(x + 1.4, 12)
    path.lineTo(17.4, 12)
    path.lineTo(19.5, 9.5)
    path.arcTo(QRectF(18.6, 8.2, 3, 3), 135, -180)
    path.lineTo(17.5, 17)
    path.cubicTo(QPointF(16, 20.5), QPointF(13, 21), QPointF(11, 21))
    path.cubicTo(QPointF(8, 21), QPointF(5.5, 19), QPointF(5.5, 15))
    path.closeSubpath()
    p.drawPath(path)


def d_zoom(p, c):
    p.setPen(_pen(c, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(10, 10), 6.5, 6.5)
    p.setPen(_pen(c, 2.6))
    p.drawLine(QPointF(15, 15), QPointF(20.5, 20.5))


def d_zoom_in(p, c):
    d_zoom(p, c)
    p.setPen(_pen(c, 1.4))
    p.drawLine(QPointF(7, 10), QPointF(13, 10))
    p.drawLine(QPointF(10, 7), QPointF(10, 13))


def d_zoom_out(p, c):
    d_zoom(p, c)
    p.setPen(_pen(c, 1.4))
    p.drawLine(QPointF(7, 10), QPointF(13, 10))


def d_swap(p, c):
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(6, 6))
    path.cubicTo(QPointF(14, 6), QPointF(18, 10), QPointF(18, 18))
    p.drawPath(path)
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(_poly((3, 6), (8, 2.5), (8, 9.5)))
    p.drawPolygon(_poly((18, 21), (14.5, 16), (21.5, 16)))


def d_default_colors(p, c):
    p.setPen(_pen(QColor("#9a9a9a"), 1))
    p.setBrush(QColor("white"))
    p.drawRect(QRectF(9, 9, 11, 11))
    p.setBrush(QColor("black"))
    p.drawRect(QRectF(4, 4, 11, 11))


def d_check(p, c):
    p.setPen(_pen(c, 2.2))
    p.drawPolyline(_poly((5, 12.5), (10, 17.5), (19.5, 6.5)))


def d_cancel(p, c):
    p.setPen(_pen(c, 2.0))
    p.drawLine(QPointF(6, 6), QPointF(18, 18))
    p.drawLine(QPointF(18, 6), QPointF(6, 18))


def d_link(p, c):
    p.setPen(_pen(c, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(8.5, 2.5, 7, 9.5), 3.5, 3.5)
    p.drawRoundedRect(QRectF(8.5, 12, 7, 9.5), 3.5, 3.5)
    p.drawLine(QPointF(12, 8), QPointF(12, 16))


def d_sel_new(p, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(5, 5, 14, 14))


def d_sel_add(p, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(3, 3, 11, 11))
    p.drawRect(QRectF(10, 10, 11, 11))


def d_sel_sub(p, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    path = QPainterPath()
    path.addRect(QRectF(3, 3, 12, 12))
    cut = QPainterPath()
    cut.addRect(QRectF(10, 10, 11, 11))
    p.drawPath(path.subtracted(cut))
    p.setPen(_pen(c, 1.1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(10.5, 10.5, 10, 10))


def d_sel_int(p, c):
    p.setPen(_pen(c, 1.1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(3.5, 3.5, 11, 11))
    p.drawRect(QRectF(9.5, 9.5, 11, 11))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(9.5, 9.5, 5, 5))


def d_new(p, c):
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(_poly((5, 3), (14, 3), (19, 8), (19, 21), (5, 21)))
    p.drawLine(QPointF(9, 13), QPointF(15, 13))
    p.drawLine(QPointF(12, 10), QPointF(12, 16))


def d_open(p, c):
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(_poly((3, 6), (9, 6), (11, 8), (21, 8), (21, 19), (3, 19)))


def d_plus(p, c):
    p.setPen(_pen(c, 1.6))
    p.drawLine(QPointF(12, 6), QPointF(12, 18))
    p.drawLine(QPointF(6, 12), QPointF(18, 12))


def d_trash(p, c):
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(5, 7), QPointF(19, 7))
    p.drawPolyline(_poly((9.5, 7), (9.5, 4.5), (14.5, 4.5), (14.5, 7)))
    p.drawPolygon(_poly((7, 7), (8, 20), (16, 20), (17, 7)))


def _align(p, c, mode):
    p.setPen(_pen(c, 1.6))
    for y, w in ((6, 16), (10, 10), (14, 16), (18, 10)):
        x = 4 if mode == 0 else 12 - w / 2 if mode == 1 else 20 - w
        p.drawLine(QPointF(x, y), QPointF(x + w, y))


def d_align_left(p, c):
    _align(p, c, 0)


def d_align_center(p, c):
    _align(p, c, 1)


def d_align_right(p, c):
    _align(p, c, 2)


def d_eye(p, c):
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(2.5, 12))
    path.cubicTo(QPointF(7, 5), QPointF(17, 5), QPointF(21.5, 12))
    path.cubicTo(QPointF(17, 19), QPointF(7, 19), QPointF(2.5, 12))
    p.drawPath(path)
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 12), 3, 3)


def d_lock(p, c):
    p.setPen(_pen(c, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(7.5, 3.5, 9, 10), 0, 180 * 16)
    p.drawLine(QPointF(7.5, 8.5), QPointF(7.5, 11))
    p.drawLine(QPointF(16.5, 8.5), QPointF(16.5, 11))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(5, 11, 14, 10), 1.5, 1.5)


def d_lock_alpha(p, c):
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(4, 4, 16, 16))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for x in range(2):
        for y in range(2):
            p.drawRect(QRectF(4 + x * 8 + (4 if y else 0), 4 + y * 8, 4, 4))
            p.drawRect(QRectF(4 + x * 8 + (0 if y else 4), 8 + y * 8, 4, 4))


def d_lock_pixels(p, c):
    p.setPen(_pen(c, 1.4))
    p.drawLine(QPointF(5, 19), QPointF(16, 8))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((15, 5), (19, 9), (21, 3)))


def d_lock_position(p, c):
    d_move(p, c)


def d_new_layer(p, c):
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
    p.drawLine(QPointF(12, 8), QPointF(12, 16))
    p.drawLine(QPointF(8, 12), QPointF(16, 12))


def d_layers(p, c):
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for dy in (0, 5):
        p.drawPolygon(_poly((12, 4 + dy), (21, 9 + dy), (12, 14 + dy), (3, 9 + dy)))


def d_globe(p, c):
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
    p.drawEllipse(QRectF(8, 3.5, 8, 17))
    p.drawLine(QPointF(3.5, 12), QPointF(20.5, 12))
    p.drawLine(QPointF(5, 7.5), QPointF(19, 7.5))
    p.drawLine(QPointF(5, 16.5), QPointF(19, 16.5))


def d_cutout(p, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c.red(), c.green(), c.blue(), 90))
    for x in range(3):
        for y in range(3):
            if (x + y) % 2 == 0:
                p.drawRect(QRectF(3 + x * 6, 3 + y * 6, 6, 6))
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 9), 3.5, 3.5)
    path = QPainterPath(QPointF(5.5, 21))
    path.cubicTo(QPointF(6, 14), QPointF(18, 14), QPointF(18.5, 21))
    path.closeSubpath()
    p.drawPath(path)


def d_wand(p, c):
    p.setPen(_pen(c, 2.0))
    p.drawLine(QPointF(4, 20), QPointF(14, 10))
    p.setPen(_pen(c, 1.3))
    for a, b in (((17, 3), (17, 7)), ((15, 5), (19, 5)), ((20, 9), (20, 12)), ((18.5, 10.5), (21.5, 10.5)),
                 ((11, 4), (11, 6)), ((10, 5), (12, 5))):
        p.drawLine(QPointF(*a), QPointF(*b))


def d_restore(p, c):
    d_brush(p, c)
    p.setPen(_pen(c, 1.4))
    p.drawLine(QPointF(17, 16), QPointF(23, 16))
    p.drawLine(QPointF(20, 13), QPointF(20, 19))


def d_convert(p, c):
    """Two arrows chasing each other (convert / batch)."""
    p.setPen(_pen(c, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(4, 4, 16, 16), 30 * 16, 150 * 16)
    p.drawArc(QRectF(4, 4, 16, 16), 210 * 16, 150 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((3.2, 9.8), (7.8, 10.6), (4.1, 14.2)))
    p.drawPolygon(_poly((20.8, 14.2), (16.2, 13.4), (19.9, 9.8)))


def d_film(p, c):
    """Film strip with a play triangle (video)."""
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3, 5, 18, 14), 2, 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for x in (5, 9, 13, 17):
        p.drawRect(QRectF(x, 6.6, 2, 1.6))
        p.drawRect(QRectF(x, 15.8, 2, 1.6))
    p.drawPolygon(_poly((10, 9.5), (15, 12), (10, 14.5)))


def _label_icon(p, c, text, size=6.6):
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 5, 19, 14), 3, 3)
    f = QFont("Segoe UI")
    f.setPixelSize(int(size * 10))
    f.setBold(True)
    path = QPainterPath()
    path.addText(0, 0, f, text)
    br = path.boundingRect()
    p.save()
    sc = min(15.0 / br.width(), 7.5 / br.height())
    p.translate(12 - br.center().x() * sc, 12 - br.center().y() * sc)
    p.scale(sc, sc)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(path)
    p.restore()


def d_gif(p, c):
    _label_icon(p, c, "GIF")


def d_webp(p, c):
    _label_icon(p, c, "WEBP")


def d_compress(p, c):
    """Arrows squeezing inward onto a picture (optimise)."""
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(7.5, 7.5, 9, 9), 1.5, 1.5)
    for (x1, y1, x2, y2) in ((2.5, 2.5, 6, 6), (21.5, 2.5, 18, 6), (2.5, 21.5, 6, 18), (21.5, 21.5, 18, 18)):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    for (x, y, dx, dy) in ((6, 6, -1, -1), (18, 6, 1, -1), (6, 18, -1, 1), (18, 18, 1, 1)):
        p.drawPolyline(_poly((x + 3 * dx, y), (x, y), (x, y + 3 * dy)))


def d_frame_grab(p, c):
    """A single frame lifted out of a film strip."""
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(2.5, 3, 11, 18))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for y in (5, 9, 13, 17):
        p.drawRect(QRectF(3.8, y, 1.6, 2))
    p.setPen(_pen(c, 1.6))
    p.setBrush(QColor(c.red(), c.green(), c.blue(), 60))
    p.drawRoundedRect(QRectF(9.5, 8, 12, 9), 1.5, 1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((12, 15.5), (15, 11.5), (17.2, 14), (18.4, 12.8), (20, 15.5)))


def d_grid(p, c):
    """Sprite sheet grid (flipbook)."""
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3, 3, 18, 18), 2, 2)
    p.drawLine(QPointF(9, 3), QPointF(9, 21))
    p.drawLine(QPointF(15, 3), QPointF(15, 21))
    p.drawLine(QPointF(3, 12), QPointF(21, 12))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for i, (x, y) in enumerate(((6, 7.5), (12, 7.5), (18, 7.5), (6, 16.5), (12, 16.5), (18, 16.5))):
        p.drawEllipse(QPointF(x, y + (-1 + (i % 3)) * 0.8), 1.3, 1.3)


def d_overlay(p, c):
    """A picture placed over another (overlay studio)."""
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 4, 14, 11), 1.5, 1.5)
    p.setBrush(QColor(c.red(), c.green(), c.blue(), 70))
    p.drawRoundedRect(QRectF(9, 10, 12.5, 10), 1.5, 1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(6.5, 8), 1.6, 1.6)


DRAWINGS = {k[2:]: v for k, v in dict(globals()).items() if k.startswith("d_")}


def _mode_color(mode, state):
    from . import theme
    c = theme.C
    if mode == QIcon.Mode.Disabled:
        return QColor(theme.mix(c["icon"], c["window"], 0.55))
    if mode in (QIcon.Mode.Active, QIcon.Mode.Selected) or state == QIcon.State.On:
        return QColor(c["text_strong"])
    return QColor(c["icon"])


class ThemedIconEngine(QIconEngine):
    """Draws a vector icon in the current theme's colours, so icons follow theme changes live."""

    def __init__(self, name, size=24):
        super().__init__()
        self.name = name
        self.size = size

    def clone(self):
        return ThemedIconEngine(self.name, self.size)

    def key(self):
        return "lumen-themed"

    def availableSizes(self, mode=QIcon.Mode.Normal, state=QIcon.State.Off):
        return [QSize(self.size, self.size)]

    def actualSize(self, size, mode, state):
        s = min(size.width(), size.height())
        return QSize(s, s)

    def _render(self, px, mode, state, scale=1.0):
        col = _mode_color(mode, state)
        key = (self.name, px, round(scale * 100), col.rgba())
        pm = _pm_cache.get(key)
        if pm is None:
            pm = pixmap(self.name, px, col, scale)
            if len(_pm_cache) > 3000:
                _pm_cache.clear()
            _pm_cache[key] = pm
        return pm

    def pixmap(self, size, mode, state):
        return QPixmap(self._render(min(size.width(), size.height()), mode, state, 1.0))

    def scaledPixmap(self, size, mode, state, scale):
        # Qt 6 passes the logical size plus the screen scale: draw at size × scale for crisp HiDPI icons
        return QPixmap(self._render(min(size.width(), size.height()), mode, state, max(1.0, scale)))

    def paint(self, painter, rect, mode, state):
        scale = painter.device().devicePixelRatioF() if painter.device() else 1.0
        s = min(rect.width(), rect.height())
        pm = self._render(s, mode, state, scale)
        painter.drawPixmap(QRectF(rect.x() + (rect.width() - s) / 2, rect.y() + (rect.height() - s) / 2, s, s), pm,
                           QRectF(pm.rect()))


def icon(name, size=24) -> QIcon:
    key = (name, size)
    if key not in _cache:
        _cache[key] = QIcon(ThemedIconEngine(name, size))
    return _cache[key]


def theme_changed():
    """Called by theme.apply(): forget pixmaps drawn in the old colours."""
    _pm_cache.clear()


def pixmap(name, size=24, color=None, scale=2) -> QPixmap:
    if color is None:
        from . import theme
        color = theme.C["icon"]
    pm = QPixmap(int(size * scale), int(size * scale))
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    DRAWINGS[name](p, QColor(color))
    p.end()
    return pm


def tool_cursor(name, hotspot=(4, 20)) -> QCursor:
    """Cursor made from an icon with a dark outline so it shows on any background."""
    size, scale = 24, 1
    base = QPixmap(size + 4, size + 4)
    base.fill(Qt.GlobalColor.transparent)
    p = QPainter(base)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    dark = pixmap(name, size, QColor(0, 0, 0), scale)
    dark.setDevicePixelRatio(1)
    for dx, dy in ((1, 2), (3, 2), (2, 1), (2, 3), (1, 1), (3, 3), (1, 3), (3, 1)):
        p.drawPixmap(dx, dy, dark)
    light = pixmap(name, size, QColor(255, 255, 255), scale)
    light.setDevicePixelRatio(1)
    p.drawPixmap(2, 2, light)
    p.end()
    return QCursor(base, hotspot[0] + 2, hotspot[1] + 2)


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(app_pixmap(s))
    return ic


def app_pixmap(s=256) -> QPixmap:
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(0, 0, s, s).adjusted(s * 0.03, s * 0.03, -s * 0.03, -s * 0.03)
    p.setPen(QPen(QColor("#4fb3ff"), max(1.0, s * 0.035)))
    p.setBrush(QColor("#071a33"))
    p.drawRoundedRect(r, s * 0.2, s * 0.2)
    f = QFont("Segoe UI")
    f.setPixelSize(int(s * 0.46))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#4fb3ff"))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Lu")
    p.end()
    return pm
