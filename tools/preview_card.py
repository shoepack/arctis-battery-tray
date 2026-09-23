"""Render the popup card for sample states to a PNG sheet."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from arctis_tray import device
from arctis_tray.card import Card
from arctis_tray.tracker import Snapshot

NOW = time.time()
SAMPLES = [
    Snapshot(device.OK, 62, charging=True, rate_per_hour=16.2, hours_left=2.9,
             typical_charge_per_hour=18, last_ok=NOW),
    Snapshot(device.OK, 57, rate_per_hour=-4.2, hours_left=13.6, last_ok=NOW),
    Snapshot(device.OK, 14, rate_per_hour=-4.5, hours_left=3.1, last_ok=NOW),
    Snapshot(device.OK, 57, stopped_at=NOW - 120, rate_per_hour=-4.2, hours_left=13.6, last_ok=NOW),
    Snapshot(device.OK, 60, charging=True, unstable=True, last_ok=NOW),
    Snapshot(device.OK, 100, charging=True, full=True, last_ok=NOW),
    Snapshot(device.OK, 57, last_ok=NOW),
    Snapshot(device.HEADSET_OFF),
    Snapshot(device.NO_DONGLE),
]

if __name__ == "__main__":
    app = QApplication(sys.argv)
    theme = sys.argv[1] if len(sys.argv) > 1 else "dark"
    shots = []
    for snap in SAMPLES:
        card = Card()
        card.show_snapshot(snap, theme, NOW)
        card.adjustSize()
        shots.append(card.grab().toImage())
    pad, cols = 16, 3
    w = max(s.width() for s in shots)
    h = max(s.height() for s in shots)
    rows = (len(shots) + cols - 1) // cols
    sheet = QImage(cols * (w + pad) + pad, rows * (h + pad) + pad, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#202020" if theme == "dark" else "#e8e8e8"))
    p = QPainter(sheet)
    for i, img in enumerate(shots):
        p.drawImage(pad + (i % cols) * (w + pad), pad + (i // cols) * (h + pad), img)
    p.end()
    out = Path(__file__).with_name(f"card_preview_{theme}.png")
    sheet.save(str(out))
    print(out)
