"""Image Optimiser for Lumen: shrink a still image (or the open Lumen document) to a size or a target."""
import os

from lumen import media


def build_optimized_image(source_path, level, output_path, square=None, spec=None):
    """Re-encode a still image at compression `level` (1-100).

    Images that need transparency are saved as lossless PNG and shrink mainly by resizing; opaque images are
    saved as JPEG, where the level also lowers the quality. Returns the real output path (.png or .jpg)."""
    PIL = media.PIL
    with media.open_any(source_path) as img:
        had_alpha = media.has_transparency(img)
        src = img.convert("RGBA").copy()
    if square:
        spec = None
    if spec:
        src = media.resize_to_spec(src, spec)
    needs_alpha = had_alpha and src.getchannel("A").getextrema()[0] < 255 or bool(square) \
        or media.spec_adds_transparency(spec)
    scale = 1.0 if spec else max(1.0 - (level / 100) * 0.7, 0.15)
    if square:
        out = media.fit_in_square(src, square, scale)
    else:
        w, h = src.size
        out = src.resize((max(1, int(w * scale)), max(1, int(h * scale))), PIL.LANCZOS)
    base = os.path.splitext(output_path)[0]
    if needs_alpha:
        path = base + ".png"
        out.save(path, format="PNG", optimize=True, compress_level=9)
    else:
        quality = max(5, round(95 - (level / 100) * 90))
        path = base + ".jpg"
        out.convert("RGB").save(path, format="JPEG", quality=quality, optimize=True)
    return path


class ImageOptimiserPage(media.OptimiserPage):
    kind = "image"
    open_filter = media.IMAGE_FILTER

    def __init__(self, api):
        super().__init__("Image Optimiser", "Shrink an image to a target size - from a file or straight from "
                         "Lumen.", "compress", api)

    def allow_lumen_source(self):
        return True

    def level_hint(self):
        return ("Pictures with see-through areas stay lossless PNG and shrink by size; solid photos become JPEG, "
                "where compression also lowers the quality.")

    def build(self, source, level, out, square, spec):
        return build_optimized_image(source, level, out, square, spec)


def register(api):
    page = ImageOptimiserPage(api)
    api.add_workspace("Image Optimiser", page, icon="compress")
    api.add_menu_action("Plugins", "Image Optimiser", lambda: api.show_workspace(page), needs_document=False)
    api.add_menu_action("File/Export", "Optimise for Web…", lambda: (api.show_workspace(page), page.use_lumen()))
    register.workspace = page
