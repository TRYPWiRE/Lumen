"""Start-up splash screen: shows for about a second, then cross-fades into the main window."""
import time

from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QRadialGradient, QFont, QPen, QPainterPath, QGuiApplication
from PyQt6.QtWidgets import QWidget

from . import icons, __version__

MIN_SHOW = 1.0      # seconds the splash stays up, even if loading is quicker
FADE_MS = 450


class Splash(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedSize(560, 340)
        self.message = "Starting…"
        self._phase = 0.0
        self._shown_at = None
        self._logo = icons.app_pixmap(112)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._anim = None
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)

    # ------------------------------------------------------------------ showing
    def start(self):
        self._shown_at = time.monotonic()
        self.show()
        self.raise_()
        self._timer.start()
        self.repaint()
        QGuiApplication.processEvents()

    def set_message(self, text):
        self.message = text
        self.repaint()
        QGuiApplication.processEvents()

    def _tick(self):
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def finish(self, window, show_window=None, done=None):
        """Wait until the splash has been up for MIN_SHOW, then fade it out while the window fades in."""
        elapsed = time.monotonic() - (self._shown_at or time.monotonic())
        QTimer.singleShot(max(0, int((MIN_SHOW - elapsed) * 1000)), lambda: self._fade(window, show_window, done))

    def _fade(self, window, show_window, done):
        self.message = "Ready"
        window.setWindowOpacity(0.0)
        (show_window or window.show)()
        self.raise_()
        group = QParallelAnimationGroup(self)
        out = QPropertyAnimation(self, b"windowOpacity", group)
        out.setDuration(FADE_MS)
        out.setStartValue(1.0)
        out.setEndValue(0.0)
        out.setEasingCurve(QEasingCurve.Type.InOutQuad)
        win = QPropertyAnimation(window, b"windowOpacity", group)
        win.setDuration(FADE_MS)
        win.setStartValue(0.0)
        win.setEndValue(1.0)
        win.setEasingCurve(QEasingCurve.Type.InOutQuad)
        group.addAnimation(out)
        group.addAnimation(win)

        def finished():
            window.setWindowOpacity(1.0)
            self._timer.stop()
            self.close()
            if done:
                done()
        group.finished.connect(finished)
        self._anim = group
        group.start()

    # ------------------------------------------------------------------ drawing
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        # soft shadow
        for i, a in ((10, 14), (7, 22), (4, 34), (2, 50)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 18 + i, 18 + i)
        card = QPainterPath()
        card.addRoundedRect(r, 18, 18)
        bg = QLinearGradient(r.topLeft(), r.bottomRight())
        bg.setColorAt(0, QColor("#0b1a2e"))
        bg.setColorAt(1, QColor("#1b1b1f"))
        p.fillPath(card, bg)
        p.save()
        p.setClipPath(card)
        glow = QRadialGradient(QPointF(r.left() + 120, r.top() + 90), 260)
        glow.setColorAt(0, QColor(79, 179, 255, 70))
        glow.setColorAt(1, QColor(79, 179, 255, 0))
        p.fillRect(r, glow)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(card)

        p.drawPixmap(int(r.left() + 40), int(r.top() + 52), self._logo)
        f = QFont("Segoe UI")
        f.setPixelSize(54)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(r.left() + 176, r.top() + 54, 340, 70), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Lumen")
        f.setPixelSize(15)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor("#9fb3c8"))
        p.drawText(QRectF(r.left() + 180, r.top() + 122, 340, 24), Qt.AlignmentFlag.AlignLeft,
                   "Photo editing, layer by layer")
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor("#6f8399"))
        p.drawText(QRectF(r.left() + 180, r.top() + 146, 340, 20), Qt.AlignmentFlag.AlignLeft, f"Version {__version__}")

        # loading bar (indeterminate sweep) + message
        bar = QRectF(r.left() + 40, r.bottom() - 62, r.width() - 80, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(bar, 2, 2)
        w = bar.width() * 0.28
        x = bar.left() - w + (bar.width() + w) * self._phase
        seg = QRectF(max(bar.left(), x), bar.top(), min(x + w, bar.right()) - max(bar.left(), x), bar.height())
        if seg.width() > 0:
            g = QLinearGradient(seg.topLeft(), seg.topRight())
            g.setColorAt(0, QColor(79, 179, 255, 0))
            g.setColorAt(0.5, QColor(79, 179, 255, 255))
            g.setColorAt(1, QColor(79, 179, 255, 0))
            p.setBrush(g)
            p.drawRoundedRect(seg, 2, 2)
        p.setPen(QColor("#8fa3b8"))
        p.drawText(QRectF(bar.left(), bar.bottom() + 12, bar.width(), 20), Qt.AlignmentFlag.AlignLeft, self.message)
        p.end()
