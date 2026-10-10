"""Horizontal Type tool: click on the canvas and type, like Photoshop. Creates editable type layers."""
import time
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from PyQt6.QtGui import (QPainter, QColor, QPen, QCursor, QFont, QTransform, QGuiApplication, QPolygonF,
                         QPainterPath)
from PyQt6.QtWidgets import QComboBox, QFontComboBox, QToolButton, QButtonGroup, QLabel, QWidget, QHBoxLayout

from . import icons
from .layers import Layer, TextData
from .widgets import separator, Swatch, icon_button

LEFT = Qt.MouseButton.LeftButton
SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier
STYLES = ["Regular", "Italic", "Bold", "Bold Italic"]


def auto_name(text):
    first = text.strip().split("\n")[0].strip()
    return first[:40] if first else None


def text_layer_at(doc, pt: QPointF):
    for L in reversed(doc.layers):
        if L.visible and L.is_text:
            inv, ok = L.text.transform.inverted()
            if ok and L.text.local_bounds().adjusted(-4, -4, 4, 4).contains(inv.map(pt)):
                return L
    return None


class TextSession:
    """One editing session on a type layer (new or existing)."""

    def __init__(self, tool, doc, layer, is_new):
        self.tool, self.doc, self.layer, self.is_new = tool, doc, layer, is_new
        self.original = layer.text.copy()
        self.original_state = (layer.image.copy(), QPoint(layer.offset))
        self.original_name = layer.name
        self.caret = len(layer.text.text)
        self.anchor = self.caret
        self.blink = time.monotonic()
        doc.editing_text = self

    # ---------------------------------------------------------------- editing
    @property
    def td(self):
        return self.layer.text

    def sel_range(self):
        return (min(self.caret, self.anchor), max(self.caret, self.anchor))

    def has_sel(self):
        return self.caret != self.anchor

    def _changed(self):
        L = self.layer
        old = L.rect()
        L.rerender_text()
        if getattr(L, "auto_named", True):
            L.name = auto_name(L.text.text) or self.tool.placeholder_name
        self.blink = time.monotonic()
        self.doc.invalidate(old.united(L.rect()))
        self.doc.layersChanged.emit()

    def insert(self, s):
        a, b = self.sel_range()
        t = self.td.text
        self.td.text = t[:a] + s + t[b:]
        self.caret = self.anchor = a + len(s)
        self._changed()

    def backspace(self, word=False):
        if self.has_sel():
            return self.insert("")
        if self.caret == 0:
            return
        start = self._word_left(self.caret) if word else self.caret - 1
        t = self.td.text
        self.td.text = t[:start] + t[self.caret:]
        self.caret = self.anchor = start
        self._changed()

    def delete(self, word=False):
        if self.has_sel():
            return self.insert("")
        t = self.td.text
        if self.caret >= len(t):
            return
        end = self._word_right(self.caret) if word else self.caret + 1
        self.td.text = t[:self.caret] + t[end:]
        self._changed()

    def _word_left(self, i):
        t = self.td.text
        while i > 0 and t[i - 1].isspace():
            i -= 1
        while i > 0 and not t[i - 1].isspace():
            i -= 1
        return i

    def _word_right(self, i):
        t = self.td.text
        while i < len(t) and not t[i].isspace():
            i += 1
        while i < len(t) and t[i].isspace():
            i += 1
        return i

    def move_caret(self, idx, extend=False):
        self.caret = max(0, min(idx, len(self.td.text)))
        if not extend:
            self.anchor = self.caret
        self.blink = time.monotonic()
        self.doc.invalidate(QRect())

    def vertical(self, step, extend):
        line, col = self.td.index_to_line_col(self.caret)
        x = self.td.caret_pos(self.caret).x()
        target = line + step
        if target < 0:
            return self.move_caret(0, extend)
        if target >= len(self.td.lines()):
            return self.move_caret(len(self.td.text), extend)
        local = QPointF(x, target * self.td.leading())
        self.move_caret(self.td.hit_index(local), extend)

    def selected_text(self):
        a, b = self.sel_range()
        return self.td.text[a:b]

    def set_style(self, **kw):
        for k, v in kw.items():
            setattr(self.td, k, v)
        self._changed()

    def translate(self, dx, dy):
        old = self.layer.rect()
        self.layer.translate(dx, dy)
        self.doc.invalidate(old.united(self.layer.rect()))

    # ---------------------------------------------------------------- finishing
    def _end(self):
        if self.doc.editing_text is self:
            self.doc.editing_text = None
        if self.tool.session is self:
            self.tool.session = None
        self.tool._sync_buttons()

    def commit(self):
        """Apply the edit as one history step (empty new text is simply discarded)."""
        if self.doc.editing_text is not self:
            return
        self._end()
        doc, L = self.doc, self.layer
        from .document import StackCommand, LayerStateCommand
        empty = not self.td.text.strip()
        if self.is_new:
            idx = doc.layers.index(L)
            before = [x for x in doc.layers if x is not L]
            prev = getattr(self, "prev_active", None) or (before[idx - 1] if idx > 0 else before[0] if before else None)
            doc.layers = before
            doc._active = prev
            if empty:
                doc.invalidate(QRect())
                doc.layersChanged.emit()
                doc.activeLayerChanged.emit()
                return
            doc.undo.push(StackCommand(doc, "Type Layer", before, before[:idx] + [L] + before[idx:], prev, L))
            return
        if self.td == self.original and L.name == self.original_name:
            return
        if empty:
            # restore then delete, so undo brings the old text back
            L.text = self.original.copy()
            L.name = self.original_name
            L.rerender_text()
            doc.delete_layer(L)
            return
        after = (L.image.copy(), QPoint(L.offset), L.text.copy())
        new_name = L.name
        L.name = self.original_name
        before = (self.original_state[0], self.original_state[1], self.original.copy())
        doc.undo.beginMacro("Edit Type Layer")
        doc.undo.push(LayerStateCommand(doc, "Edit Type Layer", L, before, after))
        if new_name != self.original_name:
            doc.set_props(L, "Rename Layer", name=new_name)
        doc.undo.endMacro()

    def cancel(self):
        if self.doc.editing_text is not self:
            return
        self._end()
        doc, L = self.doc, self.layer
        if self.is_new:
            doc.layers = [x for x in doc.layers if x is not L]
            doc._active = getattr(self, "prev_active", None) or (doc.layers[-1] if doc.layers else None)
            doc.activeLayerChanged.emit()
        else:
            L.text = self.original.copy()
            L.image, L.offset = self.original_state[0].copy(), QPoint(self.original_state[1])
            L.name = self.original_name
            L.touch()
        doc.invalidate(QRect())
        doc.layersChanged.emit()

    abort = cancel


