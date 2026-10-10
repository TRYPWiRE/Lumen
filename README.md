# Lumen v0.6.0

A Photoshop-style image editor written in Python with PyQt6.

## Run it

```
pip install -r requirements.txt
python main.py
```

You can also pass image paths on the command line (`python main.py photo.jpg`) or drag files onto the window.

## New in v0.6

Every tool from the File Converter is now a Lumen extension with its own tab. Install them from
*Plugins ▸ Extensions… ▸ Browse*. Each one also works with your Lumen documents: open results as documents
or as layers (animation frames become one layer each), or feed the open picture into a tool.

- **Batch Converter:** convert and resize images in batches to PNG, JPEG, WebP, AVIF, BMP, GIF, TIFF and ICO.
  It reads almost anything, including PSD, HEIC and camera RAW (Canon, Nikon, Sony, Fuji, Panasonic, Olympus,
  Pentax and more).
  - Add files, or a whole folder.
  - Social-media output sizes (Fit, Fill or Stretch), with a quality setting for JPEG, WebP and AVIF.
  - Animated GIFs and WebPs stay animated.
  - Save files one at a time, or use **Download All** to save next to the originals or into another folder.
  - Lumen's own **File ▸ Open** now reads HEIC, AVIF and camera RAW, and **Save As** writes GIF, AVIF and ICO.
- **Video to GIF:** pick the start, length, frame rate (5–30 fps) and width, then press **Generate Preview**
  to see the real GIF and its exact file size before saving. Also saves animated WebP. Works with MP4, MOV,
  MKV, WebM, AVI and more.
- **GIF Optimiser:** shrink a GIF with a Compression slider, or press a target: **Discord Emoji**
  (128 px, under 256 KB), **Discord Sticker** (exactly 320×320, under 512 KB), 1–500 MiB or a custom size.
  Original and result play side by side.
- **Image Optimiser:** the same for still images, from a file or straight from Lumen
  (*File ▸ Export ▸ Optimise for Web…*).
- **WebP to GIF:** convert batches of WebPs with Quality, Frames and Width controls plus target sizes.
- **Video to Image:** scrub through a video frame by frame, zoom the slider in for precise picking, then
  save, copy, open the frame in Lumen or add it as a layer. Can also export a run of frames (every Nth)
  as PNGs or layers.
- **WebP Flipbook:** turns animated WebPs and sprite sheets into GIFs.
  - Detects the frame grid automatically and shows it over the sheet, with an animation preview.
  - Keeps transparent backgrounds.
  - Can also export PNG frames, or open the frames as layers in Lumen.
- **Overlay Studio:** put one image over another, and animated GIFs/WebPs keep moving.
  - Drag the top image, or snap it to one of 9 positions, then scale it and set its opacity.
  - Either image can come straight from Lumen.
  - Save as PNG, GIF, WebP or AVIF, or open the result in Lumen.
- Every tool has an **Options** menu with *Delete original files after saving* and *Show file names after
  saving* (a list with Copy buttons). You can also drop files onto any tool.
- **Downloads:** these tools need Pillow, which downloads once (about 7 MB) the first time you install one.
  HEIC and camera RAW support downloads (about 8 MB) only when you first open such a file. The video
  decoder is built into Lumen.

## New in v0.5

- **Themes.** A new **Themes** menu restyles the whole of Lumen live: every panel, menu, icon and dialog.
  - **Themes ▸ Presets:** 13 built-in looks, each with a preview: Lumen Dark (the classic look), Graphite,
    Silver, Daylight, Midnight, OLED Black, Frost, Nightshade, Synthwave, Ember, Forest, Sakura and
    High Contrast.
  - **Themes ▸ Create Theme…:** start from any theme, then change any of the 24 interface colours with a
    live preview. *Quick start* builds a whole theme from just a background, text and accent colour, and a
    readability check warns when text gets hard to read. **Save Theme** adds it to **Themes ▸ My Themes**.
  - **Edit Current Theme…**, **Import Theme…** / **Export Current Theme…** (`.lumentheme` files you can
    share), **Delete Current Theme** and **Reset to Lumen Dark**.
  - Your choice is remembered on every start-up and survives updates. Saved themes are kept in your user
    folder (`%APPDATA%\Lumen\themes`), not the install folder.
- Extensions can read the theme's colours (`api.theme_colors()`) and react to `api.on("theme_changed", …)`
  (extension API 4). Web Images Extractor 1.0.2 and Background Remover 1.0.1 follow the theme.

## New in v0.4.1

- **Splash screen.** It shows for about a second while Lumen loads, then fades into the app. Start Lumen
  with `--no-splash` to skip it.

## New in v0.4

- **Brush cursor fixed.** Brush, Pencil and Eraser show the brush outline as the actual mouse pointer, like
  Photoshop. Very large brushes get a drawn outline plus a crosshair.
