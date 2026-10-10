"""Optional extensions: installed per-user, downloaded from the GitHub-hosted manifest.

An extension is a folder (shipped as a .zip) containing:
    manifest.json   {"id", "name", "version", "description", "author", "min_app"}
    __init__.py     defines register(api) -- see lumen/extensions/api.py
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
import zipfile

from PyQt6.QtCore import QObject, pyqtSignal

from .. import __version__, config, net, versioning

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class ExtensionError(Exception):
    pass


def bundled_dir():
    """Extensions shipped inside the app (installed copy or source checkout)."""
    override = os.environ.get("LUMEN_BUNDLED_EXTENSIONS")
    if override is not None:
        return override
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "extensions")


class Installed:
    def __init__(self, path, manifest, builtin=False):
        self.builtin = builtin          # shipped with the app (can be updated, can't be deleted)
        self.path = path
        self.manifest = manifest
        self.id = manifest["id"]
        self.name = manifest.get("name") or self.id
        self.version = str(manifest.get("version") or "0.0.0")
        self.description = manifest.get("description", "")
        self.author = manifest.get("author", "")
        self.min_app = manifest.get("min_app", "")
        self.loaded = False
        self.error = None
        self.module = None

    def compatible(self):
        return versioning.compatible(self.min_app, __version__)


def read_manifest(folder):
    p = os.path.join(folder, "manifest.json")
    if not os.path.isfile(p):
        raise ExtensionError("manifest.json is missing")
    with open(p, encoding="utf-8") as f:
        m = json.load(f)
    if not isinstance(m, dict) or not ID_RE.match(str(m.get("id", ""))):
        raise ExtensionError("manifest.json needs a valid lowercase \"id\"")
    if not os.path.isfile(os.path.join(folder, "__init__.py")):
        raise ExtensionError("__init__.py is missing")
    return m


class ExtensionManager(QObject):
    changed = pyqtSignal()

    def __init__(self, settings, root=None, parent=None, bundled=None):
        super().__init__(parent)
        self.settings = settings
        self.root = root or config.extensions_dir()
        self.bundled = bundled if bundled is not None else bundled_dir()
        self.items = {}            # id -> Installed
        self.restart_needed = False
        self.api_factory = None    # callable(ext) -> ExtensionAPI, set by the window
        self.scan()

    # ------------------------------------------------------------ discovery
    def _candidates(self):
        """id -> (folder, manifest, builtin); a downloaded copy wins over the built-in one if not older."""
        out = {}
        for base, builtin in ((self.bundled, True), (self.root, False)):
            if not base or not os.path.isdir(base):
                continue
            for name in sorted(os.listdir(base)):
                folder = os.path.join(base, name)
                if name.startswith(".") or not os.path.isdir(folder):
                    continue
                try:
                    m = read_manifest(folder)
                except Exception:
                    continue
                prev = out.get(m["id"])
                if prev is None or not versioning.is_newer(prev[1].get("version"), m.get("version")):
                    out[m["id"]] = (folder, m, builtin or (prev is not None and prev[2]))
        return out

    def scan(self):
        found = {}
        for ext_id, (folder, m, builtin) in sorted(self._candidates().items()):
            old = self.items.get(m["id"])
            ext = Installed(folder, m, builtin)
            if old is not None:  # keep runtime state across rescans
                ext.loaded, ext.error, ext.module = old.loaded, old.error, old.module
                if old.loaded and old.version != ext.version:
                    ext.version_loaded = old.version
            found[ext.id] = ext
        self.items = found
        self.changed.emit()

    def installed_versions(self):
        return {i: e.version for i, e in self.items.items()}

    # ------------------------------------------------------------ enable/disable
    def disabled(self):
        v = self.settings.value("extensions/disabled", [])
        if isinstance(v, str):
            v = [v]
        return set(v or [])

    def is_enabled(self, ext_id):
        return ext_id not in self.disabled()

    def set_enabled(self, ext_id, on):
        d = self.disabled()
        (d.discard if on else d.add)(ext_id)
        self.settings.setValue("extensions/disabled", sorted(d))
        ext = self.items.get(ext_id)
        if ext and on and not ext.loaded:
            self.load(ext)
        elif ext and not on and ext.loaded:
            self.restart_needed = True
        self.changed.emit()

    # ------------------------------------------------------------ loading
    def load_all(self):
        for ext in self.items.values():
            if self.is_enabled(ext.id) and not ext.loaded:
                self.load(ext)
        self.changed.emit()

    def load(self, ext):
        if ext.loaded:
            return True
        if not ext.compatible():
            ext.error = f"Needs Lumen {ext.min_app} or newer"
            return False
        mod_name = "lumen_ext_" + re.sub(r"[^a-zA-Z0-9_]", "_", ext.id)
        try:
            spec = importlib.util.spec_from_file_location(
                mod_name, os.path.join(ext.path, "__init__.py"), submodule_search_locations=[ext.path])
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            if not hasattr(module, "register"):
                raise ExtensionError("no register(api) function")
            api = self.api_factory(ext) if self.api_factory else None
            module.register(api)
            ext.module, ext.loaded, ext.error = module, True, None
            return True
        except Exception as e:
            sys.modules.pop(mod_name, None)
            ext.error = f"{type(e).__name__}: {e}"
            ext.traceback = traceback.format_exc()
            return False

    # ------------------------------------------------------------ install / remove
    def install_zip(self, zip_path, expected_id=None):
        """Validate and unpack an extension zip. Returns (Installed, hot_loaded)."""
        staging = tempfile.mkdtemp(prefix=".install-", dir=self.root)
        try:
            with zipfile.ZipFile(zip_path) as z:
                for info in z.infolist():
                    target = os.path.realpath(os.path.join(staging, info.filename))
                    if not target.startswith(os.path.realpath(staging) + os.sep) and target != os.path.realpath(staging):
                        raise ExtensionError(f"unsafe path in zip: {info.filename}")
                z.extractall(staging)
            src = staging
            entries = [e for e in os.listdir(staging) if not e.startswith("__MACOSX")]
            if not os.path.isfile(os.path.join(staging, "manifest.json")) and len(entries) == 1 \
                    and os.path.isdir(os.path.join(staging, entries[0])):
                src = os.path.join(staging, entries[0])   # zip with a single top folder
            m = read_manifest(src)
            if expected_id and m["id"] != expected_id:
                raise ExtensionError(f"zip contains '{m['id']}', expected '{expected_id}'")
            if not versioning.compatible(m.get("min_app"), __version__):
                raise ExtensionError(f"needs Lumen {m.get('min_app')} or newer")
            dest = os.path.join(self.root, m["id"])
            was = self.items.get(m["id"])
            if os.path.exists(dest):
                old = dest + ".old"
                shutil.rmtree(old, ignore_errors=True)
                os.replace(dest, old)
                shutil.rmtree(old, ignore_errors=True)
            shutil.move(src, dest)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self.scan()
        ext = self.items[m["id"]]
        hot = False
        if was is not None and was.loaded:
            self.restart_needed = True       # old code still running until restart
        elif self.is_enabled(ext.id):
            hot = self.load(ext)
        self.changed.emit()
        return ext, hot

    def uninstall(self, ext_id):
        """Remove a downloaded extension. Built-in ones go back to the shipped version (or get disabled)."""
        ext = self.items.get(ext_id)
        if not ext:
            return
        user_copy = os.path.join(self.root, ext_id)
        if ext.builtin and not os.path.isdir(user_copy):
            self.set_enabled(ext_id, False)
            return
        if ext.loaded:
            self.restart_needed = True
        shutil.rmtree(user_copy, ignore_errors=True)
        self.scan()

    def download_task(self, entry):
        """Task that downloads a manifest entry's zip; connect succeeded -> install_zip."""
        dest = os.path.join(tempfile.gettempdir(), "LumenExtensions", f"{entry['id']}-{entry.get('version', '')}.zip")
        return net.Task(net.download, entry["url"], dest, entry.get("sha256"), with_progress=True)
