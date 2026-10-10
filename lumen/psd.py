"""Read and write Photoshop .psd files (8-bit RGB, layers, names, opacity, fill, blend modes,
visibility, locks). Lumen's editable type layers are stored as pixels for Photoshop plus a private
image resource so Lumen can reopen them as live text."""
import json
import struct

import numpy as np
from PyQt6.QtCore import Qt, QPoint, QSize
from PyQt6.QtGui import QImage, QColor

from . import imageops
from .imageops import PREMUL, STRAIGHT
from .layers import Layer, TextData, BLEND_LABELS, flatten

LUMEN_RESOURCE_ID = 4242          # 4000-4999 is reserved for plug-in data; Photoshop ignores it
RES_RESOLUTION = 1005


class PSDError(Exception):
    pass


# =========================================================================== writing
def _pascal(name, pad):
    b = name.encode("latin-1", "replace")[:255]
    out = bytes([len(b)]) + b
    while len(out) % pad:
        out += b"\0"
    return out


def _block(key, data):
    if len(data) % 2:
        data += b"\0"
    return b"8BIM" + key + struct.pack(">I", len(data)) + data


def _channels(img: QImage):
    """Planar straight-alpha channels (R, G, B, A) as uint8 arrays."""
    a = imageops.straight_array(img)
    return a[..., 2], a[..., 1], a[..., 0], a[..., 3]


def _rle_row(row: bytes) -> bytes:
    """PackBits-encode one row (header 0..127 = literal n+1 bytes, 129..255 = repeat 257-h times)."""
    out = bytearray()
    n, i = len(row), 0
    while i < n:
        j = i + 1
        while j < n and j - i < 128 and row[j] == row[i]:
            j += 1
        run = j - i
        if run >= 2:
            out.append(257 - run)
            out.append(row[i])
            i = j
        else:
            start = i
            i += 1
            while i < n and i - start < 128 and not (i + 1 < n and row[i] == row[i + 1]):
                i += 1
            out.append(i - start - 1)
            out += row[start:i]
    return bytes(out)


def _rle_channel(ch: np.ndarray):
    rows = [_rle_row(r.tobytes()) for r in ch]
    counts = b"".join(struct.pack(">H", len(r)) for r in rows)
    return counts + b"".join(rows)


def _encode_channel(ch: np.ndarray):
    """Pick RLE when it saves space (flat areas), raw otherwise — always valid for Photoshop."""
    raw = ch.tobytes()
    if ch.size and ch.size < 4_000_000 and (np.diff(ch, axis=1) == 0).mean() > 0.5:
        rle = _rle_channel(ch)
        if len(rle) < len(raw):
            return struct.pack(">H", 1) + rle
    return struct.pack(">H", 0) + raw


