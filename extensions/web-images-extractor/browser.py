"""The Web Images Extractor workspace: a tabbed Chromium browser above the image gallery."""
import json
from urllib.parse import quote_plus

from PyQt6.QtCore import Qt, QUrl, QTimer, QSize
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QToolButton, QTabBar,
                             QStackedWidget, QSplitter, QLabel, QProgressBar)
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from .fetcher import Fetcher
from .gallery import Gallery, _colors, on_theme_changed

HOME = "https://duckduckgo.com/"

COLLECT_JS = r"""
(() => {
    const out = new Set();
    const add = (u) => {
        if (!u || typeof u !== 'string') return;
        u = u.trim();
        if (!u || u.startsWith('blob:') || u.startsWith('javascript:')) return;
        if (u.startsWith('data:')) {
            if (u.startsWith('data:image/') && u.length > 400) out.add(u);   // skip tiny placeholders
            return;
        }
        try {
            const abs = new URL(u, location.href);
            if (abs.protocol === 'http:' || abs.protocol === 'https:' || abs.protocol === 'file:') out.add(abs.href);
        } catch (e) {}
    };
    const addSrcset = (ss) => { if (ss) ss.split(/,\s+/).forEach(x => add(x.trim().split(/\s+/)[0])); };
    document.querySelectorAll('img').forEach(img => {
        add(img.currentSrc); add(img.src);
        ['data-src', 'data-original', 'data-lazy-src', 'data-image', 'data-url', 'data-full']
            .forEach(a => add(img.getAttribute(a)));
        addSrcset(img.getAttribute('srcset')); addSrcset(img.getAttribute('data-srcset'));
    });
    document.querySelectorAll('picture source, source[type^="image"]').forEach(s => {
        addSrcset(s.getAttribute('srcset')); addSrcset(s.getAttribute('data-srcset'));
    });
    document.querySelectorAll('svg image').forEach(i => add(i.getAttribute('href') || i.getAttribute('xlink:href')));
    document.querySelectorAll('video[poster]').forEach(v => add(v.poster));
    const urlRe = /url\(\s*(['"]?)(.*?)\1\s*\)/g;
    const scanBg = (v) => { if (v && v !== 'none') for (const m of v.matchAll(urlRe)) add(m[2]); };
    document.querySelectorAll('*').forEach(el => {
        scanBg(getComputedStyle(el).backgroundImage);
        scanBg(getComputedStyle(el, '::before').backgroundImage);
        scanBg(getComputedStyle(el, '::after').backgroundImage);
    });
    document.querySelectorAll('meta[property="og:image"], meta[property="og:image:url"], ' +
        'meta[name="twitter:image"], meta[name="twitter:image:src"]').forEach(m => add(m.content));
    document.querySelectorAll('a[href]').forEach(a => {
        if (/\.(png|jpe?g|gif|webp|avif|bmp|svg)(\?|#|$)/i.test(a.getAttribute('href') || '')) add(a.href);
    });
    return JSON.stringify([...out]);
})()
"""

SCROLL_JS = r"""
(() => {
    window.__lumenScrollDone = false;
    const step = Math.max(300, window.innerHeight * 0.8);
    let y = 0;
    const tick = () => {
        const max = document.documentElement.scrollHeight;
        y += step; window.scrollTo(0, y);
        if (y < max && y < 60000) setTimeout(tick, 120);
        else setTimeout(() => { window.scrollTo(0, 0); window.__lumenScrollDone = true; }, 400);
    };
    tick();
    return true;
})()
"""


def to_url(text):
    t = text.strip()
    if not t:
        return QUrl(HOME)
    if " " not in t and ("." in t or t.startswith(("localhost", "file:", "http:", "https:"))):
        u = QUrl.fromUserInput(t)
        if u.isValid():
            return u
    return QUrl("https://duckduckgo.com/?q=" + quote_plus(t))


