import pytest

from specrec.protocol import Run
from specrec.protocols_builtin import BRADFORD, MDA, SOD
from specrec.summary import build, mann_whitney

from test_protocol import finish

SAMPLES = [{"code": f"C{i}", "group": "К"} for i in range(1, 4)] + [{"code": f"D{i}", "group": "DOX"} for i in range(1, 4)]


def test_mann_whitney_exact():
    u, p = mann_whitney([1, 2, 3], [4, 5, 6])
    assert u == 0 and p == pytest.approx(0.1, abs=1e-9)      # exact: 2/20
    u, p = mann_whitney([1, 2, 3, 4, 5], [6, 7, 8, 9, 10])
    assert p == pytest.approx(0.00794, abs=1e-4)
    assert 0 < mann_whitney([1, 1, 2], [2, 3, 3])[1] <= 1        # ties: exact permutation


def test_summary_rows_and_per_protein():
    mda = Run(MDA, SAMPLES)
    finish(mda, lambda t, r, wl: 0.0 if t.type == "zero" else ({532: 0.12 if t.sample[0] == "C" else 0.18, 600: 0.0}[wl]))
    br = Run(BRADFORD, SAMPLES)
    a, b, q = 0.02, 0.95, -0.22
    finish(br, lambda t, r, wl: 0.0 if t.type == "zero" else (a + b * (t.x or 0) + q * (t.x or 0) ** 2
                                                             if t.type == "std" else a + b * 0.6 + q * 0.36))
    s = build([mda, br])
    labels = [c[0] for c in s["columns"]]
    assert labels[:2] == ["МДА", "Білок (Бредфорд)"] and "МДА / білок" in labels
    c1 = next(x for x in s["animals"] if x["code"] == "C1")
    assert c1["values"]["МДА / білок"] == pytest.approx(c1["values"]["МДА"] / c1["values"]["Білок (Бредфорд)"])
    st = next(r for r in s["stats"] if r["label"] == "МДА")
    assert st["groups"]["DOX"]["change"] == pytest.approx(0.5)
    assert st["groups"]["DOX"]["p_mw"] == pytest.approx(0.1, abs=1e-9)