def write_psd(path, doc):
    w, h = doc.width, doc.height
    layers = doc.layers
    lumen_meta = {"version": 1, "layers": []}

    recs, chan_data = [], []
    for idx, L in enumerate(layers):
        r = L.rect().intersected(doc.rect()) if not L.background else doc.rect()
        if r.isEmpty():
            r = doc.rect().adjusted(0, 0, -(w - 1), -(h - 1))
            img = QImage(1, 1, PREMUL)
            img.fill(Qt.GlobalColor.transparent)
        else:
            img = L.region(r)
        R, G, B, A = _channels(img)
        chans = [(-1, A), (0, R), (1, G), (2, B)]
        encoded = [(cid, _encode_channel(c)) for cid, c in chans]
        rec = struct.pack(">iiii", r.top(), r.left(), r.bottom() + 1, r.right() + 1)
        rec += struct.pack(">H", len(encoded))
        for cid, data in encoded:
            rec += struct.pack(">hI", cid, len(data))
        flags = (0x01 if L.lock_alpha else 0) | (0x02 if not L.visible else 0) | 0x08
        rec += b"8BIM" + (L.blend if L.blend in BLEND_LABELS else "norm").encode("ascii")
        rec += struct.pack(">BBBB", round(L.opacity * 2.55), 0, flags, 0)
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + _pascal(L.name, 4)
        uname = L.name.encode("utf-16-be")
        extra += _block(b"luni", struct.pack(">I", len(L.name)) + uname)
        extra += _block(b"iOpa", struct.pack(">B", round(L.fill * 2.55)) + b"\0\0\0")
        lock = (1 if L.lock_alpha else 0) | (2 if L.lock_pixels else 0) | (4 if L.lock_position else 0)
        if L.lock_all:
            lock |= 0x80000000
        extra += _block(b"lspf", struct.pack(">I", lock))
        rec += struct.pack(">I", len(extra)) + extra
        recs.append(rec)
        chan_data.append(b"".join(d for _, d in encoded))
        meta = {"index": idx, "background": L.background}
        if L.is_text:
            meta["text"] = L.text.to_dict()
        lumen_meta["layers"].append(meta)

    has_bg = doc.background_layer() is not None
    layer_info = struct.pack(">h", len(layers) if has_bg else -len(layers)) + b"".join(recs) + b"".join(chan_data)
    if len(layer_info) % 4:
        layer_info += b"\0" * (4 - len(layer_info) % 4)
    lm = struct.pack(">I", len(layer_info)) + layer_info + struct.pack(">I", 0)
    layer_mask_section = struct.pack(">I", len(lm)) + lm

    # image resources: resolution + Lumen metadata
    res = b""
    dpi_fixed = int(round(doc.dpi * 65536))
    resdata = struct.pack(">IHHIHH", dpi_fixed, 1, 1, dpi_fixed, 1, 1)
    res += b"8BIM" + struct.pack(">H", RES_RESOLUTION) + b"\0\0" + struct.pack(">I", len(resdata)) + resdata
    meta = json.dumps(lumen_meta).encode("utf-8")
    res += b"8BIM" + struct.pack(">H", LUMEN_RESOURCE_ID) + b"\0\0" + struct.pack(">I", len(meta)) + meta
    if len(meta) % 2:
        res += b"\0"

    comp = flatten(layers, doc.size())
    R, G, B, A = _channels(comp)
    planes = [R, G, B] + ([] if has_bg else [A])
    header = b"8BPS" + struct.pack(">H6xHIIHH", 1, len(planes), h, w, 8, 3)
    with open(path, "wb") as f:
        f.write(header)
        f.write(struct.pack(">I", 0))                       # colour mode data
        f.write(struct.pack(">I", len(res)) + res)
        f.write(layer_mask_section)
        f.write(struct.pack(">H", 0))                       # raw composite
        for pl in planes:
            f.write(pl.tobytes())


# =========================================================================== reading
class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def read(self, n):
        if self.p + n > len(self.d):
            raise PSDError("The file is truncated or damaged.")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u(self, fmt):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))


def _unpackbits(data, expected):
    out = bytearray()
    i, n = 0, len(data)
    while i < n and len(out) < expected:
        c = data[i]
        i += 1
        if c < 128:
            out += data[i:i + c + 1]
            i += c + 1
        elif c > 128:
            out += bytes([data[i]]) * (257 - c)
            i += 1
    if len(out) < expected:
        out += b"\0" * (expected - len(out))
    return bytes(out[:expected])


def _decode(rd, w, h, length=None, compression=None, plane_count=1, counts_big=False):
    """Decode `plane_count` planes; compression read from the stream if not given."""
    if compression is None:
        (compression,) = rd.u(">H")
    if compression == 0:
        return [np.frombuffer(rd.read(w * h), np.uint8).reshape(h, w) for _ in range(plane_count)]
    if compression == 1:
        counts = rd.u(f">{h * plane_count}{'I' if counts_big else 'H'}")
        planes = []
        for pl in range(plane_count):
            rows = []
            for y in range(h):
                rows.append(_unpackbits(rd.read(counts[pl * h + y]), w))
            planes.append(np.frombuffer(b"".join(rows), np.uint8).reshape(h, w) if h and w else
                          np.zeros((h, w), np.uint8))
        return planes
    if compression in (2, 3):
        import zlib
        raw = zlib.decompress(rd.read(length - 2)) if length else b""
        a = np.frombuffer(raw, np.uint8)[:w * h].copy()
        if compression == 3 and w:
            a = a.reshape(h, w)
            a = np.cumsum(a, axis=1, dtype=np.uint8)
        return [a.reshape(h, w)]
    raise PSDError(f"Unsupported channel compression ({compression}).")


