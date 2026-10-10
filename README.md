# Lumen v0.2

A Photoshop-style image editor written in Python with PyQt6.

## Run it

```
pip install -r requirements.txt
python main.py
```

You can also pass image paths on the command line (`python main.py photo.jpg`) or drag files onto the window.

## Updates & extensions (v0.2)

- **Checks on every start.** Lumen reads `updates/manifest.json` from GitHub in the background, so startup isn't
  slowed down. If something is newer, a blue bar appears under the options bar with an **Update** button.
  You can also check manually with *Help ▸ Check for Updates…*.
- **App updates.** The installed version downloads the new installer, checks its SHA-256 hash, closes,
  upgrades silently and reopens itself.
- **Extensions.** Optional features live outside the app. Manage them in *Plugins ▸ Extensions…*
  (Ctrl+Alt+X), where you can browse, install, update, disable and uninstall. Extensions are stored in
  `%APPDATA%\Lumen\extensions`, so they survive app updates.
- **First extension: Basic Filters.** Gaussian/Box Blur, Unsharp Mask, Sharpen, Add Noise and Mosaic, plus
  Brightness/Contrast, Posterize and Threshold. Every filter has a live preview.
- **Settings.** *Help ▸ Check for Updates on Startup* and *Help ▸ Update Extensions Automatically*.

See **RELEASING.md** for publishing to GitHub.

## Run the tests

Run `run_tests.bat`, or:

```
python -m unittest discover tests -v
```

There are 80 tests. They drive the real window with simulated mouse and keyboard input, covering every tool, undo/redo, file save/load and the image commands. They also include speed checks.

## Build the installer

Run `build.bat`. It runs the tests, then builds `dist\Lumen\Lumen.exe`, then makes the installer
`release\LumenSetup-<version>.exe`. The installer step needs Inno Setup 6.3+.

The installer installs Lumen for your user only, so no admin prompt is needed. It adds a Start Menu
entry and, optionally, a desktop icon and an "Open with" entry for image files.

## What's in v0.1

**Tools.** Shortcut keys are the same as Photoshop. Press Shift plus the key to cycle a group, or right-click / press and hold a toolbox button to see the hidden tools.

| Key | Tools |
|---|---|
| V | Move: drag selected pixels, arrow keys nudge, Enter applies, Esc cancels |
| M | Rectangular / Elliptical Marquee. Shift adds, Alt subtracts, Shift+Alt intersects. Drag inside a selection to move the outline |
| L | Lasso |
| C | Crop: handles, rule of thirds, Enter to commit |
| I | Eyedropper: point, 3×3 … 31×31 average. Alt+click sets the background colour |
| B | Brush (size, hardness, opacity) / Pencil (hard pixels) |
| E | Eraser: erases to transparency on transparent images, otherwise to the background colour |
| G | Paint Bucket (tolerance, contiguous) / Gradient (linear, radial, fg→bg or fg→transparent) |
| T | Type: font, size, bold and italic, with a live preview |
| U | Rectangle / Ellipse (fill + stroke) / Line. Shift constrains, Alt draws from the centre |
| H / Z | Hand / Zoom |

**Painting**
- Strokes don't build up within one stroke, so opacity works like Photoshop's.
- Painting stays inside the active selection.
- Alt+click picks a colour while painting.
- Click, then Shift+click, to draw a straight line.
- `[` and `]` change the brush size.

**Menus**
- **File:** New (with presets), Open, Open Recent, Save, Save As, Export As (PNG, JPEG, WebP, BMP, TIFF), Close.
- **Edit:** Undo/Redo, Cut/Copy/Paste, Clear, Fill with foreground/background.
- **Image:** Invert, Desaturate, Image Size, Canvas Size (with anchor), Rotate, Flip, Crop to Selection.
- **Select:** All, Deselect, Inverse.
- **View:** zoom commands, Fit on Screen, 100%.

**Interface**
- Multi-document tabs and a welcome screen with recent files.
- Panels: Color (spectrum), Swatches (add your own), Navigator, Info and History. Click a history step to jump back to it.
- A Photoshop-style colour picker.
- Hold Space to pan. Use Ctrl or Alt + mouse wheel to zoom.
- A pixel grid appears at 800% zoom and above.
- Press Tab to hide the panels.
