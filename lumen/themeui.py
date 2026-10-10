"""Themes menu, theme previews and the theme editor (Themes ▸ Create Theme…)."""
import os

from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import (QPainter, QColor, QPen, QPixmap, QLinearGradient, QPainterPath, QFont, QIcon,
                         QFontMetrics, QAction)
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QWidget,
                             QScrollArea, QFrame, QListWidget, QListWidgetItem, QCheckBox, QFileDialog,
                             QMessageBox, QMenu, QWidgetAction, QApplication, QGridLayout, QSizePolicy)

from . import theme, icons
from .colors import ColorPicker


# ====================================================================== preview painting
def paint_preview(p, rect, c, detail=True):
    """Draw a miniature Lumen window in colours `c` (a theme colour dict) inside `rect`."""
    r = QRectF(rect)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    rad = max(3.0, r.width() * 0.025)
    clip.addRoundedRect(r, rad, rad)
    p.setClipPath(clip)
    W, H = r.width(), r.height()
    x0, y0 = r.left(), r.top()

    def box(x, y, w, h, col):
        p.fillRect(QRectF(x0 + x * W, y0 + y * H, w * W, h * H), QColor(col))

    def bar(x, y, w, h, col, radius=0.4):
        rr = QRectF(x0 + x * W, y0 + y * H, w * W, h * H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        p.drawRoundedRect(rr, rr.height() * radius, rr.height() * radius)

    # window body
    box(0, 0, 1, 1, c["window"])
    # menu bar
    box(0, 0, 1, 0.075, c["header"])
    for i, w in enumerate((0.04, 0.035, 0.045, 0.04, 0.05, 0.04)):
        bar(0.02 + i * 0.065, 0.025, w, 0.025, c["text"] if i else c["text_strong"])
    bar(0.02 + 2 * 0.065 - 0.008, 0.012, 0.062, 0.05, c["hover"], 0.25)
    bar(0.02 + 2 * 0.065, 0.025, 0.045, 0.025, c["text"])
    box(0, 0.075, 1, 0.004, c["border"])
    # options bar
    bar(0.012, 0.095, 0.035, 0.05, c["pressed"], 0.25)
    for i in range(4):
        bar(0.07 + i * 0.09, 0.105, 0.06, 0.03, c["input"] if i % 2 else c["text_dim"], 0.3)
    box(0, 0.16, 1, 0.004, c["border"])
    # toolbox (left)
    box(0.058, 0.164, 0.004, 0.79, c["border"])
    for i in range(9):
        y = 0.19 + i * 0.075
        if i == 2:
            bar(0.01, y - 0.012, 0.04, 0.058, c["pressed"], 0.2)
        p.setPen(QPen(QColor(c["text_strong"] if i == 2 else c["icon"]), max(1.0, W * 0.004)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy, s = x0 + 0.03 * W, y0 + (y + 0.017) * H, min(W * 0.012, H * 0.02)
        if i % 3 == 0:
            p.drawRect(QRectF(cx - s, cy - s, 2 * s, 2 * s))
        elif i % 3 == 1:
            p.drawEllipse(QPointF(cx, cy), s, s)
        else:
            p.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
    # pasteboard + document tab
    px, pw = 0.062, 0.668
    box(px, 0.164, pw, 0.79, c["pasteboard"])
    box(px, 0.164, pw, 0.06, c["header"])
    box(px, 0.164, 0.2, 0.06, c["window"])
    box(px, 0.164, 0.2, 0.008, c["accent"])
    bar(px + 0.02, 0.185, 0.12, 0.022, c["text"])
    box(px + 0.2, 0.164, 0.003, 0.06, c["border"])
    bar(px + 0.225, 0.185, 0.1, 0.022, c["text_dim"])
    # the picture on the canvas
    ir = QRectF(x0 + (px + 0.08) * W, y0 + 0.29 * H, (pw - 0.16) * W, 0.57 * H)
    p.fillRect(ir.adjusted(2, 3, 2, 3), QColor(0, 0, 0, 60))
    sky = QLinearGradient(ir.topLeft(), ir.bottomLeft())
    sky.setColorAt(0, QColor("#6fb7ff"))
    sky.setColorAt(0.65, QColor("#ffd9a8"))
    p.fillRect(ir, sky)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#fff2c4"))
    p.drawEllipse(QPointF(ir.left() + ir.width() * 0.72, ir.top() + ir.height() * 0.36), ir.height() * 0.13,
                  ir.height() * 0.13)
    hills = QPainterPath(QPointF(ir.left(), ir.bottom()))
    hills.lineTo(ir.left(), ir.top() + ir.height() * 0.7)
    hills.quadTo(ir.left() + ir.width() * 0.25, ir.top() + ir.height() * 0.42, ir.left() + ir.width() * 0.5,
                 ir.top() + ir.height() * 0.68)
    hills.quadTo(ir.left() + ir.width() * 0.75, ir.top() + ir.height() * 0.5, ir.right(), ir.top() + ir.height() * 0.66)
    hills.lineTo(ir.right(), ir.bottom())
    p.setBrush(QColor("#3d7a5a"))
    p.drawPath(hills)
    # right panels
    rx = 0.73
    box(rx, 0.164, 0.004, 0.79, c["border"])
    box(rx + 0.004, 0.164, 1 - rx, 0.055, c["header"])
    box(rx + 0.004, 0.164, 0.09, 0.055, c["window"])
    bar(rx + 0.02, 0.182, 0.055, 0.022, c["text_strong"])
    bar(rx + 0.11, 0.182, 0.05, 0.022, c["text_dim"])
    # colour panel bit
    sw = QRectF(x0 + (rx + 0.025) * W, y0 + 0.24 * H, (1 - rx - 0.05) * W, 0.15 * H)
    g = QLinearGradient(sw.topLeft(), sw.topRight())
    g.setColorAt(0, QColor("#ffffff"))
    g.setColorAt(1, QColor(c["accent"]))
    p.fillRect(sw, g)
    g2 = QLinearGradient(sw.topLeft(), sw.bottomLeft())
    g2.setColorAt(0, QColor(0, 0, 0, 0))
    g2.setColorAt(1, QColor(0, 0, 0, 255))
    p.fillRect(sw, g2)
    # slider
    bar(rx + 0.025, 0.425, 1 - rx - 0.05, 0.008, c["border"])
    bar(rx + 0.025, 0.425, (1 - rx - 0.05) * 0.6, 0.008, c["text_dim"])
    p.setBrush(QColor(c["slider"]))
    p.drawEllipse(QPointF(x0 + (rx + 0.025 + (1 - rx - 0.05) * 0.6) * W, y0 + 0.429 * H), H * 0.014, H * 0.014)
    # layers header + rows
    box(rx + 0.004, 0.46, 1 - rx, 0.05, c["header"])
    bar(rx + 0.02, 0.475, 0.05, 0.022, c["text_strong"])
    for i in range(4):
        y = 0.515 + i * 0.075
        col = c["selection"] if i == 1 else (c["alt_row"] if i % 2 else c["window"])
        box(rx + 0.004, y, 1 - rx, 0.072, col)
        box(rx + 0.004, y + 0.072, 1 - rx, 0.003, c["border"])
        thumb = QRectF(x0 + (rx + 0.04) * W, y0 + (y + 0.012) * H, 0.05 * W, 0.048 * H)
        p.fillRect(thumb, QColor("#6fb7ff") if i != 3 else QColor("#ffffff"))
        bar(rx + 0.105, y + 0.027, 0.1 if i != 2 else 0.08, 0.02, c["text_strong"] if i == 1 else c["text"])
        p.setBrush(QColor(c["icon"]))
        p.drawEllipse(QPointF(x0 + (rx + 0.02) * W, y0 + (y + 0.036) * H), H * 0.008, H * 0.008)
    # panel footer buttons: one normal, one accent
    bar(rx + 0.03, 0.85, 0.1, 0.05, c["button"], 0.25)
    bar(rx + 0.145, 0.85, 0.1, 0.05, c["accent"], 0.25)
    bar(rx + 0.165, 0.868, 0.06, 0.015, c["accent_text"])
    bar(rx + 0.05, 0.868, 0.06, 0.015, c["text"])
    # status bar
    box(0, 0.954, 1, 0.046, c["header"])
    box(0, 0.954, 1, 0.003, c["border"])
    bar(0.02, 0.968, 0.12, 0.018, c["text_dim"])
    p.restore()
    # frame
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(0, 0, 0, 120), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
    p.restore()


def preview_pixmap(colors, w=176, h=110, dpr=None):
    dpr = dpr or (QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0)
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_preview(p, QRectF(0, 0, w, h), colors)
    p.end()
    return pm


def source_label(t):
    return {"preset": "Built-in", "ai": "AI-made", "imported": "Imported"}.get(t.source, "Yours") + \
        (f" · by {t.author}" if t.author and t.source != "preset" else "")


# ====================================================================== menu rows with previews
class ThemeMenuRow(QWidget):
    """A menu row showing a theme's preview, name and description."""
    TW, TH = 92, 58

    def __init__(self, th, action, menu):
        super().__init__()
        self.th, self.action, self.menu = th, action, menu
        self.setMouseTracking(True)
        self.setMinimumWidth(320)
        self.setFixedHeight(self.TH + 14)
        self._hover = False
        self._pm = preview_pixmap(th.colors, self.TW, self.TH)
        menu.hovered.connect(self._menu_hovered)
        self.setToolTip(th.description or th.name)

    def _menu_hovered(self, _action):
        self.update()

    def enterEvent(self, ev):
        self._hover = True
        self.menu.setActiveAction(self.action)
        self.update()

    def leaveEvent(self, ev):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(ev.position().toPoint()):
            # close the whole menu chain, then apply
            m = self.menu
            while isinstance(m, QMenu):
                m.hide()
                m = m.parentWidget() if isinstance(m.parentWidget(), QMenu) else None
            self.action.trigger()

    def paintEvent(self, ev):
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self._hover or self.menu.activeAction() is self.action
        if active:
            p.fillRect(self.rect(), QColor(c["accent"]))
        fg = QColor(c["accent_text"] if active else c["text"])
        dim = QColor(c["accent_text"] if active else c["text_dim"])
        if active:
            dim.setAlphaF(0.8)
        # tick for the current theme
        if self.action.isChecked():
            pen = QPen(fg, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            y = self.height() / 2
            p.drawPolyline([QPointF(8, y), QPointF(12, y + 4), QPointF(19, y - 4)])
        p.drawPixmap(26, 7, self._pm)
        x = 26 + self.TW + 12
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(fg)
        tw = self.width() - x - 10
        p.drawText(QRectF(x, 12, tw, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f).elidedText(self.th.name, Qt.TextElideMode.ElideRight, int(tw)))
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(dim)
        p.drawText(QRectF(x, 32, tw, 16), Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(f).elidedText(f"{self.th.kind()} · {source_label(self.th)}",
                                              Qt.TextElideMode.ElideRight, int(tw)))
        if self.th.description:
            p.drawText(QRectF(x, 47, tw, 16), Qt.AlignmentFlag.AlignLeft,
                       QFontMetrics(f).elidedText(self.th.description, Qt.TextElideMode.ElideRight, int(tw)))
        p.end()


class ThemesMenu(QMenu):
    """Themes ▸ Presets / My Themes / Create Theme… / Edit / Import / Export / Delete / Reset."""

    def __init__(self, window):
        super().__init__("T&hemes", window)
        self.win = window
        self.presets_menu = self.addMenu("Presets")
        self.presets_menu.setObjectName("ThemeMenu")
        self.mine_menu = self.addMenu("My Themes")
        self.mine_menu.setObjectName("ThemeMenu")
        self.addSeparator()
        self.create_act = self.addAction("Create Theme…", lambda: self.win.open_theme_editor(new=True))
        self.edit_act = self.addAction("Edit Current Theme…", lambda: self.win.open_theme_editor(new=False))
        self.addSeparator()
        self.addAction("Import Theme…", self.import_theme)
        self.addAction("Export Current Theme…", self.export_theme)
        self.addSeparator()
        self.delete_act = self.addAction("Delete Current Theme", self.delete_current)
        self.addAction(f"Reset to {theme.default_theme().name}", lambda: self.choose(theme.default_theme()))
        self.aboutToShow.connect(self.refresh)
        self.refresh()

    def _fill(self, menu, themes, empty_text):
        menu.clear()
        cur = theme.current()
        if not themes:
            a = menu.addAction(empty_text)
            a.setEnabled(False)
            return
        for t in themes:
            act = QWidgetAction(menu)
            act.setText(t.name)
            act.setCheckable(True)
            act.setChecked(t.id == cur.id and t.same_colors(cur))
            act.triggered.connect(lambda _=False, th=t: self.choose(th))
            act.setDefaultWidget(ThemeMenuRow(t, act, menu))
            menu.addAction(act)

    def refresh(self):
        self._fill(self.presets_menu, theme.presets(), "")
        mine = theme.user_themes()
        self._fill(self.mine_menu, mine, "No saved themes yet - use Create Theme…")
        if mine:
            self.mine_menu.addSeparator()
        self.mine_menu.addAction("Open Themes Folder", self.open_folder)
        self.delete_act.setEnabled(not theme.current().builtin and theme.find(theme.current().id) is not None)
        self.edit_act.setText("Edit Current Theme…" if not theme.current().builtin else "Customise Current Theme…")

    def choose(self, t):
        theme.apply(QApplication.instance(), t, remember_choice=True)
        self.win.statusBar().showMessage(f"Theme: {t.name}", 4000)

    def import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self.win, "Import Theme", os.path.expanduser("~"),
                                              f"Lumen themes (*{theme.FILE_EXT} *.json);;All files (*)")
        if not path:
            return
        try:
            t = theme.import_file(path)
        except Exception as e:
            QMessageBox.warning(self.win, "Import Theme", f"Couldn't import that theme.\n\n{e}")
            return
        self.choose(t)

    def export_theme(self):
        t = theme.current()
        name = "".join(ch for ch in t.name if ch.isalnum() or ch in " -_").strip() or "theme"
        path, _ = QFileDialog.getSaveFileName(self.win, "Export Theme", os.path.join(os.path.expanduser("~"),
                                              name + theme.FILE_EXT), f"Lumen theme (*{theme.FILE_EXT})")
        if path:
            try:
                path = theme.export_file(t, path)
                self.win.statusBar().showMessage(f"Theme exported to {path}", 6000)
            except OSError as e:
                QMessageBox.warning(self.win, "Export Theme", f"Couldn't save the theme.\n\n{e}")

    def delete_current(self):
        t = theme.current()
        if t.builtin:
            return
        if QMessageBox.question(self.win, "Delete Theme", f"Delete the theme “{t.name}”?\n\n"
                                "Lumen will switch back to the default theme.") != QMessageBox.StandardButton.Yes:
            return
        theme.delete_user_theme(t.id)
        self.choose(theme.default_theme())

    def open_folder(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(theme.themes_dir()))


# ====================================================================== editor pieces
class Swatch(QPushButton):
    """A small colour chip that behaves like a button."""

    def __init__(self, color="#000000", size=(30, 20), parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(*size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { min-width: 0; padding: 0; border: none; background: transparent; }")

    def set_color(self, c):
        self.color = QColor(c)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.C["separator"]), 1))
        p.setBrush(self.color)
        p.drawRoundedRect(r, 3, 3)
        if self.isChecked():
            p.setPen(QPen(QColor(theme.C["accent"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5).adjusted(1, 1, -1, -1), 3, 3)
        p.end()


class TokenRow(QFrame):
    clicked = pyqtSignal(str)
    edited = pyqtSignal(str, str)

    def __init__(self, key, label, help_text):
        super().__init__()
        self.key = key
        self.setObjectName("TokenRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(help_text)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 6, 3)
        lay.setSpacing(8)
        self.swatch = Swatch()
        self.swatch.clicked.connect(lambda: self.clicked.emit(self.key))
        lay.addWidget(self.swatch)
        self.label = QLabel(label)
        lay.addWidget(self.label, 1)
        self.hex = QLineEdit()
        self.hex.setFixedWidth(78)
        self.hex.setMaxLength(7)
        self.hex.editingFinished.connect(self._hex_done)
        lay.addWidget(self.hex)
        self.selected = False

    def mousePressEvent(self, ev):
        self.clicked.emit(self.key)

    def set_color(self, hexstr):
        self.swatch.set_color(hexstr)
        if not self.hex.hasFocus():
            self.hex.setText(hexstr)

    def _hex_done(self):
        v = theme.normalize_hex(self.hex.text())
        if v:
            self.edited.emit(self.key, v)
        else:
            self.hex.setText(self.swatch.color.name())

    def set_selected(self, on):
        self.selected = on
        c = theme.C
        self.setStyleSheet(f"QFrame#TokenRow {{ background: {c['selection'] if on else 'transparent'};"
                           f" border-radius: 4px; }}")


class ThemePreview(QWidget):
    def __init__(self):
        super().__init__()
        self.colors = dict(theme.C)
        self.setMinimumSize(360, 225)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_colors(self, c):
        self.colors = dict(c)
        self.update()

    def heightForWidth(self, w):
        return int(w * 0.625)

    def hasHeightForWidth(self):
        return True

    def paintEvent(self, ev):
        p = QPainter(self)
        w = self.width()
        h = min(self.height(), int(w * 0.625))
        w = int(h / 0.625)
        paint_preview(p, QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), self.colors)
        p.end()


# ====================================================================== editor
class ThemeEditor(QDialog):
    """Create or edit a theme: start from any theme, tweak every colour, preview live, save."""

    def __init__(self, window, base=None, new=True):
        super().__init__(window)
        self.win = window
        self.setWindowTitle("Create Theme" if new else "Edit Theme")
        self.original = theme.current()          # restored on Cancel
        base = base or theme.current()
        self.editing = None if (new or base.builtin) else base
        self.colors = dict(base.colors)
        self.selected_key = "accent"
        self._name_touched = not new and self.editing is not None
        self.saved = None
        self.resize(1180, 760)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------- left: start from
        left = QWidget()
        left.setObjectName("SidePane")
        left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left.setFixedWidth(236)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 16, 8, 12)
        lab = QLabel("START FROM")
        lab.setObjectName("Dim")
        ll.addWidget(lab)
        self.bases = QListWidget()
        self.bases.setObjectName("SidePane")
        self.bases.setIconSize(QSize(96, 60))
        self.bases.setSpacing(2)
        for t in theme.all_themes():
            it = QListWidgetItem(QIcon(preview_pixmap(t.colors, 96, 60)), f"{t.name}\n{source_label(t)}")
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setToolTip(t.description or t.name)
            self.bases.addItem(it)
        self.bases.itemClicked.connect(self._base_chosen)
        ll.addWidget(self.bases, 1)
        outer.addWidget(left)

        # ---------- middle: details + colour list
        mid = QWidget()
        mid.setFixedWidth(372)
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(16, 16, 10, 12)
        ml.setSpacing(8)
        h = QLabel("Create Theme" if self.editing is None else "Edit Theme")
        h.setObjectName("Heading")
        ml.addWidget(h)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.name = QLineEdit(self.editing.name if self.editing else theme.unique_name("My Theme"))
        self.name.textEdited.connect(self._name_edited)
        self.author = QLineEdit(self.editing.author if self.editing else self.win.ctx.settings.value("theme/author", ""))
        self.author.setPlaceholderText("Your name (optional)")
        self.desc = QLineEdit(self.editing.description if self.editing else "")
        self.desc.setPlaceholderText("A short description (optional)")
        for i, (text, w) in enumerate((("Name", self.name), ("Author", self.author), ("About", self.desc))):
            grid.addWidget(QLabel(text), i, 0)
            grid.addWidget(w, i, 1)
        ml.addLayout(grid)

        quick = QLabel("QUICK START")
        quick.setObjectName("Section")
        ml.addWidget(quick)
        qrow = QHBoxLayout()
        qrow.setSpacing(6)
        self.quick = {}
        for key, text in (("window", "Background"), ("text", "Text"), ("accent", "Accent")):
            col = QVBoxLayout()
            col.setSpacing(2)
            sw = Swatch(self.colors[key], (64, 26))
            sw.setToolTip(f"Pick the {text.lower()} colour, then press Generate")
            sw.clicked.connect(lambda _=False, k=key: self._select(k))
            self.quick[key] = sw
            col.addWidget(sw)
            l2 = QLabel(text)
            l2.setObjectName("Dim")
            l2.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(l2)
            qrow.addLayout(col)
        qrow.addSpacing(6)
        gen = QPushButton("Generate")
        gen.setToolTip("Work out every other colour from Background, Text and Accent")
        gen.clicked.connect(self._generate)
        qrow.addWidget(gen, 0, Qt.AlignmentFlag.AlignTop)
        qrow.addStretch(1)
        ml.addLayout(qrow)

        allc = QLabel("ALL COLOURS")
        allc.setObjectName("Section")
        ml.addWidget(allc)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 4, 0)
        hl.setSpacing(1)
        self.rows = {}
        for group in theme.GROUPS:
            g = QLabel(group)
            g.setObjectName("Dim")
            g.setContentsMargins(4, 8, 0, 2)
            hl.addWidget(g)
            for key, label, grp, help_text in theme.TOKENS:
                if grp != group:
                    continue
                row = TokenRow(key, label, help_text)
                row.clicked.connect(self._select)
                row.edited.connect(self._set_token)
                self.rows[key] = row
                hl.addWidget(row)
        hl.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(holder)
        ml.addWidget(sa, 1)
        outer.addWidget(mid)

        # ---------- right: preview + picker
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 16, 16, 12)
        rl.setSpacing(10)
        pl = QLabel("PREVIEW")
        pl.setObjectName("Dim")
        rl.addWidget(pl)
        self.preview = ThemePreview()
        rl.addWidget(self.preview, 1)
        self.edit_title = QLabel()
        self.edit_title.setObjectName("Heading")
        rl.addWidget(self.edit_title)
        self.edit_help = QLabel()
        self.edit_help.setObjectName("Dim")
        self.edit_help.setWordWrap(True)
        rl.addWidget(self.edit_help)
        self.picker = ColorPicker(QColor(self.colors[self.selected_key]))
        self.picker.square.setFixedSize(210, 210)
        self.picker.hue.setFixedHeight(210)
        self.picker.colorChanged.connect(self._picked)
        rl.addWidget(self.picker)
        self.contrast = QLabel()
        self.contrast.setObjectName("Dim")
        rl.addWidget(self.contrast)

        bottom = QHBoxLayout()
        self.live = QCheckBox("Preview on Lumen while editing")
        self.live.setChecked(True)
        self.live.toggled.connect(self._live_toggled)
        bottom.addWidget(self.live)
        bottom.addStretch(1)
        exp = QPushButton("Export…")
        exp.setObjectName("Flat")
        exp.clicked.connect(self._export)
        bottom.addWidget(exp)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        if self.editing is not None:
            save_new = QPushButton("Save as New")
            save_new.clicked.connect(lambda: self._save(as_new=True))
            bottom.addWidget(save_new)
        save = QPushButton("Save Theme")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(lambda: self._save(as_new=False))
        bottom.addWidget(save)
        rl.addLayout(bottom)
        outer.addWidget(right, 1)

        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(140)
        self._live_timer.timeout.connect(self._apply_live)
        theme.notifier.changed.connect(self._restyle_rows)
        self._refresh_all()
        self._select(self.selected_key)

    # ---------------------------------------------------------------- state
    def working_theme(self):
        name = self.name.text().strip() or "Untitled Theme"
        kw = dict(author=self.author.text().strip(), description=self.desc.text().strip(), source="user")
        if self.editing is not None:
            return theme.Theme(name, self.colors, id=self.editing.id, created=self.editing.created, **kw)
        return theme.Theme(name, self.colors, **kw)

    def _refresh_all(self):
        for k, row in self.rows.items():
            row.set_color(self.colors[k])
        for k, sw in self.quick.items():
            sw.set_color(self.colors[k])
        self.preview.set_colors(self.colors)
        self._update_contrast()
        self._schedule_live()

    def _select(self, key):
        self.selected_key = key
        for k, row in self.rows.items():
            row.set_selected(k == key)
        for k, sw in self.quick.items():
            sw.setCheckable(True)
            sw.setChecked(k == key)
        self.edit_title.setText(theme.LABELS[key])
        self.edit_help.setText(next(t[3] for t in theme.TOKENS if t[0] == key))
        self.picker.blockSignals(True)
        self.picker.set_color(QColor(self.colors[key]))
        self.picker.blockSignals(False)
        self.rows[key].ensurePolished()

    def _restyle_rows(self, *_):
        for k, row in self.rows.items():
            row.set_selected(k == self.selected_key)

    def _picked(self, c):
        self._set_token(self.selected_key, c.name())

    def _set_token(self, key, value):
        value = theme.normalize_hex(value)
        if not value or self.colors.get(key) == value:
            return
        self.colors[key] = value
        if key == self.selected_key:
            self.picker.blockSignals(True)
            self.picker.set_color(QColor(value))
            self.picker.blockSignals(False)
        self.rows[key].set_color(value)
        if key in self.quick:
            self.quick[key].set_color(value)
        self.preview.set_colors(self.colors)
        self._update_contrast()
        self._schedule_live()

    def _generate(self):
        self.colors = theme.generate(self.colors["window"], self.colors["text"], self.colors["accent"])
        self._refresh_all()
        self._select(self.selected_key)

    def _base_chosen(self, item):
        t = item.data(Qt.ItemDataRole.UserRole)
        self.colors = dict(t.colors)
        if not self._name_touched and self.editing is None:
            self.name.setText(theme.unique_name(f"{t.name} Custom" if t.builtin else f"{t.name} Copy"))
        self._refresh_all()
        self._select(self.selected_key)

    def _name_edited(self, _):
        self._name_touched = True

    def _update_contrast(self):
        c = self.colors
        checks = [("Text", theme.contrast(c["text"], c["window"]), 4.5),
                  ("Secondary text", theme.contrast(c["text_dim"], c["window"]), 3.0),
                  ("Accent text", theme.contrast(c["accent_text"], c["accent"]), 3.0)]
        parts = []
        for label, ratio, need in checks:
            ok = ratio >= need
            col = theme.tone("ok" if ok else "warn")
            parts.append(f"<span style='color:{col}'>{'✓' if ok else '⚠'} {label} {ratio:.1f}:1</span>")
        self.contrast.setText("Readability: " + " &nbsp; ".join(parts))

    # ---------------------------------------------------------------- live preview
    def _schedule_live(self):
        if self.live.isChecked():
            self._live_timer.start()

    def _apply_live(self):
        theme.apply(QApplication.instance(), self.working_theme(), remember_choice=False)

    def _live_toggled(self, on):
        if on:
            self._apply_live()
        else:
            self._live_timer.stop()
            theme.apply(QApplication.instance(), self.original, remember_choice=False)

    # ---------------------------------------------------------------- finishing
    def _export(self):
        t = self.working_theme()
        name = "".join(ch for ch in t.name if ch.isalnum() or ch in " -_").strip() or "theme"
        path, _ = QFileDialog.getSaveFileName(self, "Export Theme", os.path.join(os.path.expanduser("~"),
                                              name + theme.FILE_EXT), f"Lumen theme (*{theme.FILE_EXT})")
        if path:
            try:
                theme.export_file(t, path)
            except OSError as e:
                QMessageBox.warning(self, "Export Theme", f"Couldn't save the theme.\n\n{e}")

    def _save(self, as_new=False):
        t = self.working_theme()
        if as_new or self.editing is None:
            t = t.copy(id=theme.new_id(t.name))
            t.name = theme.unique_name(t.name)
        else:
            t.name = theme.unique_name(t.name, exclude_id=t.id)
        try:
            self.saved = theme.save_user_theme(t)
        except OSError as e:
            QMessageBox.warning(self, "Save Theme", f"Couldn't save the theme.\n\n{e}")
            return
        if self.author.text().strip():
            self.win.ctx.settings.setValue("theme/author", self.author.text().strip())
        self._live_timer.stop()
        theme.apply(QApplication.instance(), self.saved, remember_choice=True)
        self.accept()

    def reject(self):
        self._live_timer.stop()
        if not theme.current().same_colors(self.original) or theme.current().id != self.original.id:
            theme.apply(QApplication.instance(), self.original, remember_choice=False)
        super().reject()

    def done(self, r):
        try:
            theme.notifier.changed.disconnect(self._restyle_rows)
        except TypeError:
            pass
        super().done(r)
