"""Help ▸ About Lumen: version, a few words about the app, and where to find the community."""
import os
import sys

from PyQt6.QtCore import Qt, QUrl, QRectF, QSize
from PyQt6.QtGui import QDesktopServices, QMovie, QPainter, QPainterPath, QPixmap, QColor, QPen
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QFrame, QGridLayout

from . import __version__, icons, theme

GITHUB_URL = "https://github.com/TRYPWiRE"
TOPTRACKING_URL = "https://discord.gg/wSGNAa5aCk"
TKO_URL = "https://www.discord.gg/TKO1"

COMMUNITY = [
    # (logo file, name, kind, blurb, button, url)
    ("logo.png", "TopTracking.App", "Discord · Coming soon",
     "Our upcoming Call of Duty stat tracker. Join early for sneak peeks, beta access and launch news.",
     "Join the Discord", TOPTRACKING_URL),
    ("tko_logo.gif", "TKO Gaming & Services", "Discord",
     "Our gaming community and home of TKO's services. Friendly people, giveaways and support.",
     "Join the Discord", TKO_URL),
    ("pfp.gif", "TRYPWiRE on GitHub", "GitHub",
     "Lumen and our other projects. Follow along, star a repo, or report a bug.",
     "Visit GitHub", GITHUB_URL),
]

INTRO = ("Lumen is free, and always will be. If it has earned a place in your toolkit, the best way to support "
         "it is to join the community. Come and say hi in our Discord servers, share what you've made, suggest "
         "what we should build next, or follow along on GitHub. We'd love to meet you.")


def asset(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", "about", name)


class Logo(QWidget):
    """A logo (still or animated GIF) drawn with rounded corners; plays while visible."""

    def __init__(self, path, size=76):
        super().__init__()
        self.setFixedSize(size, size)
        self.movie = None
        self.pixmap = None
        if path.lower().endswith(".gif") and os.path.isfile(path):
            self.movie = QMovie(path, parent=self)
            self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
            self.movie.frameChanged.connect(lambda _: self.update())
        elif os.path.isfile(path):
            self.pixmap = QPixmap(path)

    def showEvent(self, ev):
        if self.movie is not None:
            self.movie.start()
        super().showEvent(ev)

    def hideEvent(self, ev):
        if self.movie is not None:
            self.movie.setPaused(True)
        super().hideEvent(ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            path = QPainterPath()
            path.addRoundedRect(r, 14, 14)
            p.fillPath(path, QColor("#121218"))         # the logos are designed for a dark background
            pm = self.movie.currentPixmap() if self.movie is not None else self.pixmap
            if pm is not None and not pm.isNull():
                p.setClipPath(path)
                s = min(r.width() / pm.width(), r.height() / pm.height())
                w, h = pm.width() * s, pm.height() * s
                p.drawPixmap(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h), pm, QRectF(pm.rect()))
                p.setClipping(False)
            p.setPen(QPen(QColor(theme.C["separator"]), 1))
            p.drawPath(path)
        finally:
            p.end()


class CommunityCard(QFrame):
    def __init__(self, logo, name, kind, blurb, label, url):
        super().__init__()
        self.url = url
        self.setObjectName("CommunityCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 18, 16, 16)
        lay.setSpacing(8)
        self.logo = Logo(asset(logo))
        lay.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(4)
        t = QLabel(name)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("font-size: 14px; font-weight: 700;")
        t.setObjectName("CardName")
        lay.addWidget(t)
        k = QLabel(kind)
        k.setObjectName("Dim")
        k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(k)
        b = QLabel(blurb)
        b.setWordWrap(True)
        b.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        b.setMinimumHeight(64)
        lay.addWidget(b, 1)
        self.button = QPushButton(label)
        self.button.setObjectName("Primary")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip(url)
        self.button.clicked.connect(self.open)
        lay.addWidget(self.button)
        self.setFixedWidth(232)

    def open(self):
        QDesktopServices.openUrl(QUrl(self.url))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Lumen")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(16)
        ic = QLabel()
        ic.setPixmap(icons.app_pixmap(72))
        head.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        title = QLabel(f"Lumen <span style='font-weight:400; color:{theme.C['text_dim']}'>{__version__}</span>")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        tl.addWidget(title)
        sub = QLabel("A free, Photoshop-style image editor: layers, filters, themes, and a growing set of "
                     "extensions for converting, optimising and creating.")
        sub.setObjectName("Dim")
        sub.setWordWrap(True)
        tl.addWidget(sub)
        head.addLayout(tl, 1)
        outer.addLayout(head)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.C['separator']};")
        outer.addWidget(line)

        h = QLabel("Join the community")
        h.setObjectName("Heading")
        outer.addWidget(h)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        outer.addWidget(intro)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.cards = [CommunityCard(*c) for c in COMMUNITY]
        for c in self.cards:
            cards.addWidget(c)
        outer.addLayout(cards)

        foot = QHBoxLayout()
        made = QLabel("Made with Python and Qt  ·  Thank you for using Lumen ♥")
        made.setObjectName("Dim")
        foot.addWidget(made, 1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        outer.addLayout(foot)
        self._style()
        theme.notifier.changed.connect(self._style)

    def _style(self, *_):
        c = theme.C
        card = theme.mix(c["window"], c["header"], 0.6)
        self.setStyleSheet(f"""
            QFrame#CommunityCard {{ background: {card}; border: 1px solid {c['separator']}; border-radius: 12px; }}
            QFrame#CommunityCard:hover {{ border-color: {c['accent']}; }}
            QFrame#CommunityCard QLabel {{ background: transparent; border: none; }}
            QFrame#CommunityCard QLabel#CardName {{ color: {c['text_strong']}; }}
        """)

    def done(self, r):
        try:
            theme.notifier.changed.disconnect(self._style)
        except TypeError:
            pass
        super().done(r)
