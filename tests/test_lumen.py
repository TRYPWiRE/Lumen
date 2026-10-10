"""Automated tests for Lumen. Run:  python -m unittest discover tests -v
Drives the real window with synthetic mouse/keyboard events (works headless)."""
import os
import sys
import time
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _env  # noqa: F401  (must come before importing lumen)

from PyQt6.QtCore import Qt, QPointF, QPoint, QRectF, QRect, QEvent, QSettings
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainterPath, QKeyEvent, QGuiApplication, QPainter
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication([])

from lumen import theme, imageops
from lumen.mainwindow import MainWindow
from lumen import dialogs, tools as tools_mod

theme.apply(app)
ERRORS = []
sys.excepthook = lambda *a: ERRORS.append(a)

L = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton
NOMOD = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier


def rgb(c):
    return (c.red(), c.green(), c.blue())


def near(a, b, tol=3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = MainWindow()
        cls.w.resize(1400, 900)
        cls.w.show()
        app.processEvents()

    def setUp(self):
        ERRORS.clear()
        w = self.w
        while w.docs.count():
            w.docs.widget(0).doc.undo.setClean()
            w.close_tab(0)
        w.ctx.default_colors()
        for t in w.ctx.tools.values():
            t.opts = dict(t.defaults)
        self.cv = w.create_document(200, 150)
        app.processEvents()
        self.cv.set_zoom(2.0)
        app.processEvents()
        self.doc = self.cv.doc

    def tearDown(self):
        app.processEvents()
        if ERRORS:
            import traceback
            msg = "".join("".join(traceback.format_exception(*e)) for e in ERRORS)
            ERRORS.clear()
            self.fail("Unhandled exception in Qt callback:\n" + msg)

    # -- input helpers --------------------------------------------------
    def send(self, kind, pt, button=L, buttons=L, mods=NOMOD, cv=None):
        cv = cv or self.cv
        vp = cv.img_to_view(QPointF(*pt) if isinstance(pt, tuple) else pt)
        ev = QMouseEvent(kind, vp, QPointF(cv.viewport().mapToGlobal(vp.toPoint())), button, buttons, mods)
        QApplication.sendEvent(cv.viewport(), ev)

    def drag(self, *pts, mods=NOMOD, cv=None, steps=6):
        self.send(QEvent.Type.MouseButtonPress, pts[0], mods=mods, cv=cv)
        for a, b in zip(pts, pts[1:]):
            for i in range(1, steps + 1):
                t = i / steps
                self.send(QEvent.Type.MouseMove, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                          button=NONE, mods=mods, cv=cv)
        self.send(QEvent.Type.MouseButtonRelease, pts[-1], buttons=NONE, mods=mods, cv=cv)
        app.processEvents()

    def click(self, pt, mods=NOMOD):
        self.drag(pt, mods=mods, steps=1)

    def px(self, x, y):
        return self.doc.image.pixelColor(x, y)

    def tool(self, name, **opts):
        self.w.set_tool(name)
        t = self.w.ctx.tools[name]
        for k, v in opts.items():
            t.set_opt(k, v)
        return t

    def key(self, key, mods=NOMOD, widget=None):
        QTest.keyClick(widget or self.cv, key, mods)
        app.processEvents()


class TestPainting(Base):
    def test_brush_paints_undo_redo(self):
        self.w.ctx.set_fg(QColor(255, 0, 0))
        self.tool("brush", size=10, hardness=100, opacity=100)
        self.drag((20, 20), (150, 20))
        self.assertEqual(rgb(self.px(80, 20)), (255, 0, 0))
        self.assertEqual(rgb(self.px(80, 60)), (255, 255, 255))
        self.assertEqual(self.doc.undo.count(), 1)
        self.assertEqual(self.doc.undo.text(0), "Brush Tool")
        self.assertTrue(self.doc.modified())
        self.w.undo()
        self.assertEqual(rgb(self.px(80, 20)), (255, 255, 255))
        self.w.redo()
        self.assertEqual(rgb(self.px(80, 20)), (255, 0, 0))

    def test_brush_opacity_no_buildup(self):
        self.w.ctx.set_fg(QColor(0, 0, 0))
        self.tool("brush", size=12, hardness=100, opacity=50)
        self.drag((20, 40), (160, 40), (20, 40), (160, 40))
        c = rgb(self.px(90, 40))
        self.assertTrue(near(c, (128, 128, 128), 3), c)

    def test_soft_brush_falloff(self):
        self.tool("brush", size=40, hardness=0, opacity=100)
        self.click((100, 75))
        centre = self.px(100, 75).red()
        edge = self.px(100 + 15, 75).red()
        self.assertLess(centre, 30)
        self.assertGreater(edge, centre + 60)

    def test_pencil_hard_pixels(self):
        self.tool("pencil", size=1, opacity=100)
        self.drag((10.5, 10.5), (60.5, 10.5))
        self.assertEqual(rgb(self.px(30, 10)), (0, 0, 0))
        self.assertEqual(rgb(self.px(30, 11)), (255, 255, 255))
        self.assertEqual(rgb(self.px(30, 9)), (255, 255, 255))

    def test_shift_click_straight_line(self):
        self.tool("brush", size=6, hardness=100)
        self.click((20, 20))
        self.click((120, 120), mods=SHIFT)
        self.assertEqual(rgb(self.px(70, 70)), (0, 0, 0))
        self.assertEqual(self.doc.undo.count(), 2)

    def test_eraser_paints_background_on_opaque_doc(self):
        self.doc.fill(QColor(0, 0, 255))
        self.w.ctx.set_bg(QColor(0, 255, 0))
        self.tool("eraser", size=10, hardness=100)
        self.drag((20, 20), (100, 20))
        self.assertEqual(rgb(self.px(50, 20)), (0, 255, 0))

    def test_eraser_makes_transparent_on_transparent_doc(self):
        cv = self.w.create_document(100, 100, None)
        cv.doc.fill(QColor(255, 0, 0))
        self.cv, self.doc = cv, cv.doc
        app.processEvents()
        self.tool("eraser", size=10, hardness=100)
        self.drag((10, 50), (90, 50))
        self.assertEqual(self.px(50, 50).alpha(), 0)
        self.assertEqual(self.px(50, 10).alpha(), 255)

    def test_brush_cursor_is_visible(self):
        """The brush outline must show: a real cursor for normal sizes, a drawn outline for huge ones."""
        t = self.tool("brush", size=20)
        cur = self.cv.viewport().cursor()
        self.assertEqual(cur.shape(), Qt.CursorShape.BitmapCursor)
        self.assertGreaterEqual(cur.pixmap().width(), int(20 * self.cv.zoom))
        self.key(Qt.Key.Key_BracketRight)                       # resizing updates the cursor
        self.assertGreater(self.cv.viewport().cursor().pixmap().width(), cur.pixmap().width())
        t.set_opt("size", 400)
        self.send(QEvent.Type.MouseMove, (100, 75), button=NONE, buttons=NONE)
        img = self.cv.viewport().grab().toImage()
        c = self.cv.img_to_view(QPointF(100, 75))
        ring = img.pixelColor(int(c.x() + 400 * self.cv.zoom / 2), int(c.y()))
        self.assertNotEqual((ring.red(), ring.green(), ring.blue()), (255, 255, 255))
        self.tool("eraser", size=30)
        self.assertEqual(self.cv.viewport().cursor().shape(), Qt.CursorShape.BitmapCursor)

    def test_brush_size_shortcuts(self):
        t = self.tool("brush", size=20)
        self.key(Qt.Key.Key_BracketRight)
        self.assertEqual(t.opts["size"], 25)
        self.key(Qt.Key.Key_BracketLeft)
        self.key(Qt.Key.Key_BracketLeft)
        self.assertEqual(t.opts["size"], 15)

    def test_alt_click_picks_colour_while_brushing(self):
        self.doc.fill(QColor(10, 200, 30))
        self.tool("brush")
        self.click((50, 50), mods=ALT)
        self.assertEqual(rgb(self.w.ctx.fg), (10, 200, 30))
        self.assertEqual(self.doc.undo.count(), 1)  # only the fill, no brush stroke

    def test_painting_clipped_to_selection(self):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, 100, 150))
        self.doc.set_selection(p)
        self.tool("brush", size=10, hardness=100)
        self.drag((10, 50), (190, 50))
        self.assertEqual(rgb(self.px(50, 50)), (0, 0, 0))
        self.assertEqual(rgb(self.px(150, 50)), (255, 255, 255))


