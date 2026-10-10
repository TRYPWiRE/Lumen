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


def _check_runtimes(app):
    """Import every installed runtime pack's modules (and start the web engine) — used by --check-extensions."""
    import importlib
    from lumen import runtimes
    lines = []
    base = runtimes.runtimes_dir()
    for rid in sorted(os.listdir(base)):
        meta = runtimes.info(rid)
        if not meta:
            continue
        try:
            runtimes.activate(rid)
            for mod in meta.get("provides", []):
                importlib.import_module(mod)
            if rid == "qtwebengine":
                from PyQt6.QtCore import QUrl, QEventLoop, QTimer
                from PyQt6.QtWebEngineWidgets import QWebEngineView
                view = QWebEngineView()
                loop = QEventLoop()
                result = []
                view.loadFinished.connect(lambda ok: (result.append(ok), loop.quit()))
                view.setHtml("<title>ok</title><p>Lumen</p>")
                QTimer.singleShot(30000, loop.quit)
                loop.exec()
                if not (result and result[0]):
                    raise RuntimeError("the page didn't load")
            lines.append(f"runtime {rid} {meta.get('version')}: ok")
        except Exception as e:
            lines.append(f"runtime {rid}: FAILED {type(e).__name__}: {e}")
    return lines


def main():
    _windows_setup()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # lets extensions load Qt WebEngine (embedded browser) after start-up
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("Lumen")
    app.setOrganizationName("Lumen")

    from lumen import theme
    theme.apply(app)
    checking = "--check-extensions" in sys.argv
    splash = None
    if not checking and "--no-splash" not in sys.argv:
        from lumen.splash import Splash
        splash = Splash()
        splash.start()                       # visible before the heavy imports below
        splash.set_message("Loading tools and extensions…")
    from lumen.mainwindow import MainWindow
    win = MainWindow()
    if checking:
        # build/CI helper: report extension load status and exit (non-zero if any failed)
        bad = [e for e in win.extensions.items.values() if win.extensions.is_enabled(e.id) and not e.loaded]
        report = [f"{e.id} {e.version}: {'loaded' if e.loaded else e.error or 'disabled'}"
                  for e in win.extensions.items.values()]
        report += _check_runtimes(app)
        bad = bad or any("FAILED" in line for line in report)
        out = os.environ.get("LUMEN_CHECK_OUTPUT")      # windowed .exe has no console: write a file instead
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n".join(report) + "\n")
        elif sys.stdout:
            print("\n".join(report))
        sys.exit(1 if bad else 0)
    app.aboutToQuit.connect(win.shutdown_workspaces)
    _dark_title_bar(win)
    for path in [a for a in sys.argv[1:] if not a.startswith("--")]:
        if os.path.isfile(path):
            win.open_path(path)
    if splash is not None:
        splash.set_message("Ready")
        splash.finish(win, win.showMaximized)    # ~1 s on screen, then cross-fades into Lumen
    else:
        win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
