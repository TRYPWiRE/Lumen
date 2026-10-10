"""Tests for workspaces, runtime packs and the bundled-for-download extensions."""
import functools
import http.server
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _env  # noqa: F401

import numpy as np
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(["lumen-tests"])

from lumen import theme, imageops, runtimes, net  # noqa: E402
from lumen import mainwindow as mw_mod  # noqa: E402
from lumen.updates import Manifest  # noqa: E402
from lumen.extensions import ui as ext_ui  # noqa: E402

_MISSING = object()
from lumen.runtimes_platform import platform_key  # noqa: E402
import build_extensions  # noqa: E402

theme.apply(app)
ERRORS = []
sys.excepthook = lambda *a: ERRORS.append(a)
EXT = os.path.join(ROOT, "extensions")


def wait(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


def rgb(c):
    return (c.red(), c.green(), c.blue())


def zip_ext(name, dest_dir):
    path = os.path.join(dest_dir, name + ".zip")
    build_extensions.zip_folder(os.path.join(EXT, name), path)
    return path


def load_pkg(name):
    """Import an extension folder as a package (without registering it)."""
    mod_name = "pkgtest_" + name.replace("-", "_")
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(EXT, name, "__init__.py"),
                                                  submodule_search_locations=[os.path.join(EXT, name)])
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Server:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="srv-")
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=self.root))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def fake_runtime(server, rid, module, body="VALUE = 42\n", qt=None, provides=None):
    """A tiny runtime pack exposing `module`, served by `server`. Returns the manifest entry."""
    pack = tempfile.mkdtemp()
    os.makedirs(os.path.join(pack, "lib", module))
    with open(os.path.join(pack, "lib", module, "__init__.py"), "w") as f:
        f.write(body)
    meta = {"id": rid, "name": f"Test {rid}", "version": "1.0", "provides": provides or [module],
            "python_paths": ["lib"]}
    if qt:
        meta["qt"] = qt
    with open(os.path.join(pack, "runtime.json"), "w") as f:
        json.dump(meta, f)
    zpath = os.path.join(server.root, f"{rid}.zip")
    with zipfile.ZipFile(zpath, "w") as z:
        for base, _, files in os.walk(pack):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, pack))
    return {"name": f"Test {rid}", "version": "1.0", "url": f"{server.base}/{rid}.zip",
            "sha256": build_extensions.sha256(zpath), "size": os.path.getsize(zpath)}


