"""Lumen's theme engine.

A theme is a set of named colours (TOKENS). Everything in the interface - the stylesheet, the Qt palette,
the icons and the custom-painted panels - reads its colours from the active theme, so switching theme
restyles the whole app live.

Themes come from three places:
  * presets built into Lumen (PRESETS)
  * themes the user made in Themes ▸ Create Theme…  (saved in <data>/themes/*.lumentheme)
  * themes imported from a file (a future online Theme gallery will hand out the same files)

The chosen theme is remembered in the settings (id + a full copy of its colours), and user themes live in
the user data folder, so both survive restarts and app updates.

Theme file format (JSON, extension .lumentheme):
    {"format": "lumen-theme", "format_version": 1, "id": "…", "name": "…", "author": "…",
     "source": "user" | "ai" | "preset" | "imported", "description": "…",
     "created": ISO date, "updated": ISO date, "app_version": "…", "colors": {token: "#rrggbb", …}}
"""
import datetime
import json
import os
import re
import uuid

from PyQt6.QtCore import QObject, pyqtSignal, QSettings
from PyQt6.QtGui import QColor, QPalette, QFont, QPixmapCache
from PyQt6.QtWidgets import QApplication

FILE_EXT = ".lumentheme"
FORMAT = "lumen-theme"
FORMAT_VERSION = 1
DEFAULT_ID = "lumen-dark"

# (key, label, group, help) - the order here is the order shown in the theme editor
TOKENS = [
    ("window", "Panels & toolbars", "Surfaces", "Background of panels, the toolbox and the options bar"),
    ("header", "Menu bar, tabs & status bar", "Surfaces", "Menu bar, tab rows, panel headers and the status bar"),
    ("pasteboard", "Canvas background", "Surfaces", "The area around your image"),
    ("border", "Borders", "Surfaces", "Lines between panels and around the window parts"),
    ("separator", "Separators & outlines", "Surfaces", "Menu separators and outlines of boxes"),
    ("input", "Input fields", "Controls", "Text boxes, number fields and drop-downs"),
    ("input_border", "Input field borders", "Controls", "Outline of text boxes and drop-downs"),
    ("button", "Buttons", "Controls", "Push buttons"),
    ("button_hover", "Buttons (hover)", "Controls", "Push buttons under the mouse"),
    ("hover", "Hover highlight", "Controls", "Tool buttons and menu-bar items under the mouse"),
    ("pressed", "Pressed / selected tool", "Controls", "The selected tool and pressed buttons"),
    ("scrollbar", "Scroll bars", "Controls", "Scroll bar handles"),
    ("slider", "Slider handles", "Controls", "The round knob on sliders"),
    ("selection", "Selected rows & layers", "Lists", "The selected layer and selected list items"),
    ("alt_row", "Alternate rows", "Lists", "Every other row in lists"),
    ("tooltip", "Tooltips", "Lists", "Tooltip background"),
    ("text", "Text", "Text & icons", "Normal text"),
    ("text_dim", "Secondary text", "Text & icons", "Hints, inactive tabs and the status bar"),
    ("text_strong", "Headings & selected text", "Text & icons", "Headings, the active tab and selected rows"),
    ("text_disabled", "Disabled text", "Text & icons", "Greyed-out menu items and controls"),
    ("icon", "Icons", "Text & icons", "Tool and button icons"),
    ("accent", "Accent", "Accent", "Highlights, default buttons, the selected menu item, checkboxes"),
    ("accent_hover", "Accent (hover)", "Accent", "Accent-coloured buttons under the mouse"),
    ("accent_text", "Text on accent", "Accent", "Text drawn on top of the accent colour"),
]
KEYS = [t[0] for t in TOKENS]
GROUPS = list(dict.fromkeys(t[2] for t in TOKENS))
LABELS = {t[0]: t[1] for t in TOKENS}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


# ============================================================== colour maths
def _c(v):
    return v if isinstance(v, QColor) else QColor(v)


