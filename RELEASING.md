# Publishing Lumen on GitHub

Lumen checks `updates/manifest.json` in the GitHub repo every time it starts. That one file tells every
installed copy the newest app version and every extension's newest version.

```
updates/
  manifest.json                    <- the app reads this on startup
  extensions/basic-filters-1.0.0.zip
extensions/
  basic-filters/                   <- extension source (manifest.json + __init__.py)
installer/lumen.iss                <- Inno Setup script
```

## One-time setup

1. Install **Git** (https://git-scm.com), the **GitHub CLI** (https://cli.github.com) and **Inno Setup 6.3+**
   (https://jrsoftware.org/isdl.php).
2. That's it. The first time you run `publish.bat`, it opens your browser to sign in to GitHub. It then
   creates the public repo `TRYPWiRE/Lumen`, connects this folder to it and pushes everything.
   To use a different repo name, change `GITHUB_OWNER` / `GITHUB_REPO` in `lumen/config.py` and the URLs in
   `installer/lumen.iss` first.

## Releasing a new app version

1. Raise `__version__` in `lumen/__init__.py` (for example `0.3.0`).
2. Run `build.bat`. It runs the tests, builds the app, makes `release\LumenSetup-0.3.0.exe` and updates the manifest.
3. Run `publish.bat`. It creates the GitHub release `v0.3.0` with the installer attached, then pushes the manifest.

Within a few minutes, everyone's Lumen shows "Lumen 0.3.0 is available". Clicking **Update** downloads the
installer, checks its SHA-256, closes Lumen, upgrades silently and reopens it. Installed extensions and settings
are kept, because they live in `%APPDATA%\Lumen`.

publish.bat pushes the code and manifest, then creates the release a few seconds later. Anyone who clicks
Update in those few seconds gets a "couldn't download" message, and it works on the next try.

## Releasing an extension update (no app release needed)

1. Edit the code in `extensions/<id>/` and raise `"version"` in its `manifest.json`.
2. Run `publish_extensions.bat <id>`.

Users get the update on their next start: either the banner, or automatically if they've turned on
*Help ▸ Update Extensions Automatically*.

## Writing a new extension

Make a folder `extensions/my-thing/` containing two files.

`manifest.json`:

```json
{"id": "my-thing", "name": "My Thing", "version": "1.0.0", "author": "Kie",
 "description": "What it does.", "min_app": "0.2.0"}
```

`__init__.py`:

```python
def register(api):
    # A filter with a live-preview dialog (fn takes and returns a QImage)
    api.add_filter("Filter/Stylize", "Invert Red…", my_fn,
                   [{"key": "amount", "label": "Amount", "min": 0, "max": 100, "default": 50, "suffix": " %"}])
    api.add_menu_action("Image/Adjustments", "Do Thing", callback, shortcut="Ctrl+Alt+T")
    api.add_tool(MyTool)            # subclass api.Tool; group="brush" puts it in an existing slot
    api.add_panel("My Panel", widget)
```

Extensions can import `PyQt6`, `numpy` and `lumen`. Those are bundled in the installed app; other pip packages
aren't. `min_app` stops the extension from being offered to Lumen versions too old to run it. To test locally
without publishing, use *Plugins ▸ Extensions… ▸ Install from File…* with a zip of the folder.
