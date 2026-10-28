"""Driver for the Mapada V-1200 spectrophotometer (also sold as ЭКРОС ПЭ-5400В).

The USB port is a Silicon Labs CP2102N USB-UART bridge; macOS shows it as
/dev/cu.usbserial-*. The protocol was worked out by experiment (see docs/PROTOCOL.md):
a text console at 19200 baud, 8N1. Every command ends with CR; the instrument echoes it
and finishes every answer with "\\n\\r>".

    CO        connect: model, current wavelength, 5 status numbers
    QU        disconnect (other commands are silent until the next CO)
    SW <nm>   go to wavelength (integer nm, takes up to ~15 s)
    BK        blank with auto gain -> dark, reference energy, gain
    GE <n>    n raw energy readings (16-bit ADC, 65535 = saturated)
    GA        current gain index 0..7 (each step doubles the signal)
    SA <n>    set gain index n-1
    RD        stored dark readings for gain 0..7
    GD        re-measure the dark readings (~12 s)
"""
from __future__ import annotations

import glob
import math
import statistics
import time
from dataclasses import dataclass

BAUD = 19200
SATURATION = 65535
NEAR_SATURATION = 65000   # above this the reading is clipped or no longer linear
WL_MIN, WL_MAX = 325, 1000
N_GAINS = 8
# Auto gain keeps the blank energy in this window (a gain step doubles the signal).
# The top is kept well below 65535 so that a sample brighter than the blank (A < 0, e.g. a
# blank that absorbs a little) still fits: up to +60 % light, A down to about −0.2.
GAIN_LOW, GAIN_HIGH = 18000, 40000


class InstrumentError(Exception):
    pass


@dataclass
class Reference:
    """Blank at one wavelength: dark and reference energy at a fixed gain."""
    wavelength: int
    dark: float
    ref: float
    gain: int


@dataclass
class Reading:
    wavelength: int
    A: float          # absorbance (inf if no light reaches the detector)
    T: float          # transmittance, %
    energy: float
    saturated: bool   # sample brighter than the ADC range: A is below the limit


CP210X_VID = 0x10C4   # Silicon Labs: the USB chip inside the V-1200


@dataclass
class PortInfo:
    device: str
    description: str
    likely: bool          # Silicon Labs CP210x, like the instrument


def list_candidates() -> list[PortInfo]:
    """USB serial ports that could be the instrument, the most likely first.
    Works on macOS (/dev/cu.usbserial-*), Linux (/dev/ttyUSB*) and Windows (COMn)."""
    found: dict[str, PortInfo] = {}
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            dev = p.device
            if dev.startswith("/dev/tty.") or "Bluetooth" in dev:
                continue                      # macOS: use the cu.* twin; skip Bluetooth
            if p.vid is None and "usbserial" not in dev and "SLAB" not in dev:
                continue                      # not a USB device
            desc = p.description if p.description and p.description != "n/a" else (p.product or "")
            found[dev] = PortInfo(dev, desc, p.vid == CP210X_VID)
    except Exception:
        pass
    for pat in ("/dev/cu.usbserial*", "/dev/cu.SLAB_USBtoUART*", "/dev/ttyUSB*"):
        for dev in sorted(glob.glob(pat)):
            found.setdefault(dev, PortInfo(dev, "USB serial", "SLAB" in dev))
    return sorted(found.values(), key=lambda p: (not p.likely, p.device))


def find_ports() -> list[str]:
    return [p.device for p in list_candidates()]


def absorbance(energy: float, ref: Reference) -> tuple[float, float]:
    span = ref.ref - ref.dark
    t = (energy - ref.dark) / span if span > 0 else float("nan")
    a = -math.log10(t) if t > 0 else float("inf")
    return a, t * 100.0


