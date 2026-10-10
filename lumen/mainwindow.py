"""Main application window: menus, toolbox, options bar, documents and panels."""
import os
import sys
from PyQt6.QtCore import Qt, QSize, QTimer, QPoint, QPointF, QRect, QRectF, QEvent, pyqtSignal
from PyQt6.QtGui import (QIcon, QAction, QKeySequence, QImage, QImageReader, QImageWriter, QPainter, QColor,
                         QUndoGroup, QTransform, QGuiApplication, QPainterPath, QShortcut, QPen, QPolygonF)
from PyQt6.QtWidgets import (QProgressDialog, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QToolBar,
                             QToolButton, QLabel, QStackedWidget, QSplitter, QFileDialog, QMessageBox,
                             QMenu, QSizePolicy, QPushButton, QListWidget, QListWidgetItem, QApplication,
                             QDialog, QTextBrowser)

from . import icons, theme, imageops, __version__
from .context import AppContext
from .document import Document
from .canvas import Canvas
from .tools import TOOL_CLASSES, TOOL_GROUPS, crop_document
from .colors import FgBgWidget, ColorPanel, SwatchesPanel
from .panels import PanelGroup, NavigatorPanel, InfoPanel, HistoryPanel
from .layerspanel import LayersPanel
from .layers import Layer
from . import psd
from .dialogs import NewDocumentDialog, ImageSizeDialog, CanvasSizeDialog, QualityDialog
from . import config, updates, versioning
from .extensions import ExtensionManager, ExtensionError
from .extensions.api import ExtensionAPI
from .extensions.manager_ui import UpdateBanner, ExtensionsDialog

OPEN_FILTER = ("All Formats (*.psd *.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *.ico *.ppm *.pgm *.pbm *.xpm);;"
               "Photoshop (*.psd);;Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;All Files (*)")
SAVE_FILTERS = {
    "Photoshop (*.psd)": "psd",
    "PNG (*.png)": "png",
    "JPEG (*.jpg *.jpeg)": "jpg",
    "WebP (*.webp)": "webp",
    "BMP (*.bmp)": "bmp",
    "TIFF (*.tif *.tiff)": "tif",
}


class ToolGroupButton(QToolButton):
    """A toolbox slot. Click selects; right-click or press-and-hold shows the hidden tools."""
    chosen = pyqtSignal(str)

    def __init__(self, group, tools, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolButton")
        self.group = group
        self.tools = tools          # list of Tool objects
        self.current = tools[0]
        self.setCheckable(True)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(34, 32)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(350)
        self._hold.timeout.connect(self.show_menu)
        self.set_current(self.current)

    def set_current(self, tool):
        self.current = tool
        self.setIcon(icons.icon(tool.icon))
        self.setToolTip(f"{tool.title}  ({tool.key})")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            self.show_menu()
            return
        if len(self.tools) > 1:
            self._hold.start()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        held = not self._hold.isActive() and len(self.tools) > 1 and ev.button() == Qt.MouseButton.LeftButton \
            and getattr(self, "_menu_shown", False)
        self._hold.stop()
        self._menu_shown = False
        if held:
            self.setDown(False)
            return
        super().mouseReleaseEvent(ev)
        if ev.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.current.name)

    def nextCheckState(self):
        pass  # checked state is driven by the window

    def show_menu(self):
        if len(self.tools) < 2:
            return
        self._menu_shown = True
        m = QMenu(self)
        for t in self.tools:
            a = m.addAction(icons.icon(t.icon), f"{t.title}\t{t.key}")
            a.setCheckable(True)
            a.setChecked(t is self.current)
            a.triggered.connect(lambda _, n=t.name: self.chosen.emit(n))
        m.exec(self.mapToGlobal(QPoint(self.width(), 0)))
        self.setDown(False)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if len(self.tools) > 1:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#9a9a9a"))
            w, h = self.width(), self.height()
            p.drawPolygon(QPolygonF([QPointF(w - 3, h - 8), QPointF(w - 3, h - 3), QPointF(w - 8, h - 3)]))


class WelcomePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("Pasteboard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(60, 50, 60, 50)
        outer.setSpacing(50)
        left = QVBoxLayout()
        left.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icons.app_pixmap(72))
        left.addWidget(logo)
        title = QLabel("Welcome to Lumen")
        title.setStyleSheet("font-size: 26px; font-weight: 600; color: white;")
        left.addWidget(title)
        sub = QLabel("Create something new, or open an image to start editing.")
        sub.setObjectName("Dim")
        left.addWidget(sub)
        left.addSpacing(10)
        for text, slot, primary in (("New file", win.new_document, True), ("Open…", win.open_dialog, False)):
            b = QPushButton(text)
            b.setObjectName("Primary" if primary else "Flat")
            b.setFixedWidth(160)
            b.clicked.connect(slot)
            left.addWidget(b)
        tip = QLabel("Tip: you can also drag image files onto this window, or paste with Ctrl+V.")
        tip.setObjectName("Dim")
        left.addSpacing(10)
        left.addWidget(tip)
        left.addStretch(1)
        outer.addLayout(left)

        right = QVBoxLayout()
        h = QLabel("Recent")
        h.setObjectName("Heading")
        right.addWidget(h)
        self.recent = QListWidget()
        self.recent.setStyleSheet(f"background: {theme.PASTEBOARD};")
        self.recent.itemActivated.connect(lambda it: win.open_path(it.data(Qt.ItemDataRole.UserRole)))
        self.recent.itemClicked.connect(lambda it: win.open_path(it.data(Qt.ItemDataRole.UserRole)))
        right.addWidget(self.recent, 1)
        outer.addLayout(right, 1)

    def refresh(self, paths):
        self.recent.clear()
        if not paths:
            it = QListWidgetItem("No recent files yet")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(it)
            return
        for p in paths:
            it = QListWidgetItem(f"{os.path.basename(p)}\n{os.path.dirname(p)}")
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setIcon(icons.icon("open"))
            self.recent.addItem(it)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumen")
        ico = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "assets", "lumen.ico")
        self.setWindowIcon(QIcon(ico) if os.path.exists(ico) else icons.app_icon())
        self.resize(1500, 920)
        self.setAcceptDrops(True)

        self.ctx = AppContext()
        self.ctx.window = self
        self.ctx.tools = {cls.name: cls(self.ctx) for cls in TOOL_CLASSES}
        self.ctx.tool = None
        self.ctx.status.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.ctx.colorsChanged.connect(self._colors_changed)
        self.undo_group = QUndoGroup(self)

        self._build_options_bar()
        self._build_toolbox()
        self._build_central()
        self._build_status()
        self._build_menus()
        self.set_tool("brush")
        self._init_extensions()
        self._update_actions()

    # ================================================================ building
    def _build_options_bar(self):
        tb = QToolBar("Options")
        tb.setObjectName("OptionsBar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setFixedHeight(40)
        self.tool_badge = QLabel()
        self.tool_badge.setFixedSize(34, 28)
        self.tool_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tool_badge.setStyleSheet(f"background: {theme.PRESSED}; border-radius: 4px;")
        tb.addWidget(self.tool_badge)
        sep = QWidget()
        sep.setFixedWidth(8)
        tb.addWidget(sep)
        self.options_stack = QStackedWidget()
        self.options_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(self.options_stack)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.options_bar = tb

    def _build_toolbox(self):
        tb = QToolBar("Tools")
        tb.setObjectName("ToolBox")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setOrientation(Qt.Orientation.Vertical)
        tb.setFixedWidth(46)
        self.group_buttons = {}
        self.tool_to_group = {}
        for gid, names, sep in TOOL_GROUPS:
            tools = [self.ctx.tools[n] for n in names]
            b = ToolGroupButton(gid, tools)
            b.chosen.connect(self.set_tool)
            tb.addWidget(b)
            self.group_buttons[gid] = b
            for n in names:
                self.tool_to_group[n] = gid
            if sep:
                tb.addSeparator()
        spacer = QWidget()
        spacer.setFixedHeight(10)
        self._toolbox_end = tb.addWidget(spacer)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(1, 0, 0, 0)
        self.fgbg = FgBgWidget(self.ctx)
        hl.addWidget(self.fgbg)
        tb.addWidget(holder)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
        self.toolbox = tb

    def _build_central(self):
        self.docs = QTabWidget()
        self.docs.setDocumentMode(True)
        self.docs.setTabsClosable(False)
        self.docs.setMovable(True)
        self.docs.tabBar().setObjectName("DocTabs")
        self.docs.tabBar().setExpanding(False)
        self.docs.tabBar().setElideMode(Qt.TextElideMode.ElideMiddle)
        self.docs.tabCloseRequested.connect(self.close_tab)
        self.docs.currentChanged.connect(self._tab_changed)

        self.welcome = WelcomePage(self)
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.welcome)
        self.center_stack.addWidget(self.docs)

        # right panel column
        self.color_panel = ColorPanel(self.ctx)
        self.swatches_panel = SwatchesPanel(self.ctx)
        self.navigator = NavigatorPanel()
        self.info = InfoPanel()
        self.history = HistoryPanel(self.undo_group)
        self.group_color = PanelGroup()
        self.group_color.addTab(self.color_panel, "Color")
        self.group_color.addTab(self.swatches_panel, "Swatches")
        self.group_nav = PanelGroup()
        self.group_nav.addTab(self.navigator, "Navigator")
        self.group_nav.addTab(self.info, "Info")
        self.group_nav.addTab(self.history, "History")
        self.group_hist = self.group_nav           # extensions' panels are added here too
        self.layers_panel = LayersPanel(self)
        self.layers_panel.editTextRequested.connect(self.edit_type_layer)
        self.group_layers = PanelGroup()
        self.group_layers.addTab(self.layers_panel, "Layers")
        self.panels = QSplitter(Qt.Orientation.Vertical)
        self.panels.addWidget(self.group_color)
        self.panels.addWidget(self.group_nav)
        self.panels.addWidget(self.group_layers)
        self.panels.setSizes([230, 200, 420])
        self.panels.setChildrenCollapsible(False)
        self.panels.setMinimumWidth(250)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.center_stack)
        split.addWidget(self.panels)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([1200, 290])
        split.setChildrenCollapsible(False)
        self.banner = UpdateBanner()
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.banner)
        cl.addWidget(split, 1)
        self.setCentralWidget(central)
        self._refresh_welcome()

    def _build_status(self):
        sb = self.statusBar()
        self.zoom_label = QLabel("")
        self.size_label = QLabel("")
        self.pos_label = QLabel("")
        self.pos_label.setMinimumWidth(110)
        for w in (self.pos_label, self.size_label, self.zoom_label):
            sb.addPermanentWidget(w)

    def _act(self, menu, text, slot, shortcut=None, icon=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        if icon:
            a.setIcon(icons.icon(icon))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(a)
        if menu is not None:
            menu.addAction(a)
        return a

    def _build_menus(self):
        mb = self.menuBar()
        A = {}
        self.menus = {}
        m = mb.addMenu("&File")
        A["new"] = self._act(m, "New…", self.new_document, "Ctrl+N")
        A["open"] = self._act(m, "Open…", self.open_dialog, "Ctrl+O")
        self.recent_menu = m.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        m.addSeparator()
        A["close"] = self._act(m, "Close", lambda: self.close_tab(self.docs.currentIndex()), "Ctrl+W")
        A["close_all"] = self._act(m, "Close All", self.close_all, "Alt+Ctrl+W")
        m.addSeparator()
        A["save"] = self._act(m, "Save", self.save, "Ctrl+S")
        A["save_as"] = self._act(m, "Save As…", self.save_as, "Shift+Ctrl+S")
        A["export"] = self._act(m, "Export As…", self.export_as, "Alt+Shift+Ctrl+W")
        m.addSeparator()
        self._act(m, "Exit", self.close, "Ctrl+Q")

        m = mb.addMenu("&Edit")
        A["undo"] = self._act(m, "Undo", self.undo, "Ctrl+Z")
        A["redo"] = self._act(m, "Redo", self.redo, ["Shift+Ctrl+Z", "Ctrl+Y"])
        m.addSeparator()
        A["cut"] = self._act(m, "Cut", self.cut, "Ctrl+X")
        A["copy"] = self._act(m, "Copy", self.copy, "Ctrl+C")
        A["copy_merged"] = self._act(m, "Copy Merged", lambda: self.copy(merged=True), "Shift+Ctrl+C")
        A["paste"] = self._act(m, "Paste", self.paste, "Ctrl+V")
        A["clear"] = self._act(m, "Clear", self.clear, ["Delete", "Backspace"])
        m.addSeparator()
        A["fill_fg"] = self._act(m, "Fill with Foreground Color", lambda: self._doc_call("fill", self.ctx.fg, "Fill"),
                                 "Alt+Backspace")
        A["fill_bg"] = self._act(m, "Fill with Background Color", lambda: self._doc_call("fill", self.ctx.bg, "Fill"),
                                 "Ctrl+Backspace")

        m = mb.addMenu("&Image")
        adj = m.addMenu("Adjustments")
        A["invert"] = self._act(adj, "Invert", lambda: self._filter("Invert", imageops.invert), "Ctrl+I")
        A["desat"] = self._act(adj, "Desaturate", lambda: self._filter("Desaturate", imageops.desaturate),
                               "Shift+Ctrl+U")
        m.addSeparator()
        A["image_size"] = self._act(m, "Image Size…", self.image_size, "Alt+Ctrl+I")
        A["canvas_size"] = self._act(m, "Canvas Size…", self.canvas_size, "Alt+Ctrl+C")
        rot = m.addMenu("Image Rotation")
        A["rot180"] = self._act(rot, "180°", lambda: self._transform("Rotate Canvas", QTransform().rotate(180)))
        A["rot90"] = self._act(rot, "90° Clockwise", lambda: self._transform("Rotate Canvas", QTransform().rotate(90)))
        A["rot270"] = self._act(rot, "90° Counter Clockwise",
                                lambda: self._transform("Rotate Canvas", QTransform().rotate(-90)))
        rot.addSeparator()
        A["fliph"] = self._act(rot, "Flip Canvas Horizontal",
                               lambda: self._transform("Flip Canvas Horizontal", QTransform().scale(-1, 1)))
        A["flipv"] = self._act(rot, "Flip Canvas Vertical",
                               lambda: self._transform("Flip Canvas Vertical", QTransform().scale(1, -1)))
        A["crop_sel"] = self._act(m, "Crop to Selection", self.crop_to_selection)

        m = mb.addMenu("&Layer")
        new = m.addMenu("New")
        A["new_layer"] = self._act(new, "Layer…", self.new_layer_dialog, "Shift+Ctrl+N")
        A["new_layer_quick"] = self._act(None, "New Layer", lambda: self._doc_call("add_layer"), "Shift+Ctrl+Alt+N")
        A["layer_from_bg"] = self._act(new, "Layer from Background", lambda: self._doc_call("background_to_layer"))
        A["bg_from_layer"] = self._act(new, "Background from Layer", lambda: self._doc_call("layer_to_background"))
        new.addSeparator()
        A["via_copy"] = self._act(new, "Layer via Copy", lambda: self._doc_call("layer_via_copy"), "Ctrl+J")
        A["via_cut"] = self._act(new, "Layer via Cut", lambda: self._doc_call("layer_via_copy", True), "Shift+Ctrl+J")
        A["dup_layer"] = self._act(m, "Duplicate Layer", lambda: self._doc_call("duplicate_layer"))
        A["del_layer"] = self._act(m, "Delete Layer", lambda: self._doc_call("delete_layer"))
        A["rename_layer"] = self._act(m, "Rename Layer…", self.rename_layer)
        m.addSeparator()
        ras = m.addMenu("Rasterize")
        A["rasterize"] = self._act(ras, "Type", lambda: self._doc_call("rasterize_layer"))
        A["select_pixels"] = self._act(m, "Select Layer Pixels",
                                       lambda: self.current_doc() and self.current_doc().select_layer_pixels(
                                           self.current_doc().active))
        m.addSeparator()
        arr = m.addMenu("Arrange")
        A["front"] = self._act(arr, "Bring to Front", lambda: self._doc_call("arrange", "front"), "Shift+Ctrl+]")
        A["forward"] = self._act(arr, "Bring Forward", lambda: self._doc_call("arrange", "forward"), "Ctrl+]")
        A["backward"] = self._act(arr, "Send Backward", lambda: self._doc_call("arrange", "backward"), "Ctrl+[")
        A["back"] = self._act(arr, "Send to Back", lambda: self._doc_call("arrange", "back"), "Shift+Ctrl+[")
        A["sel_above"] = self._act(None, "Select Layer Above", lambda: self._doc_call("select_relative", 1), "Alt+]")
        A["sel_below"] = self._act(None, "Select Layer Below", lambda: self._doc_call("select_relative", -1), "Alt+[")
        m.addSeparator()
        A["merge_down"] = self._act(m, "Merge Down", lambda: self._doc_call("merge_down"), "Ctrl+E")
        A["merge_visible"] = self._act(m, "Merge Visible", lambda: self._doc_call("merge_visible"), "Shift+Ctrl+E")
        A["flatten"] = self._act(m, "Flatten Image", lambda: self._doc_call("flatten_image"))

        m = mb.addMenu("&Select")
        A["sel_all"] = self._act(m, "All", lambda: self._doc_call("select_all"), "Ctrl+A")
        A["deselect"] = self._act(m, "Deselect", lambda: self._doc_call("deselect"), "Ctrl+D")
        A["sel_inv"] = self._act(m, "Inverse", lambda: self._doc_call("invert_selection"), "Shift+Ctrl+I")
        m.addSeparator()
        A["load_sel"] = self._act(m, "Load Selection from Layer",
                                  lambda: self.current_doc() and self.current_doc().select_layer_pixels(
                                      self.current_doc().active))

        m = mb.addMenu("Fil&ter")
        A["last_filter"] = self._act(m, "Last Filter", self.repeat_last_filter, "Ctrl+Alt+F")
        m.addSeparator()
        self._filter_tail = m.addSeparator()
        self._act(m, "Get More Filters…", self.show_extensions)
        self.menus["filter"] = m

        m = mb.addMenu("&View")
        A["zin"] = self._act(m, "Zoom In", lambda: self._canvas_call("zoom_step", 1), ["Ctrl+=", "Ctrl++"])
        A["zout"] = self._act(m, "Zoom Out", lambda: self._canvas_call("zoom_step", -1), "Ctrl+-")
        A["fit"] = self._act(m, "Fit on Screen", lambda: self._canvas_call("fit_to_screen"), "Ctrl+0")
        A["100"] = self._act(m, "100%", lambda: self._canvas_call("actual_pixels"), "Ctrl+1")

        m = mb.addMenu("&Window")
        window_menu = m
        for text, grp, page, key in (("Color", self.group_color, 0, "F6"), ("Swatches", self.group_color, 1, None),
                                     ("History", self.group_nav, 2, None), ("Info", self.group_nav, 1, "F8"),
                                     ("Layers", self.group_layers, 0, "F7"), ("Navigator", self.group_nav, 0, None)):
            self._act(m, text, lambda _, g=grp, i=page: (self.panels.show(), g.setCurrentIndex(i)), key)
        m.addSeparator()
        A["panels"] = self._act(m, "Show Panels", self.toggle_panels, "Tab", checkable=True)
        A["panels"].setChecked(True)

        m = mb.addMenu("&Plugins")
        self._act(m, "Extensions…", self.show_extensions, "Ctrl+Alt+X")
        m.addSeparator()
        self.menus["plugins"] = m
        mb.insertMenu(window_menu.menuAction(), m)   # Photoshop order: … Plugins, Window, Help

        m = mb.addMenu("&Help")
        self._act(m, "Check for Updates…", lambda: self.check_for_updates(manual=True))
        A["auto_check"] = self._act(m, "Check for Updates on Startup", self._toggle_setting("updates/check_on_start"),
                                    checkable=True)
        A["auto_ext"] = self._act(m, "Update Extensions Automatically", self._toggle_setting("updates/auto_extensions"),
                                  checkable=True)
        A["auto_check"].setChecked(self._flag("updates/check_on_start", True))
        A["auto_ext"].setChecked(self._flag("updates/auto_extensions", False))
        m.addSeparator()
        self._act(m, "Keyboard Shortcuts", self.show_shortcuts, "F1")
        self._act(m, "About Lumen", self.about)
        self.A = A
        for menu in mb.findChildren(QMenu):
            if menu.parent() is mb:
                self.menus.setdefault(menu.title().replace("&", "").lower(), menu)

        # tool shortcuts (single keys, Shift+key cycles through a group)
        by_key = {}
        for gid, names, _ in TOOL_GROUPS:
            for n in names:
                by_key.setdefault(self.ctx.tools[n].key, gid)
        for key, gid in by_key.items():
            QShortcut(QKeySequence(key), self, activated=lambda g=gid: self.set_tool(self.group_buttons[g].current.name))
            QShortcut(QKeySequence("Shift+" + key), self, activated=lambda g=gid: self.cycle_group(g))
        QShortcut(QKeySequence("X"), self, activated=self.ctx.swap_colors)
        QShortcut(QKeySequence("D"), self, activated=self.ctx.default_colors)
        QShortcut(QKeySequence("["), self, activated=lambda: self.adjust_size(-1))
        QShortcut(QKeySequence("]"), self, activated=lambda: self.adjust_size(1))
        QShortcut(QKeySequence("Return"), self, activated=self._enter)
        QShortcut(QKeySequence("Enter"), self, activated=self._enter)
        QShortcut(QKeySequence("Escape"), self, activated=self._escape)

        self.undo_group.canUndoChanged.connect(self._update_actions)
        self.undo_group.canRedoChanged.connect(self._update_actions)
        self.undo_group.undoTextChanged.connect(self._update_actions)
        self.undo_group.redoTextChanged.connect(self._update_actions)

    # ================================================================ tools
    def set_tool(self, name):
        tool = self.ctx.tools[name]
        old = self.ctx.tool
        cv = self.current_canvas()
        if old is not None and old is not tool:
            old.deactivate(cv)
        self.ctx.tool = tool
        gid = self.tool_to_group[name]
        for g, b in self.group_buttons.items():
            b.setChecked(g == gid)
        self.group_buttons[gid].set_current(tool)
        w = tool.options_widget()
        if self.options_stack.indexOf(w) < 0:
            self.options_stack.addWidget(w)
        self.options_stack.setCurrentWidget(w)
        self.tool_badge.setPixmap(icons.pixmap(tool.icon, 20, QColor("#e8e8e8")))
        self.tool_badge.setToolTip(tool.title)
        tool.activate(cv)
        for i in range(self.docs.count()):
            self.docs.widget(i).refresh_cursor()
        self.ctx.toolChanged.emit(tool)

    def cycle_group(self, gid):
        b = self.group_buttons[gid]
        i = b.tools.index(b.current)
        self.set_tool(b.tools[(i + 1) % len(b.tools)].name)

    def adjust_size(self, direction):
        t = self.ctx.tool
        if t is None or "size" not in t.opts:
            return
        s = t.opts["size"]
        step = 1 if s < 10 else 5 if s < 50 else 10 if s < 100 else 25 if s < 300 else 50
        t.set_opt("size", max(1, min(2500 if t.name != "text" else 1000, s + direction * step)))

    def _enter(self):
        cv = self.current_canvas()
        if not cv:
            return
        t = self.ctx.tool
        if t and t.name == "crop" and t.rect:
            t.commit(cv)
        elif cv.doc.floating:
            cv.doc.commit_floating()

    def _escape(self):
        cv = self.current_canvas()
        if not cv:
            return
        t = self.ctx.tool
        if t and t.name == "crop" and t.rect:
            t.cancel(cv)
        elif cv.doc.floating:
            cv.doc.cancel_floating()

    # ================================================================ documents
    def current_canvas(self):
        w = self.docs.currentWidget()
        return w if isinstance(w, Canvas) else None

    def current_doc(self):
        c = self.current_canvas()
        return c.doc if c else None

    def add_document(self, doc: Document):
        doc.bg_color = self.ctx.bg
        doc.confirm = self._confirm_layer_action
        doc.blocked.connect(lambda msg: self.statusBar().showMessage(msg, 6000))
        doc.layersChanged.connect(self._update_actions)
        doc.activeLayerChanged.connect(self._update_actions)
        doc.layersChanged.connect(lambda: self._emit_ext("layers_changed", doc))
        doc.changed.connect(lambda r: self._emit_ext("document_changed", doc, r))
        cv = Canvas(doc, self.ctx)
        self.undo_group.addStack(doc.undo)
        cv.zoomChanged.connect(lambda _: self._update_tab_title(cv))
        doc.titleChanged.connect(lambda: self._update_tab_title(cv))
        doc.titleChanged.connect(self._update_actions)
        doc.sizeChanged.connect(self._update_status)
        doc.selectionChanged.connect(self._update_actions)
        cv.cursorMoved.connect(self._cursor_moved)
        idx = self.docs.addTab(cv, doc.name)
        close = QToolButton()
        close.setIcon(icons.icon("cancel", 12))
        close.setIconSize(QSize(10, 10))
        close.setFixedSize(18, 18)
        close.setToolTip("Close")
        close.setStyleSheet("QToolButton { border-radius: 9px; padding: 0; } QToolButton:hover { background: #555; }")
        close.clicked.connect(lambda: self.close_tab(self.docs.indexOf(cv)))
        self.docs.tabBar().setTabButton(idx, self.docs.tabBar().ButtonPosition.RightSide, close)
        self.center_stack.setCurrentWidget(self.docs)
        self.docs.setCurrentIndex(idx)
        cv.refresh_cursor()
        self._update_tab_title(cv)
        cv.setFocus()
        return cv

    def _tab_changed(self, idx):
        cv = self.current_canvas()
        t = self.ctx.tool
        if t is not None and t.name == "crop":
            t.cancel(None)
        if cv:
            self.undo_group.setActiveStack(cv.doc.undo)
            self.history.view.setEmptyLabel("Open" if cv.doc.path else "New Document")
            self.setWindowTitle(f"{cv.doc.name} — Lumen")
            cv.refresh_cursor()
        else:
            self.undo_group.setActiveStack(None)
            self.setWindowTitle("Lumen")
        self.navigator.set_canvas(cv)
        self.info.set_canvas(cv)
        self.layers_panel.set_document(cv.doc if cv else None)
        self._update_status()
        self._update_actions()
        if self.docs.count() == 0:
            self.center_stack.setCurrentWidget(self.welcome)
            self._refresh_welcome()

    def _update_tab_title(self, cv):
        i = self.docs.indexOf(cv)
        if i < 0:
            return
        d = cv.doc
        star = "*" if d.modified() else ""
        self.docs.setTabText(i, f"{d.name} @ {cv.zoom * 100:.4g}% (RGB/8){star}")
        self.docs.setTabToolTip(i, d.path or d.name)
        if cv is self.current_canvas():
            self.setWindowTitle(f"{d.name}{star} — Lumen")
            self._update_status()

    def _update_status(self):
        cv = self.current_canvas()
        if not cv:
            self.zoom_label.setText("")
            self.size_label.setText("")
            self.pos_label.setText("")
            return
        self.zoom_label.setText(f"{cv.zoom * 100:.4g}%")
        self.size_label.setText(f"{cv.doc.width} px × {cv.doc.height} px ({cv.doc.dpi} ppi)")

    def _cursor_moved(self, pt):
        self.pos_label.setText("" if pt is None else f"X: {pt.x()}  Y: {pt.y()}")

    def _colors_changed(self):
        for i in range(self.docs.count()):
            self.docs.widget(i).doc.bg_color = self.ctx.bg

    def _update_actions(self, *_):
        if not hasattr(self, "A"):
            return
        doc = self.current_doc()
        has = doc is not None
        for k in ("close", "close_all", "save", "save_as", "export", "cut", "copy", "copy_merged", "clear", "fill_fg",
                  "fill_bg", "invert", "desat", "image_size", "canvas_size", "rot180", "rot90", "rot270", "fliph",
                  "flipv", "sel_all", "deselect", "sel_inv", "zin", "zout", "fit", "100", "new_layer",
                  "new_layer_quick", "via_copy", "dup_layer", "rename_layer", "select_pixels", "load_sel",
                  "sel_above", "sel_below", "merge_visible", "flatten"):
            self.A[k].setEnabled(has)
        sel = has and doc.has_selection()
        self.A["crop_sel"].setEnabled(sel)
        self.A["cut"].setEnabled(sel)
        self.A["via_cut"].setEnabled(sel)
        self.A["deselect"].setEnabled(sel)
        L = doc.active if has else None
        idx = doc.layers.index(L) if L in (doc.layers if has else []) else -1
        self.A["del_layer"].setEnabled(has and len(doc.layers) > 1)
        self.A["layer_from_bg"].setEnabled(bool(L and L.background))
        self.A["bg_from_layer"].setEnabled(bool(has and doc.background_layer() is None and L and not L.is_text))
        self.A["rasterize"].setEnabled(bool(L and L.is_text))
        self.A["merge_down"].setEnabled(idx > 0)
        movable = bool(L and not L.background)
        bottom = 1 if has and doc.background_layer() is not None else 0
        self.A["front"].setEnabled(movable and idx < len(doc.layers) - 1)
        self.A["forward"].setEnabled(movable and idx < len(doc.layers) - 1)
        self.A["backward"].setEnabled(movable and idx > bottom)
        self.A["back"].setEnabled(movable and idx > bottom)
        for a in getattr(self, "_ext_actions", []):
            if a.property("needs_document"):
                a.setEnabled(has)
        self.A["last_filter"].setEnabled(has and getattr(self, "last_filter", None) is not None)
        can_undo = has and (self.undo_group.canUndo() or doc.floating is not None)
        self.A["undo"].setEnabled(can_undo)
        self.A["undo"].setText(f"Undo {self.undo_group.undoText()}".strip() if can_undo else "Undo")
        can_redo = has and self.undo_group.canRedo()
        self.A["redo"].setEnabled(can_redo)
        self.A["redo"].setText(f"Redo {self.undo_group.redoText()}".strip() if can_redo else "Redo")

    def _refresh_welcome(self):
        self.welcome.refresh(self.recent_files())

    # ---------------------------------------------------------------- file ops
    def new_document(self):
        clip = QGuiApplication.clipboard().image()
        dlg = NewDocumentDialog(self.ctx, self, (clip.width(), clip.height()) if not clip.isNull() else None)
        if dlg.exec():
            name, w, h, dpi, fill = dlg.values()
            self.create_document(w, h, fill, name, dpi)

    def create_document(self, w, h, fill=QColor("white"), name=None, dpi=72):
        img = QImage(w, h, imageops.PREMUL)
        img.fill(Qt.GlobalColor.transparent if fill is None else QColor(fill))
        doc = Document(img, None, name, transparent=fill is None, dpi=dpi)
        if name:
            Document._counter += 1
        return self.add_document(doc)

    def open_dialog(self):
        start = self.ctx.settings.value("last_dir", os.path.expanduser("~"))
        paths, _ = QFileDialog.getOpenFileNames(self, "Open", start, OPEN_FILTER)
        for p in paths:
            self.open_path(p)

    def open_path(self, path):
        if not path:
            return None
        path = os.path.abspath(path)
        for i in range(self.docs.count()):
            if self.docs.widget(i).doc.path == path:
                self.docs.setCurrentIndex(i)
                return self.docs.widget(i)
        if path.lower().endswith(".psd"):
            try:
                data = psd.read_psd(path)
            except Exception as e:
                QMessageBox.warning(self, "Lumen", f"Could not open “{os.path.basename(path)}”.\n\n{e}")
                return None
            doc = Document(size=data["size"], layers=data["layers"], path=path, dpi=data["dpi"])
            self.ctx.settings.setValue("last_dir", os.path.dirname(path))
            self._add_recent(path)
            return self.add_document(doc)
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            QMessageBox.warning(self, "Lumen", f"Could not open “{os.path.basename(path)}”.\n\n{reader.errorString()}")
            self._remove_recent(path)
            return None
        dpi = round(img.dotsPerMeterX() * 0.0254) or 72
        has_alpha = img.hasAlphaChannel()
        doc = Document(img, path, transparent=has_alpha, dpi=dpi if 10 <= dpi <= 2400 else 72)
        self.ctx.settings.setValue("last_dir", os.path.dirname(path))
        self._add_recent(path)
        return self.add_document(doc)

    @staticmethod
    def is_simple(doc):
        """True when saving as PNG/JPEG etc. loses nothing (one plain pixel layer)."""
        return len(doc.layers) == 1 and not doc.layers[0].is_text and doc.layers[0].visible \
            and doc.layers[0].opacity == 100 and doc.layers[0].fill == 100

    def _write(self, doc, path, fmt=None):
        doc.commit_floating()             # also commits any text being typed
        fmt = (fmt or os.path.splitext(path)[1].lstrip(".")).lower()
        fmt = {"jpeg": "jpg", "tiff": "tif"}.get(fmt, fmt)
        if fmt == "psd":
            try:
                psd.write_psd(path, doc)
            except Exception as e:
                QMessageBox.critical(self, "Lumen", f"Could not save “{os.path.basename(path)}”.\n\n{e}")
                return False
            return True
        img = doc.flattened()
        quality = -1
        if fmt == "jpg":
            dlg = QualityDialog("JPEG", self, int(self.ctx.settings.value("jpeg_quality", 90)))
            if not dlg.exec():
                return False
            quality = dlg.value()
            self.ctx.settings.setValue("jpeg_quality", quality)
        elif fmt == "webp":
            dlg = QualityDialog("WebP", self, int(self.ctx.settings.value("webp_quality", 90)))
            if not dlg.exec():
                return False
            quality = dlg.value()
            self.ctx.settings.setValue("webp_quality", quality)
        return self.write_image(img, path, fmt, quality, doc.dpi)

    def write_image(self, img, path, fmt, quality=-1, dpi=72):
        if fmt in ("jpg", "bmp"):
            flat = QImage(img.size(), QImage.Format.Format_RGB32)
            flat.fill(QColor("white"))
            p = QPainter(flat)
            p.drawImage(0, 0, img)
            p.end()
            img = flat
        else:
            img = img.convertToFormat(QImage.Format.Format_ARGB32)
        dpm = round(dpi / 0.0254)
        img.setDotsPerMeterX(dpm)
        img.setDotsPerMeterY(dpm)
        w = QImageWriter(path, b"jpeg" if fmt == "jpg" else b"tiff" if fmt == "tif" else fmt.encode())
        if quality >= 0:
            w.setQuality(quality)
        if not w.write(img):
            QMessageBox.critical(self, "Lumen", f"Could not save “{os.path.basename(path)}”.\n\n{w.errorString()}")
            return False
        return True

    def save(self, doc=None):
        doc = doc if isinstance(doc, Document) else self.current_doc()
        if not doc:
            return False
        ext = os.path.splitext(doc.path or "")[1].lower().lstrip(".")
        if not doc.path or ext not in ("psd", "png", "jpg", "jpeg", "bmp", "webp", "tif", "tiff"):
            return self.save_as(doc)
        if ext != "psd" and not self.is_simple(doc):
            return self.save_as(doc)      # Photoshop: layered work goes to Save As (.psd) rather than flattening
        if self._write(doc, doc.path):
            doc.commit_floating()
            doc.undo.setClean()
            self.statusBar().showMessage(f"Saved {doc.path}", 4000)
            return True
        return False

    def _ask_path(self, doc, title):
        start_dir = os.path.dirname(doc.path) if doc.path else self.ctx.settings.value("last_dir", os.path.expanduser("~"))
        base = os.path.splitext(doc.name)[0]
        cur = os.path.splitext(doc.path or "")[1].lower().lstrip(".")
        if title == "Export As":
            default = cur if cur in ("png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff") else "png"
        else:
            default = "psd" if not self.is_simple(doc) or cur == "psd" or not cur else cur
        default = {"jpeg": "jpg", "tiff": "tif"}.get(default, default)
        flt0 = next((f for f, e in SAVE_FILTERS.items() if e == default), "PNG (*.png)")
        path, flt = QFileDialog.getSaveFileName(self, title, os.path.join(start_dir, f"{base}.{default}"),
                                                ";;".join(SAVE_FILTERS), flt0)
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext not in ("psd", "png", "jpg", "jpeg", "bmp", "webp", "tif", "tiff"):
            path += "." + SAVE_FILTERS.get(flt, default)
        self.ctx.settings.setValue("last_dir", os.path.dirname(path))
        return path

    def save_as(self, doc=None):
        doc = doc if isinstance(doc, Document) else self.current_doc()
        if not doc:
            return False
        path = self._ask_path(doc, "Save As")
        if not path or not self._write(doc, path):
            return False
        doc.commit_floating()
        doc.path = os.path.abspath(path)
        doc.name = os.path.basename(path)
        doc.undo.setClean()
        doc.titleChanged.emit()
        self._add_recent(doc.path)
        self.statusBar().showMessage(f"Saved {doc.path}", 4000)
        return True

    def export_as(self):
        doc = self.current_doc()
        if not doc:
            return
        path = self._ask_path(doc, "Export As")
        if path and self._write(doc, path):
            self.statusBar().showMessage(f"Exported {path}", 4000)

    def _confirm_close(self, doc):
        if not doc.modified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Lumen")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Save changes to “{doc.name}” before closing?")
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Don't Save", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel:
            return False
        if clicked is save:
            return self.save(doc)
        return True

    def close_tab(self, idx):
        if idx < 0:
            return True
        cv = self.docs.widget(idx)
        if not self._confirm_close(cv.doc):
            return False
        self.undo_group.removeStack(cv.doc.undo)
        self.docs.removeTab(idx)
        cv.deleteLater()
        return True

    def close_all(self):
        while self.docs.count():
            if not self.close_tab(self.docs.currentIndex()):
                return False
        return True

    def closeEvent(self, ev):
        if not self.close_all():
            ev.ignore()
            return
        ev.accept()

    # ---------------------------------------------------------------- recent
    def recent_files(self):
        r = self.ctx.settings.value("recent", [])
        if isinstance(r, str):
            r = [r]
        return [p for p in (r or []) if isinstance(p, str)]

    def _add_recent(self, path):
        r = [p for p in self.recent_files() if p != path]
        r.insert(0, path)
        self.ctx.settings.setValue("recent", r[:12])
        self._refresh_welcome()

    def _remove_recent(self, path):
        self.ctx.settings.setValue("recent", [p for p in self.recent_files() if p != path])
        self._refresh_welcome()

    def _fill_recent_menu(self):
        self.recent_menu.clear()
        files = self.recent_files()
        if not files:
            a = self.recent_menu.addAction("No recent files")
            a.setEnabled(False)
            return
        for p in files:
            self.recent_menu.addAction(os.path.basename(p), lambda p=p: self.open_path(p)).setToolTip(p)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Recent File List",
                                   lambda: (self.ctx.settings.setValue("recent", []), self._refresh_welcome()))

    # ---------------------------------------------------------------- edit ops
    def _doc_call(self, name, *args):
        d = self.current_doc()
        if d:
            getattr(d, name)(*args)

    def _canvas_call(self, name, *args):
        c = self.current_canvas()
        if c:
            getattr(c, name)(*args)

    def undo(self):
        d = self.current_doc()
        if d and d.editing_text is not None:
            d.editing_text.cancel()
            self._update_actions()
            return
        if d and d.cancel_floating():
            self._update_actions()
            return
        self.undo_group.undo()

    def redo(self):
        d = self.current_doc()
        if d:
            d.commit_floating()
        self.undo_group.redo()

    def copy(self, merged=False):
        """Copy the selection (or whole canvas) from the active layer, or from all layers when merged."""
        d = self.current_doc()
        if not d:
            return
        if d.floating and not merged:
            img = d.floating.image
        else:
            d.commit_floating()
            src = d.composite() if merged else d.layer_pixels()
            img = imageops.masked_copy(src, d.selection) if d.has_selection() else src.copy()
        if img is None or img.isNull():
            return
        QGuiApplication.clipboard().setImage(img.convertToFormat(QImage.Format.Format_ARGB32))
        return img

    def cut(self):
        d = self.current_doc()
        if not d or not d.has_selection():
            return
        d.commit_floating()
        self.copy()
        d.clear_selection_pixels("Cut")

    def paste(self):
        """Photoshop pastes onto a new layer, centred in the view (or in place over the selection)."""
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            self.statusBar().showMessage("The clipboard doesn't contain an image.", 4000)
            return
        cv = self.current_canvas()
        if cv is None:
            cv = self.create_document(img.width(), img.height(), None)
            cv.doc.layers[0].name = "Layer 1"
            cv.doc.layers[0].put_region(QRect(0, 0, img.width(), img.height()), imageops.to_working(img))
            cv.doc.invalidate(QRect())
            cv.doc.layersChanged.emit()
            self.set_tool("move")
            return
        d = cv.doc
        d.commit_floating()
        if d.has_selection():
            centre = QRectF(d.selection_bounds()).center()
        elif cv.isVisible():
            centre = cv.visible_image_rect().center()
        else:
            centre = QRectF(d.rect()).center()
        pos = QPoint(round(centre.x() - img.width() / 2), round(centre.y() - img.height() / 2))
        if img.width() >= d.width and img.height() >= d.height:
            pos = QPoint(0, 0)
        d.add_layer(d.next_layer_name(), imageops.to_working(img), pos, text="Paste")
        self.set_tool("move")

    def clear(self):
        """Delete/Backspace: clear the selection; with no selection, delete the layer (Photoshop CC)."""
        d = self.current_doc()
        if not d:
            return
        if d.floating:
            self._clear_floating(d)
            return
        if d.has_selection():
            d.clear_selection_pixels("Clear")
        else:
            d.delete_layer()

    def _clear_floating(self, d):
        d.floating.image.fill(Qt.GlobalColor.transparent)
        d.floating.label = "Clear"
        d.commit_floating()

    def _filter(self, label, fn):
        d = self.current_doc()
        if d:
            d.filter_region(label, fn)

    # ---------------------------------------------------------------- layer UI
    def _confirm_layer_action(self, kind, layer):
        if kind == "rasterize":
            r = QMessageBox.question(self, "Lumen", "This type layer must be rasterized before proceeding. "
                                     "Its text will no longer be editable.\n\nRasterize the type?",
                                     QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            return r == QMessageBox.StandardButton.Ok
        return True

    def new_layer_dialog(self):
        d = self.current_doc()
        if not d:
            return
        from .dialogs import NewLayerDialog
        dlg = NewLayerDialog(d.next_layer_name(), self)
        if dlg.exec():
            name, blend, opacity = dlg.values()
            L = d.add_layer(name)
            if blend != "norm" or opacity != 100:
                L.blend, L.opacity = blend, opacity
                d.layersChanged.emit()

    def rename_layer(self):
        d = self.current_doc()
        if d:
            rows = self.layers_panel.list.rows()
            self.layers_panel.list.start_rename(rows.index(d.active), d.active)

    def edit_type_layer(self, layer):
        cv = self.current_canvas()
        if cv is None:
            return
        self.set_tool("text")
        self.ctx.tools["text"].begin_edit(cv.doc, layer, select_all=True)
        cv.setFocus()

    # ---------------------------------------------------------------- image ops (every layer)
    def _transform_layers(self, d, label, T: QTransform, new_size, smooth=False):
        mode = Qt.TransformationMode.SmoothTransformation if smooth else Qt.TransformationMode.FastTransformation
        layers, active = [], None
        lin = QTransform(T.m11(), T.m12(), T.m21(), T.m22(), 0, 0)
        for L in d.layers:
            N = L.clone(keep_uid=True)
            if L.is_text:
                N.text.transform = L.text.transform * T
                N.rerender_text()
            else:
                mapped = T.mapRect(QRectF(L.rect()))
                img = L.image.transformed(lin, mode)
                if smooth:
                    img = L.image.scaled(max(1, round(mapped.width())), max(1, round(mapped.height())),
                                         Qt.AspectRatioMode.IgnoreAspectRatio, mode)
                N.image = imageops.to_working(img)
                N.offset = QPoint(round(mapped.left()), round(mapped.top()))
                if L.background and N.image.size() != new_size:
                    N.image = N.image.scaled(new_size, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
                    N.offset = QPoint(0, 0)
            layers.append(N)
            if L is d.active:
                active = N
        d.replace_state(label, new_size, layers, active)

    def _transform(self, label, tr):
        d = self.current_doc()
        if not d:
            return
        d.commit_floating()
        box = tr.mapRect(QRectF(d.rect()))
        T = tr * QTransform.fromTranslate(-box.left(), -box.top())
        self._transform_layers(d, label, T, box.toRect().size())

    def image_size(self):
        d = self.current_doc()
        if not d:
            return
        dlg = ImageSizeDialog(d.width, d.height, self)
        if dlg.exec():
            w, h, smooth = dlg.values()
            self.resize_image(d, w, h, smooth)

    def resize_image(self, d, w, h, smooth=True):
        if (w, h) == (d.width, d.height):
            return
        d.commit_floating()
        T = QTransform.fromScale(w / d.width, h / d.height)
        self._transform_layers(d, "Image Size", T, QSize(w, h), smooth)

    def canvas_size(self):
        d = self.current_doc()
        if not d:
            return
        dlg = CanvasSizeDialog(d.width, d.height, self)
        if dlg.exec():
            w, h, anchor, ext = dlg.values()
            self.resize_canvas(d, w, h, anchor, ext)

    def resize_canvas(self, d, w, h, anchor=(1, 1), ext=0):
        if (w, h) == (d.width, d.height):
            return
        d.commit_floating()
        fill = [self.ctx.bg, self.ctx.fg, QColor("white"), QColor("black"), None][ext]
        dx = round((w - d.width) * anchor[0] / 2)
        dy = round((h - d.height) * anchor[1] / 2)
        layers, active = [], None
        for L in d.layers:
            N = L.clone(keep_uid=True)
            if L.background:
                out = QImage(w, h, imageops.PREMUL)
                out.fill(fill if fill is not None else d.bg_color)
                p = QPainter(out)
                p.drawImage(L.offset + QPoint(dx, dy), L.image)
                p.end()
                N.image, N.offset = out, QPoint(0, 0)
            else:
                N.translate(dx, dy)
                if N.is_text:
                    N.rerender_text()
            layers.append(N)
            if L is d.active:
                active = N
        d.replace_state("Canvas Size", QSize(w, h), layers, active)

    def crop_to_selection(self):
        d = self.current_doc()
        if d and d.has_selection():
            d.commit_floating()
            crop_document(d, d.selection_bounds(), "Crop")

    # ---------------------------------------------------------------- window
    def toggle_panels(self):
        vis = not self.panels.isVisible()
        self.panels.setVisible(vis)
        self.A["panels"].setChecked(vis)

    def show_shortcuts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        dlg.resize(520, 600)
        lay = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setStyleSheet(f"background: {theme.BG}; border: none;")
        rows = []
        for gid, names, _ in TOOL_GROUPS:
            for n in names:
                t = self.ctx.tools[n]
                rows.append((t.title, t.key + ("  (Shift+" + t.key + " cycles)" if len(names) > 1 else "")))
        rows += [("Swap colours", "X"), ("Default colours", "D"), ("Brush size", "[  /  ]"),
                 ("Pan while using any tool", "Hold Space"), ("Pick colour while painting", "Alt+click"),
                 ("Zoom", "Ctrl+wheel / Alt+wheel"), ("Undo / Redo", "Ctrl+Z / Shift+Ctrl+Z"),
                 ("Fit on screen / 100%", "Ctrl+0 / Ctrl+1"), ("Fill fg / bg", "Alt+Backspace / Ctrl+Backspace"),
                 ("Straight brush line", "Click, then Shift+click"), ("Hide panels", "Tab")]
        html = "<table cellpadding=5 width='100%'>" + "".join(
            f"<tr><td>{a}</td><td align='right' style='color:#9ab'>{b}</td></tr>" for a, b in rows) + "</table>"
        tb.setHtml(html)
        lay.addWidget(tb)
        dlg.exec()

    def about(self):
        QMessageBox.about(self, "About Lumen",
                          f"<h3>Lumen {__version__}</h3><p>A Photoshop-style image editor built with Python and Qt.</p>")

    # ---------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() or ev.mimeData().hasImage():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        md = ev.mimeData()
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    self.open_path(u.toLocalFile())
        elif md.hasImage():
            img = QImage(md.imageData())
            if not img.isNull():
                self.add_document(Document(img))

    # ================================================================ extensions & updates
    def _flag(self, key, default):
        v = self.ctx.settings.value(key, default)
        return v in (True, "true", 1, "1")

    def _toggle_setting(self, key):
        return lambda checked=False: self.ctx.settings.setValue(key, bool(checked))

    def _emit_ext(self, event, *args):
        for fn in list(self.ext_events.get(event, [])):
            try:
                fn(*args)
            except Exception as e:
                self.statusBar().showMessage(f"Extension error ({event}): {e}", 6000)

    def _init_extensions(self):
        self.ext_events = {}
        self.ctx.toolChanged.connect(lambda t: self._emit_ext("tool_changed", t))
        self.last_filter = None
        self._ext_actions = []
        self.extensions = ExtensionManager(self.ctx.settings)
        self.extensions.api_factory = lambda ext: ExtensionAPI(self, ext)
        self.extensions.load_all()
        for ext in self.extensions.items.values():
            if ext.error and self.extensions.is_enabled(ext.id):
                self.statusBar().showMessage(f"Extension “{ext.name}” failed to load: {ext.error}", 8000)
        self.checker = updates.UpdateChecker(parent=self)
        self.checker.checked.connect(self._update_check_done)
        self.checker.failed.connect(self._update_check_failed)
        self._manual_check = False
        if not config.offline() and self._flag("updates/check_on_start", True):
            QTimer.singleShot(1200, self.check_for_updates)

    def menu_path(self, path):
        """'Filter/Blur' -> Blur submenu of Filter. Unknown top-level menus are created before View."""
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        key = parts[0].replace("&", "").lower()
        menu = self.menus.get(key)
        if menu is None:
            menu = QMenu(parts[0], self.menuBar())
            self.menuBar().insertMenu(self.menus["view"].menuAction(), menu)
            self.menus[key] = menu
        for name in parts[1:]:
            found = None
            for a in menu.actions():
                if a.menu() and a.text().replace("&", "") == name:
                    found = a.menu()
            if found is None:
                found = QMenu(name, menu)
                if menu is self.menus.get("filter"):
                    menu.insertMenu(self._filter_tail, found)
                else:
                    menu.addMenu(found)
            menu = found
        return menu

    def register_extension_action(self, action):
        self._ext_actions.append(action)
        # filters added directly to the Filter menu go above "Get More Filters…"
        filt = self.menus.get("filter")
        if filt is not None and action in filt.actions():
            filt.removeAction(action)
            filt.insertAction(self._filter_tail, action)
        action.setEnabled(self.current_doc() is not None or not action.property("needs_document"))

    def register_tool(self, tool_cls, group=None):
        tool = tool_cls(self.ctx)
        if tool.name in self.ctx.tools:
            raise ExtensionError(f"a tool named '{tool.name}' already exists")
        self.ctx.tools[tool.name] = tool
        if group in self.group_buttons:
            b = self.group_buttons[group]
            b.tools.append(tool)
            b.update()
            gid = group
        else:
            gid = group or tool.name
            b = ToolGroupButton(gid, [tool])
            b.chosen.connect(self.set_tool)
            self.toolbox.insertWidget(self._toolbox_end, b)
            self.group_buttons[gid] = b
            if tool.key and not any(t.key == tool.key for n, t in self.ctx.tools.items() if n != tool.name):
                QShortcut(QKeySequence(tool.key), self,
                          activated=lambda g=gid: self.set_tool(self.group_buttons[g].current.name))
        self.tool_to_group[tool.name] = gid
        return tool

    def register_panel(self, title, widget):
        self.group_hist.addTab(widget, title)
        return widget

    def repeat_last_filter(self):
        if self.last_filter and self.current_doc():
            title, fn, values = self.last_filter
            self.current_doc().filter_region(title, lambda img: fn(img, **values))

    def show_extensions(self):
        dlg = ExtensionsDialog(self)
        dlg.exec()

    # ---------------------------------------------------------------- checking
    def check_for_updates(self, manual=False):
        self._manual_check = manual
        if manual:
            self.statusBar().showMessage("Checking for updates…", 3000)
        self.checker.check()

    def _update_check_failed(self, msg):
        if self._manual_check:
            QMessageBox.warning(self, "Lumen", f"Couldn't check for updates.\n\n{msg}")
        self._manual_check = False

    def _update_check_done(self, manifest):
        manual, self._manual_check = self._manual_check, False
        app_entry = manifest.app_update()
        ext_updates = manifest.extension_updates(self.extensions.installed_versions())
        if ext_updates and self._flag("updates/auto_extensions", False):
            self.install_extensions(ext_updates, then=lambda: self._show_update_banner(app_entry, []))
            return
        if not app_entry and not ext_updates:
            if manual:
                QMessageBox.information(self, "Lumen", f"You're up to date — Lumen {__version__} and all extensions "
                                                       "are on their latest versions.")
            return
        self._show_update_banner(app_entry, ext_updates)

    def _show_update_banner(self, app_entry, ext_updates):
        parts = []
        if app_entry:
            parts.append(f"<b>Lumen {app_entry['version']}</b> is available (you have {__version__})")
        if ext_updates:
            n = len(ext_updates)
            names = ", ".join(e.get("name", e["id"]) for e in ext_updates[:3])
            parts.append(f"{n} extension update{'s' if n > 1 else ''} ({names})")
        if self.extensions.restart_needed:
            parts.append("restart to finish applying extension updates")
        if not parts:
            return
        actions = []
        if app_entry or ext_updates:
            actions.append(("Update", lambda: self.update_everything(app_entry, ext_updates), True))
        if self.extensions.restart_needed and not app_entry:
            actions.append(("Restart Now", self.restart_app, not ext_updates))
        actions.append(("Details", self.show_extensions if not app_entry else
                        lambda: QMessageBox.information(self, f"Lumen {app_entry['version']}",
                                                        app_entry.get("notes") or "A new version of Lumen is ready."),
                        False))
        msg = " · ".join(parts)
        self.banner.show_message(msg[0].upper() + msg[1:], actions)

    def update_everything(self, app_entry, ext_updates):
        self.banner.hide()

        def after_exts():
            if app_entry:
                self.update_app(app_entry)
            elif self.extensions.restart_needed:
                self._show_update_banner(None, [])
        if ext_updates:
            self.install_extensions(ext_updates, then=after_exts)
        else:
            after_exts()

    # ---------------------------------------------------------------- installing
    def _progress(self, title):
        dlg = QProgressDialog(title, "Cancel", 0, 100, self)
        dlg.setWindowTitle("Lumen")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        return dlg

    def install_extension(self, entry, then=None, quiet=False):
        task = self.extensions.download_task(entry)
        prog = None if quiet else self._progress(f"Downloading {entry.get('name', entry['id'])}…")
        if prog:
            prog.canceled.connect(task.cancel)
            task.progress.connect(lambda d, t: prog.setValue(int(d * 100 / t)) if t else prog.setRange(0, 0))

        def ok(path):
            if prog:
                prog.close()
            try:
                ext, hot = self.extensions.install_zip(path, entry["id"])
                self.statusBar().showMessage(
                    f"Installed {ext.name} {ext.version}" + ("" if hot or not self.extensions.restart_needed
                                                              else " — restart Lumen to apply"), 6000)
            except Exception as e:
                QMessageBox.warning(self, "Lumen", f"Couldn't install {entry.get('name', entry['id'])}.\n\n{e}")
            self._update_actions()
            if then:
                then()

        def fail(msg):
            if prog:
                prog.close()
            if msg != "Cancelled":
                QMessageBox.warning(self, "Lumen", f"Couldn't download {entry.get('name', entry['id'])}.\n\n{msg}")
            if then:
                then()
        task.succeeded.connect(ok)
        task.failed.connect(fail)
        task.start()
        return task

    def install_extensions(self, entries, then=None):
        queue = list(entries)

        def step():
            if not queue:
                if then:
                    then()
                return
            self.install_extension(queue.pop(0), then=step, quiet=False)
        step()

    def install_extension_file(self, path):
        try:
            ext, hot = self.extensions.install_zip(path)
        except Exception as e:
            QMessageBox.warning(self, "Lumen", f"That isn't a valid Lumen extension.\n\n{e}")
            return None
        self.statusBar().showMessage(f"Installed {ext.name} {ext.version}", 6000)
        self._update_actions()
        return ext

    def update_app(self, entry):
        if not updates.can_self_update():
            # running from source: point at the release instead of running an installer
            updates.open_releases_page()
            return
        task = updates.download_installer_task(entry)
        prog = self._progress(f"Downloading Lumen {entry['version']}…")
        prog.canceled.connect(task.cancel)
        task.progress.connect(lambda d, t: prog.setValue(int(d * 100 / t)) if t else prog.setRange(0, 0))

        def ok(path):
            prog.close()
            if not self.close_all():
                self.statusBar().showMessage("Update postponed — documents are still open.", 6000)
                return
            updates.launch_installer(path)
            self._quitting_for_update = True
            QApplication.quit()

        def fail(msg):
            prog.close()
            if msg != "Cancelled":
                QMessageBox.warning(self, "Lumen", f"The update couldn't be downloaded.\n\n{msg}")
        task.succeeded.connect(ok)
        task.failed.connect(fail)
        task.start()

    def restart_app(self):
        if not self.close_all():
            return
        from PyQt6.QtCore import QProcess
        if config.is_frozen():
            QProcess.startDetached(sys.executable, [])
        else:
            main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
            QProcess.startDetached(sys.executable, [main])
        QApplication.quit()
