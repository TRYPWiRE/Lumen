"""The collected-images gallery: cards with preview, details and 'Add as Layer'."""
import os
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QSize, QUrl
from PyQt6.QtGui import QPixmap, QGuiApplication, QAction, QImage, QDesktopServices
from PyQt6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QMenu,
                             QScrollArea, QGridLayout, QComboBox, QCheckBox, QFileDialog, QMessageBox, QSizePolicy)

from lumen import theme

from . import fetcher as F

CARD_W = 220
SIZE_FILTERS = [("All sizes", 0), ("64 px and up", 64), ("200 px and up", 200), ("500 px and up", 500)]


def _colors():
    """Theme colours (falls back to the classic dark look on Lumen versions without the theme engine)."""
    c = dict(getattr(theme, "C", {}) or {})
    c.setdefault("window", theme.BG)
    c.setdefault("header", theme.BG_DARK)
    c.setdefault("input_border", theme.INPUT_BORDER)
    c.setdefault("accent", theme.ACCENT)
    c.setdefault("pasteboard", theme.PASTEBOARD)
    c.setdefault("text_strong", "#e6e6e6")
    c.setdefault("text_dim", theme.TEXT_DIM)
    c.setdefault("hover", theme.HOVER)
    return c


def _mix(a, b, t):
    from PyQt6.QtGui import QColor
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def on_theme_changed(slot):
    """Call slot() whenever the user switches theme (no-op on older Lumen versions)."""
    n = getattr(theme, "notifier", None)
    if n is not None:
        n.changed.connect(slot)


class _Bridge(QObject):
    loaded = pyqtSignal(int, int, object)      # scan id, index, (qimage, fmt, frames) or Exception


