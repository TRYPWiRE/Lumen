"""Build the runtime packs (big libraries some extensions need) and list them in updates/manifest.json.

    python tools/build_runtimes.py                 # every pack, for Windows (win64)
    python tools/build_runtimes.py qtwebengine     # just one
    python tools/build_runtimes.py --platform linux64 --out build/rt   (used by the tests)

Packs are uploaded to the GitHub release tagged "runtimes" (publish_runtimes.bat does that) because
the web engine is bigger than GitHub allows for normal repo files. They are matched to the exact
Qt / PyQt6 versions installed here, which are the ones build.bat puts into Lumen.exe.
"""
import argparse
import glob
import hashlib
import importlib.metadata as md
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

PLATFORMS = {
    "win64": {"pip": ["--platform", "win_amd64"], "lib_ext": (".dll", ".pyd")},
    "linux64": {"pip": ["--platform", "manylinux_2_34_x86_64", "--platform", "manylinux_2_28_x86_64",
                        "--platform", "manylinux2014_x86_64", "--platform", "manylinux_2_17_x86_64"],
                "lib_ext": (".so",)},
}
# Qt / PyQt modules Lumen.exe always contains — never copied into a pack
CORE_QT = {"qt6core", "qt6gui", "qt6widgets", "qt6dbus", "qt6xcbqpa", "qt6waylandclient", "qt6egl"}
CORE_PYQT = {"QtCore", "QtGui", "QtWidgets", "sip"}


def versions():
    return md.version("PyQt6"), md.version("PyQt6-Qt6")


def pip_download(packages, dest, plat, deps=False):
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
    cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--python-version", pyver,
           "-d", dest, "-q"] + PLATFORMS[plat]["pip"] + ([] if deps else ["--no-deps"]) + packages
    subprocess.check_call(cmd)


def unzip_wheel(whl, dest, keep=None):
    with zipfile.ZipFile(whl) as z:
        for n in z.namelist():
            if ".dist-info/" in n or n.endswith("/"):
                continue
            if keep and not keep(n):
                continue
            z.extract(n, dest)
            mode = (z.getinfo(n).external_attr >> 16) & 0o777
            if mode and os.name != "nt":
                os.chmod(os.path.join(dest, n), mode)


def lib_key(name):
    """'Qt6Quick.dll' / 'libQt6Quick.so.6' -> 'qt6quick'."""
    base = os.path.basename(name).lower()
    base = re.sub(r"^lib", "", base)
    return re.sub(r"(\.so(\.\d+)*|\.dll|\.pyd)$", "", base).split(".abi3")[0]