class TestFillsAndShapes(Base):
    def test_bucket_contiguous_and_tolerance(self):
        def paint(p):
            p.fillRect(QRect(50, 50, 60, 40), QColor(0, 0, 0))
            p.fillRect(QRect(60, 60, 40, 20), QColor(250, 250, 250))
        self.doc.apply_region("setup", self.doc.rect(), paint)
        self.w.ctx.set_fg(QColor(255, 0, 0))
        self.tool("bucket", tolerance=0, contiguous=True)
        self.click((10, 10))
        self.assertEqual(rgb(self.px(10, 10)), (255, 0, 0))
        self.assertEqual(rgb(self.px(80, 70)), (250, 250, 250))  # enclosed island untouched
        self.assertEqual(rgb(self.px(55, 55)), (0, 0, 0))
        self.w.undo()
        self.tool("bucket", tolerance=10, contiguous=False)
        self.click((10, 10))
        self.assertEqual(rgb(self.px(80, 70)), (255, 0, 0))  # non-contiguous + tolerance reaches island

    def test_bucket_large_image_speed(self):
        cv = self.w.create_document(2500, 2000)
        self.cv, self.doc = cv, cv.doc
        app.processEvents()
        import numpy as np
        rng = np.random.default_rng(1)
        arr = imageops.view(self.doc.image)
        noise = rng.random((2000, 2500)) < 0.02
        arr[noise] = (0, 0, 0, 255)
        t0 = time.time()
        tools_mod.fill_at(self.doc, 1, 1, QColor(255, 0, 0), 0, True)
        dt = time.time() - t0
        self.assertLess(dt, 8.0, f"flood fill too slow: {dt:.2f}s")

    def test_gradient(self):
        self.w.ctx.set_fg(QColor(0, 0, 0))
        self.w.ctx.set_bg(QColor(255, 255, 255))
        self.tool("gradient", kind=0, mode=0, opacity=100, reverse=False)
        self.drag((0, 75), (200, 75))
        self.assertLess(self.px(2, 10).red(), 10)
        self.assertGreater(self.px(197, 10).red(), 245)
        mid = self.px(100, 140).red()
        self.assertTrue(110 < mid < 145, mid)
        self.assertEqual(self.doc.undo.text(0), "Gradient")

    def test_rectangle_fill_and_stroke(self):
        self.w.ctx.set_fg(QColor(255, 0, 0))
        self.w.ctx.set_bg(QColor(0, 0, 255))
        self.tool("rect", fill=True, stroke=True, width=4)
        self.drag((40, 40), (120, 100))
        self.assertEqual(rgb(self.px(80, 70)), (255, 0, 0))
        self.assertEqual(rgb(self.px(41, 70)), (0, 0, 255))
        self.assertEqual(rgb(self.px(130, 70)), (255, 255, 255))

    def test_ellipse_and_square_constraint(self):
        self.tool("ellipse", fill=True, stroke=False)
        self.drag((20, 20), (120, 60), mods=SHIFT)  # shift => circle 100x100
        self.assertEqual(rgb(self.px(70, 70)), (0, 0, 0))
        self.assertEqual(rgb(self.px(22, 22)), (255, 255, 255))  # bounding corner stays clear

    def test_line(self):
        self.tool("line", width=3)
        self.drag((10, 140), (190, 140))
        self.assertEqual(rgb(self.px(100, 140)), (0, 0, 0))
        self.assertEqual(rgb(self.px(100, 130)), (255, 255, 255))

    def test_fill_menu_commands(self):
        self.w.ctx.set_fg(QColor(1, 2, 3))
        self.w.A["fill_fg"].trigger()
        self.assertEqual(rgb(self.px(5, 5)), (1, 2, 3))
        self.w.A["fill_bg"].trigger()
        self.assertEqual(rgb(self.px(5, 5)), (255, 255, 255))


class TestSelection(Base):
    def test_marquee_new_add_subtract_deselect(self):
        self.tool("marquee_rect", mode=0)
        self.drag((10, 10), (60, 50))
        self.assertEqual(self.doc.selection_bounds(), QRect(10, 10, 50, 40))
        self.drag((100, 10), (150, 50), mods=SHIFT)
        self.assertEqual(self.doc.selection_bounds(), QRect(10, 10, 140, 40))
        self.drag((0, 0), (200, 30), mods=ALT)
        self.assertEqual(self.doc.selection_bounds(), QRect(10, 30, 140, 20))
        self.click((190, 140))
        self.assertFalse(self.doc.has_selection())
        self.w.undo()
        self.assertTrue(self.doc.has_selection())

    def test_marquee_drag_inside_moves_outline(self):
        self.tool("marquee_rect")
        self.drag((10, 10), (60, 50))
        self.drag((30, 30), (60, 40))
        self.assertEqual(self.doc.selection_bounds(), QRect(40, 20, 50, 40))
        self.assertEqual(self.doc.undo.text(self.doc.undo.count() - 1), "Move Selection")

    def test_ellipse_marquee_and_lasso(self):
        self.tool("marquee_ellipse")
        self.drag((20, 20), (120, 120))
        self.assertTrue(self.doc.selection.contains(QPointF(70, 70)))
        self.assertFalse(self.doc.selection.contains(QPointF(22, 22)))
        self.tool("lasso")
        self.drag((150, 10), (190, 10), (190, 60), (150, 60))
        self.assertTrue(self.doc.selection.contains(QPointF(170, 30)))
        self.assertFalse(self.doc.selection.contains(QPointF(70, 70)))

    def test_select_all_inverse_deselect_actions(self):
        self.w.A["sel_all"].trigger()
        self.assertEqual(self.doc.selection_bounds(), QRect(0, 0, 200, 150))
        p = QPainterPath()
        p.addRect(QRectF(0, 0, 50, 150))
        self.doc.set_selection(p)
        self.w.A["sel_inv"].trigger()
        self.assertTrue(self.doc.selection.contains(QPointF(100, 50)))
        self.assertFalse(self.doc.selection.contains(QPointF(25, 50)))
        self.w.A["deselect"].trigger()
        self.assertFalse(self.doc.has_selection())

    def test_clear_and_cut_and_copy(self):
        self.doc.fill(QColor(0, 0, 0))
        p = QPainterPath()
        p.addRect(QRectF(10, 10, 20, 20))
        self.doc.set_selection(p)
        self.w.A["copy"].trigger()
        clip = QGuiApplication.clipboard().image()
        self.assertEqual((clip.width(), clip.height()), (20, 20))
        self.w.A["clear"].trigger()
        self.assertEqual(rgb(self.px(15, 15)), (255, 255, 255))
        self.assertEqual(rgb(self.px(35, 35)), (0, 0, 0))