def _make_type_tool(Tool):
    class TypeTool(Tool):
        name, title, icon, key = "text", "Horizontal Type Tool", "text", "T"
        defaults = {"family": "Arial", "size": 48, "style": 0, "align": 0}
        hover_overlay = True
        placeholder_name = "Layer"

        def __init__(self, ctx):
            super().__init__(ctx)
            self.session = None
            self._drag = None
            self.color = QColor(ctx.fg)
            ctx.colorsChanged.connect(self._fg_changed)

        # ---------------------------------------------------------- options bar
        @property
        def captures_space(self):
            return self.session is not None

        def cursor(self, canvas):
            return QCursor(Qt.CursorShape.IBeamCursor)

        def build_options(self, lay):
            fc = QFontComboBox()
            fc.setCurrentFont(QFont(self.opts["family"]))
            fc.setFixedWidth(180)
            fc.setToolTip("Font family")
            fc.currentFontChanged.connect(lambda f: self._style_changed(family=f.family()))
            lay.addWidget(fc)
            st = QComboBox()
            st.addItems(STYLES)
            st.setCurrentIndex(int(self.opts["style"]))
            st.setToolTip("Font style")
            st.currentIndexChanged.connect(lambda i: self._style_changed(style=i))
            lay.addWidget(st)
            size = self.spin(lay, "size", "", 1, 1500, " px")
            size.setToolTip("Font size")
            try:
                size.valueChanged.disconnect()
            except TypeError:
                pass
            size.valueChanged.connect(lambda v: self._style_changed(size=v))
            lay.addWidget(separator())
            grp = QButtonGroup(lay.parentWidget() or None)
            for i, (ic, tip) in enumerate((("align_left", "Left align text"), ("align_center", "Center text"),
                                           ("align_right", "Right align text"))):
                b = icon_button(icons.icon(ic), tip, True, 26)
                b.setObjectName("ModeButton")
                b.setChecked(i == int(self.opts["align"]))
                grp.addButton(b, i)
                lay.addWidget(b)
            grp.idClicked.connect(lambda i: self._style_changed(align=i))
            lay.addWidget(separator())
            self.swatch = Swatch(self.color, 20)
            self.swatch.setToolTip("Set the text color")
            self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            self.swatch.clicked.connect(self._pick_color)
            lay.addWidget(self.swatch)
            lay.addWidget(separator())
            self.cancel_btn = icon_button(icons.icon("cancel"), "Cancel all current edits (Esc)")
            self.commit_btn = icon_button(icons.icon("check"), "Commit any current edits (Ctrl+Enter)")
            self.cancel_btn.clicked.connect(lambda: self.session and self.session.cancel())
            self.commit_btn.clicked.connect(lambda: self.session and self.session.commit())
            lay.addWidget(self.cancel_btn)
            lay.addWidget(self.commit_btn)
            self._widgets = {"family": fc, "style": st, "size": size, "align": grp}
            self._sync_buttons()

        def _sync_buttons(self):
            if hasattr(self, "commit_btn"):
                on = self.session is not None
                self.commit_btn.setVisible(on)
                self.cancel_btn.setVisible(on)

        def _fg_changed(self):
            if self.session is None:
                self.color = QColor(self.ctx.fg)
                if hasattr(self, "swatch"):
                    self.swatch.set_color(self.color)

        def _pick_color(self):
            from .colors import pick_color
            cur = self.session.td.color if self.session else self.color
            c = pick_color(self.swatch.window(), cur, "Color Picker (Text Color)")
            if c is not None:
                self._style_changed(color=c)

        def _show_layer_settings(self, td):
            """Reflect a type layer's settings in the options bar (without applying anything)."""
            if not hasattr(self, "_widgets"):
                return
            w = self._widgets
            for widget in (w["family"], w["style"], w["size"]):
                widget.blockSignals(True)
            w["family"].setCurrentFont(QFont(td.family))
            w["style"].setCurrentIndex((2 if td.bold else 0) + (1 if td.italic else 0))
            w["size"].setValue(int(round(td.size)))
            for widget in (w["family"], w["style"], w["size"]):
                widget.blockSignals(False)
            btn = w["align"].button(td.align)
            if btn:
                btn.setChecked(True)
            self.swatch.set_color(td.color)

        def _style_changed(self, **kw):
            attrs = {}
            for k, v in kw.items():
                if k == "style":
                    self.set_opt("style", v)
                    attrs["bold"], attrs["italic"] = v in (2, 3), v in (1, 3)
                elif k == "color":
                    self.color = QColor(v)
                    self.swatch.set_color(self.color)
                    attrs["color"] = QColor(v)
                else:
                    self.set_opt(k, v)
                    attrs[k] = float(v) if k == "size" else v
            if self.session is not None:
                self.session.set_style(**attrs)
                return
            doc = self.ctx.current_doc()
            L = doc.active if doc else None
            if L is not None and L.is_text:          # Photoshop: options apply to the selected type layer
                from .document import LayerStateCommand
                before = LayerStateCommand.capture(L)
                td = L.text.copy()
                for k, v in attrs.items():
                    setattr(td, k, v)
                img, off = td.render()
                doc.undo.push(LayerStateCommand(doc, "Character Settings", L, before, (img, off, td)))

        # ---------------------------------------------------------- sessions
        def new_text_data(self, pt):
            st = int(self.opts["style"])
            return TextData("", self.opts["family"], float(self.opts["size"]), st in (2, 3), st in (1, 3),
                            color=self.color, align=int(self.opts["align"]),
                            transform=QTransform.fromTranslate(round(pt.x()), round(pt.y())))

        def begin_new(self, doc, pt):
            doc.commit_floating()
            td = self.new_text_data(pt)
            L = Layer(doc.next_layer_name(), text=td)
            L.auto_named = True
            self.placeholder_name = L.name
            prev = doc.active
            idx = doc._insert_index()
            doc.layers.insert(idx, L)
            doc._active = L
            self.session = TextSession(self, doc, L, True)
            self.session.prev_active = prev
            doc.activeLayerChanged.emit()
            doc.layersChanged.emit()
            self._sync_buttons()
            return self.session

        def begin_edit(self, doc, L, pt=None, select_all=False):
            doc.commit_floating()
            if doc.active is not L:
                doc.set_active(L)
            L.auto_named = getattr(L, "auto_named", auto_name(L.text.text) == L.name)
            self.placeholder_name = L.name
            self.session = TextSession(self, doc, L, False)
            self._show_layer_settings(L.text)
            if select_all:
                self.session.anchor, self.session.caret = 0, len(L.text.text)
            elif pt is not None:
                inv, _ = L.text.transform.inverted()
                self.session.move_caret(L.text.hit_index(inv.map(pt)))
            self._sync_buttons()
            doc.invalidate(QRect())
            return self.session

        def deactivate(self, canvas):
            if self.session is not None:
                self.session.commit()

        # ---------------------------------------------------------- mouse
        def _inside(self, pt):
            s = self.session
            inv, ok = s.td.transform.inverted()
            return ok and s.td.local_bounds().adjusted(-6, -6, 6, 6).contains(inv.map(pt))

        def press(self, cv, pt, ev):
            if ev.button() != LEFT:
                return
            doc = cv.doc
            s = self.session
            if s is not None and s.doc is not doc:
                s.commit()
                s = None
            if s is not None:
                if ev.modifiers() & CTRL:              # Ctrl+drag moves the text while editing
                    self._drag = ("move", pt, QPoint(0, 0))
                    self.active = True
                    return
                if self._inside(pt):
                    inv, _ = s.td.transform.inverted()
                    s.move_caret(s.td.hit_index(inv.map(pt)), bool(ev.modifiers() & SHIFT))
                    self._drag = ("select",)
                    self.active = True
                    return
                s.commit()                              # click outside: commit (like Photoshop)
                return
            hit = text_layer_at(doc, pt)
            if hit is not None:
                self.begin_edit(doc, hit, pt)
                self._drag = ("select",)
                self.active = True
            else:
                self.begin_new(doc, pt)
            cv.setFocus()

        def move(self, cv, pt, ev):
            s = self.session
            if not self.active or s is None or self._drag is None:
                return
            if self._drag[0] == "move":
                d = pt - self._drag[1]
                target = QPoint(round(d.x()), round(d.y()))
                step = target - self._drag[2]
                if step.x() or step.y():
                    s.translate(step.x(), step.y())
                    self._drag = ("move", self._drag[1], target)
            else:
                inv, _ = s.td.transform.inverted()
                s.move_caret(s.td.hit_index(inv.map(pt)), extend=True)

        def release(self, cv, pt, ev):
            self.active = False
            self._drag = None

        def double_click(self, cv, pt, ev):
            s = self.session
            if s is None or not self._inside(pt):
                return self.press(cv, pt, ev)
            i = s.caret                                  # select the word under the caret
            s.anchor = s._word_left(i) if i > 0 and not s.td.text[i - 1].isspace() else i
            j = i
            t = s.td.text
            while j < len(t) and not t[j].isspace():
                j += 1
            s.move_caret(j, extend=True)

        # ---------------------------------------------------------- keyboard
        def wants_key(self, cv, ev):
            if self.session is None:
                return False
            mods = ev.modifiers() & ~(SHIFT | Qt.KeyboardModifier.KeypadModifier)
            if not mods:
                return True
            return mods == CTRL and ev.key() in (Qt.Key.Key_A, Qt.Key.Key_C, Qt.Key.Key_X, Qt.Key.Key_V,
                                                 Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Left,
                                                 Qt.Key.Key_Right, Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
                                                 Qt.Key.Key_Home, Qt.Key.Key_End)

        def key_press(self, cv, ev):
            s = self.session
            if s is None:
                return False
            k, mods = ev.key(), ev.modifiers()
            ctrl, shift = bool(mods & CTRL), bool(mods & SHIFT)
            K = Qt.Key
            if k == K.Key_Escape:
                s.cancel()
            elif k == K.Key_Enter or (k == K.Key_Return and ctrl):
                s.commit()
            elif k == K.Key_Return:
                s.insert("\n")
            elif k == K.Key_Backspace:
                s.backspace(word=ctrl)
            elif k == K.Key_Delete:
                s.delete(word=ctrl)
            elif k == K.Key_Left:
                s.move_caret(s._word_left(s.caret) if ctrl else (min(s.sel_range()) if s.has_sel() and not shift
                                                                  else s.caret - 1), shift)
            elif k == K.Key_Right:
                s.move_caret(s._word_right(s.caret) if ctrl else (max(s.sel_range()) if s.has_sel() and not shift
                                                                   else s.caret + 1), shift)
            elif k == K.Key_Up:
                s.vertical(-1, shift)
            elif k == K.Key_Down:
                s.vertical(1, shift)
            elif k == K.Key_Home:
                if ctrl:
                    s.move_caret(0, shift)
                else:
                    line, _ = s.td.index_to_line_col(s.caret)
                    s.move_caret(s.td.line_col_to_index(line, 0), shift)
            elif k == K.Key_End:
                if ctrl:
                    s.move_caret(len(s.td.text), shift)
                else:
                    line, _ = s.td.index_to_line_col(s.caret)
                    s.move_caret(s.td.line_col_to_index(line, 10 ** 6), shift)
            elif ctrl and k == K.Key_A:
                s.anchor = 0
                s.move_caret(len(s.td.text), True)
            elif ctrl and k in (K.Key_C, K.Key_X):
                if s.has_sel():
                    QGuiApplication.clipboard().setText(s.selected_text())
                    if k == K.Key_X:
                        s.insert("")
            elif ctrl and k == K.Key_V:
                txt = QGuiApplication.clipboard().text().replace("\r\n", "\n").replace("\r", "\n")
                if txt:
                    s.insert(txt)
            elif ev.text() and ev.text().isprintable():
                s.insert(ev.text())
            else:
                return True
            return True

        def input_method(self, cv, ev):
            if self.session is not None and ev.commitString():
                self.session.insert(ev.commitString())

        # ---------------------------------------------------------- drawing
        def paint_overlay(self, p, cv):
            s = self.session
            if s is None or s.doc is not cv.doc:
                return
            td = s.td
            tr = td.transform * cv.transform()
            fm = td.metrics()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            # selection highlight
            if s.has_sel():
                a, b = s.sel_range()
                la, ca = td.index_to_line_col(a)
                lb, cb = td.index_to_line_col(b)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(38, 128, 235, 110))
                for line in range(la, lb + 1):
                    txt = td.lines()[line]
                    c0 = ca if line == la else 0
                    c1 = cb if line == lb else len(txt)
                    x0 = td.line_x(line, fm) + fm.horizontalAdvance(txt[:c0])
                    x1 = td.line_x(line, fm) + fm.horizontalAdvance(txt[:c1]) + (4 if line != lb else 0)
                    y = line * td.leading()
                    poly = tr.map(QPolygonF(QRectF(QPointF(x0, y - fm.ascent()), QPointF(x1, y + fm.descent()))))
                    p.drawPolygon(poly)
            # bounding box + baselines (Photoshop shows a thin box while editing)
            box = td.local_bounds()
            pen = QPen(QColor(255, 255, 255, 170), 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(tr.map(QPolygonF(box)))
            pen = QPen(QColor(38, 128, 235), 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            for i, ln in enumerate(td.lines()):
                x0 = td.line_x(i, fm)
                y = i * td.leading()
                p.drawLine(tr.map(QPointF(x0, y + 1)), tr.map(QPointF(x0 + max(fm.horizontalAdvance(ln), 4), y + 1)))
            # blinking caret
            if (time.monotonic() - s.blink) % 1.0 < 0.55:
                c = td.caret_pos(s.caret)
                pen = QPen(QColor(0, 0, 0), 2.2)
                pen.setCosmetic(True)
                p.setPen(pen)
                top, bot = tr.map(QPointF(c.x(), c.y() - fm.ascent())), tr.map(QPointF(c.x(), c.y() + fm.descent()))
                p.drawLine(top, bot)
                pen = QPen(QColor(255, 255, 255), 1)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawLine(top, bot)

    return TypeTool
