import numpy as np
import pytest

from specrec.analysis import analyze
from specrec.gui.kinetics import parse_markers, parse_reminders

rng = np.random.default_rng(0)
T = np.arange(0, 10.01, 0.5)


def noisy(y, sd=0.003):
    return y + rng.normal(0, sd, len(y))


def test_linear():
    r = analyze(T, noisy(0.2 + 0.03 * T))
    assert r.kind == "linear" and r.v0 == pytest.approx(0.03, abs=0.002)
    assert r.lin_range == (0, 10)


def test_plateau_first_order():
    r = analyze(T, noisy(0.1 + 1.0 * (1 - np.exp(-T / 3))))
    assert r.kind == "plateau"
    assert r.a_inf == pytest.approx(1.1, abs=0.02)
    assert r.k == pytest.approx(1 / 3, rel=0.05)
    assert r.v0 == pytest.approx(1 / 3, rel=0.08)
    assert r.reached == pytest.approx(1 - np.exp(-10 / 3), abs=0.02)


def test_falling_plateau():
    r = analyze(T, noisy(1.2 - 0.8 * (1 - np.exp(-T / 3))))
    assert r.kind == "plateau" and r.v0 < 0 and r.a_inf == pytest.approx(0.4, abs=0.02)


def test_lag_phase():
    r = analyze(T, noisy(0.1 + 1 / (1 + np.exp(-(T - 6)))))
    assert r.kind == "sigmoid" and r.lag == pytest.approx(4, abs=0.7) and r.t_mid == pytest.approx(6, abs=0.3)


def test_flat():
    assert analyze(T, noisy(0.5 + 0 * T, 0.001)).kind == "flat"


def test_too_few():
    assert analyze([0, 1, 2], [0.1, 0.2, 0.3]).kind == "too_few"


def test_reminders_and_markers():
    rem = parse_reminders("5 — додати інгібітор\n2:30 перемішати\n8,5 хв: стоп\n\nабв")
    assert rem == [(2.5, "перемішати"), (5.0, "додати інгібітор"), (8.5, "стоп")]
    assert parse_markers("1.50 хв: додав H2O2; 3.00 хв: позначка 2") == [(1.5, "додав H2O2"), (3.0, "позначка 2")]
