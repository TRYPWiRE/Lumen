"""Theme engine: presets, generation, saving/remembering, import/export, live re-theming, menu and editor."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import _env  # noqa: F401,E402

from PyQt6.QtCore import QSize, QEvent, QCoreApplication  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidgetAction  # noqa: E402

app = QApplication.instance() or QApplication(["lumen-tests"])

from lumen import theme, icons  # noqa: E402

theme.apply(app)


def setUpModule():
    # Earlier test modules leave their windows alive; in the real app there is only one window, but here
    # every theme switch would restyle all of them (seconds per switch). Earlier modules are finished, so
    # dispose of everything they left behind.
    from PyQt6 import sip
    _flush_deleted()
    for w in list(app.topLevelWidgets()):
        if not sip.isdeleted(w):
            w.hide()
            sip.delete(w)


def _flush_deleted():
    """Really delete windows earlier tests closed with deleteLater(), so re-theming doesn't restyle them all."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _reset():
    _flush_deleted()
    shutil.rmtree(theme.themes_dir(), ignore_errors=True)
    s = theme._settings()
    s.remove("theme")
    s.sync()
    theme.apply(app, theme.default_theme())


class TestThemeModel(unittest.TestCase):
    def tearDown(self):
        _reset()

    def test_presets_are_complete_and_readable(self):
        ids = [t.id for t in theme.presets()]
        self.assertGreaterEqual(len(ids), 10)
        self.assertEqual(len(ids), len(set(ids)))
        for t in theme.presets():
            self.assertEqual(set(t.colors), set(theme.KEYS), t.name)
            for k, v in t.colors.items():
                self.assertRegex(v, r"^#[0-9a-f]{6}$", f"{t.name}.{k}")
            self.assertGreaterEqual(theme.contrast(t["text"], t["window"]), 4.5, t.name)
            self.assertGreaterEqual(theme.contrast(t["accent_text"], t["accent"]), 3.0, t.name)
            self.assertTrue(t.builtin)
        self.assertTrue(any(not t.dark for t in theme.presets()), "need at least one light preset")

    def test_default_matches_classic_look(self):
        d = theme.default_theme()
        self.assertEqual(d.id, theme.DEFAULT_ID)
        self.assertEqual(d["window"], "#323232")
        self.assertEqual(d["accent"], "#2680eb")
        self.assertEqual(theme.BG, "#323232")          # names older code + extensions use

    def test_generate_dark_and_light(self):
        for base, text, dark in (("#202830", "#e0e6ee", True), ("#f4f1ea", "#222222", False)):
            c = theme.generate(base, text, "#ff6600")
            self.assertEqual(set(c), set(theme.KEYS))
            t = theme.Theme("x", c)
            self.assertEqual(t.dark, dark)
            self.assertGreaterEqual(theme.contrast(c["text"], c["window"]), 4.5)

    def test_complete_fills_missing_and_ignores_junk(self):
        c = theme.complete({"window": "#101010", "accent": "ABCDEF", "text": "nope", "bogus": "#ffffff"})
        self.assertEqual(set(c), set(theme.KEYS))
        self.assertEqual(c["accent"], "#abcdef")
        self.assertEqual(c["window"], "#101010")
        self.assertNotIn("bogus", c)

    def test_save_remember_and_survive_restart(self):
        t = theme.Theme("Mine", theme.generate("#112233", "#eeeeee", "#ffaa00"))
        saved = theme.save_user_theme(t)
        self.assertTrue(os.path.isfile(os.path.join(theme.themes_dir(), saved.id + theme.FILE_EXT)))
        self.assertIn(saved.id, [x.id for x in theme.user_themes()])
        theme.apply(app, saved, remember_choice=True)
        self.assertEqual(theme.saved_theme().id, saved.id)            # what the next start-up loads
        # even if the file disappears, the remembered copy keeps the look
        theme.delete_user_theme(saved.id)
        back = theme.saved_theme()
        self.assertTrue(back.same_colors(saved))
        self.assertEqual(back.name, "Mine")

    def test_saving_a_preset_makes_a_copy(self):
        p = theme.find("midnight")
        saved = theme.save_user_theme(p.copy(name="Midnight Tweaked"))
        self.assertNotEqual(saved.id, "midnight")
        self.assertEqual(saved.source, "user")
        self.assertEqual(theme.find("midnight").source, "preset")

    def test_export_import_roundtrip(self):
        d = tempfile.mkdtemp()
        t = theme.Theme("Shared", theme.generate("#2a2033", "#f0e6ff", "#c05cff"), author="Kie", source="ai",
                        description="Made by AI")
        path = theme.export_file(t, os.path.join(d, "shared"))
        self.assertTrue(path.endswith(theme.FILE_EXT))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["format"], "lumen-theme")
        self.assertEqual(data["source"], "ai")
        imp = theme.import_file(path)
        self.assertTrue(imp.same_colors(t))
        self.assertEqual(imp.source, "ai")                          # keeps where it came from (for the gallery)
        self.assertEqual(imp.author, "Kie")
        self.assertEqual(theme.import_file(path).id, imp.id)        # same theme twice → no duplicate
        self.assertEqual(len(theme.user_themes()), 1)
        bad = os.path.join(d, "bad" + theme.FILE_EXT)
        with open(bad, "w") as f:
            f.write("{ not json")
        with self.assertRaises(ValueError):
            theme.import_file(bad)
        with open(bad, "w") as f:
            json.dump({"hello": 1}, f)
        with self.assertRaises(ValueError):
            theme.import_file(bad)
        shutil.rmtree(d)

    def test_unique_names(self):
        theme.save_user_theme(theme.Theme("Ocean", theme.default_theme().colors))
        self.assertEqual(theme.unique_name("Ocean"), "Ocean 2")
        self.assertEqual(theme.unique_name("Lumen Dark"), "Lumen Dark 2")


