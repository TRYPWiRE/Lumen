"""Build dist/Lumen with PyInstaller (called by build.bat).

* Bundles only the extensions marked "builtin" (the rest are downloaded from Plugins ▸ Extensions).
* Includes Python's whole standard library, so downloaded extensions and runtime packs can import
  anything from it (PyInstaller otherwise only keeps what Lumen itself imports).
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_STDLIB = {"tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip", "venv", "pydoc_data",
               "antigravity", "this", "msilib", "nis", "crypt", "spwd", "ossaudiodev", "_tkinter", "tty", "pty",
               "curses", "_curses", "readline", "xxlimited", "xxlimited_35", "_testcapi", "_testinternalcapi",
               "_testbuffer", "_testimportmultiple", "_testmultiphase", "_xxtestfuzz", "_ctypes_test", "_testclinic",
               "_testsinglephase", "_testlimitedcapi", "_testexternalinspection", "_testconsole", "winsound"}


def stage_bundled(dest):
    src = os.path.join(ROOT, "extensions")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    staged = []
    for name in sorted(os.listdir(src)):
        mpath = os.path.join(src, name, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        with open(mpath, encoding="utf-8") as f:
            if not json.load(f).get("builtin"):
                continue
        shutil.copytree(os.path.join(src, name), os.path.join(dest, name),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        staged.append(name)
    return staged


def stdlib_modules():
    names = sorted(n for n in getattr(sys, "stdlib_module_names", ()) if n not in SKIP_STDLIB and not n.startswith("_test"))
    if sys.platform != "win32":
        names = [n for n in names if n not in ("winreg", "msvcrt", "_winapi", "_overlapped", "nt", "winsound",
                                               "_msi", "_wmi")]
    else:
        names = [n for n in names if n not in ("posix", "pwd", "grp", "termios", "fcntl", "resource", "syslog",
                                               "_posixsubprocess", "_posixshmem", "posixpath")] + ["posixpath"]
    return names


def main(argv=None):
    import importlib.util
    import PyInstaller.__main__
    build = os.path.join(ROOT, "build")
    staged_dir = os.path.join(build, "bundled_extensions")
    staged = stage_bundled(staged_dir)
    sep = ";" if sys.platform == "win32" else ":"
    args = ["--noconfirm", "--clean", "--windowed", "--name", "Lumen",
            "--add-data", f"{os.path.join(ROOT, 'assets')}{sep}assets",
            "--add-data", f"{staged_dir}{sep}extensions",
            "--distpath", os.path.join(ROOT, "dist"), "--workpath", os.path.join(build, "pyinstaller"),
            "--specpath", build]
    icon = os.path.join(ROOT, "assets", "lumen.ico")
    if os.path.exists(icon):
        args += ["--icon", icon]
    for mod in stdlib_modules():
        if importlib.util.find_spec(mod) is not None:
            args += ["--hidden-import", mod]
    for pkg in ("email", "http", "json", "urllib", "xml", "concurrent", "asyncio", "logging", "multiprocessing",
                "importlib", "encodings", "html", "sqlite3", "ctypes", "unittest", "zoneinfo", "tomllib", "wsgiref"):
        if importlib.util.find_spec(pkg) is not None:
            args += ["--collect-submodules", pkg]
    args.append(os.path.join(ROOT, "main.py"))
    args += list(argv or [])
    print(f"Bundling extensions: {', '.join(staged) or 'none'}")
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
