"""U²-Net subject detection with onnxruntime (models from the rembg project, downloaded on first use)."""
import os
import urllib.request

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
MODELS = {
    "Balanced — general subjects (5 MB)": "u2netp.onnx",
    "Best quality — general subjects (176 MB)": "u2net.onnx",
    "People / characters (176 MB)": "u2net_human_seg.onnx",
}
INPUT = 320
_sessions = {}


def model_path(folder, name):
    return os.path.join(folder, name)


def have_model(folder, name):
    p = model_path(folder, name)
    return os.path.exists(p) and os.path.getsize(p) > 1024


def download_model(folder, name, progress=None, cancelled=None):
    dest = model_path(folder, name)
    if have_model(folder, name):
        return dest
    part = dest + ".part"
    req = urllib.request.Request(MODEL_URL + name, headers={"User-Agent": "Lumen"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancelled and cancelled():
                raise RuntimeError("Cancelled")
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(part, dest)
    return dest


def session(path):
    if path not in _sessions:
        import onnxruntime
        _sessions[path] = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])
    return _sessions[path]


def subject_alpha(img: QImage, path) -> np.ndarray:
    """uint8 (h, w) mask: 255 where the subject is, 0 for background."""
    rgb = img.convertToFormat(QImage.Format.Format_RGB888)
    small = rgb.scaled(INPUT, INPUT, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    ptr = small.bits()
    ptr.setsize(small.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(INPUT, small.bytesPerLine())[:, :INPUT * 3]
    x = arr.reshape(INPUT, INPUT, 3).astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[np.newaxis]
    s = session(path)
    pred = s.run(None, {s.get_inputs()[0].name: x})[0][0, 0]
    spread = float(pred.max() - pred.min())
    pred = (pred - pred.min()) / (spread if spread else 1.0)
    m8 = np.ascontiguousarray((pred * 255).astype(np.uint8))
    mask = QImage(m8.data, INPUT, INPUT, INPUT, QImage.Format.Format_Grayscale8).copy()
    big = mask.scaled(img.width(), img.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
    p2 = big.bits()
    p2.setsize(big.sizeInBytes())
    return np.frombuffer(p2, np.uint8).reshape(big.height(), big.bytesPerLine())[:, :big.width()].copy()
