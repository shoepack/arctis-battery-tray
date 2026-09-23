"""Render every icon state for each style at a real tray size, pixel-enlarged,
to a PNG sheet. Usage: preview_icons.py [size] [taskbar-hex-color]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

from arctis_tray.icons import STYLES, IconState, render

STATES = [
    IconState("level", 82), IconState("level", 57), IconState("level", 15),
    IconState("level", 69, charging=True), IconState("level", 100),
    IconState("level", 100, charging=True), IconState("level", 7),
    IconState("off"), IconState("no_dongle"),
]
ZOOM, PAD = 8, 8

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    dark_bg = QColor(sys.argv[2] if len(sys.argv) > 2 else "#1f1f1f")
    rows = [(style, theme) for style in STYLES for theme in ("dark", "light")]
    cell = size * ZOOM + PAD
    sheet = QImage(len(STATES) * cell + PAD, len(rows) * cell + PAD, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#808080"))
    p = QPainter(sheet)
    for r, (style, theme) in enumerate(rows):
        bg = dark_bg if theme == "dark" else QColor("#eeeeee")
        for c, st in enumerate(STATES):
            x, y = PAD + c * cell, PAD + r * cell
            p.fillRect(x, y, cell - PAD, cell - PAD, bg)
            big = render(st, theme, size, style).scaled(
                size * ZOOM, size * ZOOM, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation)
            p.drawImage(x, y, big)
    p.end()
    out = Path(__file__).with_name("icon_preview.png")
    sheet.save(str(out))
    print(out)
