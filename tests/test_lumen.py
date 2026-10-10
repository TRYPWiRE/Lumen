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

    def test_copy_paste_commit(self):
        self.doc.apply_region("setup", QRect(0, 0, 10, 10), lambda p: p.fillRect(QRect(0, 0, 10, 10), QColor(0, 255, 0)))
        p = QPainterPath()
        p.addRect(QRectF(0, 0, 10, 10))
        self.doc.set_selection(p)
        self.w.copy()
        self.w.paste()
        self.assertIsNotNone(self.doc.floating)
        self.assertEqual(self.w.ctx.tool.name, "move")
        self.drag((100, 75), (150, 75))
        self.w.A["deselect"].trigger()     # deselect commits the paste
        self.assertIsNone(self.doc.floating)
        self.assertEqual(self.doc.undo.text(self.doc.undo.count() - 2), "Paste")
        # pasted block should now be somewhere right of centre
        found = any(rgb(self.px(x, 75)) == (0, 255, 0) for x in range(130, 170))
        self.assertTrue(found)

    def test_undo_while_pasting_cancels_paste(self):
        img = QImage(10, 10, QImage.Format.Format_ARGB32)
        img.fill(QColor(9, 9, 9))
        QGuiApplication.clipboard().setImage(img)
        n = self.doc.undo.count()
        self.w.paste()
        self.w.A["undo"].trigger()
        self.assertIsNone(self.doc.floating)
        self.assertEqual(self.doc.undo.count(), n)
        self.assertEqual(rgb(self.px(100, 75)), (255, 255, 255))

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
        d.commit_floating()
        self.assertEqual(rgb(d.image.pixelColor(5, 5)), (200, 10, 10))


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

    def test_text_commit_and_undo(self):
        t = self.tool("text", size=40)
        t.commit_text(self.doc, QPointF(20, 80), "Hi")
        dark = sum(1 for x in range(20, 80) for y in range(40, 85) if self.px(x, y).red() < 128)
        self.assertGreater(dark, 50)
        self.assertTrue(self.doc.undo.text(0).startswith("Type"))
        self.w.undo()
        dark = sum(1 for x in range(20, 80) for y in range(40, 85) if self.px(x, y).red() < 128)
        self.assertEqual(dark, 0)

    def test_text_tool_click_with_dialog(self):
        orig = dialogs.TextDialog.exec

        def fake_exec(dlg):
            dlg.edit.setPlainText("Lumen")
            return 1
        dialogs.TextDialog.exec = fake_exec
        try:
            self.tool("text", size=30)
            self.click((10, 60))
        finally:
            dialogs.TextDialog.exec = orig
        self.assertIsNone(self.doc.preview)
        self.assertEqual(self.doc.undo.count(), 1)

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
        orig = dialogs.TextDialog.exec
        dialogs.TextDialog.exec = lambda dlg: 0
        try:
            for name in self.w.ctx.tools:
                self.tool(name)
                self.drag((30, 30), (80, 60), (120, 40))
                self.cv.grab()  # exercise overlay painting
                self.key(Qt.Key.Key_Escape)
                self.w.set_tool("brush")
        finally:
            dialogs.TextDialog.exec = orig


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


class TestViewFit(Base):
    def test_large_image_opens_fitted(self):
        cv = self.w.create_document(5000, 4000)
        app.processEvents()
        vw, vh = cv.viewport().width(), cv.viewport().height()
        self.assertLessEqual(cv.doc.width * cv.zoom, vw)
        self.assertLessEqual(cv.doc.height * cv.zoom, vh)
        self.assertGreater(cv.doc.height * cv.zoom, vh * 0.8)


class TestPerformance(Base):
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