class Card(QFrame):
    def __init__(self, gallery, index, url):
        super().__init__()
        self.gallery, self.index, self.url = gallery, index, url
        self.image = None
        self.fmt = ""
        self.frames = 1
        self.setObjectName("ImageCard")
        self.setFixedWidth(CARD_W)
        self._restyle()
        on_theme_changed(self._restyle)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.check = QCheckBox()
        self.check.setToolTip("Select for 'Add Selected as Layers'")
        self.check.toggled.connect(self._checked)
        top.addWidget(self.check)
        self.info = QLabel(f"Image {index + 1}")
        self.info.setObjectName("CardTitle")
        top.addWidget(self.info, 1)
        lay.addLayout(top)
        self.preview = QLabel("Loading…")
        self.preview.setObjectName("Preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(150)
        lay.addWidget(self.preview)
        shown = url if not url.startswith("data:") else "(embedded in the page)"
        u = QLabel(shown)
        u.setObjectName("Dim")
        u.setToolTip(url if len(url) < 1500 else shown)
        u.setMaximumHeight(30)
        u.setWordWrap(True)
        u.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(u)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.add_btn = QPushButton("Add as Layer")
        self.add_btn.setObjectName("Primary")
        self.add_btn.setToolTip("Place this image in the current Lumen document as a new layer")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(lambda: self.gallery.add_layers([self]))
        row.addWidget(self.add_btn, 1)
        more = QToolButton()
        more.setText("⋯")
        more.setFixedSize(30, 28)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        more.setToolTip("More: open as document, save, copy…")
        menu = QMenu(more)
        self.open_act = menu.addAction("Open as New Document", lambda: self.gallery.open_document(self))
        menu.addSeparator()
        self.save_act = menu.addAction("Save Image As…", self.save)
        self.copy_act = menu.addAction("Copy Image", self.copy_image)
        menu.addAction("Copy Image Address", lambda: QGuiApplication.clipboard().setText(self.url))
        if not url.startswith("data:"):
            menu.addAction("Open Image in New Tab", lambda: self.gallery.open_in_tab(self.url))
        for a in (self.open_act, self.save_act, self.copy_act):
            a.setEnabled(False)
        more.setMenu(menu)
        row.addWidget(more)
        lay.addLayout(row)

    def _restyle(self, *_):
        c = _colors()
        card = _mix(c["window"], c["header"], 0.8)
        self.setStyleSheet(f"""
            QFrame#ImageCard {{ background: {card}; border: 1px solid {c['input_border']}; border-radius: 8px; }}
            QFrame#ImageCard[checked="true"] {{ border: 1px solid {c['accent']}; background: {_mix(card, c['accent'], 0.18)}; }}
            QLabel#Preview {{ background: {_mix(c['pasteboard'], card, 0.3)}; border-radius: 5px; }}
            QLabel#CardTitle {{ font-weight: 600; color: {c['text_strong']}; }}
        """)

    def _checked(self, on):
        self.setProperty("checked", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.gallery.selection_changed()

    def set_result(self, result):
        if isinstance(result, Exception):
            self.preview.setText("Preview unavailable\n" + str(result)[:80])
            self.preview.setWordWrap(True)
            return
        self.image, self.fmt, self.frames = result
        thumb = self.image.scaled(CARD_W - 24, 146, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(QPixmap.fromImage(thumb))
        details = f"{self.image.width()} × {self.image.height()} · {self.fmt}"
        if self.frames > 1:
            details += f" · {self.frames} frames"
        self.info.setText(details)
        self.info.setToolTip(f"Image {self.index + 1}: {details}")
        for w in (self.add_btn, self.open_act, self.save_act, self.copy_act):
            w.setEnabled(True)

    def big_enough(self, minimum):
        return self.image is not None and max(self.image.width(), self.image.height()) >= minimum

    def name(self):
        return F.suggested_name(self.url, self.index)

    def copy_image(self):
        if self.image is not None:
            QGuiApplication.clipboard().setImage(self.image)

    def save(self):
        if self.image is None:
            return
        g = self.gallery
        orig_ext = F.extension_for(self.fmt)
        filters = [f"Original file ({self.fmt}) (*{orig_ext})", "PNG (*.png)", "JPEG (*.jpg)", "WebP (*.webp)"]
        path, flt = QFileDialog.getSaveFileName(self, "Save Image", os.path.join(g.last_dir, self.name() + orig_ext),
                                                ";;".join(filters))
        if not path:
            return
        g.last_dir = os.path.dirname(path)
        try:
            if flt.startswith("Original"):
                with open(path, "wb") as f:
                    f.write(g.fetcher.get(self.url))
            else:
                ext = {"PNG": ".png", "JPEG": ".jpg", "WebP": ".webp"}[flt.split(" ")[0]]
                if not path.lower().endswith(ext):
                    path += ext
                img = self.image
                if ext == ".jpg":
                    img = img.convertToFormat(QImage.Format.Format_RGB32)
                if not img.save(path, quality=92):
                    raise OSError("the image couldn't be written")
            g.set_status(f"Saved {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "Web Images Extractor", f"Couldn't save the image.\n\n{e}")


class Gallery(QWidget):
    def __init__(self, api, fetcher, parent=None):
        super().__init__(parent)
        self.api, self.fetcher = api, fetcher
        self.cards = []
        self.scan_id = 0
        self.last_dir = os.path.expanduser("~")
        self.on_open_tab = None
        self.pool = ThreadPoolExecutor(max_workers=6)
        self.bridge = _Bridge()
        self.bridge.loaded.connect(self._loaded, Qt.ConnectionType.QueuedConnection)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 6)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.collect_btn = QPushButton("Collect Images")
        self.collect_btn.setObjectName("Primary")
        self.collect_btn.setToolTip("Collect every image on the current page")
        bar.addWidget(self.collect_btn)
        self.deep_btn = QPushButton("Scroll + Collect")
        self.deep_btn.setObjectName("Flat")
        self.deep_btn.setToolTip("Scroll through the whole page first, so lazy-loaded images appear too")
        bar.addWidget(self.deep_btn)
        self.size_filter = QComboBox()
        for label, _ in SIZE_FILTERS:
            self.size_filter.addItem(label)
        self.size_filter.setToolTip("Hide small images such as icons")
        self.size_filter.currentIndexChanged.connect(self.relayout)
        bar.addWidget(self.size_filter)
        self.status = QLabel("Browse to a page, then collect its images.")
        self.status.setObjectName("Dim")
        bar.addWidget(self.status, 1)
        self.select_all = QCheckBox("Select all")
        self.select_all.toggled.connect(self._select_all)
        bar.addWidget(self.select_all)
        self.add_sel_btn = QPushButton("Add Selected as Layers")
        self.add_sel_btn.setObjectName("Flat")
        self.add_sel_btn.setEnabled(False)
        self.add_sel_btn.clicked.connect(lambda: self.add_layers([c for c in self.cards if c.check.isChecked()]))
        bar.addWidget(self.add_sel_btn)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.host)
        self.scroll.setMinimumHeight(120)
        lay.addWidget(self.scroll, 1)
        self._cols = 0

    # ------------------------------------------------------------ results
    def set_status(self, text):
        self.status.setText(text)

    def clear(self):
        self.scan_id += 1
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        self.select_all.setChecked(False)
        self._cols = 0

    def show_urls(self, urls, referer=""):
        """Replace the gallery with these image URLs (downloads previews in the background)."""
        self.clear()
        self.fetcher.referer = referer
        seen = []
        for u in urls:
            if u not in seen:
                seen.append(u)
        sid = self.scan_id
        for i, url in enumerate(seen):
            card = Card(self, i, url)
            self.cards.append(card)
            self.pool.submit(self._load, sid, i, url)
        self.pending = len(seen)
        self.relayout()
        self.set_status(f"Found {len(seen)} image{'s' if len(seen) != 1 else ''} — loading previews…"
                        if seen else "No images found on this page.")

    def _load(self, sid, i, url):
        try:
            result = F.probe(self.fetcher.get(url))
        except Exception as e:
            result = Exception(str(e) or type(e).__name__)
        self.bridge.loaded.emit(sid, i, result)

    def _loaded(self, sid, i, result):
        if sid != self.scan_id or i >= len(self.cards):
            return
        self.cards[i].set_result(result)
        self.pending -= 1
        if self.pending <= 0:
            ok = sum(1 for c in self.cards if c.image is not None)
            self.set_status(f"{ok} of {len(self.cards)} images ready — add them to Lumen as layers.")
        self.relayout()

    def finished(self):
        return getattr(self, "pending", 0) <= 0

    # ------------------------------------------------------------ layout
    def visible_cards(self):
        minimum = SIZE_FILTERS[self.size_filter.currentIndex()][1]
        return [c for c in self.cards if minimum == 0 or c.big_enough(minimum)]

    def relayout(self, *_):
        cols = max(1, (self.scroll.viewport().width() - 4) // (CARD_W + 12))
        while self.grid.count():
            self.grid.takeAt(0)
        vis = self.visible_cards()
        for c in self.cards:
            c.setVisible(c in vis)
        for n, c in enumerate(vis):
            self.grid.addWidget(c, n // cols, n % cols)
        self._cols = cols

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        cols = max(1, (self.scroll.viewport().width() - 4) // (CARD_W + 12))
        if cols != self._cols:
            self.relayout()

    # ------------------------------------------------------------ actions
    def selection_changed(self):
        n = sum(1 for c in self.cards if c.check.isChecked())
        self.add_sel_btn.setEnabled(n > 0)
        self.add_sel_btn.setText(f"Add {n} as Layers" if n else "Add Selected as Layers")

    def _select_all(self, on):
        for c in self.visible_cards():
            if c.image is not None:
                c.check.setChecked(on)

    def add_layers(self, cards):
        cards = [c for c in cards if c.image is not None]
        if not cards:
            return 0
        win = self.api.window()
        doc = self.api.current_document()
        if doc is not None and len(cards) > 1:
            doc.undo.beginMacro(f"Place {len(cards)} Images")
        try:
            for c in cards:
                self.api.add_image_as_layer(c.image, c.name())
        finally:
            if doc is not None and len(cards) > 1:
                doc.undo.endMacro()
        d = self.api.current_document()
        where = d.name if d else "Lumen"
        self.set_status(f"Added {len(cards)} layer{'s' if len(cards) > 1 else ''} to {where}.")
        win.statusBar().showMessage(f"Web Images Extractor: added {len(cards)} layer(s) to {where}", 5000)
        for c in cards:
            c.check.setChecked(False)
        return len(cards)

    def open_document(self, card):
        if card.image is not None:
            self.api.open_image(card.image, card.name())

    def open_in_tab(self, url):
        if self.on_open_tab:
            self.on_open_tab(url)
