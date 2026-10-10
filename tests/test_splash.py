"""Start-up splash: shows for at least a second, then cross-fades into the main window."""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import _env  # noqa: F401

from PyQt6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication(["lumen-tests"])

from lumen import splash as splash_mod  # noqa: E402


class TestSplash(unittest.TestCase):
    def test_minimum_time_then_crossfade(self):
        s = splash_mod.Splash()
        win = QWidget()
        s.start()
        self.assertTrue(s.isVisible())
        s.set_message("Loading…")
        s.grab()                                         # draws without errors
        finished = []
        t0 = time.monotonic()
        s.finish(win, done=lambda: finished.append(time.monotonic()))
        while not finished and time.monotonic() - t0 < 5:
            app.processEvents()
            time.sleep(0.01)
        self.assertTrue(finished, "splash never finished")
        took = finished[0] - t0
        self.assertGreaterEqual(took, splash_mod.MIN_SHOW + splash_mod.FADE_MS / 1000 - 0.1)
        self.assertLess(took, splash_mod.MIN_SHOW + splash_mod.FADE_MS / 1000 + 1.0)
        self.assertTrue(win.isVisible())
        self.assertAlmostEqual(win.windowOpacity(), 1.0, places=2)
        self.assertFalse(s.isVisible())
        win.close()


if __name__ == "__main__":
    unittest.main()
