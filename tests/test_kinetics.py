import numpy as np
import pytest

from specrec import storage
from specrec.gui.kinetics import fit_line, load_kinetics


def test_fit_line():
    t = np.array([0, 1, 2, 3.0])
    k, b, r2, t1, t2, n = fit_line(t, 0.1 + 0.05 * t)
    assert k == pytest.approx(0.05) and b == pytest.approx(0.1) and r2 == pytest.approx(1)
    assert fit_line(np.array([1.0]), np.array([0.2])) is None


def test_load_long_format(tmp_path):
    p = tmp_path / "k.csv"
    storage.write_table(p, ["time_s", "position", "sample", "A"],
                        [[0, 2, "A1", 0.1], [5, 3, "B1", 0.2], [30, 2, "A1", 0.15], [35, 3, "B1", float("inf")]],
                        {"wavelength_nm": 540})
    meta, series = load_kinetics(p)
    assert meta["wavelength_nm"] == "540"
    assert [s["name"] for s in series] == ["A1", "B1"]
    assert series[0]["t"] == [0, 0.5] and series[0]["pos"] == 2
    assert np.isnan(series[1]["a"][1])


def test_load_old_two_column(tmp_path):
    p = tmp_path / "old.csv"
    storage.write_table(p, ["time_s", "A"], [[0, 0.1], [60, 0.2]], {"sample": "Кінетика 1"})
    meta, series = load_kinetics(p)
    assert series[0]["name"] == "Кінетика 1" and series[0]["t"] == [0, 1]


def test_load_rejects_other_csv(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_kinetics(p)
