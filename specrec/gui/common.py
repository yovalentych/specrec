"""Small widgets and helpers shared by the tabs."""
from __future__ import annotations

import math

import pyqtgraph as pg
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from . import theme as th


def section(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("section")
    return lab


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("hint")
    lab.setWordWrap(True)
    return lab


def fmt_a(r) -> str:
    if math.isinf(r.A):
        return "> 3"
    return ("< " if r.saturated else "") + f"{r.A:.3f}"


def fmt_t(r) -> str:
    return "0.0" if math.isinf(r.A) else f"{r.T:.1f}"


def make_plot(t: th.Theme, xlabel: str, ylabel: str) -> pg.PlotWidget:
    w = pg.PlotWidget()
    w.setBackground(t.plot_bg)
    w.showGrid(x=True, y=True, alpha=t.grid_alpha)
    for ax in ("left", "bottom"):
        a = w.getAxis(ax)
        a.setPen(t.plot_fg)
        a.setTextPen(t.plot_fg)
        a.enableAutoSIPrefix(False)
    w.setLabel("bottom", xlabel)
    w.setLabel("left", ylabel)
    w.addLegend(offset=(-10, 10))
    return w


class Tile(QFrame):
    """Big readout: title, value, unit."""

    def __init__(self, title: str, unit: str = ""):
        super().__init__()
        self.setObjectName("tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.t = QLabel(title)
        self.t.setObjectName("tileTitle")
        self.v = QLabel("—")
        self.v.setObjectName("tileValue")
        self.v.setStyleSheet("font-size: 34px;")
        self.u = QLabel(unit)
        self.u.setObjectName("tileUnit")
        lay.addWidget(self.t)
        lay.addWidget(self.v)
        lay.addWidget(self.u)

    def set(self, text: str):
        self.v.setText(text)
