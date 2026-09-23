"""The popup card shown when the tray icon is clicked, styled after the
Windows 11 quick-settings flyouts."""
import time

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import device, text
from .icons import LOW

WIDTH = 296
RADIUS = 8
MARGIN = 12          # gap between the card and the taskbar / screen edge
STALE_S = 30

THEME = {
    "dark": {"bg": "#2c2c2c", "border": QColor(255, 255, 255, 22), "fg": "#ffffff",
             "muted": "#a8a8a8", "track": "#454545", "normal": "#e6e6e6",
             "low": "#ff453a", "charging": "#30d158", "warn": "#ffcc00"},
    "light": {"bg": "#f9f9f9", "border": QColor(0, 0, 0, 26), "fg": "#1a1a1a",
              "muted": "#5f5f5f", "track": "#dcdcdc", "normal": "#3a3a3a",
              "low": "#d70015", "charging": "#248a3d", "warn": "#9a6700"},
}


def _font(px: int, weight=QFont.Weight.Normal, display=False) -> QFont:
    f = QFont("Segoe UI Variable Display" if display else "Segoe UI Variable Text")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


class _Bar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(8)
        self.fraction, self.fill, self.track = 0.0, QColor(), QColor()

    def set(self, fraction, fill, track):
        self.fraction, self.fill, self.track = fraction, QColor(fill), QColor(track)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        p.setBrush(self.track)
        p.drawRoundedRect(r, 4, 4)
        if self.fraction > 0:
            p.setBrush(self.fill)
            p.drawRoundedRect(QRectF(0, 0, max(8.0, r.width() * self.fraction), r.height()), 4, 4)


class Card(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH)
        self.theme = "dark"
        self.closed_at = 0.0

        self.title = QLabel("Arctis 7")
        self.title.setFont(_font(14, QFont.Weight.DemiBold, display=True))
        self.percent = QLabel()
        self.percent.setFont(_font(28, QFont.Weight.DemiBold, display=True))
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        head = QHBoxLayout()
        head.addWidget(self.title, 1, Qt.AlignmentFlag.AlignBottom)
        head.addWidget(self.percent, 0, Qt.AlignmentFlag.AlignBottom)

        self.bar = _Bar()
        self.status = QLabel()
        self.status.setFont(_font(13))
        self.detail = QLabel()
        self.detail.setFont(_font(12))

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 14, 18, 16)
        box.setSpacing(0)
        box.addLayout(head)
        box.addSpacing(10)
        box.addWidget(self.bar)
        box.addSpacing(12)
        box.addWidget(self.status)
        box.addSpacing(3)
        box.addWidget(self.detail)

    def paintEvent(self, _):
        c = THEME[self.theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(c["border"], 1))
        p.setBrush(QColor(c["bg"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)

    def hideEvent(self, e):
        self.closed_at = time.monotonic()
        super().hideEvent(e)

    # -- content -------------------------------------------------------------

    def show_snapshot(self, snap, theme: str, now: float):
        self.theme = theme
        c = THEME[theme]
        for w, color in ((self.title, c["fg"]), (self.percent, c["fg"]), (self.status, c["fg"])):
            w.setStyleSheet(f"color: {color}; background: transparent;")
        self.detail.setStyleSheet(f"color: {c['muted']}; background: transparent;")

        if snap.status != device.OK:
            self.percent.setText("–")
            self.percent.setStyleSheet(f"color: {c['muted']}; background: transparent;")
            self.bar.set(0, c["track"], c["track"])
            self.status.setText(text.status_line(snap, now))
            self.detail.setText(text.unavailable_detail(snap))
            self.detail.setVisible(True)
        else:
            self.percent.setText(f"{snap.level}%")
            if snap.unstable:
                fill = c["warn"]
            elif snap.charging:
                fill = c["charging"]
            elif snap.level <= LOW:
                fill = c["low"]
            else:
                fill = c["normal"]
            self.bar.set(snap.level / 100, fill, c["track"])
            status = text.status_line(snap, now)
            if snap.unstable:
                status = f'<span style="color:{c["warn"]}">{status}</span>'
            self.status.setText(status)
            detail = text.rate_line(snap)
            if snap.last_ok and now - snap.last_ok > STALE_S:
                detail = " · ".join(filter(None, [detail, text.updated_ago(now - snap.last_ok)]))
            self.detail.setText(detail)
            self.detail.setVisible(bool(detail))
        self.adjustSize()
        self.update()

    # -- placement -----------------------------------------------------------

    def open_near(self, anchor: QRect, screen_rect: QRect):
        """Pop up above the tray icon, right-aligned to it, like the Windows
        flyouts; falls back to the bottom-right of the work area."""
        self.adjustSize()
        w, h = self.width(), self.height()
        if anchor.isValid() and not anchor.isEmpty():
            x = anchor.right() - w + anchor.width() // 2 + MARGIN
        else:
            x = screen_rect.right() - w - MARGIN
        x = max(screen_rect.left() + MARGIN, min(x, screen_rect.right() - w - MARGIN))
        y = screen_rect.bottom() - h - MARGIN
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
