"""Dot plot of groups: every animal as a point (slightly spread), mean ± SD as a bar."""
from __future__ import annotations

import random

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt

from ..protocol import isnum
from .common import make_plot


class GroupPlot(pg.PlotWidget):
    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        w = make_plot(theme, "", "")      # reuse the styling
        self.setBackground(theme.plot_bg)
        self.showGrid(x=False, y=True, alpha=theme.grid_alpha)
        for ax in ("left", "bottom"):
            a = self.getAxis(ax)
            a.setPen(theme.plot_fg)
            a.setTextPen(theme.plot_fg)
            a.enableAutoSIPrefix(False)
        w.deleteLater()

    def show_groups(self, groups: dict[str, list[float]], label: str, unit: str = "", labels: dict | None = None):
        """groups: {group: [values]}; labels: {group: [animal codes]} for tooltips (optional)."""
        self.clear()
        names = list(groups)
        ticks = []
        for i, g in enumerate(names):
            vals = [v for v in groups[g] if isnum(v)]
            col = self.theme.channels[i % len(self.theme.channels)]
            rnd = random.Random(g)
            xs = [i + rnd.uniform(-0.12, 0.12) for _ in vals]
            self.plot(xs, vals, pen=None, symbol="o", symbolSize=9, symbolBrush=col, symbolPen=None)
            if vals:
                m = float(np.mean(vals))
                sd = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
                pen = pg.mkPen(self.theme.text, width=2)
                self.plot([i - 0.25, i + 0.25], [m, m], pen=pen)
                if sd:
                    self.plot([i, i], [m - sd, m + sd], pen=pg.mkPen(self.theme.text, width=1.4))
                    for y in (m - sd, m + sd):
                        self.plot([i - 0.1, i + 0.1], [y, y], pen=pg.mkPen(self.theme.text, width=1.4))
            ticks.append((i, f"{g} (n={len(vals)})"))
        self.getAxis("bottom").setTicks([ticks])
        self.setXRange(-0.6, max(len(names) - 0.4, 0.6))
        self.setLabel("left", f"{label}, {unit}" if unit else label)