def mix(a, b, t):
    """Blend colour a toward b by t (0 = a, 1 = b). Returns '#rrggbb'."""
    a, b = _c(a), _c(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def luminance(c):
    """Relative luminance 0..1 (WCAG)."""
    c = _c(c)

    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def is_dark_color(c):
    return luminance(c) < 0.2


def normalize_hex(value):
    """'#AbC123' / 'abc123' → '#abc123'; anything else → None."""
    if isinstance(value, QColor):
        return value.name() if value.isValid() else None
    m = _HEX.match(str(value).strip())
    return "#" + m.group(1).lower() if m else None


def generate(base, text, accent):
    """A complete, balanced set of colours from just a background, a text and an accent colour."""
    base, text, accent = normalize_hex(base) or "#323232", normalize_hex(text) or "#d4d4d4", \
        normalize_hex(accent) or "#2680eb"
    acc_text = "#ffffff" if contrast(accent, "#ffffff") >= contrast(accent, "#111111") else "#111111"
    c = {"accent": accent, "accent_hover": mix(accent, "#ffffff", 0.1), "accent_text": acc_text, "text": text}
    if is_dark_color(base):
        very_dark = QColor(base).lightness() < 22
        c.update(
            window=base,
            header=mix(base, "#000000", 0.2),
            pasteboard=mix(base, "#000000", 0.38),
            border=mix(base, text, 0.1) if very_dark else mix(base, "#000000", 0.48),
            separator=mix(base, text, 0.16 if very_dark else 0.11),
            input=mix(base, text, 0.04) if very_dark else mix(base, "#000000", 0.3),
            input_border=mix(base, text, 0.16 if very_dark else 0.06),
            button=mix(base, text, 0.15),
            button_hover=mix(base, text, 0.24),
            hover=mix(base, text, 0.08),
            pressed=mix(base, text, 0.05) if very_dark else mix(base, "#000000", 0.44),
            scrollbar=mix(base, text, 0.16),
            slider=mix(text, "#ffffff", 0.4),
            selection=mix(mix(base, text, 0.15), accent, 0.12),
            alt_row=mix(base, text, 0.02),
            tooltip=mix(base, text, 0.13),
            text_dim=mix(text, base, 0.42),
            text_strong=mix(text, "#ffffff", 0.8),
            text_disabled=mix(text, base, 0.64),
            icon=mix(text, base, 0.07),
        )
    else:
        c.update(
            window=base,
            header=mix(base, "#000000", 0.07),
            pasteboard=mix(base, "#000000", 0.2),
            border=mix(base, "#000000", 0.3),
            separator=mix(base, "#000000", 0.18),
            input=mix(base, "#ffffff", 0.6),
            input_border=mix(base, "#000000", 0.22),
            button=mix(base, "#ffffff", 0.4),
            button_hover=mix(base, "#ffffff", 0.7),
            hover=mix(base, "#000000", 0.08),
            pressed=mix(base, "#000000", 0.17),
            scrollbar=mix(base, "#000000", 0.26),
            slider=mix(text, base, 0.25),
            selection=mix(accent, base, 0.72),
            alt_row=mix(base, "#000000", 0.03),
            tooltip=mix(base, "#ffffff", 0.75),
            text_dim=mix(text, base, 0.45),
            text_strong=mix(text, "#000000", 0.6),
            text_disabled=mix(text, base, 0.6),
            icon=mix(text, base, 0.12),
        )
    return c


# ============================================================== theme object
class Theme:
    def __init__(self, name, colors, id=None, author="", source="user", description="", created="", updated="",
                 app_version=""):
        self.name = (name or "Untitled Theme").strip()[:60] or "Untitled Theme"
        self.id = id or new_id(self.name)
        self.author = author or ""
        self.source = source or "user"
        self.description = description or ""
        self.created = created or _now()
        self.updated = updated or self.created
        self.app_version = app_version
        self.colors = complete(colors)

    # ---- helpers
    def __getitem__(self, key):
        return self.colors[key]

    def qcolor(self, key):
        return QColor(self.colors[key])

    @property
    def dark(self):
        return is_dark_color(self.colors["window"])

    @property
    def builtin(self):
        return self.source == "preset"

    def kind(self):
        return "Dark" if self.dark else "Light"

    def copy(self, **changes):
        d = self.to_dict()
        d.update(changes)
        return Theme.from_dict(d)

    def to_dict(self):
        from . import __version__
        return {"format": FORMAT, "format_version": FORMAT_VERSION, "id": self.id, "name": self.name,
                "author": self.author, "source": self.source, "description": self.description,
                "created": self.created, "updated": self.updated, "app_version": self.app_version or __version__,
                "colors": dict(self.colors)}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or not isinstance(d.get("colors"), dict):
            raise ValueError("This isn't a Lumen theme (no colours found).")
        if d.get("format", FORMAT) != FORMAT:
            raise ValueError("This isn't a Lumen theme file.")
        return cls(d.get("name"), d["colors"], id=_clean_id(d.get("id")), author=d.get("author", ""),
                   source=d.get("source", "user"), description=d.get("description", ""),
                   created=d.get("created", ""), updated=d.get("updated", ""), app_version=d.get("app_version", ""))

    def same_colors(self, other):
        return other is not None and self.colors == other.colors


def complete(colors):
    """Validate a colour dict and fill anything missing (e.g. a theme made by an older/newer Lumen)."""
    colors = dict(colors or {})
    clean = {k: normalize_hex(v) for k, v in colors.items() if k in KEYS and normalize_hex(v)}
    base = generate(clean.get("window", "#323232"), clean.get("text", "#d4d4d4"), clean.get("accent", "#2680eb"))
    base.update(clean)
    return {k: base[k] for k in KEYS}


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _clean_id(value):
    s = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").lower()).strip("-")
    return s[:64] or None


def new_id(name):
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "theme").lower()).strip("-")[:40] or "theme"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


