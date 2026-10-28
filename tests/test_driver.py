import math

import pytest

from specrec.simulator import FakeSerial
from specrec.v1200 import InstrumentError, Reference, V1200, absorbance


@pytest.fixture
def dev():
    fs = FakeSerial(speed=1000)
    d = V1200("sim", fs)
    d.connect()
    d.sim = fs
    return d


def test_connect(dev):
    assert dev.wavelength == 540.0
    assert len(dev.dark_table) == 8


def test_blank_and_read(dev):
    ref = dev.blank()
    assert ref.wavelength == 540 and ref.ref > ref.dark
    dev.sim.insert("red")
    r = dev.read(ref, 10)
    assert r.A == pytest.approx(0.85, abs=0.01)
    assert r.T == pytest.approx(100 * 10 ** -0.85, rel=0.03)


def test_quick_reference_matches_blank(dev):
    for wl in (400, 540, 700):
        dev.set_wavelength(wl)
        q = dev.quick_reference(5)
        assert 18000 <= q.ref < 40000
        dev.sim.insert("blue")
        assert dev.read(q, 5).A == pytest.approx(dev.sim and
                                                 0.45 * math.exp(-((wl - 620) / 70) ** 2) + 0.05, abs=0.01)
        dev.sim.insert("blank")


def test_sample_brighter_than_blank_is_not_clipped(dev):
    # like a blank that absorbs a little: A = -0.06 must come out right, not clipped at the ADC top
    for wl in (400, 415, 535, 700):
        dev.set_wavelength(wl)
        q = dev.quick_reference(5)
        dev.sim.insert("bright")
        r = dev.read(q, 5)
        assert not r.saturated
        assert r.A == pytest.approx(-0.06, abs=0.003)
        dev.sim.insert("blank")


def test_wavelength_limits(dev):
    with pytest.raises(InstrumentError):
        dev.set_wavelength(200)


def test_rejected_command(dev):
    with pytest.raises(InstrumentError):
        dev.cmd("XX")


def test_absorbance_edge_cases():
    ref = Reference(540, 60, 30060, 3)
    assert absorbance(3060, ref)[0] == pytest.approx(1.0)
    assert math.isinf(absorbance(50, ref)[0])