def imported_libs(path, plat):
    if plat == "win64":
        import pefile
        try:
            pe = pefile.PE(path, fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            return [e.dll.decode() for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
        except Exception:
            return []
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\).*\[(.+?)\]", out)


def pyqt_imports(path):
    with open(path, "rb") as f:
        data = f.read()
    return set(m.decode() for m in re.findall(rb"PyQt6\.(Qt[A-Za-z0-9]+)", data))


def build_qtwebengine(plat, work):
    pyqt, qt = versions()
    wheels = os.path.join(work, "wheels")
    pip_download([f"PyQt6-WebEngine=={pyqt}", f"PyQt6-WebEngine-Qt6=={qt}", f"PyQt6=={pyqt}", f"PyQt6-Qt6=={qt}"],
                 wheels, plat)
    lib = os.path.join(work, "pack", "lib")
    for whl in glob.glob(os.path.join(wheels, "*webengine*.whl")):
        unzip_wheel(whl, lib)
    # the engine also needs Qt libraries / PyQt modules Lumen.exe doesn't contain: find them
    support = os.path.join(work, "support")
    for whl in glob.glob(os.path.join(wheels, "pyqt6-*.whl")) + glob.glob(os.path.join(wheels, "pyqt6_qt6-*.whl")):
        unzip_wheel(whl, support)
    exts = PLATFORMS[plat]["lib_ext"]
    avail = {}
    for path in glob.glob(os.path.join(support, "**", "*"), recursive=True):
        if os.path.isfile(path) and (path.endswith(exts) or re.search(r"\.so\.\d+$", path)):
            avail.setdefault(lib_key(path), path)
    have = {lib_key(p) for p in glob.glob(os.path.join(lib, "**", "*"), recursive=True) if os.path.isfile(p)}
    queue = [p for p in glob.glob(os.path.join(lib, "**", "*"), recursive=True)
             if os.path.isfile(p) and (p.endswith(exts) or re.search(r"\.so\.\d+$", p) or p.endswith(".exe"))]
    added, preload = [], []
    while queue:
        path = queue.pop()
        deps = [lib_key(d) for d in imported_libs(path, plat)]
        mods = pyqt_imports(path) if path.endswith((".pyd", ".so")) and "PyQt6" in path else set()
        for m in mods - CORE_PYQT:
            deps.append(lib_key(m))
        for key in deps:
            if key in have or key in CORE_QT or key not in avail:
                continue
            src = avail[key]
            rel = os.path.relpath(src, support)
            dst = os.path.join(lib, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            have.add(key)
            added.append(rel)
            queue.append(dst)
            if plat == "linux64" and "/Qt6/lib/" in "/" + rel.replace(os.sep, "/"):
                preload.append(os.path.join("lib", rel))
    if plat == "win64":
        qtbin = "lib/PyQt6/Qt6/bin"
        meta_paths = {"dll_dirs": [qtbin],
                      "env": {"QTWEBENGINEPROCESS_PATH": f"{qtbin}/QtWebEngineProcess.exe",
                              "QTWEBENGINE_RESOURCES_PATH": "lib/PyQt6/Qt6/resources",
                              "QTWEBENGINE_LOCALES_PATH": "lib/PyQt6/Qt6/translations/qtwebengine_locales"}}
    else:
        qtlib = "lib/PyQt6/Qt6/lib"
        engine_libs = sorted(os.path.relpath(p, os.path.join(work, "pack"))
                             for p in glob.glob(os.path.join(work, "pack", qtlib, "libQt6WebEngine*.so.6")))
        meta_paths = {"dll_dirs": [qtlib],
                      "preload": preload + engine_libs,
                      "env": {"QTWEBENGINEPROCESS_PATH": "lib/PyQt6/Qt6/libexec/QtWebEngineProcess",
                              "QTWEBENGINE_RESOURCES_PATH": "lib/PyQt6/Qt6/resources",
                              "QTWEBENGINE_LOCALES_PATH": "lib/PyQt6/Qt6/translations/qtwebengine_locales"}}
    meta = {"id": "qtwebengine", "name": "Web engine (Chromium)", "version": qt, "qt": qt, "pyqt": pyqt,
            "platform": plat, "provides": ["PyQt6.QtWebEngineWidgets"], "python_paths": [],
            "pyqt6_paths": ["lib/PyQt6"], "support_added": added}
    meta.update(meta_paths)
    return meta


def build_onnxruntime(plat, work):
    wheels = os.path.join(work, "wheels")
    pip_download(["onnxruntime"], wheels, plat, deps=True)
    lib = os.path.join(work, "pack", "lib")
    version = "0"
    for whl in glob.glob(os.path.join(wheels, "*.whl")):
        name = os.path.basename(whl).lower()
        if name.startswith("numpy-"):
            continue                     # Lumen already has numpy
        unzip_wheel(whl, lib)
        if name.startswith("onnxruntime-"):
            version = name.split("-")[1]
    capi = "lib/onnxruntime/capi"
    return {"id": "onnxruntime", "name": "AI engine (onnxruntime)", "version": version, "platform": plat,
            "provides": ["onnxruntime"], "python_paths": ["lib"], "dll_dirs": [capi]}


def _wheel_pack(plat, work, packages, skip=("numpy-",)):
    """Unzip pip wheels (with their dependencies, minus what Lumen already has) into pack/lib."""
    wheels = os.path.join(work, "wheels")
    pip_download(packages, wheels, plat, deps=True)
    lib = os.path.join(work, "pack", "lib")
    versions_ = {}
    for whl in sorted(glob.glob(os.path.join(wheels, "*.whl"))):
        name = os.path.basename(whl).lower()
        if name.startswith(tuple(skip)):
            continue
        unzip_wheel(whl, lib)
        versions_[name.split("-")[0]] = name.split("-")[1]
    return versions_


def build_pillow(plat, work):
    v = _wheel_pack(plat, work, ["pillow"])
    return {"id": "pillow", "name": "Imaging library (Pillow)", "version": v.get("pillow", "0"), "platform": plat,
            "provides": ["PIL"], "python_paths": ["lib"], "dll_dirs": []}


def build_camera_formats(plat, work):
    # Pillow comes from its own pack; numpy is already in Lumen
    v = _wheel_pack(plat, work, ["pillow-heif", "rawpy"], skip=("numpy-", "pillow-"))
    version = f"{v.get('pillow_heif', '0')}+{v.get('rawpy', '0')}"
    return {"id": "camera-formats", "name": "HEIC + camera RAW support", "version": version, "platform": plat,
            "provides": ["pillow_heif", "rawpy"], "python_paths": ["lib"],
            "dll_dirs": ["lib/pillow_heif.libs", "lib/rawpy.libs", "lib/rawpy"]}


BUILDERS = {"qtwebengine": build_qtwebengine, "onnxruntime": build_onnxruntime, "pillow": build_pillow,
            "camera-formats": build_camera_formats}


def zip_dir(folder, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, dirs, files in os.walk(folder):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, folder).replace(os.sep, "/"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(ids=None, plat="win64", out=None, manifest_path=None, base_url=None):
    from build_extensions import load_manifest, save_manifest, MANIFEST
    from lumen import config
    out = out or os.path.join(ROOT, "release", "runtimes")
    manifest_path = manifest_path or MANIFEST
    base_url = base_url or f"https://github.com/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/download/runtimes"
    os.makedirs(out, exist_ok=True)
    data = load_manifest(manifest_path)
    data.setdefault("runtimes", {})
    built = []
    for rid in ids or list(BUILDERS):
        work = tempfile.mkdtemp(prefix=f"rt-{rid}-")
        try:
            meta = BUILDERS[rid](plat, work)
            pack = os.path.join(work, "pack")
            with open(os.path.join(pack, "runtime.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            fname = f"{rid}-{meta['version']}-{plat}.zip"
            dest = os.path.join(out, fname)
            zip_dir(pack, dest)
            data["runtimes"].setdefault(rid, {})[plat] = {
                "name": meta["name"], "version": meta["version"], "qt": meta.get("qt", ""),
                "url": f"{base_url.rstrip('/')}/{fname}", "sha256": sha256(dest), "size": os.path.getsize(dest)}
            built.append(dest)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    save_manifest(data, manifest_path)
    return built


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--platform", default="win64", choices=list(PLATFORMS))
    ap.add_argument("--out")
    a = ap.parse_args()
    for path in build(a.ids or None, a.platform, a.out):
        print(f"Built {os.path.relpath(path, ROOT)}  ({os.path.getsize(path) / 1048576:.0f} MB)")
    print("Updated updates/manifest.json - run publish_runtimes.bat to upload the packs.")
