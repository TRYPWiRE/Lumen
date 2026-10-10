"""The file-conversion tools (Batch Converter, Video to GIF, GIF / Image Optimiser, WebP to GIF, Video to Image,
WebP Flipbook, Overlay Studio) and the shared lumen.media toolkit they're built on."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from test_extension_packs import Base, app  # noqa: E402  (sets up the app, MainWindow and patches)
import _media  # noqa: E402

from PyQt6.QtCore import QSize  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QMessageBox, QFileDialog  # noqa: E402

from lumen import media, theme  # noqa: E402

HAS_PIL = media.pil_available()
needs_pil = unittest.skipUnless(HAS_PIL, "Pillow isn't installed here (it's a download in Lumen)")


def pil(path):
    """Read what a test needs from an image file and close it again."""
    from types import SimpleNamespace
    with media.PIL.Image.open(path) as im:
        snap = SimpleNamespace(size=im.size, format=im.format, mode=im.mode, info=dict(im.info),
                               n_frames=getattr(im, "n_frames", 1))
        im.seek(0)
        snap.first = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im.copy()
    return snap


def close(a, b, tol=14):
    a, b = QColor(a), QColor(b)
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) <= tol


class ToolBase(Base):
    ext = None

    def setUp(self):
        super().setUp()
        self.media_dir = tempfile.mkdtemp(prefix="lumen-media-")
        media.set_flag(media.DELETE_ORIGINALS, False)
        media.set_flag(media.SHOW_FILENAMES, False)
        self.patch(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        self.patch(QMessageBox, "critical", staticmethod(lambda *a, **k: self.boxes.append(a)))
        self.page = None
        if self.ext:
            e = self.install(self.ext)
            self.assertTrue(e.loaded, e.error)
            self.page = next(w for t, w in self.w.workspaces if t == e.name)
            self.w.show_workspace(self.page)
            app.processEvents()

    def tearDown(self):
        media.wait_all()
        if self.page is not None:
            self.page.shutdown()
        super().tearDown()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.media_dir, name)

    def assertNoErrors(self):
        self.assertEqual([b for b in self.boxes if b and "fail" in str(b[1]).lower()], [])


# ====================================================================== shared toolkit
@needs_pil
class TestMediaKit(unittest.TestCase):
    def test_sizes_and_resize_modes(self):
        self.assertEqual(media.format_size(512), "512 B")
        self.assertEqual(media.format_size(1536), "1.5 KB")
        self.assertIn("50% smaller", media.size_change(500, 1000))
        Image = media.PIL.Image
        im = Image.new("RGBA", (200, 100), (255, 0, 0, 255))
        fit = media.resize_to_spec(im, {"size": (100, 100), "mode": "fit"})
        self.assertEqual(fit.size, (100, 100))
        self.assertEqual(fit.getpixel((50, 10))[3], 0)          # padded = see-through
        self.assertEqual(fit.getpixel((50, 50))[:3], (255, 0, 0))
        fill = media.resize_to_spec(im, {"size": (100, 100), "mode": "fill"})
        self.assertEqual(fill.getpixel((50, 2))[3], 255)        # cropped, no padding
        self.assertEqual(media.resize_to_spec(im, {"size": (50, 70), "mode": "stretch"}).size, (50, 70))
        small = Image.new("RGBA", (10, 10), (0, 0, 255, 255))
        no_up = media.resize_to_spec(small, {"size": (100, 100), "mode": "fit", "upscale": False})
        self.assertEqual(no_up.getpixel((50, 50))[:3], (0, 0, 255))
        self.assertEqual(no_up.getpixel((10, 10))[3], 0)        # stayed 10px in the middle
        self.assertTrue(media.spec_adds_transparency({"size": (1, 1), "mode": "fit"}))
        self.assertIsNone(media.resize_to_spec(None, None))

    def test_resize_widget_specs(self):
        for compact in (False, True):
            r = media.ResizeOptions(compact=compact)
            self.assertIsNone(r.spec())
            r.set_spec({"size": (1080, 1350), "mode": "fill", "upscale": False})
            self.assertEqual(r.spec(), {"size": (1080, 1350), "mode": "fill", "upscale": False})
            r.set_spec({"size": (333, 222), "mode": "stretch"})
            self.assertEqual(r.spec()["size"], (333, 222))
            self.assertTrue(r.w.isEnabled())

    def test_gif_keeps_one_transparent_index(self):
        path = tempfile.mktemp(suffix=".gif")
        _media.animated(path, n=5)
        frames, durs = media.read_frames(path)
        self.assertEqual(len(frames), 5)
        out = tempfile.mktemp(suffix=".gif")
        media.save_gif(frames, durs, out, colors=64)
        with media.PIL.Image.open(out) as g:
            self.assertEqual(g.n_frames, 5)
            self.assertIsNotNone(g.info.get("transparency"))
            for i in range(5):
                g.seek(i)
                self.assertEqual(g.convert("RGBA").getpixel((2, 2))[3], 0)    # corner stays see-through
        os.remove(path)
        os.remove(out)

    def test_qimage_pil_roundtrip(self):
        q = QImage(7, 5, QImage.Format.Format_ARGB32)
        q.fill(QColor(10, 200, 30, 128))
        p = media.qimage_to_pil(q)
        self.assertEqual(p.size, (7, 5))
        back = media.pil_to_qimage(p)
        c = back.pixelColor(3, 3)
        self.assertEqual((c.green(), c.alpha()), (200, 128))

    def test_animation_view_plays_and_paints(self):
        v = media.AnimationView()
        v.resize(200, 150)
        frames = [_media.color_frame(i, 40, 30) for i in range(3)]
        v.set_frames(frames, [30, 30, 30])
        self.assertTrue(v.playing)
        v.grab()
        v.step(1)
        self.assertEqual(v.index, 1)
        self.assertFalse(v.playing)
        path = tempfile.mktemp(suffix=".gif")
        _media.animated(path, n=4)
        self.assertEqual(v.load_file(path), 4)
        os.remove(path)


class TestVideoReader(unittest.TestCase):
    def test_exact_frames_from_a_video(self):
        path = tempfile.mktemp(suffix=".avi")
        _media.write_avi(path, [_media.color_frame(i) for i in range(10)], fps=10)
        r = media.VideoReader(path).open()
        try:
            self.assertAlmostEqual(r.duration, 1.0, delta=0.15)
            self.assertEqual(round(r.fps), 10)
            self.assertEqual(r.size, QSize(160, 120))
            for i in (0, 4, 9, 4, 0):
                self.assertTrue(close(r.frame(i).pixelColor(80, 60), _media.FRAME_COLORS[i]), i)
            frames = r.frames(0.2, 0.5, 10, width=80)
            self.assertEqual(len(frames), 5)
            self.assertEqual(frames[0].width(), 80)
            self.assertTrue(close(frames[0].pixelColor(40, 30), _media.FRAME_COLORS[2]))
        finally:
            r.close()
            os.remove(path)

    def test_not_a_video(self):
        path = tempfile.mktemp(suffix=".mp4")
        with open(path, "wb") as f:
            f.write(b"this is not a video" * 50)
        with self.assertRaises(ValueError):
            media.VideoReader(path).open(timeout_ms=5000)
        os.remove(path)


# ====================================================================== GIF Optimiser
@needs_pil
class TestGifOptimiser(ToolBase):
    ext = "gif-optimiser"

    def test_compress_target_and_discord_presets(self):
        from importlib import import_module
        src = _media.animated(self.path("anim.gif"), n=12, w=300, h=200)
        p = self.page
        self.assertTrue(p.load(src))
        self.assertEqual(len(p.before.frames), 12)
        self.assertTrue(p.optimise_btn.isEnabled())
        p.level.setValue(85)                       # > 80: every 3rd frame, fewer colours, smaller
        p.optimise()
        media.wait_all()
        self.assertIsNotNone(p.result)
        g = pil(p.result)
        self.assertEqual(g.n_frames, 4)
        self.assertLess(g.size[0], 300)
        # Discord sticker: exactly 320×320 and under 512 KB
        p.target(media.DISCORD_STICKER_MAX_BYTES, media.DISCORD_STICKER_SIZE_PX)
        media.wait_all()
        g = pil(p.result)
        self.assertEqual(g.size, (320, 320))
        self.assertLessEqual(os.path.getsize(p.result), media.DISCORD_STICKER_MAX_BYTES)
        # an impossible target still finishes, and says so
        self.boxes.clear()
        p.target(10, 0)
        media.wait_all()
        self.assertTrue(any("target" in str(b[1]).lower() for b in self.boxes))
        # save next to the source, with -optimized
        self.assertTrue(p.save_to(p.default_out()))
        self.assertTrue(os.path.isfile(self.path("anim-optimized.gif")))
        self.assertTrue(os.path.isfile(src))       # originals kept unless the option is on

    def test_output_size_spec_and_delete_original(self):
        src = _media.animated(self.path("x.gif"), n=4)
        p = self.page
        p.load(src)
        p.resize.set_spec({"size": (512, 512), "mode": "fit"})
        p.optimise()
        media.wait_all()
        self.assertEqual(pil(p.result).size, (512, 512))
        media.set_flag(media.DELETE_ORIGINALS, True)
        try:
            p.save_to(self.path("out.gif"))
        finally:
            media.set_flag(media.DELETE_ORIGINALS, False)
        self.assertFalse(os.path.exists(src))
        self.assertTrue(os.path.exists(self.path("out.gif")))

    def test_open_result_in_lumen_as_layers(self):
        p = self.page
        p.load(_media.animated(self.path("y.gif"), n=5))
        p.optimise()
        media.wait_all()
        n = len(p.after.frames)
        p.open_in_lumen()
        d = self.w.current_doc()
        self.assertIsNotNone(d)
        self.assertEqual(len(d.layers), n)
        self.assertIs(self.w.workspace_stack.currentIndex(), 0)


# ====================================================================== Image Optimiser
@needs_pil
class TestImageOptimiser(ToolBase):
    ext = "image-optimiser"

    def test_opaque_becomes_smaller_jpeg_alpha_stays_png(self):
        p = self.page
        src = _media.photo(self.path("photo.png"))
        p.load(src)
        p.level.setValue(60)
        p.optimise()
        media.wait_all()
        self.assertTrue(p.result.endswith(".jpg"))
        self.assertLess(os.path.getsize(p.result), os.path.getsize(src))
        alpha = _media.photo(self.path("alpha.png"), alpha=True)
        p.load(alpha)
        p.optimise()
        media.wait_all()
        self.assertTrue(p.result.endswith(".png"))
        p.target(media.DISCORD_EMOJI_MAX_BYTES, media.DISCORD_EMOJI_SIZE_PX)
        media.wait_all()
        im = pil(p.result)
        self.assertEqual(im.size, (128, 128))
        self.assertLessEqual(os.path.getsize(p.result), media.DISCORD_EMOJI_MAX_BYTES)

    def test_from_lumen_document(self):
        self.doc_with_picture(300, 200)
        p = self.page
        p.use_lumen()
        self.assertTrue(p.lumen_source)
        self.assertEqual(p.before.frames[0].size(), QSize(300, 200))
        p.optimise()
        media.wait_all()
        dest = self.path("from-lumen" + os.path.splitext(p.result)[1])
        self.assertTrue(p.save_to(dest))
        self.assertTrue(os.path.isfile(dest))

    def test_file_export_menu_entry(self):
        self.doc_with_picture()
        acts = [a.text() for a in self.w.menu_path("File/Export").actions()]
        self.assertIn("Optimise for Web…", acts)
        file_menu = self.w.menus["file"]
        texts = [a.text() for a in file_menu.actions()]
        self.assertLess(texts.index("Export"), texts.index("Exit"))     # above Exit, like Photoshop


# ====================================================================== WebP to GIF
@needs_pil
class TestWebpToGif(ToolBase):
    ext = "webp-to-gif"

    def test_batch_convert_frames_quality_and_save_all(self):
        p = self.page
        a = _media.animated(self.path("a.webp"), n=10, fmt="WEBP", duration=50)
        b = _media.animated(self.path("b.webp"), n=4, fmt="WEBP", transparent=False)
        self.assertEqual(len(p.add([a, b])), 2)
        self.assertEqual(p.add([a]), [])                   # no duplicates
        p.frames.setValue(50)                              # keep every 2nd frame, timing kept
        p.convert()
        media.wait_all()
        res = p.queue.results()
        self.assertEqual(set(res), {a, b})
        g = pil(res[a])
        self.assertEqual(g.n_frames, 5)
        self.assertEqual(g.info.get("duration"), 100)
        p.preview(a)
        self.assertEqual(len(p.view.frames), 5)
        p.save_all()
        self.assertTrue(os.path.isfile(self.path("a.gif")))
        self.assertTrue(os.path.isfile(self.path("b.gif")))
        p.clear()
        self.assertEqual(p.queue.results(), {})

    def test_target_size_and_width(self):
        p = self.page
        a = _media.animated(self.path("w.webp"), n=6, w=300, h=150, fmt="WEBP")
        p.add([a])
        p.keep_width.setChecked(False)
        p.width.setValue(150)
        p.convert(target=5 * media.MIB)
        media.wait_all()
        g = pil(p.queue.results()[a])
        self.assertEqual(g.size, (150, 75))
        p.open_in_lumen(a)
        self.assertEqual(len(self.w.current_doc().layers), 6)


# ====================================================================== Video to GIF
@needs_pil
class TestVideoToGif(ToolBase):
    ext = "video-to-gif"

    def test_trim_fps_width_preview_and_save(self):
        video = _media.write_avi(self.path("clip.avi"), [_media.color_frame(i) for i in range(10)], fps=10)
        p = self.page
        self.assertTrue(p.load(video))
        self.assertTrue(p.generate_btn.isEnabled())
        self.assertIsNotNone(p.start_view.frames)
        p.start.setValue(2)            # 0.2 s
        p.length.setValue(5)           # 0.5 s
        p.fps.setValue(10)
        p.keep_width.setChecked(False)
        p.width.setValue(100)
        p.generate()
        media.wait_all()
        self.assertIsNotNone(p.result, self.boxes)
        g = pil(p.result)
        self.assertEqual(g.n_frames, 5)
        self.assertEqual(g.size[0], 100)
        self.assertTrue(close(QColor(*g.first.convert("RGB").getpixel((50, 37))), _media.FRAME_COLORS[2], 30))
        self.assertIn("Output file size", p.size_label.text())
        self.assertTrue(p.save_to(p.default_out()))
        self.assertTrue(os.path.isfile(self.path("clip.gif")))
        p.open_in_lumen()
        self.assertEqual(len(self.w.current_doc().layers), 5)

    def test_webp_output(self):
        video = _media.write_avi(self.path("c2.avi"), [_media.color_frame(i) for i in range(6)], fps=10)
        p = self.page
        p.load(video)
        p.fmt.setCurrentIndex(1)
        p.generate()
        media.wait_all()
        self.assertTrue(p.result.endswith(".webp"))
        self.assertEqual(pil(p.result).n_frames, 6)

    def test_bad_video(self):
        bad = self.path("bad.mp4")
        with open(bad, "wb") as f:
            f.write(b"nope" * 100)
        self.assertFalse(self.page.load(bad))
        self.assertTrue(self.boxes)
        self.assertFalse(self.page.generate_btn.isEnabled())


# ====================================================================== Video to Image
class TestVideoToImage(ToolBase):
    ext = "video-to-image"

    def test_scrub_zoom_save_and_layers(self):
        video = _media.write_avi(self.path("v.avi"), [_media.color_frame(i) for i in range(10)], fps=10)
        p = self.page
        self.assertTrue(p.load(video))
        self.assertTrue(close(p.current.pixelColor(80, 60), _media.FRAME_COLORS[0]))
        p.slider.setValue(6)
        p._timer.timeout.emit()
        self.assertEqual(p.current_index, 6)
        self.assertTrue(close(p.current.pixelColor(80, 60), _media.FRAME_COLORS[6]))
        p.step(1)
        p._timer.timeout.emit()
        self.assertEqual(p.current_index, 7)
        p.zoom(4)                                   # never narrower than 10 frames
        self.assertEqual(p.window_size, 10)
        self.assertTrue(p.save_to(p.default_out()))
        self.assertTrue(os.path.isfile(self.path("v-frame7.png")))
        self.assertTrue(p.save_to(self.path("f.jpg")))
        p.copy()
        p.open_in_lumen()
        d = self.w.current_doc()
        self.assertEqual((d.width, d.height), (160, 120))
        p.add_layer()
        self.assertEqual(len(d.layers), 2)
        # a run of frames as layers
        p.from_spin.setValue(2)
        p.to_spin.setValue(8)
        p.every.setValue(3)
        p.seq_as.setCurrentIndex(1)
        imgs = p.export_run()
        self.assertEqual(len(imgs), 3)
        self.assertEqual([L.name for L in self.w.current_doc().layers], ["Frame 2", "Frame 5", "Frame 8"])

    def test_run_to_png_folder(self):
        video = _media.write_avi(self.path("w.avi"), [_media.color_frame(i) for i in range(10)], fps=10)
        p = self.page
        p.load(video)
        p.every.setValue(5)
        self.patch(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: self.media_dir))
        folder = p.export_run()
        self.assertEqual(sorted(os.listdir(folder)), ["frame_00000.png", "frame_00005.png"])


# ====================================================================== WebP Flipbook
@needs_pil
class TestFlipbook(ToolBase):
    ext = "webp-flipbook"

    def test_detect_grid_convert_png_and_layers(self):
        sheet = _media.sprite_sheet(self.path("sheet.png"), cols=4, rows=2)
        p = self.page
        self.assertTrue(p.load(sheet))
        self.assertEqual((p.cols_edit.text(), p.rows_edit.text()), ("4", "2"))
        self.assertEqual(p.grid(), (4, 2))
        p.view.grab()                                  # draws the grid overlay
        p.preview_animation()
        self.assertEqual(len(p.view.frames), 8)
        p.toggle_animation()
        self.assertEqual(len(p.view.frames), 1)
        p.export_frames.setChecked(True)
        p.start(__import__(type(p).__module__ + ".flipbook", fromlist=["x"]).gif_job)
        media.wait_all()
        r = p.last_result
        g = pil(r["gif"])
        self.assertEqual(g.n_frames, 8)
        self.assertEqual(g.size, (64, 64))
        self.assertIn("transparency", g.info)
        self.assertEqual(len(os.listdir(r["folder"])), 8)
        p.open_layers()
        self.assertEqual(len(self.w.current_doc().layers), 8)

    def test_manual_grid_errors_and_animated_webp(self):
        p = self.page
        p.load(_media.sprite_sheet(self.path("s2.png"), cols=3, rows=1))
        p.cols_edit.setText("5")
        p.rows_edit.setText("1")
        self.boxes.clear()
        p.preview_animation()
        self.assertTrue(any("divide" in str(b[2]) for b in self.boxes))
        p.cols_edit.setText("x")
        with self.assertRaises(ValueError):
            p.parse_grid()
        anim = _media.animated(self.path("a.webp"), n=7, fmt="WEBP")
        p.load(anim)
        self.assertTrue(p.animated)
        self.assertFalse(p.cols_edit.isEnabled())
        self.assertEqual(len(p.view.frames), 7)

    def test_from_lumen(self):
        d = self.doc_with_picture(256, 128)
        p = self.page
        p.use_lumen()
        self.assertTrue(p.from_lumen)
        p.cols_edit.setText("2")
        p.rows_edit.setText("1")
        p.output_dir = self.media_dir
        p.start(__import__(type(p).__module__ + ".flipbook", fromlist=["x"]).gif_job)
        media.wait_all()
        self.assertEqual(pil(p.last_result["gif"]).n_frames, 2)


# ====================================================================== Overlay Studio
@needs_pil
class TestOverlayStudio(ToolBase):
    ext = "overlay-studio"

    def wait_layers(self):
        media.wait_all()
        app.processEvents()

    def test_place_scale_animate_and_save(self):
        p = self.page
        bg = _media.animated(self.path("bg.gif"), n=4, w=200, h=100, transparent=False, duration=100)
        fg = self.path("fg.png")
        media.PIL.Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(fg)
        p.load_path("bg", bg)
        p.load_path("fg", fg)
        self.wait_layers()
        self.assertIsNotNone(p.bg)
        self.assertIsNotNone(p.fg_item)
        p.apply_preset(("r", "b"))
        self.assertEqual(p.fg_pos, (200 - 40 - 20, 100 - 40 - 20))
        p.scale_spin.setValue(50)                    # anchored: stays bottom-right
        self.assertEqual(p.fg_pos, (200 - 20 - 20, 100 - 20 - 20))
        p.x_spin.setValue(10)                        # manual move drops the anchor
        self.assertIsNone(p.anchor)
        p.x_spin.setValue(-50)                       # kept inside
        self.assertEqual(p.fg_pos[0], 0)
        frames, durs = p.render()
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[0].getpixel((5, 70))[:3], (255, 0, 0))
        p.opacity.setValue(50)
        frames, _ = p.render()
        self.assertGreater(frames[0].getpixel((5, 70))[1], 60)     # half see-through red over white = pink
        p.fmt.setCurrentText("GIF")
        p.save(self.path("out.gif"))
        media.wait_all()
        self.assertEqual(pil(self.path("out.gif")).n_frames, 4)
        p.fmt.setCurrentText("PNG")
        p.save(self.path("still.png"))
        media.wait_all()
        self.assertEqual(pil(self.path("still.png")).size, (200, 100))
        p.open_in_lumen()
        self.assertEqual(len(self.w.current_doc().layers), 4)

    def test_lumen_sources_swap_and_clear(self):
        self.doc_with_picture(300, 200)
        p = self.page
        p.from_lumen("bg")
        self.wait_layers()
        self.assertEqual(p.bg.size, (300, 200))
        fg = self.path("small.png")
        media.PIL.Image.new("RGBA", (500, 500), (0, 255, 0, 255)).save(fg)
        p.load_path("fg", fg)
        self.wait_layers()
        self.assertLess(p.scale_spin.value(), 100)    # bigger than the background: auto-shrunk
        p.swap()
        self.assertEqual(p.bg.size, (500, 500))
        p.clear("fg")
        self.assertIsNone(p.fg_item)
        theme.apply(app, theme.find("daylight"))      # follows the theme
        p.grab()
        theme.apply(app, theme.default_theme())


# ====================================================================== Batch Converter
@needs_pil
class TestBatchConverter(ToolBase):
    ext = "batch-converter"

    def test_convert_many_formats_and_save_all(self):
        p = self.page
        png = _media.photo(self.path("one.png"), alpha=True)
        gif = _media.animated(self.path("two.gif"), n=5)
        jpg = self.path("three.jpg")
        media.PIL.Image.new("RGB", (64, 48), (0, 0, 255)).save(jpg)
        self.assertEqual(len(p.add([png, gif, jpg])), 3)
        self.assertEqual(p.from_combo.currentText(), "PNG")         # auto-picked from the first file
        p.convert()
        media.wait_all()
        res = p.queue.results()
        self.assertEqual(len(res), 3)
        self.assertEqual(len(res[gif]["frames"]), 5)
        p.to_combo.setCurrentText("WEBP")
        p.save_all(None)
        self.assertTrue(os.path.isfile(self.path("one.webp")))
        self.assertEqual(pil(self.path("two.webp")).n_frames, 5)   # stays animated
        # JPEG: transparency flattened onto white
        p.to_combo.setCurrentText("JPG / JPEG")
        out = self.path("out")
        os.makedirs(out)
        p.save_all(out)
        im = pil(os.path.join(out, "one.jpg"))
        self.assertEqual(im.mode, "RGB")
        self.assertGreater(min(im.first.getpixel((2, 2))), 240)
        # ICO with several sizes, resized to an icon preset
        p.to_combo.setCurrentText("ICO")
        p.resize.set_spec({"size": (512, 512), "mode": "fit"})
        p.save_one(png)
        ico = pil(self.path("one.ico"))
        self.assertIn((256, 256), ico.info.get("sizes", {(256, 256)}))
        # Save never overwrites the source with itself
        p.to_combo.setCurrentText("PNG")
        p.resize.set_spec(None)
        p.save_one(png)
        self.assertTrue(os.path.isfile(self.path("one (2).png")))

    def test_psd_source_folder_and_open_in_lumen(self):
        from lumen import psd
        doc = self.doc_with_picture(120, 80)
        psd_path = self.path("pic.psd")
        psd.write_psd(psd_path, doc)
        p = self.page
        self.patch(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: self.media_dir))
        p.from_combo.setCurrentText("PSD")
        p.choose_folder()
        self.assertEqual(p.queue.pending(), [os.path.abspath(psd_path)])
        p.convert()
        media.wait_all()
        d = p.queue.results()[os.path.abspath(psd_path)]
        self.assertEqual(d["size"], (120, 80))
        p.open_in_lumen(os.path.abspath(psd_path))
        self.assertEqual((self.w.current_doc().width, self.w.current_doc().height), (120, 80))

    def test_failures_show_in_completed(self):
        bad = self.path("broken.png")
        with open(bad, "wb") as f:
            f.write(b"not an image")
        p = self.page
        p.add([bad])
        p.convert()
        media.wait_all()
        self.assertEqual(p.queue.completed[os.path.abspath(bad)]["state"], "failed")
        self.assertIn("1 failed", p.queue.summary())
        p.queue.clear_completed()
        self.assertEqual(p.queue.completed, {})

    def test_lumen_can_now_save_gif_ico_and_open_avif(self):
        self.doc_with_picture(64, 64)
        self.assertIn("GIF (*.gif)", self.w.save_filters())
        self.assertIn("ico", self.w.file_writers)
        out = self.path("lumen.gif")
        self.assertTrue(self.w._write(self.w.current_doc(), out, "gif"))
        self.assertEqual(pil(out).format, "GIF")
        self.assertIn("*.cr2", self.w.open_filter())
        if media.avif_supported():
            av = self.path("photo.avif")
            media.PIL.Image.new("RGB", (40, 30), (200, 100, 0)).save(av)
            cv = self.w.open_path(av)
            self.assertIsNotNone(cv)
            self.assertEqual((cv.doc.width, cv.doc.height), (40, 30))

    def test_heic_when_supported(self):
        if not media.heif_supported():
            self.skipTest("pillow-heif isn't installed here (it's a download in Lumen)")
        media.register_heif()
        h = self.path("phone.heic")
        media.PIL.Image.new("RGB", (48, 32), (10, 120, 220)).save(h)
        cv = self.w.open_path(h)
        self.assertEqual((cv.doc.width, cv.doc.height), (48, 32))
        p = self.page
        p.add([h])
        p.convert()
        media.wait_all()
        self.assertEqual(p.queue.results()[os.path.abspath(h)]["size"], (48, 32))


class TestEnsureRuntime(ToolBase):
    ext = "video-to-image"

    def test_api_downloads_a_pack_on_demand(self):
        from test_extension_packs import Server, fake_runtime, wait
        from lumen.updates import Manifest
        from lumen.runtimes_platform import platform_key
        from lumen.extensions.api import ExtensionAPI
        api = ExtensionAPI(self.w, self.w.extensions.items["video-to-image"])
        srv = Server()
        try:
            entry = fake_runtime(srv, "ondemand", "lumen_ondemand_mod")
            self.w.checker.manifest = Manifest({"runtimes": {"ondemand": {platform_key(): entry}}})
            self.assertFalse(api.runtime_ready("ondemand", ["lumen_ondemand_mod"]))
            got = []
            api.ensure_runtime("ondemand", got.append, "a test")
            self.assertTrue(wait(lambda: got, 20), "never finished")
            self.assertEqual(got, [True])
            import lumen_ondemand_mod
            self.assertEqual(lumen_ondemand_mod.VALUE, 42)
            again = []
            api.ensure_runtime("ondemand", again.append)       # already there: no download, straight away
            self.assertEqual(again, [True])
            missing = []
            api.ensure_runtime("not-in-manifest", missing.append)
            self.assertTrue(wait(lambda: missing, 10))
            self.assertEqual(missing, [False])
        finally:
            srv.stop()


class TestOptionsAndNames(ToolBase):
    ext = "video-to-image"

    def test_options_menu_and_filenames_window(self):
        p = self.page
        p._sync_options()
        p.opt_names.setChecked(True)
        self.assertTrue(media.flag(media.SHOW_FILENAMES))
        f = self.path("a.txt")
        open(f, "w").close()
        media.after_save(p, [f], [])
        win = media.FilenamesWindow._instance
        self.assertIsNotNone(win)
        self.assertEqual(win.names, ["a.txt"])
        win.close()
        p.opt_names.setChecked(False)
        self.assertFalse(media.flag(media.SHOW_FILENAMES))


if __name__ == "__main__":
    unittest.main()