class Page(QWebEnginePage):
    def __init__(self, profile, workspace):
        super().__init__(profile, workspace)
        self.workspace = workspace

    def createWindow(self, kind):       # links that open new windows/tabs open as a new tab here
        view = self.workspace.new_tab(None)
        return view.page()


class WebImagesWorkspace(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.fetcher = Fetcher()
        self.views = []
        self._polls = 0
        self.profile = QWebEngineProfile.defaultProfile()
        self.fetcher.user_agent = self.profile.httpUserAgent()
        store = self.profile.cookieStore()
        store.cookieAdded.connect(self.fetcher.add_cookie)
        store.loadAllCookies()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        browser = QWidget()
        bl = QVBoxLayout(browser)
        bl.setContentsMargins(8, 8, 8, 0)
        bl.setSpacing(6)
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.back_btn = self._nav_button("‹", "Back (Alt+Left)", lambda: self.view() and self.view().back())
        self.fwd_btn = self._nav_button("›", "Forward (Alt+Right)", lambda: self.view() and self.view().forward())
        self.reload_btn = self._nav_button("↻", "Reload (F5)", lambda: self.view() and self.view().reload())
        for b in (self.back_btn, self.fwd_btn, self.reload_btn):
            nav.addWidget(b)
        self.url = QLineEdit()
        self.url.setPlaceholderText("Enter a web address, or type words to search…")
        self.url.setMinimumHeight(30)
        self.url.returnPressed.connect(self.go)
        nav.addWidget(self.url, 1)
        go = QPushButton("Go")
        go.setObjectName("Primary")
        go.clicked.connect(self.go)
        nav.addWidget(go)
        nav.addWidget(self._nav_button("+", "New tab (Ctrl+T)", lambda: self.new_tab(QUrl(HOME), focus=True)))
        bl.addLayout(nav)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(2)
        self.progress.setTextVisible(False)
        self._style_progress()
        on_theme_changed(self._style_progress)
        bl.addWidget(self.progress)
        self.tabs = QTabBar()
        self.tabs.setObjectName("DocTabs")
        self.tabs.setTabsClosable(False)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        bl.addWidget(self.tabs)
        self.stack = QStackedWidget()
        bl.addWidget(self.stack, 1)

        self.gallery = Gallery(api, self.fetcher)
        self.gallery.collect_btn.clicked.connect(lambda: self.collect(scroll=False))
        self.gallery.deep_btn.clicked.connect(lambda: self.collect(scroll=True))
        self.gallery.on_open_tab = lambda u: self.new_tab(QUrl(u))

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(browser)
        split.addWidget(self.gallery)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        browser.setMinimumHeight(200)
        self.gallery.setMinimumHeight(170)
        self.split = split
        self._sized = False
        root.addWidget(split, 1)

        QShortcut(QKeySequence("Ctrl+T"), self, activated=lambda: self.new_tab(QUrl(HOME), focus=True))
        QShortcut(QKeySequence("F5"), self, activated=lambda: self.view() and self.view().reload())
        self.new_tab(QUrl(api.setting("home", HOME) or HOME))

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._sized and self.split.height() > 300:
            self._sized = True
            h = self.split.height()
            self.split.setSizes([int(h * 0.56), h - int(h * 0.56)])

    def _style_progress(self, *_):
        self.progress.setStyleSheet("QProgressBar { background: transparent; border: none; }"
                                    f"QProgressBar::chunk {{ background: {_colors()['accent']}; }}")

    def shutdown(self):
        """Delete every page before Qt releases the browser profile (otherwise Qt WebEngine crashes on exit)."""
        from PyQt6 import sip
        views, self.views = list(self.views), []
        for v in views:
            if sip.isdeleted(v):
                continue
            page = v.page()
            v.stop()
            self.stack.removeWidget(v)
            sip.delete(v)
            if page is not None and not sip.isdeleted(page):
                sip.delete(page)

    def _nav_button(self, text, tip, fn):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setFixedSize(30, 30)
        f = b.font()
        f.setPointSize(f.pointSize() + 3)
        b.setFont(f)
        b.clicked.connect(fn)
        return b

    # ------------------------------------------------------------ tabs
    def view(self):
        w = self.stack.currentWidget()
        return w if isinstance(w, QWebEngineView) else None

    def new_tab(self, url, focus=False):
        v = QWebEngineView()
        page = Page(self.profile, self)
        v.setPage(page)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        self.views.append(v)
        self.stack.addWidget(v)
        i = self.tabs.addTab("New Tab")
        close = QToolButton()
        close.setText("×")
        close.setFixedSize(18, 18)
        close.setToolTip("Close tab")
        c = _colors()
        close.setStyleSheet(f"QToolButton {{ border-radius: 9px; padding: 0; color: {c['text_dim']}; }}"
                            f"QToolButton:hover {{ background: {c['hover']}; color: {c['text_strong']}; }}")
        close.clicked.connect(lambda _, v=v: v in self.views and self.close_tab(self.views.index(v)))
        self.tabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, close)
        v.titleChanged.connect(lambda t, v=v: self._set_title(v, t))
        v.urlChanged.connect(lambda u, v=v: v is self.view() and self.url.setText(u.toDisplayString()))
        v.loadProgress.connect(lambda p, v=v: v is self.view() and self.progress.setValue(p if p < 100 else 0))
        v.loadFinished.connect(lambda ok, v=v: v is self.view() and self._update_nav())
        if url is not None:
            v.load(url)
        self.tabs.setCurrentIndex(i)
        if focus:
            self.url.setFocus()
            self.url.selectAll()
        return v

    def _set_title(self, v, title):
        i = self.views.index(v) if v in self.views else -1
        if i >= 0:
            self.tabs.setTabText(i, (title or "Untitled")[:28])
            self.tabs.setTabToolTip(i, title)

    def _tab_changed(self, i):
        if 0 <= i < len(self.views):
            self.stack.setCurrentWidget(self.views[i])
            self.url.setText(self.views[i].url().toDisplayString())
            self._update_nav()

    def close_tab(self, i):
        if not (0 <= i < len(self.views)):
            return
        if len(self.views) == 1:
            self.views[0].load(QUrl(HOME))
            return
        v = self.views.pop(i)
        self.tabs.removeTab(i)
        self.stack.removeWidget(v)
        v.deleteLater()

    def _update_nav(self):
        v = self.view()
        if v is not None:
            h = v.history()
            self.back_btn.setEnabled(h.canGoBack())
            self.fwd_btn.setEnabled(h.canGoForward())

    def go(self):
        v = self.view() or self.new_tab(None)
        v.load(to_url(self.url.text()))
        v.setFocus()

    # ------------------------------------------------------------ collecting
    def collect(self, scroll=False):
        v = self.view()
        if v is None:
            return
        self.gallery.collect_btn.setEnabled(False)
        self.gallery.deep_btn.setEnabled(False)
        if scroll:
            self.gallery.set_status("Scrolling through the page so lazy-loaded images appear…")
            self._polls = 0
            v.page().runJavaScript(SCROLL_JS, lambda _: self._poll_scroll(v))
        else:
            self._run_collect(v)

    def _poll_scroll(self, v):
        self._polls += 1
        if self._polls > 300:
            return self._run_collect(v)

        def check(done):
            if done:
                QTimer.singleShot(500, lambda: self._run_collect(v))      # let late images start loading
            else:
                QTimer.singleShot(250, lambda: self._poll_scroll(v))
        v.page().runJavaScript("window.__lumenScrollDone === true", check)

    def _run_collect(self, v):
        self.gallery.set_status("Collecting images…")
        v.page().runJavaScript(COLLECT_JS, lambda result: self._receive(v, result))

    def _receive(self, v, result):
        self.gallery.collect_btn.setEnabled(True)
        self.gallery.deep_btn.setEnabled(True)
        try:
            urls = json.loads(result) if isinstance(result, str) else list(result or [])
        except ValueError:
            urls = []
        self.fetcher.clear_cache()
        self.gallery.show_urls(urls, referer=v.url().toString())
