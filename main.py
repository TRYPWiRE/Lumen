"""Lumen launcher."""
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


_mutex = None


def _windows_setup():
    global _mutex
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Lumen.ImageEditor")
        # lets the installer/uninstaller know Lumen is running (name must match installer/lumen.iss)
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "LumenImageEditorMutex")
    except Exception:
        pass


def _dark_title_bar(win):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(win.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def main():
    _windows_setup()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Lumen")
    app.setOrganizationName("Lumen")

    from lumen import theme
    from lumen.mainwindow import MainWindow
    theme.apply(app)
    win = MainWindow()
    if "--check-extensions" in sys.argv:
        # build/CI helper: report extension load status and exit (non-zero if any failed)
        bad = [e for e in win.extensions.items.values() if win.extensions.is_enabled(e.id) and not e.loaded]
        for e in win.extensions.items.values() if sys.stdout else []:   # windowed .exe has no stdout
            print(f"{e.id} {e.version}: {'loaded' if e.loaded else e.error or 'disabled'}")
        sys.exit(1 if bad else 0)
    _dark_title_bar(win)
    win.showMaximized()
    for path in [a for a in sys.argv[1:] if not a.startswith("--")]:
        if os.path.isfile(path):
            win.open_path(path)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
