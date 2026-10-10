"""Runtime packs: big third-party libraries (Qt WebEngine, onnxruntime…) that some extensions need.

They're downloaded once (from GitHub Releases), unpacked to <data>/runtimes/<id>/ and put on the import
path at start-up, so the installer stays small and extensions can stay tiny.

A pack is a zip containing runtime.json plus files:
{
  "id": "qtwebengine", "version": "6.11.2", "qt": "6.11.2",
  "provides": ["PyQt6.QtWebEngineWidgets"],
  "python_paths": ["lib"],                 # added to sys.path
  "pyqt6_paths": ["lib/PyQt6"],            # added to PyQt6.__path__ (extra Qt modules)
  "dll_dirs": ["lib/PyQt6/Qt6/bin"],       # Windows DLL search + PATH (for helper processes)
  "env": {"QTWEBENGINEPROCESS_PATH": "lib/PyQt6/Qt6/bin/QtWebEngineProcess.exe"}
}
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile

from PyQt6.QtCore import qVersion

QT_VERSION_STR = qVersion()          # the Qt actually running (PyQt may be built against an older one)

from . import config, net

_active = {}


class RuntimeError_(Exception):
    pass


def runtimes_dir():
    d = os.path.join(config.data_dir(), "runtimes")
    os.makedirs(d, exist_ok=True)
    return d


def importable(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def info(rid):
    p = os.path.join(runtimes_dir(), rid, "runtime.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def installed_ok(rid, entry=None):
    """Installed and matching what the manifest (or this build's Qt) needs."""
    meta = info(rid)
    if meta is None:
        return False
    if meta.get("qt") and meta["qt"] != QT_VERSION_STR:
        return False
    if entry and entry.get("version") and str(meta.get("version")) != str(entry["version"]):
        return False
    return True


def satisfied(rid, provides=None):
    """True when the libraries are usable now (bundled, pip-installed, or an active/installed pack)."""
    if rid in _active:
        return True
    mods = provides or (info(rid) or {}).get("provides") or []
    if mods and all(importable(m) for m in mods):
        return True
    return installed_ok(rid) and activate(rid)


def activate(rid):
    """Put an installed pack on the import path. Safe to call more than once."""
    if rid in _active:
        return True
    meta = info(rid)
    if meta is None:
        return False
    if meta.get("qt") and meta["qt"] != QT_VERSION_STR:
        raise RuntimeError_(f"The {meta.get('name', rid)} pack was built for Qt {meta['qt']}, "
                            f"but this copy of Lumen uses Qt {QT_VERSION_STR}. Re-download it from Plugins.")
    root = os.path.join(runtimes_dir(), rid)
    for rel in meta.get("python_paths", []):
        p = os.path.join(root, rel)
        if p not in sys.path:
            sys.path.insert(0, p)
    if meta.get("pyqt6_paths"):
        import PyQt6
        for rel in meta["pyqt6_paths"]:
            p = os.path.join(root, rel)
            if p not in PyQt6.__path__:
                PyQt6.__path__.append(p)
    dll_dirs = [os.path.join(root, rel) for rel in meta.get("dll_dirs", [])]
    if dll_dirs:
        try:
            import PyQt6
            for sub in ("bin", "lib"):
                qt_dir = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", sub)
                if os.path.isdir(qt_dir):
                    dll_dirs.append(qt_dir)      # helper processes need Lumen's own Qt libraries too
            if getattr(sys, "_MEIPASS", None):
                dll_dirs.append(sys._MEIPASS)    # installed app: some Qt libraries sit at the top level
        except Exception:
            pass
        os.environ["PATH"] = os.pathsep.join(dll_dirs + [os.environ.get("PATH", "")])
        if sys.platform == "win32":
            for d in dll_dirs:
                if os.path.isdir(d):
                    os.add_dll_directory(d)
        else:
            os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(dll_dirs + [os.environ.get("LD_LIBRARY_PATH", "")])
    if sys.platform.startswith("linux"):
        # Linux reads LD_LIBRARY_PATH only at start-up, so load the pack's libraries up front
        import ctypes
        for rel in meta.get("preload", []):
            try:
                ctypes.CDLL(os.path.join(root, rel), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass
    for key, rel in meta.get("env", {}).items():
        os.environ.setdefault(key, os.path.join(root, rel))
    for key, value in meta.get("env_raw", {}).items():
        os.environ.setdefault(key, value)
    importlib.invalidate_caches()
    _active[rid] = meta
    return True


def install_zip(rid, zip_path):
    """Unpack a downloaded pack (replacing an older one)."""
    base = runtimes_dir()
    staging = tempfile.mkdtemp(prefix=f".{rid}-", dir=base)
    try:
        with zipfile.ZipFile(zip_path) as z:
            real = os.path.realpath(staging)
            for m in z.infolist():
                target = os.path.realpath(os.path.join(staging, m.filename))
                if not (target == real or target.startswith(real + os.sep)):
                    raise RuntimeError_(f"unsafe path in runtime pack: {m.filename}")
            for m in z.infolist():
                z.extract(m, staging)
                mode = (m.external_attr >> 16) & 0o777
                if mode and os.name != "nt":
                    os.chmod(os.path.join(staging, m.filename), mode)   # keep helper programs executable
        meta_path = os.path.join(staging, "runtime.json")
        if not os.path.isfile(meta_path):
            raise RuntimeError_("runtime.json missing from the pack")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("id") != rid:
            raise RuntimeError_(f"pack contains '{meta.get('id')}', expected '{rid}'")
        dest = os.path.join(base, rid)
        if rid in _active and os.path.isdir(dest):
            # in use by this process (Windows locks DLLs): finish on next start
            pending = dest + ".pending"
            shutil.rmtree(pending, ignore_errors=True)
            os.replace(staging, pending)
            return "pending"
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(staging, dest)
        return "installed"
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def finish_pending():
    """Swap in packs that were updated while in use (called at start-up)."""
    base = runtimes_dir()
    for name in os.listdir(base):
        if name.endswith(".pending"):
            rid = name[:-8]
            dest = os.path.join(base, rid)
            try:
                shutil.rmtree(dest, ignore_errors=True)
                os.replace(os.path.join(base, name), dest)
            except OSError:
                pass


def download_task(rid, entry):
    dest = os.path.join(tempfile.gettempdir(), "LumenRuntimes", f"{rid}-{entry.get('version', '')}.zip")
    return net.Task(net.download, entry["url"], dest, entry.get("sha256"), with_progress=True)


def describe(entry, rid):
    size = entry.get("size") or 0
    mb = f" ({size / 1048576:.0f} MB)" if size else ""
    return f"{entry.get('name', rid)}{mb}"
