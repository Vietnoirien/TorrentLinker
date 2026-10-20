"""Draw the app icon (two chain links) into src/torrentlinker/assets/icon.png."""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

app = QGuiApplication(sys.argv)
size = 256
img = QImage(size, size, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setBrush(QColor("#1e5aa8"))
p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)
p.setBrush(Qt.BrushStyle.NoBrush)
p.translate(128, 128)
p.rotate(-45)
for x, color in ((-38, "#ffffff"), (38, "#9fd3ff")):
    p.setPen(QPen(QColor(color), 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawRoundedRect(QRectF(x - 52, -30, 104, 60), 30, 30)
p.end()
out = Path(__file__).parent.parent / "src" / "torrentlinker" / "assets" / "icon.png"
img.save(str(out))
print(out)