# ============================================================== presets
DEFAULT_COLORS = {
    "window": "#323232", "header": "#282828", "pasteboard": "#1f1f1f", "border": "#1a1a1a", "separator": "#444444",
    "input": "#232323", "input_border": "#3c3c3c", "button": "#4a4a4a", "button_hover": "#585858",
    "hover": "#404040", "pressed": "#1c1c1c", "scrollbar": "#4b4b4b", "slider": "#e6e6e6",
    "selection": "#4a4a4a", "alt_row": "#353535", "tooltip": "#484848",
    "text": "#d4d4d4", "text_dim": "#8f8f8f", "text_strong": "#ffffff", "text_disabled": "#6a6a6a", "icon": "#c9c9c9",
    "accent": "#2680eb", "accent_hover": "#378ef0", "accent_text": "#ffffff",
}

# id, name, description, (background, text, accent), overrides
_PRESET_SPECS = [
    (DEFAULT_ID, "Lumen Dark", "The classic dark grey workspace.", None, DEFAULT_COLORS),
    ("graphite", "Graphite", "A softer, medium-dark grey.", ("#535353", "#e3e3e3", "#2680eb"),
     {"pasteboard": "#282828", "header": "#454545", "border": "#2b2b2b", "input": "#454545"}),
    ("silver", "Silver", "Light grey panels with dark text.", ("#b8b8b8", "#1d1d1d", "#1473e6"),
     {"pasteboard": "#8f8f8f", "input": "#d6d6d6"}),
    ("daylight", "Daylight", "Bright and airy, for well-lit rooms.", ("#f0f0f0", "#2c2c2c", "#1473e6"),
     {"pasteboard": "#d4d4d4", "input": "#ffffff"}),
    ("midnight", "Midnight", "Deep navy blues with a sky-blue accent.", ("#15233a", "#d6e2f0", "#4fb3ff"),
     {"pasteboard": "#0b1424", "accent_text": "#06121f"}),
    ("oled", "OLED Black", "True black - easy on the eyes at night.", ("#0a0a0a", "#d0d0d0", "#2680eb"),
     {"pasteboard": "#000000", "header": "#000000", "pressed": "#000000", "input": "#141414"}),
    ("frost", "Frost", "Cool arctic slate with icy blue highlights.", ("#2e3440", "#e5e9f0", "#88c0d0"),
     {"pasteboard": "#242933", "accent_text": "#1d222b"}),
    ("nightshade", "Nightshade", "Dusky purple with a lavender glow.", ("#282a36", "#f8f8f2", "#bd93f9"),
     {"pasteboard": "#1e1f29", "accent_text": "#1e1f29"}),
    ("synthwave", "Synthwave", "Neon pink on a dark violet night.", ("#1d1532", "#f2e9ff", "#ff4fd8"),
     {"pasteboard": "#120c22"}),
    ("ember", "Ember", "Warm charcoal with a glowing orange accent.", ("#2b2420", "#eadfd6", "#ff7a2f"), {}),
    ("forest", "Forest", "Deep greens with a fresh mint accent.", ("#1f2a24", "#dbe7df", "#3ecf8e"),
     {"accent_text": "#08261a"}),
    ("sakura", "Sakura", "Soft blossom pink, light and calm.", ("#f6eef1", "#3a2a31", "#d94f84"),
     {"pasteboard": "#e2d3d9", "input": "#ffffff"}),
    ("high-contrast", "High Contrast", "Maximum legibility: black, white and yellow.", ("#000000", "#ffffff", "#ffd400"),
     {"border": "#9a9a9a", "separator": "#bdbdbd", "input_border": "#d0d0d0", "text_dim": "#d6d6d6",
      "selection": "#1f4fd8", "hover": "#2b2b2b", "pressed": "#3a3a3a", "button": "#1a1a1a",
      "button_hover": "#333333", "text_disabled": "#9a9a9a", "icon": "#ffffff", "accent_text": "#000000"}),
]