class Base(unittest.TestCase):
    def setUp(self):
        ERRORS.clear()
        self.data = tempfile.mkdtemp(prefix="lumen-data-")
        os.environ["LUMEN_DATA_DIR"] = self.data
        os.environ["LUMEN_SETTINGS"] = os.path.join(self.data, "settings.ini")
        self.tmp = tempfile.mkdtemp()
        self.boxes = []
        self._patches = []
        self.patch(QMessageBox, "warning", staticmethod(lambda *a, **k: self.boxes.append(a)))
        self.patch(QMessageBox, "information", staticmethod(lambda *a, **k: self.boxes.append(a)))
        self.patch(ext_ui.ParamsDialog, "exec", lambda dlg: (dlg._preview(), 1)[1])
        self.w = mw_mod.MainWindow()
        self.w.resize(1300, 850)
        self.w.show()
        app.processEvents()

    def patch(self, obj, name, value):
        # remember whether the attribute was the object's own, so tearDown can put things back exactly
        # (copying an inherited Qt method onto a subclass breaks it for later tests)
        own = name in getattr(obj, "__dict__", {})
        self._patches.append((obj, name, getattr(obj, name) if own else _MISSING))
        setattr(obj, name, value)

    def tearDown(self):
        for obj, name, old in reversed(self._patches):
            if old is _MISSING:
                delattr(obj, name)
            else:
                setattr(obj, name, old)
        while self.w.docs.count():
            self.w.docs.widget(0).doc.undo.setClean()
            self.w.close_tab(0)
        self.w.close()
        self.w.deleteLater()
        app.processEvents()
        if ERRORS:
            import traceback
            msg = "".join("".join(traceback.format_exception(*e)) for e in ERRORS)
            ERRORS.clear()
            self.fail("Unhandled exception in Qt callback:\n" + msg)

    def install(self, name):
        ext = self.w.install_extension_file(zip_ext(name, self.tmp))
        self.assertIsNotNone(ext)
        return ext

    def doc_with_picture(self, w=200, h=150):
        cv = self.w.create_document(w, h)
        d = cv.doc

        def paint(p):
            p.fillRect(QRect(0, 0, w, h), QColor(60, 120, 200))
            p.fillRect(QRect(w // 4, h // 4, w // 2, h // 2), QColor(230, 90, 40))
        d.apply_region("paint", d.rect(), paint)
        return d

    def action(self, path, text):
        for a in self.w.menu_path(path).actions():
            if a.text() == text:
                return a
        self.fail(f"menu item {path} ▸ {text} not found")


# =========================================================================== core features
class TestWorkspacesAndRuntimes(Base):
    def test_workspace_tab_bar(self):
        from PyQt6.QtWidgets import QLabel
        self.w.create_document(50, 50)
        self.assertFalse(self.w.ws_bar.isVisible())          # only Lumen: no tab bar
        page = QLabel("hello")
        self.w.register_workspace("Tool", page, "globe")
        self.assertTrue(self.w.ws_bar.isVisible())
        self.assertEqual([self.w.ws_tabs.tabText(i) for i in range(self.w.ws_tabs.count())], ["Lumen", "Tool"])
        self.w.show_workspace(page)
        self.assertIs(self.w.workspace_stack.currentWidget(), page)
        self.assertFalse(self.w.toolbox.isVisible())
        self.assertFalse(self.w.options_bar.isVisible())
        self.assertFalse(any(s.isEnabled() for s in self.w.lumen_shortcuts))   # typing "b" won't pick the brush
        self.assertFalse(self.w.A["close"].isEnabled())
        self.w.show_workspace(0)
        self.assertTrue(self.w.toolbox.isVisible())
        self.assertTrue(all(s.isEnabled() for s in self.w.lumen_shortcuts))
        self.assertTrue(self.w.A["close"].isEnabled())

    def test_extension_downloads_runtime_once(self):
        srv = Server()
        try:
            entry = fake_runtime(srv, "testrt", "lumen_testrt_mod")
            self.w.checker.manifest = Manifest({"runtimes": {"testrt": {platform_key(): entry}}})
            src = os.path.join(self.tmp, "needs-rt")
            os.makedirs(src)
            with open(os.path.join(src, "manifest.json"), "w") as f:
                json.dump({"id": "needs-rt", "name": "Needs RT", "version": "1.0", "min_app": "0.4.0",
                           "requires": [{"id": "testrt", "provides": ["lumen_testrt_mod"]}]}, f)
            with open(os.path.join(src, "__init__.py"), "w") as f:
                f.write("def register(api):\n    import lumen_testrt_mod\n    register.value = lumen_testrt_mod.VALUE\n")
            zp = os.path.join(self.tmp, "needs-rt.zip")
            build_extensions.zip_folder(src, zp)
            ext = self.w.install_extension_file(zp)
            self.assertTrue(wait(lambda: ext.loaded or self.boxes, 20), "extension never loaded")
            self.assertTrue(ext.loaded, (ext.error, self.boxes))
            self.assertEqual(ext.module.register.value, 42)
            self.assertTrue(os.path.isfile(os.path.join(self.data, "runtimes", "testrt", "runtime.json")))
            # next start: activated from disk, no download
            w2 = mw_mod.MainWindow()
            self.assertTrue(w2.extensions.items["needs-rt"].loaded)
            w2.close()
            w2.deleteLater()
        finally:
            srv.stop()

    def test_runtime_rejects_tampered_or_wrong_qt(self):
        srv = Server()
        try:
            entry = fake_runtime(srv, "badrt", "lumen_badrt_mod")
            entry["sha256"] = "0" * 64
            done = []
            t = runtimes.download_task("badrt", entry)
            t.failed.connect(done.append)
            t.succeeded.connect(done.append)
            t.start()
            self.assertTrue(wait(lambda: done))
            self.assertIn("integrity", done[0])
            entry = fake_runtime(srv, "oldqt", "lumen_oldqt_mod", qt="5.0.0")
            path = os.path.join(self.tmp, "oldqt.zip")
            shutil.copy(os.path.join(srv.root, "oldqt.zip"), path)
            runtimes.install_zip("oldqt", path)
            self.assertFalse(runtimes.installed_ok("oldqt"))
            with self.assertRaises(runtimes.RuntimeError_):
                runtimes.activate("oldqt")
        finally:
            srv.stop()

    def test_store_extensions_are_not_bundled(self):
        os.environ["LUMEN_BUNDLED_EXTENSIONS"] = EXT
        try:
            w2 = mw_mod.MainWindow()
            self.assertEqual(sorted(w2.extensions.items), ["basic-filters"])   # only "builtin" ones ship inside
            w2.close()
            w2.deleteLater()
        finally:
            os.environ["LUMEN_BUNDLED_EXTENSIONS"] = os.path.join(tempfile.gettempdir(), "no-bundled")

    def test_param_dialog_types(self):
        got = []
        vals = None

        def preview(v):
            got.append(v)
        dlg = ext_ui.ParamsDialog(self.w, "T", [
            {"key": "s", "label": "S", "min": 0, "max": 10, "default": 3},
            {"key": "c", "label": "C", "type": "check", "default": True},
            {"key": "k", "label": "K", "type": "choice", "items": ["a", "b"], "default": 1},
            {"key": "col", "label": "Col", "type": "color", "default": lambda: QColor("red")}], preview)
        vals = dlg.values()
        self.assertEqual(vals["s"], 3)
        self.assertTrue(vals["c"])
        self.assertEqual(vals["k"], 1)
        self.assertEqual(vals["col"].name(), "#ff0000")
        dlg._preview()
        self.assertEqual(got[-1]["k"], 1)
        dlg.reject()
        self.assertIsNone(got[-1])                           # preview cleared on close


# =========================================================================== adjustments
class TestAdjustments(Base):
    def setUp(self):
        super().setUp()
        self.install("adjustments")
        self.m = sys.modules["lumen_ext_adjustments"]

    def solid(self, c):
        img = QImage(4, 4, imageops.PREMUL)
        img.fill(c)
        return img

    def test_maths(self):
        m = self.m
        img = self.solid(QColor(100, 150, 200))
        self.assertEqual(rgb(m.curves(img, {}).pixelColor(0, 0)), (100, 150, 200))        # identity curve
        self.assertEqual(rgb(m.levels(img).pixelColor(0, 0)), (100, 150, 200))           # identity levels
        self.assertEqual(rgb(m.levels(img, 0, 100, 1.0, 200).pixelColor(0, 0)), (0, 128, 255))
        red = self.solid(QColor(255, 0, 0))
        r, g, b = rgb(m.hue_saturation(red, 120).pixelColor(0, 0))
        self.assertTrue(g > 200 and r < 30 and b < 30, (r, g, b))                         # red + 120° = green
        r, g, b = rgb(m.black_white(red).pixelColor(0, 0))
        self.assertTrue(r == g == b and abs(r - 102) <= 2, (r, g, b))                       # Reds 40%
        low = QImage(16, 1, imageops.PREMUL)
        for x in range(16):
            low.setPixelColor(x, 0, QColor(100 + x * 4, 100 + x * 4, 100 + x * 4))
        out = m.auto_contrast(low)
        self.assertLess(out.pixelColor(0, 0).red(), 10)
        self.assertGreater(out.pixelColor(15, 0).red(), 245)
        lut = m.monotone_curve([(0, 0), (128, 200), (255, 255)])
        self.assertTrue((np.diff(lut.astype(int)) >= 0).all())                              # monotone
        self.assertEqual(int(lut[128]), 200)
        g = m.gradient_map(self.solid(QColor(0, 0, 0)), QColor("red"), QColor("blue"))
        self.assertEqual(rgb(g.pixelColor(0, 0)), (255, 0, 0))

    def test_menu_items_apply_to_active_layer(self):
        d = self.doc_with_picture()
        for name in ("Levels…", "Curves…", "Exposure…", "Vibrance…", "Hue/Saturation…", "Color Balance…",
                     "Black & White…", "Photo Filter…", "Gradient Map…", "Shadows/Highlights…", "Equalize"):
            n = d.undo.index()
            self.action("Image/Adjustments", name).trigger()
            self.assertEqual(d.undo.index(), n + 1, name)
        for name in ("Auto Tone", "Auto Contrast", "Auto Color"):
            self.action("Image", name).trigger()
        d = self.doc_with_picture()
        before = rgb(d.image.pixelColor(100, 75))
        self.patch(ext_ui.FilterDialog, "values", lambda dlg: {"hue": 180, "saturation": 0, "lightness": 0,
                                                               "colorize": False})
        self.action("Image/Adjustments", "Hue/Saturation…").trigger()
        self.assertNotEqual(rgb(d.image.pixelColor(100, 75)), before)

    def test_curves_editor_drives_result(self):
        d = self.doc_with_picture()
        seen = {}

        def accept(dlg):
            ed = dlg.curve_editor
            ed.points[0] = [(0, 0), (128, 230), (255, 255)]
            seen["vals"] = dlg.values()
            return 1
        self.patch(ext_ui.ParamsDialog, "exec", accept)
        before = d.image.pixelColor(10, 10).blue()
        self.action("Image/Adjustments", "Curves…").trigger()
        self.assertIn("curves", seen["vals"])
        self.assertGreater(d.image.pixelColor(10, 10).blue(), before)


# =========================================================================== creative filters
class TestCreativeFilters(Base):
    def test_every_filter_runs_from_the_menu(self):
        self.install("creative-filters")
        d = self.doc_with_picture(120, 90)
        items = {"Filter/Blur": ["Motion Blur…", "Radial Blur…"],
                 "Filter/Distort": ["Pinch…", "Polar Coordinates…", "Ripple…", "Spherize…", "Twirl…", "Wave…"],
                 "Filter/Noise": ["Dust & Scratches…", "Median…"],
                 "Filter/Pixelate": ["Color Halftone…", "Crystallize…"],
                 "Filter/Render": ["Clouds", "Difference Clouds", "Vignette…"],
                 "Filter/Stylize": ["Diffuse…", "Emboss…", "Find Edges", "Oil Paint…", "Solarize"],
                 "Filter/Other": ["High Pass…", "Maximum…", "Minimum…", "Offset…"]}
        for path, names in items.items():
            for name in names:
                n = d.undo.index()
                self.action(path, name).trigger()
                self.assertEqual(d.undo.index(), n + 1, f"{path} ▸ {name}")
                self.w.undo()
        m = sys.modules["lumen_ext_creative_filters"]
        img = d.layer_pixels()
        self.assertEqual(rgb(m.offset(img, 120, 0).pixelColor(5, 5)), rgb(img.pixelColor(5, 5)))   # full wrap
        mb = m.motion_blur(img, 0, 30)
        self.assertNotEqual(rgb(mb.pixelColor(30, 45)), rgb(img.pixelColor(30, 45)))           # edge smeared
        self.assertEqual(rgb(m.twirl(img, 300).pixelColor(60, 45)), rgb(img.pixelColor(60, 45)))  # centre fixed

    def test_clouds_use_foreground_and_background(self):
        self.install("creative-filters")
        d = self.doc_with_picture(80, 60)
        self.w.ctx.set_fg(QColor(255, 0, 0))
        self.w.ctx.set_bg(QColor(0, 0, 255))
        self.action("Filter/Render", "Clouds").trigger()
        r, g, b = rgb(d.image.pixelColor(40, 30))
        self.assertEqual(g, 0)
        self.assertEqual(r + b, 255)


# =========================================================================== layer effects
class TestLayerEffects(Base):
    def test_effects_create_layers(self):
        self.install("layer-effects")
        d = self.w.create_document(200, 150).doc
        img = QImage(60, 40, imageops.PREMUL)
        img.fill(QColor(255, 255, 255))
        L = d.add_layer("Logo", img, QPoint(70, 55))
        self.action("Layer/Layer Style", "Drop Shadow…").trigger()
        names = [x.name for x in d.layers]
        self.assertEqual(names, ["Background", "Logo's Drop Shadow", "Logo"])
        self.assertIs(d.active, L)
        sh = d.layers[1]
        self.assertEqual(sh.blend, "mul ")
        self.assertLess(d.image.pixelColor(70 + 62, 55 + 20).red(), 255)     # shadow visible to the lower right
        self.action("Layer/Layer Style", "Stroke…").trigger()
        self.assertEqual(d.layers[-1].name, "Logo's Stroke")
        self.assertEqual(d.layers[-1].alpha_at(QPoint(68, 70)), 255)          # outside the shape
        self.assertEqual(d.layers[-1].alpha_at(QPoint(100, 75)), 0)           # not over it
        for name in ("Outer Glow…", "Inner Shadow…", "Inner Glow…", "Color Overlay…", "Gradient Overlay…",
                     "Bevel & Emboss…"):
            n = len(d.layers)
            self.action("Layer/Layer Style", name).trigger()
            self.assertEqual(len(d.layers), n + 1, name)
        for _ in range(8):
            self.w.undo()
        self.assertEqual([x.name for x in d.layers], ["Background", "Logo"])

    def test_cancel_leaves_no_preview_layer(self):
        self.install("layer-effects")
        d = self.w.create_document(100, 100).doc
        img = QImage(20, 20, imageops.PREMUL)
        img.fill(QColor(0, 0, 0))
        d.add_layer("Dot", img, QPoint(40, 40))
        self.patch(ext_ui.ParamsDialog, "exec", lambda dlg: (dlg._preview(), 0)[1])
        self.action("Layer/Layer Style", "Outer Glow…").trigger()
        self.assertEqual([x.name for x in d.layers], ["Background", "Dot"])

    def test_background_refused(self):
        self.install("layer-effects")
        d = self.w.create_document(50, 50).doc
        self.action("Layer/Layer Style", "Drop Shadow…").trigger()
        self.assertEqual(len(d.layers), 1)


# =========================================================================== background remover
def _install_with_fake_onnx(case):
    """Install Background Remover; if onnxruntime isn't available, satisfy it with a stand-in pack."""
    if not runtimes.importable("onnxruntime"):
        meta_dir = os.path.join(case.data, "runtimes", "onnxruntime", "lib", "onnxruntime")
        os.makedirs(meta_dir)
        with open(os.path.join(meta_dir, "__init__.py"), "w") as f:
            f.write("raise ImportError('stand-in onnxruntime for tests')\n")
        with open(os.path.join(case.data, "runtimes", "onnxruntime", "runtime.json"), "w") as f:
            json.dump({"id": "onnxruntime", "version": "test", "provides": ["onnxruntime"],
                       "python_paths": ["lib"]}, f)
    ext = case.install("background-remover")
    case.assertTrue(ext.loaded, ext.error)
    return sys.modules["lumen_ext_background_remover"]


class TestBackgroundRemover(Base):
    def picture(self):
        d = self.w.create_document(160, 120).doc

        def paint(p):
            p.fillRect(QRect(0, 0, 160, 120), QColor(40, 200, 60))
            p.setBrush(QColor(220, 40, 40))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(80, 60), 35, 35)
        d.apply_region("paint", d.rect(), paint)
        return d

    def test_tab_and_manual_tools(self):
        mod = _install_with_fake_onnx(self)
        ws = mod.register.workspace
        self.assertIn("Background Remover", [self.w.ws_tabs.tabText(i) for i in range(self.w.ws_tabs.count())])
        d = self.picture()
        self.assertTrue(ws.from_active_layer())
        ws._pressed(QPointF(3, 3))                                   # magic wand on the green
        self.assertEqual(ws.cut.alpha[3, 3], 0)
        self.assertEqual(ws.cut.alpha[60, 80], 255)
        ws.set_tool("erase")
        ws._pressed(QPointF(80, 60))
        ws._dragged(QPointF(90, 60))
        self.assertEqual(ws.cut.alpha[60, 85], 0)
        ws.undo()
        self.assertEqual(ws.cut.alpha[60, 85], 255)
        ws.set_tool("restore")
        ws._pressed(QPointF(5, 5))
        self.assertEqual(ws.cut.alpha[5, 5], 255)
        ws.reset()
        ws.clear_edges()
        self.assertEqual(ws.cut.alpha[2, 150], 0)
        self.assertEqual(ws.cut.alpha[60, 80], 255)
        ws._edit(lambda c: c.tighten())
        ws._edit(lambda c: c.soften())
        self.assertTrue(ws.apply_to_layer())
        self.assertEqual(d.image.pixelColor(3, 3).alpha(), 0)
        self.assertEqual(d.layers[0].name, "Layer 0")                 # Background was converted, like Photoshop
        self.w.undo()
        self.assertEqual(d.image.pixelColor(3, 3).alpha(), 255)
        ws.trim.setChecked(True)
        img, crop = ws.result()
        self.assertTrue(abs(img.width() - 70) <= 4, img.width())
        ws.add_as_layer()
        self.assertTrue(d.layers[-1].name.endswith("cut-out"))

    def test_ai_paths_with_stub_model(self):
        mod = _install_with_fake_onnx(self)
        ai = sys.modules["lumen_ext_background_remover.ai"]
        d = self.picture()

        def fake_alpha(img, path):
            m = np.zeros((img.height(), img.width()), np.uint8)
            m[25:95, 45:115] = 255
            return m
        self.patch(ai, "subject_alpha", fake_alpha)
        self.patch(ai, "download_model", lambda folder, name, progress=None, cancelled=None: "stub.onnx")
        ws = mod.register.workspace
        ws.from_active_layer()
        ws.run_ai()
        self.assertTrue(wait(lambda: ws._task is None, 10))
        self.assertEqual(ws.cut.alpha[5, 5], 0)
        self.assertEqual(ws.cut.alpha[60, 80], 255)
        t = mod.register.select_subject()
        self.assertTrue(wait(lambda: t.isFinished(), 10))
        app.processEvents()
        self.assertEqual(d.selection_bounds(), QRect(45, 25, 70, 70))
        d.deselect()
        t = mod.register.remove_background()
        self.assertTrue(wait(lambda: t.isFinished(), 10))
        app.processEvents()
        self.assertEqual(d.image.pixelColor(5, 5).alpha(), 0)
        self.assertEqual(d.undo.text(d.undo.count() - 1), "Remove Background")

    @unittest.skipUnless(runtimes.importable("onnxruntime") and os.environ.get("LUMEN_TEST_MODEL"),
                         "set LUMEN_TEST_MODEL to a u2netp.onnx path to test the real AI model")
    def test_real_model(self):
        from importlib import import_module
        ai = import_module(load_pkg("background-remover").__name__ + ".ai")
        img = QImage(320, 240, imageops.PREMUL)
        img.fill(QColor(150, 190, 230))
        p = QPainter(img)
        p.setBrush(QColor(230, 120, 40))
        p.drawEllipse(QPointF(160, 120), 70, 70)
        p.end()
        m = ai.subject_alpha(img, os.environ["LUMEN_TEST_MODEL"])
        self.assertGreater(m[120, 160], 200)
        self.assertLess(m[10, 10], 50)


# =========================================================================== web images extractor
class TestWebImages(Base):
    def setUp(self):
        super().setUp()
        self.srv = Server()
        for name, c, w, h in (("a.png", "#ff0000", 120, 80), ("b.jpg", "#0000ff", 300, 200), ("tiny.png", "#00ff00", 12, 12)):
            img = QImage(w, h, QImage.Format.Format_ARGB32)
            img.fill(QColor(c))
            img.save(os.path.join(self.srv.root, name))

    def tearDown(self):
        self.srv.stop()
        super().tearDown()

    def test_gallery_downloads_and_adds_layers(self):
        pkg = load_pkg("web-images-extractor")
        from importlib import import_module
        gallery = import_module(pkg.__name__ + ".gallery")
        fetcher = import_module(pkg.__name__ + ".fetcher")
        api = type("A", (), {})()
        from lumen.extensions.api import ExtensionAPI
        api = ExtensionAPI(self.w, None)
        g = gallery.Gallery(api, fetcher.Fetcher())
        g.resize(900, 400)
        g.show()
        urls = [f"{self.srv.base}/a.png", f"{self.srv.base}/b.jpg", f"{self.srv.base}/tiny.png",
                f"{self.srv.base}/missing.png", f"{self.srv.base}/a.png"]
        g.show_urls(urls, referer=self.srv.base)
        self.assertEqual(len(g.cards), 4)                      # duplicates removed
        self.assertTrue(wait(g.finished, 15))
        infos = [c.info.text() for c in g.cards]
        self.assertIn("120 × 80 · PNG", infos)
        self.assertIn("300 × 200 · JPEG", infos)
        self.assertIsNone(g.cards[3].image)                   # the 404 shows an error, doesn't crash
        g.size_filter.setCurrentIndex(1)                      # 64 px and up
        self.assertEqual(len(g.visible_cards()), 2)
        # no document open → first image opens a new document
        g.add_layers([g.cards[0]])
        d = self.w.current_doc()
        self.assertEqual((d.width, d.height), (120, 80))
        g.cards[1].check.setChecked(True)
        g.cards[0].check.setChecked(True)
        self.assertEqual(g.add_sel_btn.text(), "Add 2 as Layers")
        g.add_layers([c for c in g.cards if c.check.isChecked()])
        self.assertEqual([L.name for L in d.layers][-2:], ["a", "b"])
        self.assertEqual(d.undo.text(d.undo.count() - 1), "Place 2 Images")
        g.open_document(g.cards[1])
        self.assertEqual(self.w.current_doc().width, 300)
        data = fetcher.decode_data_uri("data:image/png;base64,aGVsbG8=")
        self.assertEqual(data, b"hello")

    @unittest.skipUnless(runtimes.importable("PyQt6.QtWebEngineWidgets"), "Qt WebEngine not available here")
    def test_browser_collects_images(self):
        with open(os.path.join(self.srv.root, "index.html"), "w") as f:
            f.write("<html><head><title>T</title></head><body><img src='a.png'>"
                    "<div style=\"background-image:url('b.jpg')\">x</div></body></html>")
        ext = self.install("web-images-extractor")
        self.assertTrue(ext.loaded, ext.error)
        ws = sys.modules["lumen_ext_web_images_extractor"].register.workspace
        self.w.show_workspace(ws)
        ws.url.setText(f"{self.srv.base}/index.html")
        ws.go()
        self.assertTrue(wait(lambda: ws.view().title() == "T", 30))
        ws.collect()
        self.assertTrue(wait(lambda: len(ws.gallery.cards) == 2 and ws.gallery.finished(), 30))


if __name__ == "__main__":
    unittest.main(verbosity=2)