class TestMoveAndPaste(Base):
    def test_move_selection_pixels_and_undo(self):
        self.doc.apply_region("setup", QRect(10, 10, 20, 20), lambda p: p.fillRect(QRect(10, 10, 20, 20), QColor(255, 0, 0)))
        p = QPainterPath()
        p.addRect(QRectF(10, 10, 20, 20))
        self.doc.set_selection(p)
        self.tool("move")
        self.drag((15, 15), (65, 15))
        self.assertIsNotNone(self.doc.floating)
        self.key(Qt.Key.Key_Return)
        self.assertIsNone(self.doc.floating)
        self.assertEqual(rgb(self.px(70, 20)), (255, 0, 0))
        self.assertEqual(rgb(self.px(15, 20)), (255, 255, 255))
        self.assertEqual(self.doc.selection_bounds(), QRect(60, 10, 20, 20))
        self.w.undo()
        self.assertEqual(rgb(self.px(15, 20)), (255, 0, 0))
        self.assertEqual(rgb(self.px(70, 20)), (255, 255, 255))
        self.assertEqual(self.doc.selection_bounds(), QRect(10, 10, 20, 20))

    def test_arrow_nudge_and_escape_cancels(self):
        self.doc.apply_region("setup", QRect(10, 10, 20, 20), lambda p: p.fillRect(QRect(10, 10, 20, 20), QColor(255, 0, 0)))
        p = QPainterPath()
        p.addRect(QRectF(10, 10, 20, 20))
        self.doc.set_selection(p)
        self.tool("move")
        self.key(Qt.Key.Key_Right, SHIFT)
        self.assertEqual(self.doc.floating.pos, QPoint(20, 10))
        self.key(Qt.Key.Key_Escape)
        self.assertIsNone(self.doc.floating)
        self.assertEqual(rgb(self.px(15, 15)), (255, 0, 0))

    def test_copy_paste_makes_new_layer(self):
        self.doc.apply_region("setup", QRect(0, 0, 10, 10), lambda p: p.fillRect(QRect(0, 0, 10, 10), QColor(0, 255, 0)))
        p = QPainterPath()
        p.addRect(QRectF(0, 0, 10, 10))
        self.doc.set_selection(p)
        self.w.copy()
        self.w.paste()
        self.assertEqual(len(self.doc.layers), 2)
        L = self.doc.active
        self.assertEqual(L.name, "Layer 1")
        self.assertEqual(self.w.ctx.tool.name, "move")
        self.assertEqual(L.offset, QPoint(0, 0))          # pasted in place over the selection
        self.w.A["deselect"].trigger()
        self.drag((5, 5), (105, 55))                       # Move tool drags the whole layer
        self.assertEqual(L.offset, QPoint(100, 50))
        self.assertEqual(rgb(self.px(105, 55)), (0, 255, 0))
        self.assertEqual(self.doc.undo.text(self.doc.undo.count() - 1), "Move")
        self.w.undo()
        self.assertEqual(L.offset, QPoint(0, 0))
        self.w.undo()
        self.w.undo()                                      # undo the paste itself
        self.assertEqual(len(self.doc.layers), 1)

    def test_copy_merged_vs_copy(self):
        self.doc.fill(QColor(255, 0, 0))
        L = self.doc.add_layer("Top", self._solid(20, 20, QColor(0, 0, 255)), QPoint(0, 0))
        self.doc.set_active(self.doc.layers[0])
        img = self.w.copy()
        self.assertEqual(rgb(img.pixelColor(5, 5)), (255, 0, 0))        # current layer only
        img = self.w.copy(merged=True)
        self.assertEqual(rgb(img.pixelColor(5, 5)), (0, 0, 255))        # everything visible

    def test_paste_without_document_creates_one(self):
        while self.w.docs.count():
            self.w.docs.widget(0).doc.undo.setClean()
            self.w.close_tab(0)
        img = QImage(64, 32, QImage.Format.Format_ARGB32)
        img.fill(QColor(200, 10, 10))
        QGuiApplication.clipboard().setImage(img)
        self.w.paste()
        d = self.w.current_doc()
        self.assertEqual((d.width, d.height), (64, 32))
        self.assertEqual(rgb(d.image.pixelColor(5, 5)), (200, 10, 10))

    def _solid(self, w, h, c):
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(c)
        return img