- **Workspace tabs.** Extensions can add their own top-level tab next to **Lumen**. The tab bar only appears
  once you install one. Lumen's tools and shortcuts switch off while another tab is in front, so typing
  never triggers tool shortcuts.
- **New extensions** (install them from *Plugins ▸ Extensions… ▸ Browse*):
  - **Web Images Extractor:** a browser with tabs in its own workspace. *Collect* or *Scroll + Collect* every
    image a page shows, including lazy-loaded images, CSS backgrounds and og:image. Filter out small icons.
    Then send any image to Lumen with **Add as Layer**, select several and add them in one step, open one as
    a new document, or save it (original file, PNG, JPEG or WebP).
  - **Background Remover:** its own workspace with AI subject detection (U²-Net, three models), a magic
    wand, erase/restore brushes, *clear from the edges*, and soften/tighten/grow edges. Use **Use Active
    Layer** to bring a layer in, then **Apply to the Original Layer** or **Add as New Layer** to send the
    result back. It also adds **Layer ▸ Remove Background** and **Select ▸ Subject**, like Photoshop.
  - **Adjustments Pro:**
    - Levels (Ctrl+L), Curves (Ctrl+M, with a curve editor), Exposure, Vibrance and Hue/Saturation (Ctrl+U).
    - Color Balance (Ctrl+B), Black & White, Photo Filter, Gradient Map, Shadows/Highlights and Equalize.
    - Auto Tone, Auto Contrast and Auto Color.
  - **Creative Filters:**
    - Motion and Radial Blur.
    - Twirl, Pinch, Spherize, Ripple, Wave and Polar Coordinates.
    - Median and Dust & Scratches.
    - Color Halftone and Crystallize.
    - Clouds, Difference Clouds and Vignette.
    - Emboss, Find Edges, Oil Paint, Solarize and Diffuse.
    - High Pass, Minimum, Maximum and Offset.
  - **Layer Effects:** Drop Shadow, Outer Glow, Inner Shadow, Inner Glow, Stroke, Color Overlay, Gradient
    Overlay and Bevel & Emboss. Each one goes on its own layer and has a live preview.
- **Runtime packs.** The browser engine (134 MB) and the AI engine (14 MB) aren't part of the installer.
  The extensions that need them download them once, from GitHub Releases, when you install the extension.

## New in v0.3

- **Layers, like Photoshop.** The Layers panel has blend modes (all 27 of Photoshop's), Opacity, Fill and lock
  buttons. You can show or hide a layer with the eye (Alt+click shows only that layer), rename it by
  double-clicking, and drag layers to reorder them. Ctrl+click a thumbnail to load its pixels as a selection.
  Right-click a layer for more options.
- **Background layer.** A new document starts with a locked *Background*. Double-click it to make it a normal
  layer.
- **Layer menu.** New Layer (Shift+Ctrl+N), Layer via Copy/Cut (Ctrl+J / Shift+Ctrl+J), Duplicate, Delete,
  Rename, Rasterize Type and Arrange (Ctrl+[ / Ctrl+]). Also Merge Down (Ctrl+E), Merge Visible (Shift+Ctrl+E)
  and Flatten Image. Alt+[ and Alt+] select the layer below or above.
- **Type tool.** Click on the image and type straight onto it. You get a caret, you can select text, and
  arrows, Home/End and copy/paste all work. Ctrl+Enter or ✓ commits; Esc cancels. Clicking existing text edits
  it, and Ctrl+drag while typing moves it. Font, style, size, alignment and colour live in the options bar and
  apply to the selected type layer.
- **Move tool.** Moves the whole layer, or only the selected pixels if there's a selection. It has an
  *Auto-Select Layer* option, and Ctrl+click picks the layer under the cursor. Type layers stay editable after
  moving.
- **Paste** goes onto a new layer, like Photoshop. **Copy Merged** (Shift+Ctrl+C) copies all visible layers.
  Pressing **Delete** with no selection deletes the layer.
- **Number keys** set opacity: 5 = 50%, 0 = 100%, two quick digits for an exact value. This changes the layer's
  opacity, or the tool's opacity when a painting tool is selected.
- **Shapes** go onto their own new layer (*Shape* mode) or the current layer (*Pixels* mode).
- **PSD files.** Open and save .psd with layers, names, blend modes, opacity, fill, visibility and locks. Type
  layers reopen as editable text in Lumen. Saving a layered image as PNG or JPEG takes you to Save As (PSD).
- **Filters fixed.** They were working on an empty copy of the image. Basic Filters now also ships with the
  app, so it works offline and out of the box, and can still be updated from GitHub.

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

There are 125 tests. They drive the real window with simulated mouse and keyboard input, covering every tool, undo/redo, file save/load and the image commands. They also include speed checks.

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
| T | Type: click and type directly on the image (editable type layers) |
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
