"""Dark, Photoshop-style theme for Lumen."""
from PyQt6.QtGui import QColor, QPalette, QFont
from PyQt6.QtWidgets import QApplication

# Core palette (modelled on Photoshop's darkest interface theme)
BG = "#323232"          # panels / toolbars
BG_DARK = "#282828"     # tab rows, headers
PASTEBOARD = "#1f1f1f"  # area behind the canvas
BORDER = "#1a1a1a"
INPUT = "#232323"
INPUT_BORDER = "#3c3c3c"
HOVER = "#404040"
PRESSED = "#1c1c1c"
TEXT = "#d4d4d4"
TEXT_DIM = "#8f8f8f"
ACCENT = "#2680eb"
ACCENT_HOVER = "#378ef0"

FONT_STACK = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'

QSS = f"""
* {{
    font-family: {FONT_STACK};
    font-size: 12px;
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QMainWindow::separator {{ background: {BORDER}; width: 2px; height: 2px; }}
QWidget#Pasteboard {{ background: {PASTEBOARD}; }}

/* ---------- menus ---------- */
QMenuBar {{
    background: {BG_DARK};
    border-bottom: 1px solid {BORDER};
    padding: 1px 4px;
}}
QMenuBar::item {{ background: transparent; padding: 4px 9px; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {HOVER}; }}
QMenuBar::item:pressed {{ background: {ACCENT}; color: white; }}
QMenu {{
    background: {BG};
    border: 1px solid {BORDER};
    padding: 4px 0;
}}
QMenu::item {{ padding: 5px 34px 5px 26px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::item:disabled {{ color: #6a6a6a; }}
QMenu::separator {{ height: 1px; background: #444; margin: 4px 8px; }}
QMenu::indicator {{ width: 12px; height: 12px; left: 8px; }}
QMenu::right-arrow {{ width: 8px; height: 8px; }}

/* ---------- tool bars ---------- */
QToolBar {{
    background: {BG};
    border: none;
    spacing: 2px;
}}
QToolBar#OptionsBar {{ border-bottom: 1px solid {BORDER}; padding: 2px 6px; }}
QToolBar#ToolBox {{ border-right: 1px solid {BORDER}; padding: 6px 3px; }}
QToolBar::separator {{ background: #444; width: 1px; height: 1px; margin: 5px 6px; }}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px;
}}
QToolButton:hover {{ background: {HOVER}; }}
QToolButton:pressed {{ background: {PRESSED}; }}
QToolButton:checked {{ background: {PRESSED}; border: 1px solid #111; }}
QToolButton#ToolButton {{ padding: 4px; }}
QToolButton#ModeButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QFontComboBox {{
    background: {INPUT};
    border: 1px solid {INPUT_BORDER};
    border-radius: 3px;
    padding: 3px 5px;
    selection-background-color: {ACCENT};
    min-height: 16px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}
QSpinBox, QDoubleSpinBox {{ padding-right: 2px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox::down-arrow {{ image: url(%ARROW%); width: 8px; height: 8px; }}
QComboBox QAbstractItemView {{
    background: {BG}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; selection-color: white;
}}
QCheckBox, QRadioButton {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 13px; height: 13px; background: {INPUT}; border: 1px solid #555;
}}
QCheckBox::indicator {{ border-radius: 2px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{ image: url(%CHECK%); }}

QSlider::groove:horizontal {{ height: 3px; background: #1a1a1a; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: #8a8a8a; border-radius: 1px; }}
QSlider::handle:horizontal {{
    background: #e6e6e6; width: 10px; height: 10px; margin: -4px 0; border-radius: 5px;
}}
QSlider::handle:horizontal:hover {{ background: white; }}

QPushButton {{
    background: #4a4a4a;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px 18px;
    min-width: 60px;
}}
QPushButton:hover {{ background: #585858; }}
QPushButton:pressed {{ background: #3a3a3a; }}
QPushButton:default, QPushButton#Primary {{
    background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600;
}}
QPushButton:default:hover, QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Flat {{
    background: transparent; border: 1px solid #5a5a5a;
}}
QPushButton#Flat:hover {{ background: {HOVER}; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: none; background: {PASTEBOARD}; }}
QTabBar {{ background: {BG_DARK}; }}
QTabBar::tab {{
    background: {BG_DARK};
    color: {TEXT_DIM};
    padding: 6px 10px 6px 12px;
    border-right: 1px solid {BORDER};
    min-width: 60px;
}}
QTabBar::tab:selected {{ background: {BG}; color: {TEXT}; }}
QTabBar::tab:hover:!selected {{ background: #2f2f2f; color: {TEXT}; }}
QTabBar#DocTabs::tab {{ padding: 7px 10px 7px 14px; }}
QTabBar#DocTabs::tab:selected {{ border-top: 2px solid {ACCENT}; padding-top: 5px; }}
QTabBar::close-button {{ subcontrol-position: right; margin-left: 4px; }}

QTabWidget#PanelGroup::pane {{ background: {BG}; border: none; border-top: 1px solid {BORDER}; }}
QTabWidget#PanelGroup > QTabBar::tab {{
    padding: 5px 12px; min-width: 0px; font-size: 11px; border-right: 1px solid {BORDER};
}}
QTabWidget#PanelGroup > QTabBar::tab:selected {{ color: white; font-weight: 600; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: {PASTEBOARD}; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: {PASTEBOARD}; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: #4b4b4b; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:hover {{ background: #5e5e5e; }}
QScrollBar::handle:vertical {{ min-height: 30px; }}
QScrollBar::handle:horizontal {{ min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QAbstractScrollArea {{ background: {BG}; border: none; }}

/* ---------- misc ---------- */
QStatusBar {{
    background: {BG_DARK};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {TEXT_DIM}; font-size: 11px; padding: 0 6px; }}
QListView, QListWidget, QTreeView {{
    background: {BG};
    border: none;
    alternate-background-color: #353535;
}}
QListView::item, QListWidget::item {{ padding: 4px 6px; }}
QListView::item:selected, QListWidget::item:selected {{ background: #4a4a4a; color: white; }}
QListView::item:hover, QListWidget::item:hover {{ background: #3a3a3a; }}
QToolTip {{
    background: #484848; color: #f0f0f0; border: 1px solid #222; padding: 4px 6px;
}}
QGroupBox {{
    border: 1px solid #444; border-radius: 4px; margin-top: 14px; padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {TEXT_DIM}; }}
QLabel {{ background: transparent; }}
QLabel#Dim {{ color: {TEXT_DIM}; }}
QLabel#Heading {{ font-size: 15px; font-weight: 600; color: white; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:vertical {{ height: 2px; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QFrame#OptSep {{ background: #4a4a4a; max-width: 1px; min-width: 1px; margin: 4px 6px; }}
"""