class TestImageOps(Base):
    def test_crop_tool(self):
        self.tool("crop")
        self.drag((20, 30), (120, 90))
        self.key(Qt.Key.Key_Return)
        self.assertEqual((self.doc.width, self.doc.height), (100, 60))
        self.w.undo()
        self.assertEqual((self.doc.width, self.doc.height), (200, 150))

    def test_crop_tool_escape(self):
        t = self.tool("crop")
        self.drag((20, 30), (120, 90))
        self.key(Qt.Key.Key_Escape)
        self.assertIsNone(t.rect)
        self.assertEqual((self.doc.width, self.doc.height), (200, 150))

    def test_crop_to_selection(self):
        p = QPainterPath()
        p.addRect(QRectF(5, 5, 50, 40))
        self.doc.set_selection(p)
        self.w.A["crop_sel"].trigger()
        self.assertEqual((self.doc.width, self.doc.height), (50, 40))

    def test_image_and_canvas_size(self):
        self.doc.apply_region("setup", QRect(0, 0, 10, 10), lambda p: p.fillRect(QRect(0, 0, 10, 10), QColor(255, 0, 0)))
        self.w.resize_image(self.doc, 400, 300, True)
        self.assertEqual((self.doc.width, self.doc.height), (400, 300))
        self.assertEqual(rgb(self.px(5, 5)), (255, 0, 0))
        self.w.resize_canvas(self.doc, 500, 300, (2, 1), 3)   # anchor right, extend black
        self.assertEqual(self.doc.width, 500)
        self.assertEqual(rgb(self.px(50, 150)), (0, 0, 0))
        self.assertEqual(rgb(self.px(105, 5)), (255, 0, 0))
        self.w.undo()
        self.w.undo()
        self.assertEqual((self.doc.width, self.doc.height), (200, 150))

    def test_rotate_and_flip(self):
        self.doc.apply_region("setup", QRect(0, 0, 10, 10), lambda p: p.fillRect(QRect(0, 0, 10, 10), QColor(255, 0, 0)))
        self.w.A["rot90"].trigger()
        self.assertEqual((self.doc.width, self.doc.height), (150, 200))
        self.assertEqual(rgb(self.px(145, 5)), (255, 0, 0))     # top-left -> top-right
        self.w.A["fliph"].trigger()
        self.assertEqual(rgb(self.px(5, 5)), (255, 0, 0))
        self.w.A["flipv"].trigger()
        self.assertEqual(rgb(self.px(5, 195)), (255, 0, 0))
        self.w.A["rot180"].trigger()
        self.assertEqual(rgb(self.px(145, 5)), (255, 0, 0))
        self.w.A["rot270"].trigger()
        self.assertEqual((self.doc.width, self.doc.height), (200, 150))

    def test_invert_and_desaturate_in_selection(self):
        self.doc.fill(QColor(200, 50, 0))
        p = QPainterPath()
        p.addRect(QRectF(0, 0, 100, 150))
        self.doc.set_selection(p)
        self.w.A["invert"].trigger()
        self.assertEqual(rgb(self.px(10, 10)), (55, 205, 255))
        self.assertEqual(rgb(self.px(150, 10)), (200, 50, 0))
        self.w.A["deselect"].trigger()
        self.w.A["desat"].trigger()
        r, g, b = rgb(self.px(150, 10))
        self.assertEqual(r, g)
        self.assertEqual(g, b)


class TestOtherTools(Base):
    def test_eyedropper(self):
        self.doc.fill(QColor(12, 34, 56))
        self.tool("eyedropper", sample=0)
        self.click((50, 50))
        self.assertEqual(rgb(self.w.ctx.fg), (12, 34, 56))
        self.doc.fill(QColor(100, 0, 0))
        self.click((50, 50), mods=ALT)
        self.assertEqual(rgb(self.w.ctx.bg), (100, 0, 0))
        self.assertEqual(rgb(self.w.ctx.fg), (12, 34, 56))

    def test_eyedropper_average(self):
        self.doc.apply_region("s", QRect(0, 0, 200, 150), lambda p: (p.fillRect(QRect(0, 0, 200, 150), QColor(0, 0, 0)),
                                                                     p.fillRect(QRect(50, 50, 1, 1), QColor(255, 255, 255))))
        self.tool("eyedropper", sample=1)
        self.click((50.5, 50.5))
        self.assertTrue(near(rgb(self.w.ctx.fg), (28, 28, 28), 2), rgb(self.w.ctx.fg))

    def setUp(self):
        super().setUp()
        if self._testMethodName.startswith("test_text") and not _env.fonts_available():
            self.skipTest("Qt found no fonts in the test environment, so text can't be drawn")

    def type_text(self, text):
        for ch in text:
            if ch == "\n":
                QTest.keyClick(self.cv, Qt.Key.Key_Return)
            else:
                QTest.keyClicks(self.cv, ch)
        app.processEvents()

    def dark_pixels(self, x0, y0, x1, y1):
        return sum(1 for x in range(x0, x1) for y in range(y0, y1) if self.px(x, y).red() < 128)

    def test_type_on_canvas_creates_type_layer(self):
        self.tool("text", size=40)
        self.click((20, 80))
        s = self.w.ctx.tools["text"].session
        self.assertIsNotNone(s)
        self.type_text("Hi B")                 # letters must not trigger tool shortcuts (B = brush)
        self.assertEqual(self.w.ctx.tool.name, "text")
        self.assertEqual(s.td.text, "Hi B")
        self.assertGreater(self.dark_pixels(20, 45, 110, 90), 50)   # visible live, on the image
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNone(self.w.ctx.tools["text"].session)
        self.assertEqual(len(self.doc.layers), 2)
        L = self.doc.active
        self.assertTrue(L.is_text)
        self.assertEqual(L.name, "Hi B")
        self.assertEqual(self.doc.undo.count(), 1)
        self.w.undo()
        self.assertEqual(len(self.doc.layers), 1)
        self.assertEqual(self.dark_pixels(20, 45, 110, 90), 0)
        self.w.redo()
        self.assertGreater(self.dark_pixels(20, 45, 110, 90), 50)

    def test_type_editing_keys(self):
        self.tool("text", size=30)
        self.click((10, 60))
        s = self.w.ctx.tools["text"].session
        self.type_text("abc\ndef")
        self.assertEqual(s.td.text, "abc\ndef")
        self.key(Qt.Key.Key_Backspace)
        self.key(Qt.Key.Key_Left)
        self.type_text("X")
        self.assertEqual(s.td.text, "abc\ndXe")
        self.key(Qt.Key.Key_Up)
        self.key(Qt.Key.Key_Home)
        self.type_text("Z")
        self.assertEqual(s.td.text, "Zabc\ndXe")
        self.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.type_text("new")
        self.assertEqual(s.td.text, "new")
        self.key(Qt.Key.Key_Escape)                 # Esc cancels a brand-new type layer
        self.assertEqual(len(self.doc.layers), 1)
        self.assertEqual(self.doc.undo.count(), 0)

    def test_edit_existing_type_layer_and_move_it(self):
        self.tool("text", size=40)
        self.click((20, 80))
        self.type_text("Hello")
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        L = self.doc.active
        # click on the existing text with the Type tool -> edits it (no new layer)
        self.click((40, 70))
        s = self.w.ctx.tools["text"].session
        self.assertIs(s.layer, L)
        self.key(Qt.Key.Key_End)
        self.type_text("!")
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(L.text.text, "Hello!")
        self.assertEqual(L.name, "Hello!")
        self.assertEqual(len(self.doc.layers), 2)
        self.w.undo()
        self.assertEqual(L.text.text, "Hello")
        self.w.redo()
        # Move tool moves the type layer and it stays editable
        self.tool("move")
        before = self.dark_pixels(20, 45, 150, 90)
        self.drag((40, 70), (40, 120))
        self.assertTrue(L.is_text)
        self.assertEqual(self.dark_pixels(20, 45, 150, 90), 0)
        self.assertGreater(self.dark_pixels(20, 95, 150, 140), before // 2)
        self.tool("text")
        self.click((40, 120))
        self.assertIs(self.w.ctx.tools["text"].session.layer, L)

    def test_options_bar_changes_selected_type_layer(self):
        t = self.tool("text", size=20)
        self.click((20, 80))
        self.type_text("Size")
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        L = self.doc.active
        w0 = L.rect().width()
        t._style_changed(size=60)                    # nothing being typed: applies to the type layer
        self.assertEqual(L.text.size, 60)
        self.assertGreater(L.rect().width(), w0 * 2)
        self.assertEqual(self.doc.undo.text(self.doc.undo.count() - 1), "Character Settings")
        t._style_changed(color=QColor(255, 0, 0))
        self.assertEqual(L.text.color.name(), "#ff0000")

    def test_click_outside_commits_and_switching_tools_commits(self):
        self.tool("text", size=30)
        self.click((10, 50))
        self.type_text("One")
        self.click((150, 140))                       # outside the text box: commit only
        self.assertIsNone(self.w.ctx.tools["text"].session)
        self.assertEqual(len(self.doc.layers), 2)
        self.click((150, 140))                       # next click starts a new one
        self.type_text("Two")
        self.w.set_tool("brush")                     # switching tools commits
        self.assertEqual(len(self.doc.layers), 3)

    def test_painting_on_type_layer_asks_to_rasterize(self):
        self.tool("text", size=30)
        self.click((10, 50))
        self.type_text("Ras")
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        L = self.doc.active
        asked = []
        self.doc.confirm = lambda kind, layer: asked.append(kind) or False
        self.tool("brush", size=10, hardness=100)
        self.drag((10, 140), (100, 140))
        self.assertEqual(asked, ["rasterize"])
        self.assertTrue(L.is_text)                   # declined: nothing happened
        self.doc.confirm = lambda kind, layer: True
        self.drag((10, 140), (100, 140))
        self.assertFalse(L.is_text)
        self.assertEqual(rgb(self.px(50, 140)), (0, 0, 0))

    def test_zoom_tool_and_view(self):
        self.tool("zoom", out=False)
        z = self.cv.zoom
        self.click((100, 75))
        self.assertGreater(self.cv.zoom, z)
        z = self.cv.zoom
        self.click((100, 75), mods=ALT)
        self.assertLess(self.cv.zoom, z)
        self.w.A["100"].trigger()
        self.assertEqual(self.cv.zoom, 1.0)
        self.w.A["zin"].trigger()
        self.assertEqual(self.cv.zoom, 1.5)
        self.cv.set_zoom(16)
        app.processEvents()
        self.cv.grab()  # paints pixel grid path
        self.w.A["fit"].trigger()
        self.assertLess(self.cv.zoom, 16)

    def test_zoom_keeps_point_under_cursor(self):
        self.cv.set_zoom(8.0)
        anchor = QPointF(self.cv.viewport().width() / 2 + 40, self.cv.viewport().height() / 2 - 30)
        before = self.cv.view_to_img(anchor)
        self.cv.zoom_step(1, anchor)
        after = self.cv.view_to_img(anchor)
        self.assertLess(abs(before.x() - after.x()), 1.0)
        self.assertLess(abs(before.y() - after.y()), 1.0)

    def test_hand_and_space_pan(self):
        self.cv.set_zoom(8)
        app.processEvents()
        h = self.cv.horizontalScrollBar()
        start = h.value()
        self.tool("hand")
        self.drag((100, 75), (90, 75))
        self.assertGreater(h.value(), start)
        self.tool("brush")
        v = h.value()
        QApplication.sendEvent(self.cv, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, NOMOD))
        self.drag((100, 75), (95, 75))
        QApplication.sendEvent(self.cv, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, NOMOD))
        self.assertNotEqual(h.value(), v)
        self.assertEqual(self.doc.undo.count(), 0)  # panning painted nothing

    def test_every_tool_survives_mouse_input(self):
        self.doc.add_layer("Second", None)
        for name in self.w.ctx.tools:
            self.tool(name)
            self.drag((30, 30), (80, 60), (120, 40))
            self.cv.grab()  # exercise overlay painting
            self.key(Qt.Key.Key_Escape)
            self.w.set_tool("brush")