def _build_presets():
    out = []
    for pid, name, desc, gen, overrides in _PRESET_SPECS:
        colors = generate(*gen) if gen else {}
        colors.update(overrides)
        out.append(Theme(name, colors, id=pid, author="Lumen", source="preset", description=desc,
                         created="2026-10-10T00:00:00"))
    return out


PRESETS = _build_presets()


def presets():
    return list(PRESETS)


def default_theme():
    return PRESETS[0]


# ============================================================== storage
def themes_dir():
    from .config import data_dir
    d = os.path.join(data_dir(), "themes")
    os.makedirs(d, exist_ok=True)
    return d


def _settings():
    override = os.environ.get("LUMEN_SETTINGS")
    return QSettings(override, QSettings.Format.IniFormat) if override else QSettings("Lumen", "Lumen")


def _path_for(theme_id):
    return os.path.join(themes_dir(), f"{theme_id}{FILE_EXT}")


def load_file(path):
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"The theme file is damaged ({e.msg}).") from None
    return Theme.from_dict(data)


def user_themes():
    out = []
    for name in sorted(os.listdir(themes_dir())):
        if not name.endswith(FILE_EXT):
            continue
        try:
            t = load_file(os.path.join(themes_dir(), name))
        except Exception:
            continue
        if t.source == "preset":            # a file can't pretend to be built in
            t.source = "user"
        t.id = name[:-len(FILE_EXT)]
        out.append(t)
    out.sort(key=lambda t: t.name.lower())
    return out


def all_themes():
    return presets() + user_themes()


def find(theme_id):
    for t in all_themes():
        if t.id == theme_id:
            return t
    return None


