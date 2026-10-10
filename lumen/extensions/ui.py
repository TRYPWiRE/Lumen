"""Shared UI for extension filters: a parameter dialog with live on-canvas preview."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QGuiApplication, QCursor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSlider, QDoubleSpinBox,
                             QCheckBox, QPushButton)


def _render_preview(doc, fn, values):
    """Live preview on the active layer only (like Photoshop)."""
    rect = doc.selection_bounds() if doc.has_selection() else doc.rect()
    L = doc.active
    if rect.isEmpty() or L is None or L.is_text or L.pixels_locked():
        return
    doc.preview_region(rect, fn(L.region(rect), **values))


class FilterDialog(QDialog):
    def __init__(self, window, title, fn, params):
        super().__init__(window)
        self.setWindowTitle(title)
        self.doc = window.current_doc()
        self.fn = fn
        self.params = params
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
            dec = int(prm.get("decimals", 0))
            scale = 10 ** dec
            lab = QLabel(prm.get("label", prm["key"]) + ":")
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(int(prm["min"] * scale), int(prm["max"] * scale))
            sl.setMinimumWidth(220)
            sp = QDoubleSpinBox()
            sp.setDecimals(dec)
            sp.setRange(prm["min"], prm["max"])
            sp.setSingleStep(1 / scale if dec else 1)
            sp.setSuffix(prm.get("suffix", ""))
            sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            sp.setFixedWidth(80)
            sp.setValue(prm["default"])
            sl.setValue(int(round(prm["default"] * scale)))
            sl.valueChanged.connect(lambda v, s=sp, k=scale: s.setValue(v / k))
            sp.valueChanged.connect(lambda v, s=sl, k=scale: (s.blockSignals(True), s.setValue(int(round(v * k))),
                                                              s.blockSignals(False), self._schedule()))
            grid.addWidget(lab, r, 0)
            grid.addWidget(sl, r, 1)
            grid.addWidget(sp, r, 2)
            self.controls[prm["key"]] = (sp, dec)
        lay.addLayout(grid)
        row = QHBoxLayout()
        self.preview_box = QCheckBox("Preview")
        self.preview_box.setChecked(True)
        self.preview_box.toggled.connect(self._schedule)
        row.addWidget(self.preview_box)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._preview)
        self._schedule()

    def values(self):
        out = {}
        for k, (sp, dec) in self.controls.items():
            out[k] = sp.value() if dec else int(round(sp.value()))
        return out

    def _schedule(self, *_):
        self._timer.start()

    def _preview(self):
        if not self.doc:
            return
        if self.preview_box.isChecked():
            QGuiApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
            try:
                _render_preview(self.doc, self.fn, self.values())
            finally:
                QGuiApplication.restoreOverrideCursor()
        else:
            self.doc.set_preview(None)

    def done(self, r):
        self._timer.stop()
        if self.doc:
            self.doc.set_preview(None)
        super().done(r)


def run_filter(window, title, fn, params):
    doc = window.current_doc()
    if doc is None:
        return False
    doc.commit_floating()
    if doc.try_target("apply " + title) is None:      # locked / hidden / type layer the user won't rasterize
        return False
    values = {}
    if params:
        dlg = FilterDialog(window, title, fn, params)
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
