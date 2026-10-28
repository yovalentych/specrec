"""Automatic analysis of a kinetic curve A(t), t in minutes (numpy only, no scipy).

Three models compete; the simplest one that is not clearly worse wins (AICc):
  linear       A = a + v·t                                   2 parameters
  first order  A = A∞ − ΔA·exp(−k·(t − t0))                  3   (rise or fall to a plateau)
  logistic     A = A0 + ΔA / (1 + exp(−(t − tm)/w))          4   (lag phase → growth → plateau)
For every curve: the type, the initial rate v0, the linear range from the start and,
depending on the type, the plateau (A∞, % reached, t½, t95) or the lag phase and the
maximum rate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class KineticResult:
    kind: str                    # flat | linear | plateau | sigmoid | accelerating | too_few
    summary: str                 # one line in Ukrainian
    n: int = 0
    noise: float = 0.0           # RMS of the residuals of the chosen model
    v0: float | None = None      # initial rate, A/min
    lin_range: tuple[float, float] | None = None
    lin_rate: float | None = None
    lin_r2: float | None = None
    r2: float | None = None      # of the chosen model
    a_inf: float | None = None   # plateau level
    k: float | None = None       # first order rate constant, 1/min
    t_half: float | None = None  # min
    t95: float | None = None     # min from the start of the record
    reached: float | None = None  # fraction of the total change already passed, 0..1
    lag: float | None = None     # lag time, min
    v_max: float | None = None   # maximum rate (logistic), A/min
    t_mid: float | None = None   # inflection point (logistic), min
    model_t: list = field(default_factory=list)
    model_a: list = field(default_factory=list)


# ---------------------------------------------------------------- fitting helpers
def _linfit(t, a):
    k, b = np.polyfit(t, a, 1)
    res = a - (k * t + b)
    ss = np.sum((a - a.mean()) ** 2)
    r2 = 1 - np.sum(res ** 2) / ss if ss > 0 else 1.0
    return k, b, float(np.sum(res ** 2)), r2, res


def _lsq2(x, a):
    """a ≈ c0 + c1·x: least squares, returns (sse, c0, c1)."""
    X = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(X, a, rcond=None)
    res = a - X @ coef
    return float(res @ res), float(coef[0]), float(coef[1])


def _golden(f, lo, hi, it=40):
    gr = (math.sqrt(5) - 1) / 2
    for _ in range(it):
        c, d = hi - gr * (hi - lo), lo + gr * (hi - lo)
        if f(c) < f(d):
            hi = d
        else:
            lo = c
    return (lo + hi) / 2


def fit_first_order(t, a):
    """A = P − D·e^{−k(t−t0)}: for a fixed k it is linear in P, D; search k on a log grid."""
    tt = t - t[0]
    span = tt[-1]
    sse = lambda lk: _lsq2(-np.exp(-math.exp(lk) * tt), a)[0]
    grid = np.linspace(math.log(0.03 / span), math.log(30 / span), 160)
    vals = [sse(g) for g in grid]
    i = int(np.argmin(vals))
    lk = _golden(sse, grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)])
    k = math.exp(lk)
    s, p, d = _lsq2(-np.exp(-k * tt), a)
    return k, p, d, s, i in (0, len(grid) - 1)


def fit_logistic(t, a):
    """A = A0 + ΔA·σ((t−tm)/w): for fixed tm, w it is linear in A0, ΔA; 2-D grid + refinement."""
    span = t[-1] - t[0]

    def sse(tm, w):
        return _lsq2(1 / (1 + np.exp(-(t - tm) / w)), a)[0]

    tms = np.linspace(t[0] - 0.3 * span, t[-1] + 0.6 * span, 45)
    ws = np.exp(np.linspace(math.log(span / 80), math.log(span), 30))
    best = min(((sse(tm, w), tm, w) for tm in tms for w in ws), key=lambda x: x[0])
    _, tm, w = best
    dtm, dlw = tms[1] - tms[0], (math.log(ws[1]) - math.log(ws[0]))
    for _ in range(3):                      # local refinement
        cand = [(sse(tm + i * dtm / 2, w * math.exp(j * dlw / 2)), tm + i * dtm / 2, w * math.exp(j * dlw / 2))
                for i in (-1, 0, 1) for j in (-1, 0, 1)]
        _, tm, w = min(cand, key=lambda x: x[0])
        dtm, dlw = dtm / 2, dlw / 2
    s, a0, da = _lsq2(1 / (1 + np.exp(-(t - tm) / w)), a)
    return tm, w, a0, da, s


def _aicc(sse, n, p):
    sse = max(sse, 1e-12)
    return n * math.log(sse / n) + 2 * p + (2 * p * (p + 1)) / max(n - p - 1, 1)


def linear_range(t, a, tol, min_pts=4, min_r2=0.99):
    """Longest stretch from the first point that a straight line fits: every point within tol,
    R² ≥ min_r2 and no significant bend (a parabola is not clearly better)."""
    best = None
    for j in range(min_pts, len(t) + 1):
        k, b, sse_l, r2, res = _linfit(t[:j], a[:j])
        bent = False
        if j >= 7:
            q = np.polyfit(t[:j], a[:j], 2)
            sse_q = float(np.sum((a[:j] - np.polyval(q, t[:j])) ** 2))
            bent = _aicc(sse_q, j, 3) < _aicc(sse_l, j, 2) - 6 and np.max(np.abs(res)) > tol / 2
        if np.max(np.abs(res)) <= tol and r2 >= min_r2 and not bent:
            best = (j, k, r2)
        elif best is not None and j - best[0] >= 2:
            break      # two points in a row do not fit any more
    return best


# ---------------------------------------------------------------- analysis
def analyze(t_min, a_vals) -> KineticResult:
    t = np.asarray(t_min, float)
    a = np.asarray(a_vals, float)
    m = ~np.isnan(a)
    t, a = t[m], a[m]
    n = len(t)
    if n < 4 or np.ptp(t) <= 0:
        return KineticResult("too_few", "Замало точок для аналізу (потрібно щонайменше 4).", n=n)

    k_lin, b_lin, sse_lin, r2_lin, _ = _linfit(t, a)
    noise_lin = float(np.sqrt(sse_lin / max(n - 2, 1)))
    # noise from the point-to-point scatter (independent of any model)
    d2 = np.diff(a, 2)
    noise_pp = float(np.median(np.abs(d2)) / 0.6745 / math.sqrt(6)) if len(d2) else noise_lin
    ss_tot = float(np.sum((a - a.mean()) ** 2))
    r = KineticResult("linear", "", n=n)

    # --- flat: no change beyond the noise
    if abs(k_lin * np.ptp(t)) < max(4 * noise_pp, 0.003) and np.ptp(a) < max(8 * noise_pp, 0.006):
        r.kind = "flat"
        r.noise = noise_lin
        r.v0 = r.lin_rate = float(k_lin)
        r.lin_range = (float(t[0]), float(t[-1]))
        r.summary = f"Змін немає: A стабільна ({a.mean():.4f}), дрейф {k_lin:+.5f} A/хв, шум ±{noise_lin:.4f}."
        r.model_t = [float(t[0]), float(t[-1])]
        r.model_a = [float(k_lin * t[0] + b_lin), float(k_lin * t[-1] + b_lin)]
        return r

    span = float(np.ptp(t))
    models = {"linear": _aicc(sse_lin, n, 2)}
    if n >= 5:
        k, p, dlt, sse_exp, edge = fit_first_order(t, a)
        if k * span > 0.15 and not edge:
            models["plateau"] = _aicc(sse_exp, n, 3)
    if n >= 7:
        tm, w, a0, da, sse_log = fit_logistic(t, a)
        # a real lag: the curve starts flatter than it gets later, inflection after the start
        if tm - 1.5 * w > t[0] and w < span:
            models["sigmoid"] = _aicc(sse_log, n, 4)
    # prefer the simpler model unless the more complex one is clearly better
    order = ["linear", "plateau", "sigmoid"]
    choice = "linear"
    for name in order[1:]:
        if name in models and models[name] < models[choice] - 4:
            choice = name

    tm_grid = np.linspace(t[0], t[-1], 200)
    if choice == "plateau":
        t0 = t[0]
        r.kind, r.k, r.a_inf, r.v0 = "plateau", k, float(p), float(dlt * k)
        r.t_half = math.log(2) / k
        r.t95 = float(t0 + math.log(20) / k)
        r.reached = float(1 - math.exp(-k * (t[-1] - t0)))
        fit = p - dlt * np.exp(-k * (t - t0))
        r.model_t, r.model_a = tm_grid.tolist(), (p - dlt * np.exp(-k * (tm_grid - t0))).tolist()
        dof = 3
        grow = "зростає" if dlt > 0 else "спадає"
        if r.reached >= 0.95:
            pl = f"плато досягнуто з ~{r.t95:.1f} хв"
        else:
            pl = (f"плато ще не досягнуто: пройдено {r.reached * 100:.0f} % змін, "
                  f"95 % — орієнтовно на {r.t95:.1f} хв")
        r.summary = f"A {grow} й виходить на плато (кінетика 1-го порядку), {pl}."
    elif choice == "sigmoid":
        sig = lambda x: 1 / (1 + np.exp(-(x - tm) / w))
        fit = a0 + da * sig(t)
        r.model_t, r.model_a = tm_grid.tolist(), (a0 + da * sig(tm_grid)).tolist()
        dof = 4
        r.t_mid, r.v_max = float(tm), float(da / (4 * w))
        r.lag = float(tm - 2 * w)                  # the tangent at the inflection meets the start level
        r.v0 = float(da * sig(t[0]) * (1 - sig(t[0])) / w)
        r.a_inf = float(a0 + da)
        r.reached = float((sig(t[-1]) - sig(t[0])) / (1 - sig(t[0])))
        if tm > t[-1]:
            r.kind = "accelerating"
            r.summary = ("Швидкість зростає з часом (лаг-фаза / автокаталіз); перегину ще не видно — "
                         "запис закінчився раніше.")
        else:
            r.kind = "sigmoid"
            pl = ("вийшла на плато" if r.reached >= 0.95 else f"плато ще не досягнуто ({r.reached * 100:.0f} %)")
            r.summary = f"S-подібна крива: лаг-фаза, прискорення, потім сповільнення; {pl}."
    else:
        fit = k_lin * t + b_lin
        dof = 2
        r.kind, r.v0 = "linear", float(k_lin)
        r.model_t = [float(t[0]), float(t[-1])]
        r.model_a = [float(k_lin * t[0] + b_lin), float(k_lin * t[-1] + b_lin)]
        r.summary = "A змінюється рівномірно: пряма на всьому записі, плато не видно."

    res = a - fit
    r.noise = float(np.sqrt(np.sum(res ** 2) / max(n - dof, 1)))
    r.r2 = float(1 - np.sum(res ** 2) / ss_tot) if ss_tot > 0 else 1.0

    tol = max(3 * noise_pp, 2 * r.noise, 0.002)
    lr = linear_range(t, a, tol)
    if lr and r.kind in ("linear", "plateau"):
        j, k_l, r2_l = lr
        r.lin_range = (float(t[0]), float(t[j - 1]))
        r.lin_rate, r.lin_r2 = float(k_l), float(r2_l)
    return r


MODEL_NAMES = {"linear": "пряма", "plateau": "експонента до плато", "sigmoid": "логістична (S-крива)",
               "accelerating": "логістична (S-крива)"}


def report_lines(r: KineticResult) -> list[str]:
    """Human-readable lines (Ukrainian) for the GUI and export."""
    out = [r.summary]
    if r.kind in ("too_few", "flat"):
        return out
    if r.v0 is not None:
        out.append(f"Початкова швидкість v₀ = {r.v0:+.4f} A/хв")
    if r.kind in ("sigmoid", "accelerating"):
        if r.lag is not None and r.lag > 0:
            out.append(f"Лаг-фаза ≈ {r.lag:.1f} хв")
        out.append(f"Максимальна швидкість {r.v_max:+.4f} A/хв"
                   + (f" при t ≈ {r.t_mid:.1f} хв" if r.kind == "sigmoid" else " (оцінка, перегин після запису)"))
        if r.kind == "sigmoid":
            out.append(f"Плато A∞ ≈ {r.a_inf:.3f}")
    elif r.lin_range:
        lo, hi = r.lin_range
        out.append(f"Лінійна ділянка: {lo:.1f}–{hi:.1f} хв, {r.lin_rate:+.4f} A/хв (R² {r.lin_r2:.3f})")
    elif r.kind == "plateau":
        out.append("Лінійної ділянки немає: крива вигинається одразу — орієнтуйтеся на v₀ "
                   "або міряйте частіше (менший інтервал).")
    if r.kind == "plateau":
        out.append(f"Плато A∞ ≈ {r.a_inf:.3f};  k = {r.k:.3f} хв⁻¹,  t½ = {r.t_half:.1f} хв")
    out.append(f"Модель: {MODEL_NAMES[r.kind]}, R² {r.r2:.4f}, шум ±{r.noise:.4f}")
    return out
