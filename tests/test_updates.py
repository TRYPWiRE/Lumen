"""Tests for the update checker, extension system and Basic Filters, against a local fake 'GitHub'."""
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from functools import partial

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _env  # noqa: F401

from PyQt6.QtCore import Qt, QRect, QRectF
from PyQt6.QtGui import QColor, QImage, QPainterPath
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])

from lumen import theme, versioning, updates, config, __version__  # noqa: E402
from lumen import mainwindow as mw_mod  # noqa: E402
from lumen.extensions import ExtensionManager, ExtensionError  # noqa: E402
from lumen.extensions import ui as ext_ui  # noqa: E402
import build_extensions  # noqa: E402
import release  # noqa: E402

theme.apply(app)
ERRORS = []
sys.excepthook = lambda *a: ERRORS.append(a)


def wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def write_bytes(path, data):
    with open(path, "wb") as f:
        f.write(data)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class FakeGitHub:
    """Serves a folder over http://127.0.0.1 like raw.githubusercontent.com would."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="fake-gh-")
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=self.root))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"
        self.src = os.path.join(self.root, "src")
        shutil.copytree(os.path.join(ROOT, "extensions"), self.src)
        self.manifest = os.path.join(self.root, "updates", "manifest.json")

    @property
    def manifest_url(self):
        return f"{self.base}/updates/manifest.json"

    def publish(self):
        build_extensions.build(src=self.src, out=os.path.join(self.root, "updates", "extensions"),
                               manifest_path=self.manifest, base_url=f"{self.base}/updates/extensions")

    def set_ext_version(self, ext_id, version, **extra):
        p = os.path.join(self.src, ext_id, "manifest.json")
        m = read_json(p)
        m["version"] = version
        m.update(extra)
        write_json(p, m)

    def edit_manifest(self, fn):
        data = read_json(self.manifest)
        fn(data)
        write_json(self.manifest, data)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def make_ext_zip(folder, ext_id, code, version="1.0.0", min_app="0.2.0", extra_files=None):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{ext_id}.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"id": ext_id, "name": ext_id.title(), "version": version,
                                                "min_app": min_app}))
        z.writestr("__init__.py", code)
        for name, data in (extra_files or {}).items():
            z.writestr(name, data)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        ERRORS.clear()
        self.data = tempfile.mkdtemp(prefix="lumen-data-")
        os.environ["LUMEN_DATA_DIR"] = self.data
        os.environ["LUMEN_SETTINGS"] = os.path.join(self.data, "settings.ini")
        self.gh = FakeGitHub()
        self.gh.publish()
        self.patches = []
        # never pop real modal boxes during tests
        self.boxes = []
        self.patch(QMessageBox, "warning", staticmethod(lambda *a, **k: self.boxes.append(("warning", a))))
        self.patch(QMessageBox, "information", staticmethod(lambda *a, **k: self.boxes.append(("info", a))))
        self.w = self.new_window()

    def new_window(self):
        w = mw_mod.MainWindow()
        w.checker.url = self.gh.manifest_url
        w.resize(1300, 850)
        w.show()
        app.processEvents()
        return w

    def patch(self, obj, name, value):
        self.patches.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def tearDown(self):
        for obj, name, old in reversed(self.patches):
            setattr(obj, name, old)
        for w in list(getattr(self, "_windows", [])) + [self.w]:
            while w.docs.count():
                w.docs.widget(0).doc.undo.setClean()
                w.close_tab(0)
            w.close()
            w.deleteLater()
        app.processEvents()
        self.gh.stop()
        if ERRORS:
            import traceback
            msg = "".join("".join(traceback.format_exception(*e)) for e in ERRORS)
            ERRORS.clear()
            self.fail("Unhandled exception in Qt callback:\n" + msg)

    # helpers
    def check(self):
        done = []
        self.w.checker.checked.connect(lambda m: done.append(m))
        self.w.checker.failed.connect(lambda m: done.append(m))
        self.w.check_for_updates()
        self.assertTrue(wait(lambda: done), "update check never finished")
        return done[0]

    def install(self, ext_id="basic-filters"):
        man = self.check()
        entry = man.extensions[ext_id]
        self.w.install_extension(entry)
        self.assertTrue(wait(lambda: ext_id in self.w.extensions.items), "extension never installed")
        return self.w.extensions.items[ext_id]

    def find_action(self, path, text):
        menu = self.w.menu_path(path)
        for a in menu.actions():
            if a.text() == text:
                return a
        return None


class TestVersioning(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(versioning.is_newer("0.2.1", "0.2.0"))
        self.assertTrue(versioning.is_newer("v1.0", "0.9.9"))
        self.assertTrue(versioning.is_newer("1.10.0", "1.9.0"))
        self.assertFalse(versioning.is_newer("1.0.0", "1.0"))
        self.assertTrue(versioning.is_newer("1.0.0", "1.0.0-beta"))
        self.assertTrue(versioning.compatible("0.2.0", "0.2.0"))
        self.assertFalse(versioning.compatible("0.3", "0.2.9"))
        self.assertTrue(versioning.compatible("", "0.1"))

    def test_manifest_parsing(self):
        m = updates.Manifest({"app": {"version": "9.0.0", "url": "x"},
                              "extensions": [{"id": "a", "version": "2.0", "url": "u"}, {"bad": 1}]})
        self.assertEqual(m.app_update("1.0")["version"], "9.0.0")
        self.assertIsNone(m.app_update("9.0.0"))
        self.assertEqual([e["id"] for e in m.extension_updates({"a": "1.0"})], ["a"])
        self.assertEqual(m.extension_updates({"a": "2.0"}), [])
        self.assertEqual(updates.Manifest({}).extensions, {})


class TestPublishingTools(unittest.TestCase):
    def test_build_is_deterministic_and_release_sets_app(self):
        tmp = tempfile.mkdtemp()
        out, man = os.path.join(tmp, "ext"), os.path.join(tmp, "manifest.json")
        build_extensions.build(out=out, manifest_path=man, base_url="https://x/ext")
        sha1 = read_json(man)["extensions"][0]["sha256"]
        build_extensions.build(out=out, manifest_path=man, base_url="https://x/ext")
        data = read_json(man)
        self.assertEqual(data["extensions"][0]["sha256"], sha1)
        ver = read_json(os.path.join(ROOT, "extensions", "basic-filters", "manifest.json"))["version"]
        self.assertEqual(os.listdir(out), [f"basic-filters-{ver}.zip"])
        fake = os.path.join(tmp, "LumenSetup-0.2.0.exe")
        write_bytes(fake, b"installer")
        app_entry = release.set_app(fake, "notes", man)
        self.assertEqual(app_entry["version"], __version__)
        self.assertTrue(app_entry["url"].endswith(f"/releases/download/v{__version__}/LumenSetup-0.2.0.exe"))
        self.assertEqual(read_json(man)["extensions"][0]["sha256"], sha1)  # extensions untouched

    def test_repo_manifest_is_valid(self):
        data = read_json(os.path.join(ROOT, "updates", "manifest.json"))
        m = updates.Manifest(data)
        e = m.extensions["basic-filters"]
        self.assertTrue(e["url"].startswith(config.RAW_BASE))
        zp = os.path.join(ROOT, "updates", "extensions", os.path.basename(e["url"]))
        self.assertEqual(build_extensions.sha256(zp), e["sha256"])


class TestExtensions(Base):
    def test_install_from_github_and_use_filter(self):
        ext = self.install()
        self.assertTrue(ext.loaded, ext.error)
        self.assertFalse(self.w.extensions.restart_needed)   # fresh install loads immediately
        gauss = self.find_action("Filter/Blur", "Gaussian Blur…")
        self.assertIsNotNone(gauss)
        self.assertIsNotNone(self.find_action("Image/Adjustments", "Brightness/Contrast…"))
        self.assertFalse(gauss.isEnabled())                 # no document open yet

        cv = self.w.create_document(80, 60)
        d = cv.doc
        d.apply_region("setup", QRect(0, 0, 40, 60), lambda p: p.fillRect(QRect(0, 0, 40, 60), QColor(0, 0, 0)))
        self.assertTrue(gauss.isEnabled())
        self.patch(ext_ui.FilterDialog, "exec", lambda dlg: (dlg._preview(), 1)[1])
        gauss.trigger()
        mid = d.image.pixelColor(40, 30).red()
        self.assertTrue(60 < mid < 200, mid)                # edge is now soft
        self.assertEqual(d.image.pixelColor(2, 30).red(), 0)
        self.assertEqual(d.undo.text(d.undo.count() - 1), "Gaussian Blur")
        self.assertTrue(all(L.preview is None for L in d.layers))
        self.w.undo()
        self.assertEqual(d.image.pixelColor(40, 30).red(), 255)
        self.w.A["last_filter"].trigger()                   # Ctrl+Alt+F repeats it
        self.assertLess(d.image.pixelColor(40, 30).red(), 255)

    def test_filter_respects_selection_and_cancel_clears_preview(self):
        self.install()
        cv = self.w.create_document(60, 60)
        d = cv.doc
        p = QPainterPath()
        p.addRect(QRectF(0, 0, 30, 60))
        d.set_selection(p)
        self.patch(ext_ui.FilterDialog, "exec", lambda dlg: (dlg._preview(), 0)[1])   # preview then Cancel
        self.find_action("Image/Adjustments", "Threshold…").trigger()
        self.assertTrue(all(L.preview is None for L in d.layers))
        self.assertEqual(d.undo.count(), 1)  # only the selection
        self.patch(ext_ui.FilterDialog, "exec", lambda dlg: 1)
        self.w.ctx.set_fg(QColor(0, 0, 0))
        self.find_action("Image/Adjustments", "Brightness/Contrast…")
        dlg_vals = {}
        orig_values = ext_ui.FilterDialog.values
        self.patch(ext_ui.FilterDialog, "values", lambda dlg: {**orig_values(dlg), "brightness": -100})
        self.find_action("Image/Adjustments", "Brightness/Contrast…").trigger()
        self.assertLess(d.image.pixelColor(10, 10).red(), 200)
        self.assertEqual(d.image.pixelColor(50, 10).red(), 255)

    def test_extension_loads_on_next_start(self):
        self.install()
        w2 = self.new_window()
        self._windows = [w2]
        self.assertTrue(w2.extensions.items["basic-filters"].loaded)
        self.assertIsNotNone(next((a for a in w2.menu_path("Filter/Blur").actions() if a.text() == "Box Blur…"), None))

    def test_extension_update_flow_and_banner(self):
        self.install()
        self.gh.set_ext_version("basic-filters", "9.1.0")
        self.gh.publish()
        self.check()
        self.assertTrue(self.w.banner.isVisible())
        self.assertIn("1 extension update", self.w.banner.label.text())
        self.w.update_everything(None, self.w.checker.manifest.extension_updates(self.w.extensions.installed_versions()))
        self.assertTrue(wait(lambda: self.w.extensions.items["basic-filters"].version == "9.1.0"))
        self.assertTrue(self.w.extensions.restart_needed)
        self.assertTrue(wait(lambda: "Restart" in self.w.banner.label.text()
                             or "restart" in self.w.banner.label.text()))

    def test_auto_update_extensions_setting(self):
        self.install()
        self.w.ctx.settings.setValue("updates/auto_extensions", True)
        self.gh.set_ext_version("basic-filters", "9.2.0")
        self.gh.publish()
        self.check()
        self.assertTrue(wait(lambda: self.w.extensions.items["basic-filters"].version == "9.2.0"))

    def test_sha_mismatch_is_rejected(self):
        self.gh.edit_manifest(lambda d: d["extensions"][0].__setitem__("sha256", "0" * 64))
        man = self.check()
        done = []
        self.w.install_extension(man.extensions["basic-filters"], then=lambda: done.append(1))
        self.assertTrue(wait(lambda: done))
        self.assertNotIn("basic-filters", self.w.extensions.items)
        self.assertTrue(any("integrity" in str(b) for b in self.boxes))

    def test_incompatible_extension_not_installable(self):
        self.gh.set_ext_version("basic-filters", "20.0.0", min_app="99.0.0")
        self.gh.publish()
        man = self.check()
        self.assertEqual(man.extension_updates({"basic-filters": "1.0.0"}), [])
        zp = make_ext_zip(tempfile.mkdtemp(), "future", "def register(api): pass", min_app="99.0")
        with self.assertRaises(ExtensionError):
            self.w.extensions.install_zip(zp)

    def test_zip_slip_and_bad_zips_rejected(self):
        tmp = tempfile.mkdtemp()
        evil = os.path.join(tmp, "evil.zip")
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("manifest.json", json.dumps({"id": "evil", "version": "1"}))
            z.writestr("__init__.py", "def register(api): pass")
            z.writestr("../../escaped.txt", "x")
        with self.assertRaises(ExtensionError):
            self.w.extensions.install_zip(evil)
        self.assertFalse(os.path.exists(os.path.join(self.data, "escaped.txt")))
        nomani = os.path.join(tmp, "nomani.zip")
        with zipfile.ZipFile(nomani, "w") as z:
            z.writestr("__init__.py", "x")
        self.assertIsNone(self.w.install_extension_file(nomani))
        self.assertEqual(self.w.extensions.items, {})
        self.assertEqual([n for n in os.listdir(self.w.extensions.root)], [])  # no staging leftovers

    def test_broken_extension_does_not_break_app(self):
        zp = make_ext_zip(tempfile.mkdtemp(), "broken", "def register(api):\n    raise RuntimeError('boom')\n")
        ext = self.w.install_extension_file(zp)
        self.assertFalse(ext.loaded)
        self.assertIn("boom", ext.error)
        w2 = self.new_window()            # still starts fine with it installed
        self._windows = [w2]
        self.assertIn("boom", w2.extensions.items["broken"].error)

    def test_disable_enable_uninstall(self):
        self.install()
        mgr = self.w.extensions
        mgr.set_enabled("basic-filters", False)
        self.assertTrue(mgr.restart_needed)
        w2 = self.new_window()
        self._windows = [w2]
        self.assertFalse(w2.extensions.items["basic-filters"].loaded)
        self.assertIsNone(next((a for a in w2.menu_path("Filter/Blur").actions() if a.text() == "Box Blur…"), None))
        w2.extensions.set_enabled("basic-filters", True)       # enabling hot-loads
        self.assertTrue(w2.extensions.items["basic-filters"].loaded)
        w2.extensions.uninstall("basic-filters")
        self.assertNotIn("basic-filters", w2.extensions.items)
        self.assertFalse(os.path.exists(os.path.join(self.data, "extensions", "basic-filters")))

    def test_extension_can_add_tool_panel_and_menu(self):
        code = '''
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QColor
from .helper import COLOUR

class StampTool:
    pass

def register(api):
    class Stamp(api.Tool):
        name, title, icon, key = "stamp", "Stamp Tool", "rect", "J"
        def press(self, cv, pt, ev):
            cv.doc.fill(QColor(COLOUR), "Stamp")
    api.add_tool(Stamp)
    api.add_tool(type("Dot", (api.Tool,), {"name": "dot", "title": "Dot Tool", "icon": "pencil", "key": ""}),
                 group="brush")
    api.add_panel("Hello", QLabel("hi"))
    api.add_menu_action("Fancy/Sub", "Do It", lambda: api.status("did it"), needs_document=False)
'''
        zp = make_ext_zip(tempfile.mkdtemp(), "toolkit", code, extra_files={"helper.py": "COLOUR = '#123456'\n"})
        ext = self.w.install_extension_file(zp)
        self.assertTrue(ext.loaded, getattr(ext, "traceback", ext.error))
        self.assertIn("stamp", self.w.group_buttons)
        self.assertIn("dot", [t.name for t in self.w.group_buttons["brush"].tools])
        self.assertEqual(self.w.group_hist.tabText(self.w.group_hist.count() - 1), "Hello")
        self.assertIn("fancy", self.w.menus)
        cv = self.w.create_document(20, 20)
        self.w.set_tool("stamp")
        from PyQt6.QtTest import QTest
        self.w.set_tool("move")
        QTest.keyClick(cv, Qt.Key.Key_J)
        app.processEvents()
        self.assertEqual(self.w.ctx.tool.name, "stamp")
        self.w.ctx.tool.press(cv, None, None)
        self.assertEqual(cv.doc.image.pixelColor(5, 5).name(), "#123456")

    def test_extensions_dialog(self):
        self.install()
        self.patch(ext_ui.FilterDialog, "exec", lambda dlg: 1)
        dlg = mw_mod.ExtensionsDialog(self.w)
        dlg.show()
        app.processEvents()
        inst = dlg.installed_list[1]
        self.assertGreaterEqual(inst.count(), 2)            # one row + stretch
        dlg.grab().save(os.path.join(tempfile.gettempdir(), "lumen-ext-dialog.png"))
        dlg.close()


class TestBuiltinExtensions(Base):
    def setUp(self):
        os.environ["LUMEN_BUNDLED_EXTENSIONS"] = os.path.join(ROOT, "extensions")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        os.environ["LUMEN_BUNDLED_EXTENSIONS"] = os.path.join(tempfile.gettempdir(), "lumen-no-bundled")

    def test_filters_ship_with_the_app_and_work_offline(self):
        ext = self.w.extensions.items["basic-filters"]
        self.assertTrue(ext.builtin)
        self.assertTrue(ext.loaded, ext.error)
        cv = self.w.create_document(60, 40)
        cv.doc.apply_region("s", QRect(0, 0, 30, 40), lambda p: p.fillRect(QRect(0, 0, 30, 40), QColor(0, 0, 0)))
        blur = self.find_action("Filter/Blur", "Blur")
        blur.trigger()
        self.assertTrue(0 < cv.doc.image.pixelColor(30, 20).red() < 255)

    def test_filters_on_large_image_regression(self):
        """1.0.0 read freed memory: on big images every filter worked on a blank copy."""
        cv = self.w.create_document(3000, 2000)
        d = cv.doc
        d.apply_region("s", QRect(0, 0, 1500, 2000), lambda p: p.fillRect(QRect(0, 0, 1500, 2000), QColor(0, 0, 0)))
        self.patch(ext_ui.FilterDialog, "exec", lambda dlg: (dlg._preview(), 1)[1])
        self.find_action("Filter/Blur", "Gaussian Blur…").trigger()
        self.assertEqual(d.image.pixelColor(100, 1000).red(), 0)             # still black far from the edge
        self.assertEqual(d.image.pixelColor(2900, 1000).red(), 255)          # still white
        self.assertTrue(0 < d.image.pixelColor(1500, 1000).red() < 255)     # edge blurred
        self.find_action("Image/Adjustments", "Threshold…").trigger()
        v = d.image.pixelColor(1499, 1000).red()
        self.assertIn(v, (0, 255))

    def test_downloaded_update_overrides_builtin_and_revert(self):
        self.gh.set_ext_version("basic-filters", "9.0.0")
        self.gh.publish()
        man = self.check()
        self.w.install_extension(man.extensions["basic-filters"])
        self.assertTrue(wait(lambda: self.w.extensions.items["basic-filters"].version == "9.0.0"))
        self.assertTrue(self.w.extensions.items["basic-filters"].builtin)
        self.assertTrue(self.w.extensions.restart_needed)
        self.w.extensions.uninstall("basic-filters")        # "Revert" → back to the shipped version
        ext = self.w.extensions.items["basic-filters"]
        self.assertNotEqual(ext.version, "9.0.0")
        self.w.extensions.uninstall("basic-filters")        # built-in can't be deleted: it's disabled
        self.assertIn("basic-filters", self.w.extensions.items)
        self.assertFalse(self.w.extensions.is_enabled("basic-filters"))


class TestAppUpdates(Base):
    def set_app(self, version, payload=b"fake installer"):
        inst = os.path.join(self.gh.root, "releases", f"LumenSetup-{version}.exe")
        os.makedirs(os.path.dirname(inst), exist_ok=True)
        write_bytes(inst, payload)
        release.set_app(inst, "Big update", self.gh.manifest, version=version, base_url=f"{self.gh.base}/releases")
        return inst

    def test_up_to_date_manual_check(self):
        self.w.check_for_updates(manual=True)
        self.assertTrue(wait(lambda: self.boxes))
        self.assertIn("up to date", str(self.boxes[-1]))
        self.assertFalse(self.w.banner.isVisible())

    def test_new_version_shows_banner_and_source_build_opens_releases(self):
        self.set_app("9.9.9")
        self.check()
        self.assertTrue(self.w.banner.isVisible())
        self.assertIn("Lumen 9.9.9", self.w.banner.label.text())
        opened = []
        self.patch(updates, "open_releases_page", lambda: opened.append(1))
        self.w.update_app(self.w.checker.manifest.app)
        self.assertEqual(opened, [1])

    def test_installed_build_downloads_verifies_and_launches_installer(self):
        self.set_app("9.9.9", b"x" * 300000)
        man = self.check()
        launched, quit_called = [], []
        self.patch(updates, "can_self_update", lambda: True)
        self.patch(updates, "launch_installer", lambda p: launched.append(p))
        self.patch(mw_mod.QApplication, "quit", staticmethod(lambda: quit_called.append(1)))
        self.w.update_app(man.app)
        ok = wait(lambda: launched, 15)
        self.assertTrue(ok, f"boxes={self.boxes}")
        self.assertTrue(launched[0].endswith("LumenSetup-9.9.9.exe"))
        self.assertEqual(os.path.getsize(launched[0]), 300000)
        self.assertEqual(quit_called, [1])
        cmd = updates.installer_command("C:/x/setup.exe")
        self.assertIn("/SILENT", cmd)

    def test_tampered_installer_is_not_launched(self):
        self.set_app("9.9.9")
        self.gh.edit_manifest(lambda d: d["app"].__setitem__("sha256", "f" * 64))
        man = self.check()
        launched = []
        self.patch(updates, "can_self_update", lambda: True)
        self.patch(updates, "launch_installer", lambda p: launched.append(p))
        self.w.update_app(man.app)
        self.assertTrue(wait(lambda: self.boxes, 10))
        self.assertEqual(launched, [])

    def test_offline_check_fails_quietly_or_warns_when_manual(self):
        self.w.checker.url = "http://127.0.0.1:9/updates/manifest.json"
        result = self.check()
        self.assertIsInstance(result, str)
        self.assertFalse(self.w.banner.isVisible())
        self.assertEqual(self.boxes, [])
        self.w.check_for_updates(manual=True)
        self.assertTrue(wait(lambda: self.boxes))


class TestFilterMaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        from lumen import imageops
        spec = importlib.util.spec_from_file_location("bf_test", os.path.join(ROOT, "extensions", "basic-filters",
                                                                               "__init__.py"))
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)
        cls.m._ops = imageops

    def img(self, w, h, color):
        i = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        i.fill(color)
        return i

    def test_blur_of_red_on_transparent_has_no_dark_halo(self):
        i = self.img(40, 40, Qt.GlobalColor.transparent)
        from PyQt6.QtGui import QPainter
        p = QPainter(i)
        p.fillRect(10, 10, 20, 20, QColor(255, 0, 0))
        p.end()
        out = self.m.f_gaussian(i, 3.0)
        c = out.pixelColor(10, 20)
        self.assertTrue(0 < c.alpha() < 255)
        self.assertGreater(c.red(), 240)
        self.assertLess(c.green() + c.blue(), 10)

    def test_mosaic_posterize_threshold(self):
        from lumen import imageops
        import numpy as np
        i = self.img(23, 17, QColor(0, 0, 0))
        arr = imageops.view(i)
        arr[..., :3] = np.random.default_rng(0).integers(0, 255, (17, 23, 3), dtype=np.uint8)
        m = self.m.f_mosaic(i, 5)
        self.assertEqual(m.pixelColor(0, 0), m.pixelColor(4, 4))
        self.assertEqual((m.width(), m.height()), (23, 17))
        pst = imageops.straight_array(self.m.f_posterize(i, 2))
        self.assertTrue(set(np.unique(pst[..., :3])) <= {0, 255})
        th = imageops.straight_array(self.m.f_threshold(i, 128))
        self.assertTrue(set(np.unique(th[..., :3])) <= {0, 255})
        self.assertTrue((th[..., 0] == th[..., 2]).all())

    def test_unsharp_increases_contrast_and_noise_changes_pixels(self):
        i = self.img(30, 30, QColor(100, 100, 100))
        from PyQt6.QtGui import QPainter
        p = QPainter(i)
        p.fillRect(15, 0, 15, 30, QColor(150, 150, 150))
        p.end()
        s = self.m.f_unsharp(i, 200, 2.0, 0)
        self.assertLess(s.pixelColor(14, 15).red(), 100)
        self.assertGreater(s.pixelColor(15, 15).red(), 150)
        n = self.m.f_noise(self.img(30, 30, QColor(128, 128, 128)), 20)
        vals = {n.pixelColor(x, 5).red() for x in range(30)}
        self.assertGreater(len(vals), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