def _image_from_planes(w, h, r, g, b, a=None):
    arr = np.empty((h, w, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = b, g, r
    arr[..., 3] = 255 if a is None else a
    return imageops.from_array(arr, STRAIGHT).convertToFormat(PREMUL)


def read_psd(path):
    """Returns dict(size, layers, dpi)."""
    with open(path, "rb") as f:
        rd = _Reader(f.read())
    if rd.read(4) != b"8BPS":
        raise PSDError("Not a Photoshop file.")
    version, = rd.u(">H")
    if version != 1:
        raise PSDError("Large Document Format (.psb) isn't supported yet.")
    rd.read(6)
    nchan, h, w, depth, mode = rd.u(">HIIHH")
    if depth != 8:
        raise PSDError(f"Only 8-bit images are supported (this file is {depth}-bit).")
    if mode not in (1, 3):
        raise PSDError("Only RGB and Grayscale Photoshop files are supported.")
    (cm_len,) = rd.u(">I")
    rd.read(cm_len)
    (res_len,) = rd.u(">I")
    res_end = rd.p + res_len
    dpi, meta = 72, None
    while rd.p < res_end:
        if rd.read(4) != b"8BIM":
            break
        (rid,) = rd.u(">H")
        (nl,) = rd.u(">B")
        rd.read(nl + (1 if (nl + 1) % 2 else 0))
        (size,) = rd.u(">I")
        data = rd.read(size)
        if size % 2:
            rd.read(1)
        if rid == RES_RESOLUTION and size >= 4:
            dpi = round(struct.unpack(">I", data[:4])[0] / 65536) or 72
        elif rid == LUMEN_RESOURCE_ID:
            try:
                meta = json.loads(data.decode("utf-8"))
            except ValueError:
                meta = None
    rd.p = res_end

    (lm_len,) = rd.u(">I")
    lm_end = rd.p + lm_len
    layers = []
    if lm_len and mode == 3:
        (li_len,) = rd.u(">I")
        li_end = rd.p + li_len
        if li_len:
            (count,) = rd.u(">h")
            count = abs(count)
            recs = []
            for _ in range(count):
                top, left, bottom, right = rd.u(">iiii")
                (nc,) = rd.u(">H")
                chans = [rd.u(">hI") for _ in range(nc)]
                if rd.read(4) != b"8BIM":
                    raise PSDError("Damaged layer record.")
                blend = rd.read(4).decode("latin-1")
                opacity, clipping, flags, _ = rd.u(">BBBB")
                (extra_len,) = rd.u(">I")
                extra_end = rd.p + extra_len
                (mlen,) = rd.u(">I")
                mask = None
                if mlen:
                    mdata = rd.read(mlen)
                    if mlen >= 18:
                        mt, ml, mb, mr = struct.unpack(">iiii", mdata[:16])
                        mask = {"rect": (mt, ml, mb, mr), "default": mdata[16], "flags": mdata[17]}
                (brl,) = rd.u(">I")
                rd.read(brl)
                (nlen,) = rd.u(">B")
                name = rd.read(nlen).decode("latin-1", "replace")
                pad = (4 - (nlen + 1) % 4) % 4
                rd.read(pad)
                info = {}
                while rd.p + 12 <= extra_end:
                    sig = rd.read(4)
                    if sig not in (b"8BIM", b"8B64"):
                        break
                    key = rd.read(4)
                    (ln,) = rd.u(">I")
                    info[key] = rd.read(ln)
                    if ln % 2 and rd.p < extra_end and key not in (b"luni",):
                        pass
                rd.p = extra_end
                if b"luni" in info and len(info[b"luni"]) >= 4:
                    n = struct.unpack(">I", info[b"luni"][:4])[0]
                    name = info[b"luni"][4:4 + n * 2].decode("utf-16-be", "replace")
                recs.append(dict(top=top, left=left, bottom=bottom, right=right, chans=chans, blend=blend,
                                 opacity=opacity, flags=flags, name=name, info=info, mask=mask))
            for rec in recs:
                lw, lh = rec["right"] - rec["left"], rec["bottom"] - rec["top"]
                planes = {}
                for cid, length in rec["chans"]:
                    start = rd.p
                    cw, ch = (lw, lh)
                    if cid == -2 and rec["mask"]:
                        mt, ml, mb, mr = rec["mask"]["rect"]
                        cw, ch = mr - ml, mb - mt
                    if cw <= 0 or ch <= 0:
                        rd.p = start + length
                        continue
                    (comp,) = rd.u(">H")
                    planes[cid] = _decode(rd, cw, ch, length, comp)[0]
                    rd.p = start + length
                rec["planes"] = planes
            rd.p = li_end
        rd.p = lm_end

        meta_layers = {m["index"]: m for m in (meta or {}).get("layers", [])} if meta else {}
        for idx, rec in enumerate(recs if lm_len and mode == 3 and li_len else []):
            info = rec["info"]
            if b"lsct" in info:          # group start/end markers: groups are flattened into the list
                continue
            lw, lh = rec["right"] - rec["left"], rec["bottom"] - rec["top"]
            pl = rec["planes"]
            if lw > 0 and lh > 0 and 0 in pl and 1 in pl and 2 in pl:
                a = pl.get(-1)
                if -2 in pl and rec["mask"]:
                    a = _apply_mask(a, pl[-2], rec, lw, lh)
                img = _image_from_planes(lw, lh, pl[0], pl[1], pl[2], a)
            else:
                img = QImage(1, 1, PREMUL)
                img.fill(Qt.GlobalColor.transparent)
            m = meta_layers.get(idx, {})
            td = TextData.from_dict(m["text"]) if m.get("text") else None
            L = Layer(rec["name"] or f"Layer {idx + 1}", img, QPoint(rec["left"], rec["top"]),
                      background=bool(m.get("background")), text=td)
            if td is not None:
                L.name = rec["name"] or L.name
            L.blend = rec["blend"] if rec["blend"] in BLEND_LABELS else "norm"
            L.opacity = round(rec["opacity"] / 2.55)
            L.visible = not (rec["flags"] & 0x02)
            L.lock_alpha = bool(rec["flags"] & 0x01)
            if b"iOpa" in info:
                L.fill = round(info[b"iOpa"][0] / 2.55)
            if b"lspf" in info and len(info[b"lspf"]) >= 4:
                lk = struct.unpack(">I", info[b"lspf"][:4])[0]
                L.lock_alpha = bool(lk & 1) or L.lock_alpha
                L.lock_pixels = bool(lk & 2)
                L.lock_position = bool(lk & 4)
                L.lock_all = bool(lk & 0x80000000)
            layers.append(L)
    rd.p = lm_end

    if not layers:
        (comp,) = rd.u(">H")
        rest = len(rd.d) - rd.p
        planes = _decode(rd, w, h, rest + 2, comp, nchan, counts_big=False)
        if mode == 1:
            g = planes[0]
            img = _image_from_planes(w, h, g, g, g)
        else:
            # extra channels in a flat PSD are usually saved selections, not transparency
            img = _image_from_planes(w, h, planes[0], planes[1], planes[2], None)
        layers = [Layer("Background", img, background=True)]
    return {"size": QSize(w, h), "layers": layers, "dpi": dpi}


def _apply_mask(alpha, mask, rec, lw, lh):
    """Bake a layer mask into the layer's transparency (masks aren't editable in Lumen yet)."""
    if rec["mask"]["flags"] & 0x02:      # mask disabled
        return alpha
    a = np.full((lh, lw), 255, np.uint8) if alpha is None else alpha.astype(np.uint8)
    mt, ml, mb, mr = rec["mask"]["rect"]
    full = np.full((lh, lw), rec["mask"]["default"], np.uint8)
    y0, x0 = mt - rec["top"], ml - rec["left"]
    ys0, xs0 = max(0, y0), max(0, x0)
    ys1, xs1 = min(lh, y0 + mask.shape[0]), min(lw, x0 + mask.shape[1])
    if ys1 > ys0 and xs1 > xs0:
        full[ys0:ys1, xs0:xs1] = mask[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0]
    if rec["mask"]["flags"] & 0x04:      # inverted
        full = 255 - full
    return (a.astype(np.uint16) * full // 255).astype(np.uint8)