def _write(theme, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(theme.to_dict(), f, indent=2)
    os.replace(tmp, path)


def save_user_theme(theme):
    """Save (or overwrite) a theme in My Themes. Presets are saved as a copy. Returns the saved Theme."""
    if theme.source == "preset" or any(p.id == theme.id for p in PRESETS):
        theme = theme.copy(id=new_id(theme.name), source="user", created=_now())
    theme.updated = _now()
    _write(theme, _path_for(theme.id))
    return theme


def delete_user_theme(theme_id):
    path = _path_for(theme_id)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def unique_name(name, exclude_id=None):
    taken = {t.name.lower() for t in all_themes() if t.id != exclude_id}
    if name.lower() not in taken:
        return name
    i = 2
    while f"{name} {i}".lower() in taken:
        i += 1
    return f"{name} {i}"


def import_file(path):
    """Copy a .lumentheme file into My Themes. Returns the imported Theme."""
    t = load_file(path)
    if t.source in ("preset", "user", ""):
        t.source = "imported"
    existing = find(t.id) if t.id else None
    if existing is not None:
        if existing.same_colors(t):
            return existing
        t.id = new_id(t.name)
    t.name = unique_name(t.name)
    _write(t, _path_for(t.id))
    return t


def export_file(theme, path):
    if not path.lower().endswith((FILE_EXT, ".json")):
        path += FILE_EXT
    _write(theme, path)
    return path


# ============================================================== the active theme
class _Notifier(QObject):
    changed = pyqtSignal(object)        # Theme


notifier = _Notifier()
_current = default_theme()
C = dict(_current.colors)               # live colour table: theme.C["accent"]


def current():
    return _current


def color(key):
    return QColor(C[key])


def tone(kind):
    """Readable status colours for the current theme: 'error', 'warn', 'ok', 'info', 'muted'."""
    dark = _current.dark
    table = {"error": ("#ff8a80", "#c62828"), "warn": ("#ffcc80", "#9a5b00"), "ok": ("#8fe3a0", "#2e7d32"),
             "muted": ("#9ab8d8", "#4a6a8c")}
    if kind == "info":
        return C["accent"] if contrast(C["accent"], C["window"]) >= 3 else C["text_strong"]
    pair = table.get(kind, (C["text"], C["text"]))
    return pair[0] if dark else pair[1]


def saved_theme():
    """The theme the user picked last time (falls back to the stored copy, then the default)."""
    s = _settings()
    tid = s.value("theme/id", DEFAULT_ID)
    t = find(tid)
    if t is not None:
        return t
    raw = s.value("theme/data", "")
    if raw:
        try:
            return Theme.from_dict(json.loads(raw))
        except Exception:
            pass
    return default_theme()


def remember(theme):
    s = _settings()
    s.setValue("theme/id", theme.id)
    s.setValue("theme/data", json.dumps(theme.to_dict()))
    s.sync()


def _set_globals(theme):
    global _current, BG, BG_DARK, PASTEBOARD, BORDER, INPUT, INPUT_BORDER, HOVER, PRESSED, TEXT, TEXT_DIM, ACCENT, \
        ACCENT_HOVER
    _current = theme
    C.clear()
    C.update(theme.colors)
    # names older code and extensions use
    BG, BG_DARK, PASTEBOARD, BORDER = C["window"], C["header"], C["pasteboard"], C["border"]
    INPUT, INPUT_BORDER, HOVER, PRESSED = C["input"], C["input_border"], C["hover"], C["pressed"]
    TEXT, TEXT_DIM, ACCENT, ACCENT_HOVER = C["text"], C["text_dim"], C["accent"], C["accent_hover"]


_set_globals(_current)

FONT_STACK = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'


def build_qss(c, arrow, check):
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 12px;
    color: {c['text']};
    outline: none;
}}
QMainWindow, QDialog {{ background: {c['window']}; }}
QMainWindow::separator {{ background: {c['border']}; width: 2px; height: 2px; }}
QWidget#Pasteboard {{ background: {c['pasteboard']}; }}

