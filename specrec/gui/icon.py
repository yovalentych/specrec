"""Application icon drawn in code (like LangRec): a cuvette with a light beam and a spectrum."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


def _paint(p: QPainter, s: float):
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor("#0f3b47"))
    g.setColorAt(1, QColor("#0e7490"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(r, s * 0.22, s * 0.22)

    # rainbow beam behind the cuvette
    beam = QLinearGradient(QPointF(s * 0.1, 0), QPointF(s * 0.9, 0))
    for pos, col in [(0, "#7c3aed"), (0.25, "#2563eb"), (0.45, "#10b981"), (0.6, "#facc15"),
                     (0.78, "#f97316"), (1, "#ef4444")]:
        beam.setColorAt(pos, QColor(col))
    p.setBrush(beam)
    p.drawRect(QRectF(s * 0.1, s * 0.47, s * 0.8, s * 0.07))

    # cuvette with liquid
    p.setPen(QPen(QColor("white"), s * 0.03))
    p.setBrush(QColor(255, 255, 255, 40))
    cuv = QRectF(s * 0.36, s * 0.2, s * 0.28, s * 0.6)
    p.drawRoundedRect(cuv, s * 0.03, s * 0.03)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(236, 72, 153, 170))
    p.drawRoundedRect(QRectF(s * 0.385, s * 0.42, s * 0.23, s * 0.355), s * 0.02, s * 0.02)

    # absorption peak trace
    pen = QPen(QColor("white"), s * 0.035)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(s * 0.14, s * 0.32))
    path.cubicTo(QPointF(s * 0.30, s * 0.32), QPointF(s * 0.40, s * 0.08), QPointF(s * 0.52, s * 0.12))
    path.cubicTo(QPointF(s * 0.64, s * 0.16), QPointF(s * 0.70, s * 0.32), QPointF(s * 0.86, s * 0.32))
    p.drawPath(path)


def make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        _paint(p, size)
        p.end()
        icon.addPixmap(pm)
    return icon


def save_icon_png(path: str, size: int = 1024) -> None:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    _paint(p, size)
    p.end()
    img.save(path)
