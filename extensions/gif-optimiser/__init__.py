"""GIF Optimiser for Lumen: shrink a GIF to a size or a target, with a live before/after preview."""
from lumen import media


def build_optimized_gif(source_path, level, output_path, square=None, spec=None):
    """Re-encode a GIF at compression `level` (1-100). Higher = fewer colours, smaller frames, fewer frames.

    square (Discord presets) fits every frame into an exact square canvas whose content shrinks with the
    level; spec (Output size) pins an exact size so the level works through colours and frame count instead."""
    PIL = media.PIL
    frames, durations = [], []
    with PIL.Image.open(source_path) as im:
        had_alpha = media.has_transparency(im)
        for fr in PIL.ImageSequence.Iterator(im):
            frames.append(fr.convert("RGBA").copy())
            durations.append(fr.info.get("duration", 100) or 100)
    if not frames:
        raise RuntimeError("No frames could be read from this GIF.")
    if square:
        spec = None                       # the preset's own size wins
    if spec:
        frames = [media.resize_to_spec(f, spec) for f in frames]
    needs_alpha = had_alpha or bool(square) or media.spec_adds_transparency(spec)
    colors = max(8, int(256 - (level / 100) * 248))
    scale = 1.0 if spec else max(1.0 - (level / 100) * 0.7, 0.15)
    keep_every = 4 if level > 95 else 3 if level > 80 else 2 if level > 60 else 1
    outs, durs = [], []
    for i, (f, d) in enumerate(zip(frames, durations)):
        if i % keep_every:
            continue
        if square:
            out = media.fit_in_square(f, square, scale)
        else:
            w, h = f.size
            out = f.resize((max(1, int(w * scale)), max(1, int(h * scale))), PIL.LANCZOS)
        outs.append(out)
        durs.append(d * keep_every)
    if not outs:
        raise RuntimeError("No frames left after optimising.")
    media.save_gif(outs, durs, output_path, colors=colors, dither=PIL.DITHER_FS, transparent=needs_alpha)
    return output_path


class GifOptimiserPage(media.OptimiserPage):
    kind = "GIF"
    open_filter = "GIF images (*.gif);;All files (*)"

    def __init__(self, api):
        super().__init__("GIF Optimiser", "Shrink a GIF to a target size - Discord emoji and sticker presets "
                         "included.", "gif", api)

    def level_hint(self):
        return ("Higher compression uses fewer colours and smaller frames, and above 60% drops every 2nd, 3rd or "
                "4th frame (timing is kept).")

    def build(self, source, level, out, square, spec):
        out = out.rsplit(".", 1)[0] + ".gif"
        return build_optimized_gif(source, level, out, square, spec)


def register(api):
    page = GifOptimiserPage(api)
    api.add_workspace("GIF Optimiser", page, icon="gif")
    api.add_menu_action("Plugins", "GIF Optimiser", lambda: api.show_workspace(page), needs_document=False)
    register.workspace = page