/* ---------- menus ---------- */
QMenuBar {{
    background: {c['header']};
    border-bottom: 1px solid {c['border']};
    padding: 1px 4px;
}}
QMenuBar::item {{ background: transparent; padding: 4px 9px; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {c['hover']}; }}
QMenuBar::item:pressed {{ background: {c['accent']}; color: {c['accent_text']}; }}
QMenu {{
    background: {c['window']};
    border: 1px solid {c['border']};
    padding: 4px 0;
}}
QMenu::item {{ padding: 5px 34px 5px 26px; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['accent_text']}; }}
QMenu::item:disabled {{ color: {c['text_disabled']}; }}
QMenu::separator {{ height: 1px; background: {c['separator']}; margin: 4px 8px; }}
QMenu::indicator {{ width: 12px; height: 12px; left: 8px; }}
QMenu::right-arrow {{ width: 8px; height: 8px; }}
QMenu#ThemeMenu::item {{ padding: 0; }}

/* ---------- tool bars ---------- */
QToolBar {{
    background: {c['window']};
    border: none;
    spacing: 2px;
}}
QToolBar#OptionsBar {{ border-bottom: 1px solid {c['border']}; padding: 2px 6px; }}
QToolBar#ToolBox {{ border-right: 1px solid {c['border']}; padding: 6px 3px; }}
QToolBar::separator {{ background: {c['separator']}; width: 1px; height: 1px; margin: 5px 6px; }}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px;
}}
QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:pressed {{ background: {c['pressed']}; }}
QToolButton:checked {{ background: {c['pressed']}; border: 1px solid {c['border']}; }}
QToolButton#ToolButton {{ padding: 4px; }}
QToolButton#ModeButton:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QLabel#ToolBadge {{ background: {c['pressed']}; border-radius: 4px; }}

QToolBar#WorkspaceBar {{ background: {c['header']}; border-bottom: 1px solid {c['border']}; padding: 0 8px; spacing: 0; }}
QTabBar#WorkspaceTabs {{ background: transparent; }}
QTabBar#WorkspaceTabs::tab {{
    background: transparent; color: {c['text_dim']}; border: none; border-bottom: 2px solid transparent;
    padding: 7px 18px 6px 14px; margin-right: 2px; min-width: 0px; font-weight: 600;
}}
QTabBar#WorkspaceTabs::tab:selected {{ color: {c['text_strong']}; border-bottom: 2px solid {c['accent']}; background: {c['window']}; }}
QTabBar#WorkspaceTabs::tab:hover:!selected {{ color: {c['text']}; background: {mix(c['header'], c['window'], 0.5)}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QFontComboBox, QTextEdit {{
    background: {c['input']};
    border: 1px solid {c['input_border']};
    border-radius: 3px;
    padding: 3px 5px;
    selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
    min-height: 16px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {c['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {c['text_disabled']}; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 2px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox::down-arrow {{ image: url({arrow}); width: 8px; height: 8px; }}
QComboBox QAbstractItemView {{
    background: {c['window']}; border: 1px solid {c['border']};
    selection-background-color: {c['accent']}; selection-color: {c['accent_text']};
}}
QCheckBox, QRadioButton {{ spacing: 6px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c['text_disabled']}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 13px; height: 13px; background: {c['input']}; border: 1px solid {mix(c['input_border'], c['text'], 0.25)};
}}
QCheckBox::indicator {{ border-radius: 2px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']};
}}
QCheckBox::indicator:checked {{ image: url({check}); }}

QSlider::groove:horizontal {{ height: 3px; background: {c['border']}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {c['text_dim']}; border-radius: 1px; }}
QSlider::handle:horizontal {{
    background: {c['slider']}; width: 10px; height: 10px; margin: -4px 0; border-radius: 5px;
}}
QSlider::handle:horizontal:hover {{ background: {mix(c['slider'], c['text_strong'], 0.5)}; }}
QProgressBar {{ background: {c['input']}; border: 1px solid {c['input_border']}; border-radius: 3px;
    text-align: center; color: {c['text']}; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 2px; }}

QPushButton {{
    background: {c['button']};
    border: 1px solid {mix(c['button'], c['text'], 0.08)};
    border-radius: 4px;
    padding: 5px 18px;
    min-width: 60px;
}}
QPushButton:hover {{ background: {c['button_hover']}; }}
QPushButton:pressed {{ background: {c['pressed']}; }}
QPushButton:disabled {{ color: {c['text_disabled']}; }}
QPushButton:default, QPushButton#Primary {{
    background: {c['accent']}; border-color: {c['accent']}; color: {c['accent_text']}; font-weight: 600;
}}
QPushButton:default:hover, QPushButton#Primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton:default:disabled, QPushButton#Primary:disabled {{ background: {c['button']}; border-color: {c['button']};
    color: {c['text_disabled']}; }}