class TestAppShell(Base):
    def test_tool_shortcuts(self):
        for key, name in ((Qt.Key.Key_E, "eraser"), (Qt.Key.Key_V, "move"), (Qt.Key.Key_M, "marquee_rect"),
                          (Qt.Key.Key_G, "bucket"), (Qt.Key.Key_T, "text"), (Qt.Key.Key_I, "eyedropper"),
                          (Qt.Key.Key_U, "rect"), (Qt.Key.Key_Z, "zoom"), (Qt.Key.Key_H, "hand"),
                          (Qt.Key.Key_C, "crop"), (Qt.Key.Key_L, "lasso"), (Qt.Key.Key_B, "brush")):
            self.key(key)
            self.assertEqual(self.w.ctx.tool.name, name)
        self.key(Qt.Key.Key_B, SHIFT)
        self.assertEqual(self.w.ctx.tool.name, "pencil")
        self.key(Qt.Key.Key_B)
        self.assertEqual(self.w.ctx.tool.name, "pencil")   # B returns to last-used tool of the group
        self.key(Qt.Key.Key_U, SHIFT)
        self.key(Qt.Key.Key_U, SHIFT)
        self.assertEqual(self.w.ctx.tool.name, "line")

    def test_colour_shortcuts(self):
        self.w.ctx.set_fg(QColor(1, 1, 1))
        self.w.ctx.set_bg(QColor(2, 2, 2))
        self.key(Qt.Key.Key_X)
        self.assertEqual(rgb(self.w.ctx.fg), (2, 2, 2))
        self.key(Qt.Key.Key_D)
        self.assertEqual(rgb(self.w.ctx.fg), (0, 0, 0))
        self.assertEqual(rgb(self.w.ctx.bg), (255, 255, 255))

    def test_undo_menu_text_and_keys(self):
        self.tool("brush")
        self.drag((10, 10), (50, 10))
        self.assertEqual(self.w.A["undo"].text(), "Undo Brush Tool")
        self.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.doc.undo.index(), 0)
        self.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | SHIFT)
        self.assertEqual(self.doc.undo.index(), 1)

    def test_history_panel_click_reverts(self):
        self.tool("brush")
        self.drag((10, 10), (50, 10))
        self.drag((10, 30), (50, 30))
        view = self.w.history.view
        view.setCurrentIndex(view.model().index(1, 0))   # row 0 is the "New Document" state
        app.processEvents()
        self.assertEqual(self.doc.undo.index(), 1)

    def test_save_open_png_roundtrip_with_alpha(self):
        cv = self.w.create_document(40, 30, None)
        d = cv.doc
        d.apply_region("s", QRect(0, 0, 10, 10), lambda p: p.fillRect(QRect(0, 0, 10, 10), QColor(255, 0, 0, 128)))
        path = os.path.join(tempfile.mkdtemp(), "out.png")
        orig = self.w._ask_path
        self.w._ask_path = lambda doc, title: path
        try:
            self.assertTrue(self.w.save_as(d))
        finally:
            self.w._ask_path = orig
        self.assertFalse(d.modified())
        self.assertEqual(d.name, "out.png")
        cv2 = self.w.open_path(path)
        self.assertIs(cv2, cv)   # already open -> just focuses the tab
        d.path = None
        cv3 = self.w.open_path(path)
        img = cv3.doc.image
        self.assertEqual((img.width(), img.height()), (40, 30))
        c = img.pixelColor(5, 5)
        self.assertEqual(c.alpha(), 128)
        self.assertTrue(near(rgb(c), (255, 0, 0), 2))
        self.assertEqual(img.pixelColor(20, 20).alpha(), 0)
        self.assertTrue(cv3.doc.transparent)

    def test_save_jpeg_and_webp(self):
        from lumen import mainwindow
        orig = mainwindow.QualityDialog.exec
        mainwindow.QualityDialog.exec = lambda dlg: 1
        try:
            folder = tempfile.mkdtemp()
            for ext in ("jpg", "webp", "bmp", "tif"):
                path = os.path.join(folder, "x." + ext)
                self.assertTrue(self.w._write(self.doc, path), ext)
                self.assertFalse(QImage(path).isNull(), ext)
        finally:
            mainwindow.QualityDialog.exec = orig

    def test_open_bad_file_warns(self):
        orig = QMessageBox.warning
        seen = []
        QMessageBox.warning = staticmethod(lambda *a, **k: seen.append(a))
        try:
            p = os.path.join(tempfile.mkdtemp(), "bad.png")
            with open(p, "wb") as fh:
                fh.write(b"not an image")
            self.assertIsNone(self.w.open_path(p))
        finally:
            QMessageBox.warning = orig
        self.assertEqual(len(seen), 1)

    def test_close_modified_prompts(self):
        self.tool("brush")
        self.drag((10, 10), (50, 10))
        answers = []
        orig = self.w._confirm_close
        self.w._confirm_close = lambda doc: answers.append(doc.modified()) or False
        try:
            self.assertFalse(self.w.close_tab(0))
            self.assertEqual(self.w.docs.count(), 1)
        finally:
            self.w._confirm_close = orig
        self.assertEqual(answers, [True])

    def test_welcome_page_when_no_docs(self):
        self.doc.undo.setClean()
        self.w.close_tab(0)
        self.assertIs(self.w.center_stack.currentWidget(), self.w.welcome)
        self.assertFalse(self.w.A["save"].isEnabled())
        self.w.create_document(10, 10)
        self.assertIs(self.w.center_stack.currentWidget(), self.w.docs)

    def test_multiple_documents_independent_history(self):
        self.tool("brush")
        self.drag((10, 10), (50, 10))
        cv2 = self.w.create_document(50, 50)
        app.processEvents()
        self.assertEqual(cv2.doc.undo.count(), 0)
        self.assertFalse(self.w.A["undo"].isEnabled())
        self.w.docs.setCurrentIndex(0)
        self.assertTrue(self.w.A["undo"].isEnabled())

    def test_dialogs_construct(self):
        nd = dialogs.NewDocumentDialog(self.w.ctx, self.w, (300, 200))
        nd.presets.setCurrentRow(2)   # row 0 = clipboard size, 1 = default
        name, w, h, dpi, fill = nd.values()
        self.assertEqual((w, h), (1280, 720))
        isd = dialogs.ImageSizeDialog(200, 100, self.w)
        isd.w.setValue(100)
        self.assertEqual(isd.values()[:2], (100, 50))
        isd.units.setCurrentIndex(1)
        isd.w.setValue(50)
        self.assertEqual(isd.values()[:2], (100, 50))
        csd = dialogs.CanvasSizeDialog(200, 100, self.w)
        csd.rel.setChecked(True)
        csd.w.setValue(20)
        self.assertEqual(csd.values()[:2], (220, 100))

    def test_colour_picker(self):
        from lumen.colors import ColorPicker
        p = ColorPicker(QColor("black"))
        got = []
        p.colorChanged.connect(got.append)
        p.hex.setText("3A7BD5")
        p.hex.editingFinished.emit()
        self.assertEqual(got[-1].name(), "#3a7bd5")
        p.spins["R"].setValue(255)
        self.assertEqual(got[-1].red(), 255)
        self.w.color_panel.picker.set_color(QColor(9, 99, 199), emit=True)
        self.assertEqual(rgb(self.w.ctx.fg), (9, 99, 199))

    def test_navigator_and_info(self):
        self.w.navigator.view.invalidate()
        self.w.navigator.grab()
        self.w.info.cursor(QPoint(5, 5))
        self.assertEqual(self.w.info.vals["R"].text(), "255")


