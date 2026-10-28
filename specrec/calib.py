"""Calibration curve: A against concentration of standards, then concentration of unknowns.

Models: "linear" A = a + b·C, "origin" A = b·C, "quadratic" A = a + b·C + c·C².
Every replicate is its own point. Reported: equation, R², s(y/x), LOD = 3.3·s/b,
LOQ = 10·s/b, and for an unknown: C with its standard error (linear models, the usual
formula for inverse prediction) and whether it lies inside the range of the standards.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MODELS = {"linear": "Пряма  A = a + b·C", "origin": "Пряма через 0  A = b·C",
          "quadratic": "Квадратична  A = a + b·C + c·C²"}


@dataclass
class Fit:
    model: str
    coef: tuple          # (a, b, c) — always three numbers, unused ones are 0
    r2: float
    s_yx: float          # residual standard deviation
    n: int
    c_min: float
    c_max: float
    lod: float | None
    loq: float | None
    x_mean: float
    sxx: float
    y_mean: float

    def predict_a(self, c):
        a, b, q = self.coef
        c = np.asarray(c, float)
        return a + b * c + q * c * c

    def equation(self, unit: str = "") -> str:
        a, b, q = self.coef
        u = f" ({unit})" if unit else ""
        if self.model == "origin":
            return f"A = {b:.5g}·C{u}"
        if self.model == "linear":
            return f"A = {a:+.4f} {'+' if b >= 0 else '−'} {abs(b):.5g}·C{u}".replace("A = +", "A = ")
        return (f"A = {a:+.4f} {'+' if b >= 0 else '−'} {abs(b):.5g}·C "
                f"{'+' if q >= 0 else '−'} {abs(q):.4g}·C²{u}").replace("A = +", "A = ")

    def conc(self, A: float, replicates: int = 1) -> tuple[float, float | None]:
        """Concentration for absorbance A and its standard error (None if unknown)."""
        a, b, q = self.coef
        if self.model in ("linear", "origin"):
            if b == 0:
                return float("nan"), None
            c = (A - a) / b
            if self.sxx > 0 and self.n > 2:
                se = (self.s_yx / abs(b)) * math.sqrt(1 / replicates + 1 / self.n
                                                       + (A - self.y_mean) ** 2 / (b * b * self.sxx))
            else:
                se = None
            return float(c), se
        # quadratic: the root inside (or nearest to) the range of the standards
        if abs(q) < 1e-15:
            return ((A - a) / b if b else float("nan")), None
        disc = b * b - 4 * q * (a - A)
        if disc < 0:
            return float("nan"), None
        roots = [(-b + s * math.sqrt(disc)) / (2 * q) for s in (1, -1)]
        mid = (self.c_min + self.c_max) / 2
        c = min(roots, key=lambda r: (not (self.c_min - 0.5 * (self.c_max - self.c_min) <= r
                                            <= self.c_max + 0.5 * (self.c_max - self.c_min)), abs(r - mid)))
        slope = b + 2 * q * c
        se = self.s_yx / abs(slope) * math.sqrt(1 / replicates + 1 / self.n) if slope else None
        return float(c), se


def fit_calibration(conc, absb, model: str = "linear") -> Fit:
    x = np.asarray(conc, float)
    y = np.asarray(absb, float)
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    n = len(x)
    need = {"linear": 2, "origin": 1, "quadratic": 3}[model]
    if n < need + 1 or len(set(x)) < need:
        raise ValueError(f"Потрібно щонайменше {need + 1} точок із {need} різними концентраціями")
    if model == "origin":
        b = float(np.sum(x * y) / np.sum(x * x))
        coef, p = (0.0, b, 0.0), 1
        pred = b * x
        ss_tot = float(np.sum(y * y))          # R² about zero for a line through the origin
    elif model == "linear":
        b, a = np.polyfit(x, y, 1)
        coef, p = (float(a), float(b), 0.0), 2
        pred = a + b * x
        ss_tot = float(np.sum((y - y.mean()) ** 2))
    else:
        q, b, a = np.polyfit(x, y, 2)
        coef, p = (float(a), float(b), float(q)), 3
        pred = a + b * x + q * x * x
        ss_tot = float(np.sum((y - y.mean()) ** 2))
    sse = float(np.sum((y - pred) ** 2))
    r2 = 1 - sse / ss_tot if ss_tot > 0 else 1.0
    s_yx = math.sqrt(sse / (n - p)) if n > p else 0.0
    slope0 = coef[1] + 2 * coef[2] * float(x.min())
    lod = 3.3 * s_yx / abs(slope0) if slope0 else None
    loq = 10 * s_yx / abs(slope0) if slope0 else None
    return Fit(model, coef, float(r2), s_yx, n, float(x.min()), float(x.max()), lod, loq,
               float(x.mean()), float(np.sum((x - x.mean()) ** 2)), float(y.mean()))


def range_note(fit: Fit, c: float) -> str:
    if math.isnan(c):
        return "поза кривою"
    span = fit.c_max - fit.c_min
    if c < fit.c_min - 0.02 * span or c > fit.c_max + 0.02 * span:
        return "поза діапазоном стандартів (екстраполяція)"
    if fit.loq is not None and c < fit.loq:
        return "нижче LOQ" if (fit.lod is None or c >= fit.lod) else "нижче LOD"
    return ""