QToolButton#Primary {{ background: {c['accent']}; border: 1px solid {c['accent']}; color: {c['accent_text']};
    font-weight: 600; padding: 5px 16px; border-radius: 4px; }}
QToolButton#Primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#Flat {{
    background: transparent; border: 1px solid {c['separator']};
}}
QPushButton#Flat:hover {{ background: {c['hover']}; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: none; background: {c['pasteboard']}; }}
QTabBar {{ background: {c['header']}; }}
QTabBar::tab {{
    background: {c['header']};
    color: {c['text_dim']};
    padding: 6px 10px 6px 12px;
    border-right: 1px solid {c['border']};
    min-width: 60px;
}}
QTabBar::tab:selected {{ background: {c['window']}; color: {c['text']}; }}
QTabBar::tab:hover:!selected {{ background: {mix(c['header'], c['window'], 0.5)}; color: {c['text']}; }}
QTabBar#DocTabs::tab {{ padding: 7px 10px 7px 14px; }}
QTabBar#DocTabs::tab:selected {{ border-top: 2px solid {c['accent']}; padding-top: 5px; }}
QTabBar::close-button {{ subcontrol-position: right; margin-left: 4px; }}

QTabWidget#PanelGroup::pane {{ background: {c['window']}; border: none; border-top: 1px solid {c['border']}; }}
QTabWidget#PanelGroup > QTabBar::tab {{
    padding: 5px 12px; min-width: 0px; font-size: 11px; border-right: 1px solid {c['border']};
}}
QTabWidget#PanelGroup > QTabBar::tab:selected {{ color: {c['text_strong']}; font-weight: 600; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: {c['pasteboard']}; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: {c['pasteboard']}; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: {c['scrollbar']}; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {mix(c['scrollbar'], c['text'], 0.2)}; }}
QScrollBar::handle:vertical {{ min-height: 30px; }}
QScrollBar::handle:horizontal {{ min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QAbstractScrollArea {{ background: {c['window']}; border: none; }}

/* ---------- misc ---------- */
QStatusBar {{
    background: {c['header']};
    border-top: 1px solid {c['border']};
    color: {c['text_dim']};
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {c['text_dim']}; font-size: 11px; padding: 0 6px; }}
QListView, QListWidget, QTreeView {{
    background: {c['window']};
    border: none;
    alternate-background-color: {c['alt_row']};
}}
QListView::item, QListWidget::item {{ padding: 4px 6px; }}
QListView::item:selected, QListWidget::item:selected {{ background: {c['selection']}; color: {c['text_strong']}; }}
QListView::item:hover:!selected, QListWidget::item:hover:!selected {{ background: {c['hover']}; }}
QListWidget#RecentList {{ background: {c['pasteboard']}; }}
QToolTip {{
    background: {c['tooltip']}; color: {c['text_strong']}; border: 1px solid {c['border']}; padding: 4px 6px;
}}
QGroupBox {{
    border: 1px solid {c['separator']}; border-radius: 4px; margin-top: 14px; padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {c['text_dim']}; }}
QLabel {{ background: transparent; }}
QLabel#Dim {{ color: {c['text_dim']}; }}
QLabel#Heading {{ font-size: 15px; font-weight: 600; color: {c['text_strong']}; }}
QLabel#Section {{ font-size: 11px; font-weight: 600; color: {c['text_dim']}; padding-top: 6px; }}
QTextBrowser#Plain {{ background: {c['window']}; border: none; }}
QSplitter::handle {{ background: {c['border']}; }}
QSplitter::handle:vertical {{ height: 2px; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QFrame#OptSep {{ background: {c['separator']}; max-width: 1px; min-width: 1px; margin: 4px 6px; }}
QFrame#PanelFooter {{ background: {c['window']}; border-top: 1px solid {c['border']}; }}
QWidget#SidePane {{ background: {c['header']}; }}
QFrame#ToolHeader {{ background: {c['header']}; border-bottom: 1px solid {c['border']}; }}
QWidget#ToolBody {{ background: {c['window']}; }}
QGroupBox::title {{ font-weight: 600; }}
QListWidget#SidePane {{ background: {c['header']}; }}
"""


def build_palette(c):
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: c["window"],
        QPalette.ColorRole.WindowText: c["text"],
        QPalette.ColorRole.Base: c["input"],
        QPalette.ColorRole.AlternateBase: c["alt_row"],
        QPalette.ColorRole.Text: c["text"],
        QPalette.ColorRole.Button: c["button"],
        QPalette.ColorRole.ButtonText: c["text"],
        QPalette.ColorRole.BrightText: c["text_strong"],
        QPalette.ColorRole.Highlight: c["accent"],
        QPalette.ColorRole.HighlightedText: c["accent_text"],
        QPalette.ColorRole.ToolTipBase: c["tooltip"],
        QPalette.ColorRole.ToolTipText: c["text_strong"],
        QPalette.ColorRole.PlaceholderText: c["text_dim"],
        QPalette.ColorRole.Light: c["button_hover"],
        QPalette.ColorRole.Midlight: c["button"],
        QPalette.ColorRole.Mid: c["separator"],
        QPalette.ColorRole.Dark: c["border"],
        QPalette.ColorRole.Shadow: "#000000",
        QPalette.ColorRole.Link: c["accent"],
    }
    for role, col in roles.items():
        pal.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["text_disabled"]))
    return pal


def apply(app: QApplication = None, theme=None, remember_choice=False):
    """Style the whole app with `theme` (default: the one the user picked last time)."""
    app = app or QApplication.instance()
    theme = theme or saved_theme()
    _set_globals(theme)
    app.setStyle("Fusion")
    app.setPalette(build_palette(C))
    f = QFont("Segoe UI")
    f.setPointSizeF(9)
    app.setFont(f)
    arrow, check = _write_assets(C)
    app.setStyleSheet(build_qss(C, arrow, check))
    QPixmapCache.clear()
    try:
        from . import icons
        icons.theme_changed()
    except Exception:
        pass
    if remember_choice:
        remember(theme)
    notifier.changed.emit(theme)
    for w in app.topLevelWidgets():
        w.update()
    return theme


def _write_assets(c):
    """Render the few stylesheet glyphs (QSS needs files). Names include the colour so Qt never reuses a stale one."""
    import tempfile
    from PyQt6.QtCore import Qt, QPointF
    from PyQt6.QtGui import QPixmap, QPainter, QPen, QPolygonF
    folder = os.path.join(tempfile.gettempdir(), "lumen_ui")
    os.makedirs(folder, exist_ok=True)
    arrow = os.path.join(folder, f"arrow_{c['text_dim'][1:]}.png")
    check = os.path.join(folder, f"check_{c['accent_text'][1:]}.png")
    if not os.path.exists(arrow):
        pm = QPixmap(16, 16)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["text_dim"]))
        p.drawPolygon(QPolygonF([QPointF(2, 5), QPointF(14, 5), QPointF(8, 12)]))
        p.end()
        pm.save(arrow)
    if not os.path.exists(check):
        pm = QPixmap(26, 26)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(c["accent_text"]), 3.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(6, 13.5), QPointF(11, 18.5), QPointF(20, 7.5)]))
        p.end()
        pm.save(check)
    return arrow.replace("\\", "/"), check.replace("\\", "/")