class TestLayers(Base):
    def solid(self, w, h, c):
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(c)
        return img

    def test_new_document_has_background_and_new_layer(self):
        d = self.doc
        self.assertEqual([L.name for L in d.layers], ["Background"])
        self.assertTrue(d.layers[0].background)
        self.w.A["new_layer_quick"].trigger()
        self.assertEqual([L.name for L in d.layers], ["Background", "Layer 1"])
        self.assertIs(d.active, d.layers[1])
        self.w.undo()
        self.assertEqual(len(d.layers), 1)

    def test_paint_goes_to_active_layer_only(self):
        d = self.doc
        top = d.add_layer()
        self.tool("brush", size=10, hardness=100)
        self.drag((20, 20), (150, 20))
        self.assertEqual(rgb(self.px(80, 20)), (0, 0, 0))
        self.assertEqual(top.alpha_at(QPoint(80, 20)), 255)
        self.assertEqual(rgb(d.layers[0].image.pixelColor(80, 20)), (255, 255, 255))   # background untouched
        d.toggle_visible(top)
        self.assertEqual(rgb(self.px(80, 20)), (255, 255, 255))
        d.toggle_visible(top)
        self.assertEqual(rgb(self.px(80, 20)), (0, 0, 0))

    def test_eraser_on_layer_makes_transparent(self):
        d = self.doc
        L = d.add_layer("Red", self.solid(200, 150, QColor(255, 0, 0)))
        self.tool("eraser", size=10, hardness=100)
        self.drag((20, 50), (150, 50))
        self.assertEqual(L.alpha_at(QPoint(80, 50)), 0)
        self.assertEqual(rgb(self.px(80, 50)), (255, 255, 255))   # background shows through

    def test_opacity_fill_and_blend_modes(self):
        d = self.doc
        d.fill(QColor(200, 100, 50))
        L = d.add_layer("Top", self.solid(200, 150, QColor(100, 100, 100)))
        d.set_props(L, "Blending Change", blend="mul ")
        self.assertTrue(near(rgb(self.px(5, 5)), (78, 39, 20), 2))           # multiply
        d.set_props(L, "Blending Change", blend="scrn")
        self.assertTrue(near(rgb(self.px(5, 5)), (222, 161, 131), 2))        # screen
        d.set_props(L, "Blending Change", blend="norm", opacity=50)
        self.assertTrue(near(rgb(self.px(5, 5)), (150, 100, 75), 2))
        d.set_props(L, "Fill", opacity=100, fill=0)
        self.assertEqual(rgb(self.px(5, 5)), (200, 100, 50))
        d.set_props(L, "Fill", fill=100)
        from lumen.layers import BLEND_KEYS
        for key in BLEND_KEYS:                                              # every mode renders
            d.set_props(L, "Blend", blend=key)
            c = self.px(5, 5)
            self.assertEqual(c.alpha(), 255, key)
        d.set_props(L, "Blend", blend="lum ")                               # grey luminosity onto colour
        r, g, b = rgb(self.px(5, 5))
        self.assertTrue(abs((r * .3 + g * .59 + b * .11) - 100) < 3)

    def test_reorder_duplicate_delete_merge_flatten(self):
        d = self.doc
        a = d.add_layer("A", self.solid(50, 50, QColor(255, 0, 0)))
        b = d.add_layer("B", self.solid(50, 50, QColor(0, 0, 255)), QPoint(25, 0))
        self.assertEqual(rgb(self.px(30, 10)), (0, 0, 255))
        self.w.A["backward"].trigger()                       # Ctrl+[ : B below A
        self.assertEqual([L.name for L in d.layers], ["Background", "B", "A"])
        self.assertEqual(rgb(self.px(30, 10)), (255, 0, 0))
        self.w.A["backward"].trigger()                       # can't go below the Background
        self.assertEqual(d.layers[0].name, "Background")
        d.set_active(a)
        self.w.A["dup_layer"].trigger()
        self.assertEqual(d.active.name, "A copy")
        self.w.A["del_layer"].trigger()
        self.assertEqual(len(d.layers), 3)
        d.set_active(a)
        self.w.A["merge_down"].trigger()                     # A into B
        self.assertEqual([L.name for L in d.layers], ["Background", "B"])
        self.assertEqual(rgb(self.px(30, 10)), (255, 0, 0))
        self.assertEqual(rgb(self.px(60, 10)), (0, 0, 255))
        self.w.A["flatten"].trigger()
        self.assertEqual(len(d.layers), 1)
        self.assertTrue(d.layers[0].background)
        self.assertEqual(rgb(self.px(30, 10)), (255, 0, 0))
        for _ in range(5):
            self.w.undo()
        self.assertEqual([L.name for L in d.layers], ["Background", "A", "B"])

    def test_layer_via_copy_and_cut(self):
        d = self.doc
        d.fill(QColor(0, 200, 0))
        p = QPainterPath()
        p.addRect(QRectF(10, 10, 30, 20))
        d.set_selection(p)
        self.w.A["via_copy"].trigger()
        self.assertEqual(d.active.name, "Layer 1")
        self.assertEqual(d.active.rect(), QRect(10, 10, 30, 20))
        d.set_active(d.layers[0])
        d.set_selection(p)
        self.w.A["via_cut"].trigger()
        self.assertEqual(rgb(d.layers[0].image.pixelColor(15, 15)), (255, 255, 255))   # cut leaves bg colour
        self.assertEqual(rgb(self.px(15, 15)), (0, 200, 0))

    def test_background_rules_and_conversion(self):
        d = self.doc
        bg = d.layers[0]
        self.tool("move")
        self.drag((50, 50), (90, 50))
        self.assertEqual(bg.offset, QPoint(0, 0))                    # locked position
        self.assertEqual(d.undo.count(), 0)
        d.background_to_layer()
        self.assertFalse(bg.background)
        self.assertEqual(bg.name, "Layer 0")
        self.drag((50, 50), (90, 50))
        self.assertEqual(bg.offset, QPoint(40, 0))
        self.assertEqual(self.px(10, 10).alpha(), 0)                 # transparency revealed
        self.tool("eraser", size=10)
        self.drag((100, 100), (120, 100))
        self.assertEqual(self.px(110, 100).alpha(), 0)

    def test_locks(self):
        d = self.doc
        L = d.add_layer("Shape", self.solid(40, 40, QColor(255, 0, 0)), QPoint(10, 10))
        d.set_props(L, "Lock", lock_alpha=True)
        self.tool("brush", size=30, hardness=100)
        self.drag((5, 30), (100, 30))
        self.assertEqual(rgb(self.px(30, 30)), (0, 0, 0))            # painted inside existing pixels
        self.assertEqual(L.alpha_at(QPoint(70, 30)), 0)              # but not outside them
        d.set_props(L, "Lock", lock_alpha=False, lock_pixels=True)
        n = d.undo.count()
        self.drag((5, 40), (100, 40))
        self.assertEqual(d.undo.count(), n)
        d.set_props(L, "Lock", lock_pixels=False, lock_position=True)
        self.tool("move")
        before = QPoint(L.offset)
        self.drag((30, 30), (60, 60))
        self.assertEqual(L.offset, before)

    def test_auto_select_and_ctrl_click_pick_layer(self):
        d = self.doc
        a = d.add_layer("A", self.solid(40, 40, QColor(255, 0, 0)), QPoint(0, 0))
        b = d.add_layer("B", self.solid(40, 40, QColor(0, 0, 255)), QPoint(100, 100))
        self.tool("move", auto_select=False)
        self.drag((10, 10), (20, 10), mods=Qt.KeyboardModifier.ControlModifier)
        self.assertIs(d.active, a)
        self.assertEqual(a.offset, QPoint(10, 0))
        self.tool("move", auto_select=True)
        self.drag((110, 110), (110, 120))
        self.assertIs(d.active, b)
        self.assertEqual(b.offset, QPoint(100, 110))

    def test_number_keys_set_opacity(self):
        d = self.doc
        L = d.add_layer("A", self.solid(40, 40, QColor(255, 0, 0)))
        self.tool("move")
        self.key(Qt.Key.Key_5)
        self.assertEqual(L.opacity, 50)
        b = self.tool("brush")
        self.cv._digit = None
        self.key(Qt.Key.Key_3)
        self.assertEqual(b.opts["opacity"], 30)

    def test_load_selection_from_layer(self):
        d = self.doc
        L = d.add_layer("A", self.solid(30, 20, QColor(255, 0, 0)), QPoint(15, 25))
        d.select_layer_pixels(L)
        self.assertEqual(d.selection_bounds(), QRect(15, 25, 30, 20))

    def test_filters_and_fill_apply_to_active_layer(self):
        d = self.doc
        L = d.add_layer("A", self.solid(200, 150, QColor(10, 20, 30)))
        self.w.A["invert"].trigger()
        self.assertEqual(rgb(L.image.pixelColor(5, 5)), (245, 235, 225))
        self.assertEqual(rgb(d.layers[0].image.pixelColor(5, 5)), (255, 255, 255))

    def test_crop_resize_rotate_keep_layers(self):
        d = self.doc
        a = d.add_layer("A", self.solid(20, 20, QColor(255, 0, 0)), QPoint(100, 50))
        self.w.resize_canvas(d, 300, 150, (0, 1), 2)                 # anchor left
        self.assertEqual(len(d.layers), 2)
        self.assertEqual(a.rect(), QRect(100, 50, 20, 20)) if a in d.layers else None
        self.assertEqual(rgb(self.px(110, 60)), (255, 0, 0))
        self.w.resize_image(d, 150, 75, True)
        self.assertEqual((d.width, d.height), (150, 75))
        self.assertTrue(near(rgb(self.px(55, 30)), (255, 0, 0), 3))
        self.w.A["rot90"].trigger()
        self.assertEqual((d.width, d.height), (75, 150))
        self.assertEqual(len(d.layers), 2)
        self.assertTrue(near(rgb(self.px(75 - 30, 55)), (255, 0, 0), 3))
        crop = QRect(30, 40, 30, 30)
        from lumen.tools import crop_document
        crop_document(d, crop)
        self.assertEqual((d.width, d.height), (30, 30))
        for _ in range(4):
            self.w.undo()
        self.assertEqual((d.width, d.height), (200, 150))
        self.assertEqual(d.layers[1].rect(), QRect(100, 50, 20, 20))

    def test_shape_tool_makes_new_layer(self):
        self.tool("rect", fill=True, stroke=False, pixels=0)
        self.drag((20, 20), (80, 60))
        self.assertEqual(len(self.doc.layers), 2)
        self.assertEqual(self.doc.active.name, "Rectangle 1")
        self.tool("rect", fill=True, stroke=False, pixels=1)
        self.drag((100, 20), (150, 60))
        self.assertEqual(len(self.doc.layers), 2)

    def test_layers_panel_interactions(self):
        d = self.doc
        a = d.add_layer("A", self.solid(40, 40, QColor(255, 0, 0)))
        b = d.add_layer("B", self.solid(40, 40, QColor(0, 0, 255)))
        lst = self.w.layers_panel.list
        lst.resize(260, 400)
        from lumen.layerspanel import ROW_H, EYE_W
        def click(row, x=120, mods=Qt.KeyboardModifier.NoModifier, button=L):
            pos = QPointF(x, row * ROW_H + ROW_H / 2)
            QApplication.sendEvent(lst, QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, button, button, mods))
            QApplication.sendEvent(lst, QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos, button, NONE, mods))
        self.assertEqual([x.name for x in lst.rows()], ["B", "A", "Background"])
        click(1)
        self.assertIs(d.active, a)
        click(0, x=EYE_W // 2)
        self.assertFalse(b.visible)
        # drag A above B
        start = QPointF(120, 1 * ROW_H + 10)
        end = QPointF(120, 0 * ROW_H + 2)
        QApplication.sendEvent(lst, QMouseEvent(QEvent.Type.MouseButtonPress, start, start, L, L, NOMOD))
        QApplication.sendEvent(lst, QMouseEvent(QEvent.Type.MouseMove, end, end, NONE, L, NOMOD))
        QApplication.sendEvent(lst, QMouseEvent(QEvent.Type.MouseButtonRelease, end, end, L, NONE, NOMOD))
        self.assertEqual([x.name for x in d.layers], ["Background", "B", "A"])
        # opacity/blend from the panel
        self.w.layers_panel.opacity.setValue(40)
        self.assertEqual(a.opacity, 40)
        self.w.layers_panel.opacity.setValue(30)
        self.assertEqual(d.undo.text(d.undo.count() - 1), "Opacity Change")
        n = d.undo.count()
        self.w.layers_panel.opacity.setValue(20)
        self.assertEqual(d.undo.count(), n)                            # slider drags merge into one step
        i = self.w.layers_panel.blend.findData("mul ")
        self.w.layers_panel.blend.setCurrentIndex(i)
        self.w.layers_panel._blend_chosen(i)
        self.assertEqual(a.blend, "mul ")
        # rename
        lst.start_rename(0, a)
        lst._editor[0].setText("Renamed")
        lst._close_editor(True)
        self.assertEqual(a.name, "Renamed")
        lst.grab()

    def test_psd_roundtrip_keeps_layers_and_text(self):
        d = self.doc
        d.fill(QColor(240, 240, 240))
        a = d.add_layer("Red", self.solid(60, 40, QColor(255, 0, 0, 160)), QPoint(30, 20))
        d.set_props(a, "x", blend="mul ", opacity=80)
        if _env.fonts_available():
            self.tool("text", size=30)
            self.click((20, 120))
            QTest.keyClicks(self.cv, "PSD")
            self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        path = os.path.join(tempfile.mkdtemp(), "layers.psd")
        orig = self.w._ask_path
        self.w._ask_path = lambda doc, title: path
        try:
            self.assertTrue(self.w.save_as(d))
        finally:
            self.w._ask_path = orig
        d.path = None
        cv2 = self.w.open_path(path)
        d2 = cv2.doc
        self.assertEqual([L.name for L in d2.layers], [L.name for L in d.layers])
        self.assertTrue(d2.layers[0].background)
        self.assertEqual(d2.layers[1].blend, "mul ")
        self.assertEqual(d2.layers[1].opacity, 80)
        if _env.fonts_available():
            self.assertTrue(d2.layers[2].is_text)
            self.assertEqual(d2.layers[2].text.text, "PSD")
        import numpy as np
        diff = np.abs(imageops.straight_array(d.composite()).astype(int)
                      - imageops.straight_array(d2.composite()).astype(int)).max()
        self.assertLessEqual(diff, 1)

    def test_save_layered_as_png_goes_to_save_as_psd(self):
        d = self.doc
        d.add_layer("A", self.solid(10, 10, QColor(255, 0, 0)))
        d.path = os.path.join(tempfile.mkdtemp(), "x.png")
        asked = []
        orig = self.w.save_as
        self.w.save_as = lambda doc=None: asked.append(1) or False
        try:
            self.w.save(d)
        finally:
            self.w.save_as = orig
        self.assertEqual(asked, [1])


class TestViewFit(Base):
    def test_large_image_opens_fitted(self):
        cv = self.w.create_document(5000, 4000)
        app.processEvents()
        vw, vh = cv.viewport().width(), cv.viewport().height()
        self.assertLessEqual(cv.doc.width * cv.zoom, vw)
        self.assertLessEqual(cv.doc.height * cv.zoom, vh)
        self.assertGreater(cv.doc.height * cv.zoom, vh * 0.8)


class TestPerformance(Base):
    def test_stroke_speed_with_many_layers(self):
        cv = self.w.create_document(3000, 2000)
        self.cv, self.doc = cv, cv.doc
        app.processEvents()
        for i in range(6):
            img = QImage(3000, 2000, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor(i * 30, 100, 200, 60))
            L = self.doc.add_layer(f"L{i}", img)
            self.doc.set_props(L, "b", blend=["norm", "mul ", "scrn", "over", "sLit", "colr"][i])
        self.tool("brush", size=80, hardness=0)
        t0 = time.time()
        self.drag((100, 100), (2900, 1900), steps=40)
        dt = time.time() - t0
        self.assertLess(dt, 12.0, f"layered stroke too slow: {dt:.2f}s")

    def test_big_brush_stroke_speed(self):
        cv = self.w.create_document(4000, 3000)
        self.cv, self.doc = cv, cv.doc
        app.processEvents()
        self.tool("brush", size=200, hardness=0)
        t0 = time.time()
        self.drag((100, 100), (3900, 2900), steps=60)
        dt = time.time() - t0
        self.assertLess(dt, 6.0, f"brush stroke too slow: {dt:.2f}s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
