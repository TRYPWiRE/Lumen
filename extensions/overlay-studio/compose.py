"""Overlay compositing (pure Pillow, also used for export) - from the File Converter's Overlay Studio."""
import bisect

from lumen import media

MAX_LAYER_FRAMES = 400
MAX_OUTPUT_FRAMES = 600
PRESETS = [("Top Left", "l", "t"), ("Top Center", "c", "t"), ("Top Right", "r", "t"),
           ("Middle Left", "l", "m"), ("Center", "c", "m"), ("Middle Right", "r", "m"),
           ("Bottom Left", "l", "b"), ("Bottom Center", "c", "b"), ("Bottom Right", "r", "b")]


class Layer:
    """An image (still or animated) as RGBA frames with durations."""

    def __init__(self, name, frames, durations):
        self.name, self.frames, self.durations = name, frames, durations
        self.cum, total = [], 0
        for d in durations:
            total += d
            self.cum.append(total)
        self.qimages = [media.pil_to_qimage(f) for f in frames]
        self.pixmaps = []                  # made on the GUI thread

    @property
    def size(self):
        return self.frames[0].size

    @property
    def animated(self):
        return len(self.frames) > 1

    @property
    def total(self):
        return self.cum[-1]

    def index_at(self, t):
        if not self.animated:
            return 0
        return min(bisect.bisect_right(self.cum, t % self.total), len(self.frames) - 1)

    def boundaries(self, until):
        out, base = [], 0
        while base < until:
            out.append(base)
            out += [base + c for c in self.cum[:-1] if base + c < until]
            base += self.total
        return out


def build_layer(data, name):
    """data: bytes or a Pillow image."""
    img = media.open_bytes(data) if isinstance(data, (bytes, bytearray)) else data
    frames, durs = media.read_frames(img, limit=MAX_LAYER_FRAMES)
    return Layer(name, frames, durs)


def compose(bg, fg, x, y, scale, opacity, animate):
    """(frames, durations) of fg placed on bg at (x, y) in background pixels."""
    Image = media.PIL.Image
    if animate and (bg.animated or (fg and fg.animated)):
        total = max(bg.total, fg.total if fg else 0)
        starts = set(bg.boundaries(total))
        if fg:
            starts.update(fg.boundaries(total))
        starts = sorted(starts)[:MAX_OUTPUT_FRAMES]
        ends = starts[1:] + [total]
        timeline = []
        for s, e in zip(starts, ends):
            if e - s < 10 and timeline:            # merge slivers into the previous frame
                timeline[-1] = (timeline[-1][0], timeline[-1][1] + (e - s))
                continue
            timeline.append((s, e - s))
    else:
        timeline = [(0, 100)]
    cache = {}

    def fg_frame(i):
        if i not in cache:
            f = fg.frames[i]
            w, h = max(1, round(f.width * scale)), max(1, round(f.height * scale))
            if (w, h) != f.size:
                f = f.resize((w, h), media.PIL.LANCZOS)
            if opacity < 1.0:
                f = f.copy()
                f.putalpha(f.getchannel("A").point(lambda v: round(v * opacity)))
            cache[i] = f
        return cache[i]

    frames, durs = [], []
    for start, d in timeline:
        base = bg.frames[bg.index_at(start)].copy()
        if fg:
            layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
            layer.paste(fg_frame(fg.index_at(start)), (round(x), round(y)))
            base = Image.alpha_composite(base, layer)
        frames.append(base)
        durs.append(max(20, int(d)))
    return frames, durs
