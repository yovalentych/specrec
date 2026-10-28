import math
import time

import pytest

from specrec.protocol import Run, evaluate, t_two_sided_p, validate, welch
from specrec.protocols_builtin import BUILTIN, CATALASE, MDA, SH, SOD

SAMPLES = [{"code": "C1", "group": "К"}, {"code": "D1", "group": "DOX"}]


def finish(run, values_for, t0=1000.0):
    """Drive every tube to the end: confirm actions, jump over waits, read values."""
    now = t0
    for _ in range(500):
        tube = run.next_tube()
        if tube is None:
            break
        s = run.state(tube, now)
        if s in ("do", "ready"):
            run.confirm(tube, now)
        elif s == "read":
            cur = run.current(tube)
            run.record(tube, {wl: values_for(tube, cur["read"], wl) for wl in cur["wl"]}, now)
        now += 5
        for t in run.tubes:            # jump the clock over waits
            if t.due is not None and run.state(t, now) == "wait":
                now = max(now, t.due)
        run.tick(now)
    return now


def test_formulas_are_safe_and_work():
    assert evaluate("mean(x) * 2", {"x": [1, 2, 3]}) == 4
    assert evaluate("a if a > 1 else 0", {"a": 2}) == 2
    assert math.isnan(evaluate("missing + 1", {}))
    assert evaluate("nz(missing, 5)", {}) == 5
    with pytest.raises(Exception):
        evaluate("__import__('os')", {})
    with pytest.raises(Exception):
        evaluate("open('x')", {})


def test_builtins_are_valid():
    for p in BUILTIN:
        assert validate(p) == [], p["id"]


def test_mda_journal_formula():
    run = Run(MDA, SAMPLES)
    finish(run, lambda t, r, wl: {532: 0.12, 600: 0.01}[wl])
    c = run.compute()
    s = c["samples"][0]
    assert s["res"]["C"] == pytest.approx((0.12 - 0.01) * 4 / 0.156)
    assert s["complete"]


def test_sod_inhibition():
    run = Run(SOD, SAMPLES)
    vals = {"control": {"A0": 0.1, "A10": 0.6}, "test": {"A0": 0.1, "A10": 0.35}}
    finish(run, lambda t, r, wl: vals[t.type][r] if t.type in vals else 0.0)
    c = run.compute()
    assert c["series"]["dAk"] == pytest.approx(0.5)
    s = c["samples"][0]["res"]
    T = (0.5 - 0.25) / 0.5
    assert s["T"] == pytest.approx(T)
    assert s["uo_ml"] == pytest.approx(T / (1 - T) / 0.05 * 1.5)       # = у.о. × 30
    assert c["series_flags"] == []


def test_sod_wait_timing():
    run = Run(SOD, SAMPLES[:1])
    run.record(run.zero_tube(), {540: 0.0}, 0)
    k1 = next(t for t in run.tubes if t.type == "control")
    run.confirm(k1, 100)                     # start
    run.record(k1, {540: 0.1}, 110)          # A0
    assert run.state(k1, 500) == "wait" and k1.due == pytest.approx(700)   # 10 min from the start
    assert run.state(k1, 701) == "ready"
    run.tick(701)
    assert run.state(k1, 702) == "read" and run.current(k1)["read"] == "A10"


def test_catalase_calibration_and_activity():
    run = Run(CATALASE, SAMPLES)
    k = 0.04

    def val(t, r, wl):
        return {"zero": 0, "std": 0.01 + k * (t.x or 0), "blank": 0.70, "test": 0.45, "bg": 0.05}[t.type]
    finish(run, val)
    c = run.compute()
    assert c["series"]["k_slope"] == pytest.approx(k)
    s = c["samples"][0]["res"]
    dE = 0.70 - (0.45 - 0.05)
    assert s["A"] == pytest.approx(dE / (k * 10 * 0.1))
    assert s["lin"] == pytest.approx((0.45 - 0.05) / 0.70)


def test_sh_and_hemolysis():
    run = Run(SH, SAMPLES)
    v = {"reag": {"A": 0.02}, "gsh": {"fon": 0.0, "zr": 0.37},
         "test": {"fon": {380: 0.05, 412: 0.07, 415: 0.08, 450: 0.04}, "zr": 0.35}}

    def val(t, r, wl):
        if t.type == "zero":
            return 0.0
        x = v[t.type][r]
        return x[wl] if isinstance(x, dict) else x
    finish(run, val)
    c = run.compute()
    s = c["samples"][0]["res"]
    dA = 0.35 - 0.07 * 1 / 1.02 - 0.02
    assert s["SH"] == pytest.approx(dA / 0.01415 * 1.02 / 0.05)
    assert s["Hb"] == pytest.approx(20 * (167.2 * 0.08 - 83.6 * 0.05 - 83.6 * 0.04))


def test_group_stats_and_welch():
    t, df, p = welch([1, 2, 3, 4], [3, 4, 5, 6])
    assert t == pytest.approx(2.191, abs=1e-3) and p == pytest.approx(0.0710, abs=1e-3)
    assert t_two_sided_p(2.0, 10) == pytest.approx(0.0734, abs=1e-4)


def test_save_and_resume(tmp_path):
    run = Run(SOD, SAMPLES)
    run.record(run.zero_tube(), {540: 0.0}, 0)
    path = tmp_path / "run.json"
    run.save(path)
    import json
    r2 = Run.from_json(json.loads(path.read_text()))
    assert len(r2.tubes) == len(run.tubes) and r2.state(r2.zero_tube()) == "done"


@pytest.mark.parametrize("proto", ["bradford", "lowry"])
def test_protein_quadratic_curve(proto):
    from specrec.protocols_builtin import BRADFORD, LOWRY
    p = BRADFORD if proto == "bradford" else LOWRY
    a, b, q = (0.02, 0.95, -0.22) if proto == "bradford" else (0.01, 1.7, -1.1)
    curve = lambda c: a + b * c + q * c * c
    c_true = 0.6 if proto == "bradford" else 0.25        # mg/ml in the diluted sample
    run = Run(p, SAMPLES)
    finish(run, lambda t, r, wl: {"zero": 0.0, "std": curve(t.x or 0), "test": curve(c_true)}[t.type])
    c = run.compute()
    s = c["samples"][0]["res"]
    assert c["series"]["k_r2"] == pytest.approx(1, abs=1e-9)
    assert s["Cdil"] == pytest.approx(c_true, rel=1e-6)
    assert s["C"] == pytest.approx(c_true * p["inputs"]["dilution"]["default"], rel=1e-6)
    assert c["samples"][0]["flags"] == []


def test_lowry_timing_two_waits():
    from specrec.protocols_builtin import LOWRY
    run = Run(LOWRY, SAMPLES[:1])
    run.record(run.zero_tube(), {750: 0.0}, 0)
    t = next(x for x in run.tubes if x.type == "test")
    run.confirm(t, 100)                       # + reagent C
    assert t.due == pytest.approx(700)        # 10 min
    run.tick(700)
    run.confirm(t, 705)                       # + Folin
    assert t.due == pytest.approx(705 + 1800)  # 30 min from the Folin
