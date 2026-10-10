"""Extensions manager dialog and the update banner shown under the options bar."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QWidget,
                             QScrollArea, QFrame, QFileDialog, QSizePolicy, QToolButton)

from .. import __version__, theme, versioning, icons


class UpdateBanner(QFrame):
    """Slim notification strip: message + action buttons + close."""

    def __init__(self, parent=None, tint=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.tint = tint            # None = the theme's accent colour
        self._restyle()
        theme.notifier.changed.connect(self._restyle)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 5, 6, 5)
        lay.setSpacing(8)
        self.label = QLabel()
        lay.addWidget(self.label, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(self.buttons)
        close = QToolButton()
        close.setIcon(icons.icon("cancel", 12))
        close.setToolTip("Dismiss")
        close.clicked.connect(self.hide)
        lay.addWidget(close)
        self.hide()

    def show_message(self, text, actions=()):
        """actions: list of (label, callback, primary)"""
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.label.setText(text)
        for label, cb, primary in actions:
            b = QPushButton(label)
            b.setObjectName("Primary" if primary else "Flat")
            b.setMinimumWidth(0)
            b.setStyleSheet("padding: 3px 12px;")
            b.clicked.connect(cb)
            self.buttons.addWidget(b)
        self.show()

    def _restyle(self, *_):
        c = theme.C
        bg = theme.mix(self.tint or c["accent"], c["window"], 0.68)
        self.setStyleSheet(f"""
            QFrame#Banner {{ background: {bg}; border-bottom: 1px solid {c['border']}; }}
            QFrame#Banner QLabel {{ color: {c['text_strong']}; }}
        """)


class _Row(QFrame):
    def __init__(self, title, version, author, desc, status="", status_color=None):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background: {theme.C['window']}; border-bottom: 1px solid {theme.C['border']}; }}"
                           "QLabel { border: none; background: transparent; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        text = QVBoxLayout()
        text.setSpacing(2)
        top = QLabel(f"<b style='color:{theme.C["text_strong"]};font-size:13px'>{title}</b>"
                     f"&nbsp;&nbsp;<span style='color:{theme.TEXT_DIM}'>v{version}"
                     f"{' · ' + author if author else ''}</span>")
        text.addWidget(top)
        if desc:
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setObjectName("Dim")
            text.addWidget(d)
        if status:
            s = QLabel(status)
            s.setWordWrap(True)
            s.setStyleSheet(f"color: {status_color or theme.tone('info')};")
            text.addWidget(s)
        lay.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        lay.addLayout(self.actions)

    def add_button(self, label, cb, primary=False, enabled=True):
        b = QPushButton(label)
        b.setObjectName("Primary" if primary else "Flat")
        b.setEnabled(enabled)
        b.clicked.connect(cb)
        self.actions.addWidget(b)
        return b


class ExtensionsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.mgr = window.extensions
        self.setWindowTitle("Extensions")
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget()
        head.setObjectName("SidePane")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 14, 14, 14)
        t = QVBoxLayout()
        title = QLabel("Extensions")
        title.setObjectName("Heading")
        t.addWidget(title)
        self.sub = QLabel("")
        self.sub.setObjectName("Dim")
        t.addWidget(self.sub)
        hl.addLayout(t, 1)
        self.check_btn = QPushButton("Check for Updates")
        self.check_btn.setObjectName("Flat")
        self.check_btn.clicked.connect(self._check)
        hl.addWidget(self.check_btn)
        fbtn = QPushButton("Install from File…")
        fbtn.setObjectName("Flat")
        fbtn.clicked.connect(self._from_file)
        hl.addWidget(fbtn)
        lay.addWidget(head)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("PanelGroup")
        self.installed_list = self._list_area()
        self.available_list = self._list_area()
        self.tabs.addTab(self.installed_list[0], "Installed")
        self.tabs.addTab(self.available_list[0], "Browse")
        lay.addWidget(self.tabs, 1)

        self.restart = UpdateBanner(tint="#e0a030")
        lay.addWidget(self.restart)

        self.mgr.changed.connect(self.refresh)
        window.checker.checked.connect(self.refresh)
        window.checker.failed.connect(self._failed)
        self.refresh()
        if window.checker.manifest is None:
            self._check()

    def _list_area(self):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addStretch(1)
        sa.setWidget(inner)
        return sa, v

    def _clear(self, v):
        while v.count() > 1:
            w = v.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _empty(self, v, text):
        lab = QLabel(text)
        lab.setObjectName("Dim")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setMinimumHeight(120)
        lab.setWordWrap(True)
        v.insertWidget(v.count() - 1, lab)

    def refresh(self, *_):
        man = self.w.checker.manifest
        avail = man.extensions if man else {}
        n = len(self.mgr.items)
        self.sub.setText(f"{n} installed · Lumen {__version__}" + ("" if man else " · checking online…"
                                                                   if self.w.checker.busy else ""))
        # installed
        v = self.installed_list[1]
        self._clear(v)
        if not self.mgr.items:
            self._empty(v, "No extensions installed yet.\nOpen the Browse tab to add some.")
        for ext in sorted(self.mgr.items.values(), key=lambda e: e.name.lower()):
            enabled = self.mgr.is_enabled(ext.id)
            status, color = "", None
            if ext.error:
                status, color = f"⚠ {ext.error}", theme.tone("error")
            elif not enabled:
                status, color = "Disabled", theme.TEXT_DIM
            remote = avail.get(ext.id)
            update = remote and versioning.is_newer(remote.get("version"), ext.version)
            if update:
                ok = versioning.compatible(remote.get("min_app"), __version__)
                status = (f"Update available: v{remote['version']}" if ok
                          else f"v{remote['version']} available — needs Lumen {remote.get('min_app')}")
                color = None if ok else theme.tone("warn")
            author = (ext.author + " · " if ext.author else "") + ("Built-in" if ext.builtin else "")
            row = _Row(ext.name, ext.version, author.strip(" ·"), ext.description, status, color)
            if update and versioning.compatible(remote.get("min_app"), __version__):
                row.add_button("Update", lambda _, e=remote: self.w.install_extension(e), True)
            row.add_button("Disable" if enabled else "Enable",
                           lambda _, i=ext.id, en=enabled: self.mgr.set_enabled(i, not en))
            import os as _os
            if not ext.builtin or _os.path.isdir(_os.path.join(self.mgr.root, ext.id)):
                row.add_button("Revert" if ext.builtin else "Uninstall", lambda _, i=ext.id: self._uninstall(i))
            v.insertWidget(v.count() - 1, row)
        # available
        v = self.available_list[1]
        self._clear(v)
        if not man:
            self._empty(v, "Checking for extensions…" if self.w.checker.busy
                        else "Couldn't reach the extension list. Check your connection and try again.")
        elif not avail:
            self._empty(v, "No extensions published yet.")
        for e in sorted(avail.values(), key=lambda e: str(e.get("name", e["id"])).lower()):
            have = self.mgr.items.get(e["id"])
            compat = versioning.compatible(e.get("min_app"), __version__)
            status = "" if compat else f"Needs Lumen {e.get('min_app')} or newer"
            extra = []
            for rid in e.get("requires", []) or []:
                from .. import runtimes
                rt = man.runtime(rid) if man else None
                if not runtimes.installed_ok(rid) and not runtimes.importable(
                        {"qtwebengine": "PyQt6.QtWebEngineWidgets"}.get(rid, rid)):
                    extra.append(runtimes.describe(rt, rid) if rt else rid)
            if extra and compat:
                status = "Also downloads once: " + ", ".join(extra)
            row = _Row(e.get("name", e["id"]), e.get("version", "?"), e.get("author", ""), e.get("description", ""),
                       status, theme.tone("warn") if not compat else theme.tone("muted"))
            if have and not versioning.is_newer(e.get("version"), have.version):
                row.add_button("Installed", lambda: None, enabled=False)
            elif have:
                row.add_button("Update", lambda _, x=e: self.w.install_extension(x), True, compat)
            else:
                row.add_button("Install", lambda _, x=e: self.w.install_extension(x), True, compat)
            v.insertWidget(v.count() - 1, row)
        if self.mgr.restart_needed:
            self.restart.show_message("Restart Lumen to finish applying extension changes.",
                                      [("Restart Now", self.w.restart_app, True)])
        else:
            self.restart.hide()

    def _check(self):
        self.w.checker.check()
        self.refresh()

    def _failed(self, msg):
        self.refresh()
        self.sub.setText(f"Couldn't check for extensions ({msg.split(':')[0]})")

    def _uninstall(self, ext_id):
        self.mgr.uninstall(ext_id)

    def _from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Install Extension", "", "Lumen extension (*.zip)")
        if path:
            self.w.install_extension_file(path)