def apply(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: INPUT,
        QPalette.ColorRole.AlternateBase: "#353535",
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: "#4a4a4a",
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: "#484848",
        QPalette.ColorRole.ToolTipText: "#f0f0f0",
        QPalette.ColorRole.PlaceholderText: TEXT_DIM,
        QPalette.ColorRole.Mid: "#444444",
        QPalette.ColorRole.Dark: BORDER,
    }
    for role, col in roles.items():
        pal.setColor(role, QColor(col))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6a6a6a"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#6a6a6a"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6a6a6a"))
    app.setPalette(pal)
    f = QFont("Segoe UI")
    f.setPointSizeF(9)
    app.setFont(f)
    arrow, check = _write_assets()
    app.setStyleSheet(QSS.replace("%ARROW%", arrow).replace("%CHECK%", check))


def _write_assets():
    """Render the few stylesheet glyphs to a temp folder (QSS needs files)."""
    import os
    import tempfile
    from PyQt6.QtCore import Qt, QPointF
    from PyQt6.QtGui import QPixmap, QPainter, QPen, QPolygonF
    folder = os.path.join(tempfile.gettempdir(), "lumen_ui")
    os.makedirs(folder, exist_ok=True)
    arrow = os.path.join(folder, "arrow.png")
    check = os.path.join(folder, "check.png")
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(TEXT_DIM))
    p.drawPolygon(QPolygonF([QPointF(2, 5), QPointF(14, 5), QPointF(8, 12)]))
    p.end()
    pm.save(arrow)
    pm = QPixmap(26, 26)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("white"), 3.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(6, 13.5), QPointF(11, 18.5), QPointF(20, 7.5)]))
    p.end()
    pm.save(check)
    return arrow.replace("\\", "/"), check.replace("\\", "/")