class V1200:
    def __init__(self, port: str | None = None, serial_obj=None):
        """serial_obj: an already open serial-like object (the simulator passes one)."""
        self.port = port
        self.ser = serial_obj
        self.model = ""
        self.wavelength: float | None = None
        self.dark_table: list[int] = []
        self.blank_ref: Reference | None = None

    # ---------- console ----------
    def open(self):
        if self.ser is None:
            import serial
            if not self.port:
                ports = find_ports()
                if not ports:
                    raise InstrumentError("Прилад не знайдено. Перевірте USB-кабель і чи ввімкнено прилад.")
                self.port = ports[0]
            try:
                self.ser = serial.Serial(self.port, BAUD, timeout=0.1)
            except serial.SerialException as e:
                if "ermission" in str(e):
                    raise InstrumentError(
                        f"Немає доступу до порту {self.port}. На Linux додайте користувача до групи "
                        "dialout:  sudo usermod -aG dialout $USER  і перезайдіть у систему.") from e
                raise InstrumentError(f"Не вдалося відкрити {self.port}: {e}") from e
            time.sleep(0.2)
        self.ser.reset_input_buffer()
        self.ser.write(b"\r")
        try:
            self._read_until_prompt(2.0, 0, end=b">")
        except InstrumentError:
            self.ser.close()
            self.ser = None
            raise InstrumentError(f"Прилад на {self.port} не відповідає. Він увімкнений?")

    def close(self):
        if self.ser is not None:
            try:
                self.cmd("QU", timeout=2)
            except Exception:
                pass
            try:
                self.ser.close()
            finally:
                self.ser = None

    @property
    def is_open(self) -> bool:
        return self.ser is not None

    def _read_until_prompt(self, timeout: float, echo_len: int, end: bytes = b"\n\r>") -> bytes:
        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = self.ser.read(4096)
            if chunk:
                buf += chunk
                if len(buf) > echo_len and buf.endswith(end):
                    return buf
        raise InstrumentError(f"Прилад не відповів за {timeout:.0f} с")

    def cmd(self, command: str, timeout: float = 10.0) -> list[str]:
        """Send one command, return the answer lines (echo and prompt removed)."""
        if self.ser is None:
            raise InstrumentError("Немає з'єднання з приладом")
        self.ser.reset_input_buffer()
        self.ser.write(command.encode("ascii") + b"\r")
        self.ser.flush()
        raw = self._read_until_prompt(timeout, len(command) + 2)
        body = raw.split(b"\r\n", 1)[1] if b"\r\n" in raw else raw
        lines = [ln.strip() for ln in body.split(b"\n\r")]
        text = [ln.decode("gb2312", "replace") for ln in lines if ln and ln != b">"]
        if text and text[0] in ("Invalid Command.", "Bad Argument"):
            raise InstrumentError(f"Прилад відхилив команду {command!r}: {text[0]}")
        return text

    # ---------- instrument ----------
    def connect(self) -> dict:
        """Open the port and check that a V-1200 answers. On any failure the port is closed again,
        so a wrong device (another USB serial gadget) is left alone."""
        try:
            if self.ser is None:
                self.open()
            info = self.cmd("CO", timeout=3)
            try:
                self.model = info[0]
                self.wavelength = float(info[1])
            except (IndexError, ValueError):
                raise InstrumentError(f"Пристрій на {self.port} не схожий на спектрофотометр V-1200")
            self.dark_table = [int(x) for x in self.cmd("RD")]
        except Exception:
            if self.ser is not None:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
            raise
        return {"model": self.model, "wavelength": self.wavelength, "port": self.port}

    def remeasure_dark(self) -> list[int]:
        self.dark_table = [int(x) for x in self.cmd("GD", timeout=40)]
        return self.dark_table

    def set_wavelength(self, wl: float) -> int:
        wl = int(round(float(wl)))
        if not WL_MIN <= wl <= WL_MAX:
            raise InstrumentError(f"Довжина хвилі має бути в межах {WL_MIN}–{WL_MAX} нм")
        if self.wavelength is None or abs(self.wavelength - wl) > 0.01:
            # time grows with the distance: ~0.05 s/nm plus overhead
            dist = abs((self.wavelength or 650) - wl)
            self.cmd(f"SW {wl}", timeout=20 + dist * 0.1)
            self.wavelength = float(wl)
        return wl

    def gain(self) -> int:
        return int(self.cmd("GA")[0])

    def set_gain(self, g: int):
        self.cmd(f"SA {int(g) + 1}")

    def energy(self, n: int = 10) -> tuple[float, int]:
        """Mean of n raw readings and their maximum (to detect saturation)."""
        vals = [int(x) for x in self.cmd(f"GE {int(n)}", timeout=5 + n * 0.05)]
        if not vals:
            raise InstrumentError("Прилад не повернув відліків")
        return statistics.fmean(vals), max(vals)

    def dark_for(self, g: int) -> float:
        return float(self.dark_table[g]) if g < len(self.dark_table) else 0.0

    def blank(self) -> Reference:
        """The instrument's own blank (BK): also zeroes the reading on its display."""
        d, r, g = (int(x) for x in self.cmd("BK", timeout=40)[:3])
        self.blank_ref = Reference(int(self.wavelength or 0), d, r, g)
        return self.blank_ref

    def quick_reference(self, n: int = 10, start_gain: int | None = None) -> Reference:
        """Blank without BK (faster, for scans): choose the gain ourselves."""
        g = self.gain() if start_gain is None else start_gain
        for _ in range(N_GAINS + 1):
            self.set_gain(g)
            e, emax = self.energy(2)
            if emax >= GAIN_HIGH and g > 0:
                g -= 1
            elif e < GAIN_LOW and g < N_GAINS - 1 and e * 2 < GAIN_HIGH:
                g += 1
            else:
                break
        e, _ = self.energy(n)
        return Reference(int(self.wavelength or 0), self.dark_for(g), e, g)

    def read(self, ref: Reference, n: int = 10) -> Reading:
        """Sample reading at the current wavelength against a reference."""
        self.set_gain(ref.gain)
        e, emax = self.energy(n)
        a, t = absorbance(e, ref)
        return Reading(ref.wavelength, a, t, e, emax >= NEAR_SATURATION)