class TestLiveTheming(unittest.TestCase):
    def tearDown(self):
        _reset()

    def test_apply_restyles_app_icons_and_notifies(self):
        seen = []
        theme.notifier.changed.connect(seen.append)
        try:
            ic = icons.icon("brush")
            before = ic.pixmap(QSize(24, 24)).toImage()
            light = theme.find("daylight")
            theme.apply(app, light)
            self.assertIn(light["window"], app.styleSheet())
            self.assertEqual(app.palette().window().color().name(), light["window"])
            after = ic.pixmap(QSize(24, 24)).toImage()        # the same QIcon redraws in the new colours
            self.assertNotEqual(_ink(before), _ink(after))
            self.assertEqual(_ink(after), QColor(light["icon"]).name())
            self.assertEqual(seen[-1].id, "daylight")
            self.assertEqual(theme.C["window"], light["window"])
            self.assertEqual(theme.PASTEBOARD, light["pasteboard"])
        finally:
            theme.notifier.changed.disconnect(seen.append)

    def test_tone_is_readable_on_light_and_dark(self):
        for tid in ("lumen-dark", "daylight"):
            theme.apply(app, theme.find(tid))
            for kind in ("error", "warn", "ok"):
                self.assertGreaterEqual(theme.contrast(theme.tone(kind), theme.C["window"]), 3.0, (tid, kind))


def _ink(img: QImage):
    """The most opaque pixel's colour - i.e. the icon's stroke colour."""
    best, col = -1, None
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > best:
                best, col = c.alpha(), c
    col.setAlpha(255)
    return col.name()


class TestThemesUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lumen.mainwindow import MainWindow
        cls.w = MainWindow()
        cls.w.show()
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()
        cls.w.deleteLater()
        app.processEvents()

    def tearDown(self):
        _reset()

    def test_menu_has_presets_with_previews_and_create(self):
        titles = [a.text().replace("&", "") for a in self.w.menuBar().actions()]
        self.assertIn("Themes", titles)
        self.assertLess(titles.index("Themes"), titles.index("Help"))
        tm = self.w.themes_menu
        tm.refresh()
        rows = [a for a in tm.presets_menu.actions() if isinstance(a, QWidgetAction)]
        self.assertEqual([a.text() for a in rows], [t.name for t in theme.presets()])
        self.assertTrue(rows[0].isChecked())                        # current theme is ticked
        rows[0].defaultWidget().grab()                              # preview row draws
        texts = [a.text() for a in tm.actions()]
        self.assertIn("Create Theme…", texts)
        self.assertIn("Import Theme…", texts)
        # picking a preset applies and remembers it
        frost = next(a for a in rows if a.text() == "Frost")
        frost.trigger()
        app.processEvents()
        self.assertEqual(theme.current().id, "frost")
        self.assertEqual(theme._settings().value("theme/id"), "frost")
        tm.refresh()
        self.assertTrue(next(a for a in tm.presets_menu.actions() if a.text() == "Frost").isChecked())

    def test_editor_cancel_restores_and_save_applies(self):
        from lumen.themeui import ThemeEditor
        theme.apply(app, theme.find("graphite"), remember_choice=True)
        dlg = ThemeEditor(self.w, base=theme.current(), new=True)
        dlg.show()
        dlg._set_token("accent", "#ff3366")
        dlg._apply_live()                                           # live preview on the whole app
        self.assertEqual(theme.C["accent"], "#ff3366")
        dlg.reject()
        self.assertEqual(theme.current().id, "graphite")
        self.assertEqual(theme.C["accent"], theme.find("graphite")["accent"])

        dlg = ThemeEditor(self.w, base=theme.current(), new=True)
        dlg.name.setText("Hot Pink")
        dlg._set_token("accent", "#ff3366")
        dlg._set_token("window", "zzz")                             # ignored
        dlg._save()
        t = theme.current()
        self.assertEqual(t.name, "Hot Pink")
        self.assertEqual(t["accent"], "#ff3366")
        self.assertEqual(t["window"], theme.find("graphite")["window"])
        self.assertIn(t.id, [x.id for x in theme.user_themes()])
        self.assertEqual(theme.saved_theme().id, t.id)

        # editing that theme overwrites it in place
        dlg = ThemeEditor(self.w, base=t, new=False)
        dlg._set_token("text", "#ffffff")
        dlg._save()
        self.assertEqual(theme.current().id, t.id)
        self.assertEqual(len(theme.user_themes()), 1)
        self.assertEqual(theme.user_themes()[0]["text"], "#ffffff")

    def test_editor_generate_and_start_from(self):
        from lumen.themeui import ThemeEditor
        dlg = ThemeEditor(self.w, base=theme.current(), new=True)
        dlg._set_token("window", "#f2f2f2")
        dlg._set_token("text", "#202020")
        dlg._generate()
        self.assertFalse(theme.Theme("t", dlg.colors).dark)
        self.assertEqual(dlg.colors["window"], "#f2f2f2")
        item = next(dlg.bases.item(i) for i in range(dlg.bases.count())
                    if dlg.bases.item(i).text().startswith("Ember"))
        dlg._base_chosen(item)
        self.assertEqual(dlg.colors, theme.find("ember").colors)
        self.assertTrue(dlg.name.text().startswith("Ember"))
        dlg.grab()
        dlg.reject()


if __name__ == "__main__":
    unittest.main()
