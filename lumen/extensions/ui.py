"""Shared UI for extensions: a parameter dialog (sliders, checkboxes, choices, colours) with live preview."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QCursor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSlider, QDoubleSpinBox,
                             QCheckBox, QPushButton, QComboBox, QWidget)


def _render_preview(doc, fn, values):
    """Live preview on the active layer only (like Photoshop)."""
    rect = doc.selection_bounds() if doc.has_selection() else doc.rect()
    L = doc.active
    if rect.isEmpty() or L is None or L.is_text or L.pixels_locked():
        return
    doc.preview_region(rect, fn(L.region(rect), **values))


class _ColorButton(QPushButton):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(46, 22)
        self.setMinimumWidth(46)
        self.clicked.connect(self._pick)
        self._sync()
        self.on_change = None

    def _sync(self):
        self.setStyleSheet(f"QPushButton {{ background: {self.color.name()}; border: 1px solid #111; "
                           "border-radius: 3px; min-width: 40px; padding: 0; }")

    def _pick(self):
        from ..colors import pick_color
        c = pick_color(self.window(), self.color, "Color Picker")
        if c is not None:
            self.color = c
            self._sync()
            if self.on_change:
                self.on_change()


class ParamsDialog(QDialog):
    """params: list of dicts. Common keys: key, label, default. Types:
         slider (default): min, max, suffix, decimals
         check: a checkbox            choice: items=[...] (value = index)
         color: a colour button (value = QColor)"""

    def __init__(self, window, title, params, on_change=None, ok_text="OK"):
        super().__init__(window)
        self.setWindowTitle(title)
        self.params = params
        self.on_change = on_change
        self.controls = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        h = QLabel(title)
        h.setObjectName("Heading")
        lay.addWidget(h)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for r, prm in enumerate(params):
            if callable(prm.get("default")):          # e.g. lambda: current foreground colour
                prm = dict(prm, default=prm["default"]())
            kind = prm.get("type", "slider")
            label = QLabel(prm.get("label", prm["key"]) + ("" if kind == "check" else ":"))
            if kind == "slider":
                dec = int(prm.get("decimals", 0))
                scale = 10 ** dec
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(int(round(prm["min"] * scale)), int(round(prm["max"] * scale)))
                sl.setMinimumWidth(240)
                sp = QDoubleSpinBox()
                sp.setDecimals(dec)
                sp.setRange(prm["min"], prm["max"])
                sp.setSingleStep(1 / scale if dec else 1)
                sp.setSuffix(prm.get("suffix", ""))
                sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
                sp.setFixedWidth(84)
                sp.setValue(prm["default"])
                sl.setValue(int(round(prm["default"] * scale)))
                sl.valueChanged.connect(lambda v, s=sp, k=scale: s.setValue(v / k))
                sp.valueChanged.connect(lambda v, s=sl, k=scale: (s.blockSignals(True), s.setValue(int(round(v * k))),
                                                                  s.blockSignals(False), self._schedule()))
                grid.addWidget(label, r, 0)
                grid.addWidget(sl, r, 1)
                grid.addWidget(sp, r, 2)
                self.controls[prm["key"]] = ("slider", sp, dec)
            elif kind == "check":
                cb = QCheckBox(prm.get("label", prm["key"]))
                cb.setChecked(bool(prm.get("default", False)))
                cb.toggled.connect(self._schedule)
                grid.addWidget(cb, r, 1, 1, 2)
                self.controls[prm["key"]] = ("check", cb, 0)
            elif kind == "choice":
                combo = QComboBox()
                combo.addItems(prm["items"])
                combo.setCurrentIndex(int(prm.get("default", 0)))
                combo.currentIndexChanged.connect(self._schedule)
                grid.addWidget(label, r, 0)
                grid.addWidget(combo, r, 1, 1, 2)
                self.controls[prm["key"]] = ("choice", combo, 0)
            elif kind == "color":
                btn = _ColorButton(prm.get("default", QColor("black")))
                btn.on_change = self._schedule
                holder = QWidget()
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.addWidget(btn)
                hl.addStretch(1)
                grid.addWidget(label, r, 0)
                grid.addWidget(holder, r, 1, 1, 2)
                self.controls[prm["key"]] = ("color", btn, 0)
        lay.addLayout(grid)
        self.extra = QVBoxLayout()          # for custom widgets (e.g. a curves editor)
        lay.addLayout(self.extra)
        row = QHBoxLayout()
        self.preview_box = QCheckBox("Preview")
        self.preview_box.setChecked(True)
        self.preview_box.toggled.connect(self._schedule)
        self.preview_box.setVisible(on_change is not None)
        row.addWidget(self.preview_box)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton(ok_text)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._preview)
        self.extra_values = lambda: {}
        self._schedule()

    def values(self):
        out = {}
        for k, (kind, w, dec) in self.controls.items():
            if kind == "slider":
                out[k] = w.value() if dec else int(round(w.value()))
            elif kind == "check":
                out[k] = w.isChecked()
            elif kind == "choice":
                out[k] = w.currentIndex()
            elif kind == "color":
                out[k] = QColor(w.color)
        out.update(self.extra_values())
        return out

    def _schedule(self, *_):
        self._timer.start()

    def _preview(self):
        if self.on_change is None:
            return
        QGuiApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            self.on_change(self.values() if self.preview_box.isChecked() else None)
        finally:
            QGuiApplication.restoreOverrideCursor()

    def done(self, r):
        self._timer.stop()
        if self.on_change is not None:
            self.on_change(None)
        super().done(r)


class FilterDialog(ParamsDialog):
    def __init__(self, window, title, fn, params):
        self.doc = window.current_doc()
        self.fn = fn
        super().__init__(window, title, params, on_change=self._show)

    def _show(self, values):
        if not self.doc:
            return
        if values is None:
            self.doc.set_preview(None)
        else:
            _render_preview(self.doc, self.fn, values)


def run_filter(window, title, fn, params, dialog_hook=None):
    doc = window.current_doc()
    if doc is None:
        return False
    doc.commit_floating()
    if doc.try_target("apply " + title) is None:      # locked / hidden / type layer the user won't rasterize
        return False
    values = {}
    if params or dialog_hook:
        dlg = FilterDialog(window, title, fn, params)
        if dialog_hook:
            dialog_hook(dlg)
        accepted = dlg.exec()
        doc.set_preview(None)
        if not accepted:
            return False
        values = dlg.values()
    QGuiApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    try:
        doc.filter_region(title, lambda img: fn(img, **values))
    finally:
        QGuiApplication.restoreOverrideCursor()
    window.last_filter = (title, fn, values)
    if hasattr(window, "A"):
        window.A["last_filter"].setText(title)   # like Photoshop: the menu names the last filter
    return True
