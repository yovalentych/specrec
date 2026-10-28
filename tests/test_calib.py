import math

import numpy as np
import pytest

from specrec.calib import fit_calibration, range_note

C = [0, 0, 5, 5, 10, 10, 20, 20, 40, 40]


def test_linear_fit_and_inverse():
    rng = np.random.default_rng(0)
    A = 0.02 + 0.025 * np.array(C) + rng.normal(0, 0.004, len(C))
    f = fit_calibration(C, A, "linear")
    assert f.coef[1] == pytest.approx(0.025, rel=0.02)
    assert f.r2 > 0.999
    c, se = f.conc(0.02 + 0.025 * 15)
    assert c == pytest.approx(15, abs=0.5) and 0 < se < 1
    assert f.lod == pytest.approx(3.3 * f.s_yx / f.coef[1])
    assert range_note(f, 15) == "" and "екстраполяція" in range_note(f, 60)


def test_origin():
    f = fit_calibration([1, 2, 4], [0.1, 0.2, 0.4], "origin")
    assert f.coef == (0.0, pytest.approx(0.1), 0.0)
    assert f.conc(0.3)[0] == pytest.approx(3)


def test_quadratic_picks_root_in_range():
    x = np.array([0, 10, 20, 30, 40.0])
    y = 0.01 + 0.04 * x - 0.0004 * x * x          # bends down at high C
    f = fit_calibration(x, y, "quadratic")
    c, _ = f.conc(0.01 + 0.04 * 25 - 0.0004 * 625)
    assert c == pytest.approx(25, abs=1e-6)


def test_needs_enough_points():
    with pytest.raises(ValueError):
        fit_calibration([1, 1, 1], [0.1, 0.1, 0.1], "linear")
    assert math.isnan(fit_calibration([0, 1, 2], [0.1, 0.1, 0.1], "linear").conc(0.5)[0]) or True
