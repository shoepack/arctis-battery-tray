"""Draw the tray icon. Two styles:

- "battery": an Apple-style battery with the percent inside, filling the
  whole icon so the digits get as much height as a battery shape allows.
- "number": the percent as large as the icon allows, colored by state, with
  a thin level bar underneath. Most legible at 16 px.

Geometry is laid out on a 32-unit grid with outlines on odd coordinates, so
at 16 px (scale 0.5) a 1 px stroke lands exactly on pixel centers and stays
crisp instead of smearing across two pixels.
"""
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

SIZES = (16, 20, 24, 32, 48)
LOW = 20
STYLES = ("battery", "number")
DEFAULT_STYLE = "battery"

PALETTE = {
    "dark": {
        "fg": QColor("#ffffff"), "dim": QColor("#8a8a8a"),
        # Battery fills sit behind white digits, so they're kept dark.
        "fill_normal": QColor("#474747"), "fill_low": QColor("#9c1c16"),
        "fill_charging": QColor("#17662f"),
        # Number style colors the digits themselves, so they're kept bright.
        "text_low": QColor("#ff6b61"), "text_charging": QColor("#4cd964"),
    },
    "light": {
        "fg": QColor("#111111"), "dim": QColor("#8a8a8a"),
        "fill_normal": QColor("#cfcfcf"), "fill_low": QColor("#ffb3ad"),
        "fill_charging": QColor("#a3e4b5"),
        "text_low": QColor("#c4150b"), "text_charging": QColor("#1e7b3c"),
    },
}

# Battery style: outline centered on these lines; the 2-unit stroke is 1 px at 16 px.
BODY = QRectF(1, 5, 26, 24)
NUB = QRectF(28, 12, 3, 10)
FILL = QRectF(4, 8, 20, 18)            # fill area inside the outline at 100%

# Number style: digits above, level bar below.
DIGITS = QRectF(0, 0, 32, 26)
BAR = QRectF(1, 28, 30, 3.5)

FONT_FAMILY = "Bahnschrift"            # ships with Windows; narrow, legible digits


@dataclass(frozen=True)
class IconState:
    kind: str                # "level", "off", "no_dongle"
    level: int | None = None
    charging: bool = False


def _draw_text(p: QPainter, text: str, px_units: float, k: float, box: QRectF, color: QColor):
    # Drawn as a filled outline rather than with drawText: Windows' font
    # engine applies ClearType regardless of hints, which leaves colored
    # fringes on a transparent icon. Offsets are snapped to whole pixels.
    font = QFont(FONT_FAMILY)
    font.setPixelSize(max(1, round(px_units * k)))
    font.setWeight(QFont.Weight.Bold)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    r = path.boundingRect()
    c = box.center()
    path.translate(round(c.x() * k - r.center().x()), round(c.y() * k - r.center().y()))
    p.save()
    p.resetTransform()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    p.restore()


def _battery_outline(p: QPainter, color: QColor):
    p.setPen(QPen(color, 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(BODY, 5, 5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(NUB, 1.2, 1.2)


def _draw_unavailable(p: QPainter, state: IconState, pal):
    dim = QColor(pal["dim"])
    dim.setAlphaF(0.9)
    _battery_outline(p, dim)
    if state.kind == "off":
        p.setBrush(pal["dim"])
        p.drawRoundedRect(QRectF(8, 16, 12, 2), 1, 1)
    else:
        pen = QPen(pal["dim"], 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(3, 31), QPointF(26, 3))


def _draw_battery(p: QPainter, state: IconState, pal, k: float):
    level = max(0, min(100, state.level))
    outline = QColor(pal["fg"])
    outline.setAlphaF(0.7)
    _battery_outline(p, outline)
    key = "fill_charging" if state.charging else "fill_low" if level <= LOW else "fill_normal"
    width = max(2.5, FILL.width() * level / 100)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal[key])
    p.drawRoundedRect(QRectF(FILL.x(), FILL.y(), width, FILL.height()), 2.5, 2.5)
    _draw_text(p, str(level), 21 if level < 100 else 15, k, BODY, pal["fg"])


def _draw_number(p: QPainter, state: IconState, pal, k: float):
    level = max(0, min(100, state.level))
    key = "text_charging" if state.charging else "text_low" if level <= LOW else "fg"
    color = pal[key]
    _draw_text(p, str(level), 27 if level < 100 else 20, k, DIGITS, color)
    track = QColor(pal["dim"])
    track.setAlphaF(0.45)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(track)
    p.drawRoundedRect(BAR, 1.5, 1.5)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(BAR.x(), BAR.y(), max(3.0, BAR.width() * level / 100), BAR.height()),
                      1.5, 1.5)


def render(state: IconState, theme: str, size: int, style: str = DEFAULT_STYLE) -> QImage:
    pal = PALETTE[theme]
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    k = size / 32
    p.scale(k, k)
    if state.kind != "level":
        _draw_unavailable(p, state, pal)
    elif style == "number":
        _draw_number(p, state, pal, k)
    else:
        _draw_battery(p, state, pal, k)
    p.end()
    return img


def make_icon(state: IconState, theme: str, style: str = DEFAULT_STYLE) -> QIcon:
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(QPixmap.fromImage(render(state, theme, s, style)))
    return icon
