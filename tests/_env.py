"""Isolate tests from the real machine: no network checks, temp settings + data folders."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Qt's hidden "offscreen" window has no fonts of its own on Windows ("Qt no longer ships fonts"),
# so text would render as nothing. Point it at the system font folder instead.
if sys.platform == "win32" and "QT_QPA_FONTDIR" not in os.environ:
    os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

os.environ["LUMEN_OFFLINE"] = "1"
_tmp = tempfile.mkdtemp(prefix="lumen-tests-")
os.environ["LUMEN_SETTINGS"] = os.path.join(_tmp, "settings.ini")
os.environ["LUMEN_DATA_DIR"] = os.path.join(_tmp, "data")

# Hide harmless messages from the offscreen platform so real failures are easy to spot.
from PyQt6.QtCore import qInstallMessageHandler  # noqa: E402

_QUIET = ("propagateSizeHints", "does not support raise", "grabbing the keyboard", "grabbing the mouse")


def _qt_messages(mode, context, message):
    if not any(q in message for q in _QUIET):
        sys.stderr.write(message + "\n")


qInstallMessageHandler(_qt_messages)


def fonts_available():
    """True when Qt can actually draw text in the test environment."""
    from PyQt6.QtGui import QFontDatabase
    return bool(QFontDatabase.families())
