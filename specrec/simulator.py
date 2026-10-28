"""A virtual V-1200: a serial-like object that answers the same console commands.

Used for the demo mode and the tests. The lamp is a halogen bulb (black body ~2900 K)
seen through a silicon photodiode; the cuvette holds one of SAMPLES.
"""
from __future__ import annotations

import math
import random
import threading
import time

# what is in the cuvette: name -> absorbance A(λ nm, t s since the sample was inserted)
SAMPLES = {
    "blank": ("Бланк (вода)", lambda wl, t: 0.0),
    "red": ("Барвник, пік 540 нм", lambda wl, t: 0.85 * math.exp(-((wl - 540) / 38) ** 2)
            + 0.25 * math.exp(-((wl - 380) / 30) ** 2)),
    "blue": ("Мідний комплекс, пік 620 нм", lambda wl, t: 0.45 * math.exp(-((wl - 620) / 70) ** 2)
             + 0.05),
    "kinetic": ("Реакція: A₅₄₀ росте", lambda wl, t: (0.05 + 1.2 * (1 - math.exp(-t / 240)))
                * math.exp(-((wl - 540) / 45) ** 2)),
    "kinetic_slow": ("Повільна реакція", lambda wl, t: (0.10 + 0.9 * (1 - math.exp(-t / 900)))
                     * math.exp(-((wl - 540) / 45) ** 2)),
    "dense": ("Дуже щільний зразок (A > 3)", lambda wl, t: 3.6),
    "bright": ("Світліший за бланк (A = −0,06)", lambda wl, t: -0.06),
}


def lamp(wl: float) -> float:
    """Raw energy at gain 0 with an empty light path (≈ 5200 at 540 nm, like the real one)."""
    def planck(lam_nm):
        lam = lam_nm * 1e-9
        return 1 / (lam ** 5 * (math.exp(1.4388e-2 / (lam * 2900)) - 1))
    si = (wl / 900) if wl < 950 else (950 / 900) * max(0.05, 1 - (wl - 950) / 120)
    si *= 1 / (1 + math.exp(-(wl - 360) / 18))           # glass/optics cut-off in the near UV
    ref = planck(540) * (540 / 900) / (1 + math.exp(-(540 - 360) / 18))
    return 5200 * planck(wl) * si / ref


class FakeSerial:
    DARK = [5, 12, 28, 60, 124, 253, 503, 1008]

    def __init__(self, speed: float = 20.0, model: str = "V-1200 (симулятор)"):
        self.speed = speed           # >1: wavelength moves and blanks run faster than real
        self.model = model
        self.connected = False
        self.wl = 540.0
        self.gain = 2
        self.sample = "blank"
        self.custom: dict[int, float] | None = None   # protocols in demo mode: {wavelength: A}
        self.t0: dict[str, float] = {}       # when each sample was first put in (reactions run on)
        self._out = b""
        self._lock = threading.Lock()
        self.is_open = True

    # --- what the GUI can change in demo mode ---
    def insert(self, key: str, restart: bool = False):
        self.sample = key
        if restart or key not in self.t0:
            self.t0[key] = time.monotonic()

    # --- serial-like API ---
    def reset_input_buffer(self):
        with self._lock:
            self._out = b""

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def read(self, n: int = 1) -> bytes:
        with self._lock:
            chunk, self._out = self._out[:n], self._out[n:]
        if not chunk:
            time.sleep(0.01)
        return chunk

    def write(self, data: bytes):
        for line in data.split(b"\r"):
            if line == b"" and data.endswith(b"\r"):
                continue
            self._handle(line.decode("ascii", "replace").strip(), echo=line)
        return len(data)

    # --- model ---
    def _sleep(self, real_seconds: float):
        time.sleep(real_seconds / self.speed)

    def _signal(self) -> float:
        if self.custom is not None:
            a = self.custom.get(int(round(self.wl)), 0.0)
        else:
            a = SAMPLES[self.sample][1](self.wl, time.monotonic() - self.t0.get(self.sample, time.monotonic()))
        e = lamp(self.wl) * (2 ** self.gain) * 10 ** (-a) + self.DARK[self.gain]
        return e

    def _energy(self) -> int:
        e = self._signal() + random.gauss(0, 3 + 0.0002 * self._signal())
        return int(max(0, min(65535, round(e))))

    def _auto_gain(self):
        for g in range(7, -1, -1):
            self.gain = g
            if self._signal() < 45000:
                return

    def _handle(self, cmd: str, echo: bytes):
        out = echo + b"\r\n"
        parts = cmd.split()
        name = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else None
        known = {"CO", "QU", "SW", "BK", "GE", "GA", "SA", "RD", "GD", "DI", "DO", "WI", "WO", "SL"}
        lines: list[str] | None = []
        if name == "":
            out = b"\r\n>"
            lines = None
        elif name not in known:
            lines = ["Invalid Command."]
        elif name == "CO":
            self.connected = True
            lines = [self.model, f"{self.wl:.1f}", "0", "0", "3", "1", "0"]
        elif not self.connected:
            lines = None
            out = echo + b"\r\n"   # the real instrument stays silent until CO
        elif name == "QU":
            self.connected = False
        elif name == "SW":
            try:
                wl = float(arg)
            except (TypeError, ValueError):
                lines = ["Bad Argument"]
            else:
                self._sleep(1.5 + abs(wl - self.wl) * 0.045)
                self.wl = wl
        elif name == "BK":
            self._sleep(7)
            self._auto_gain()
            e = sum(self._energy() for _ in range(10)) / 10
            lines = [str(self.DARK[self.gain]), str(int(e)), str(self.gain)]
        elif name == "GE":
            try:
                n = int(arg)
                assert n >= 1
            except Exception:
                lines = ["Bad Argument"]
            else:
                time.sleep(0.003 * n)
                lines = [str(self._energy()) for _ in range(n)]
        elif name == "GA":
            lines = [str(self.gain)]
        elif name == "SA":
            try:
                self.gain = max(0, min(7, int(arg) - 1))
            except (TypeError, ValueError):
                lines = ["Bad Argument"]
        elif name in ("RD", "GD"):
            if name == "GD":
                self._sleep(12)
            lines = [str(d) for d in self.DARK]
        if lines is not None:
            out += b"".join(s.encode("gb2312", "replace") + b"\n\r" for s in lines) + b"\n\r>"
        with self._lock:
            self._out += out
