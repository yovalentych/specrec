"""Front panel of the Mapada V-1200 on screen: the blue LCD and the keys of the real instrument.

    ▲ / ▼     wavelength set point ±1 nm (Shift: ±10)
    SET       type a wavelength
    GOTO λ    move the instrument to the set point
    ZERO      blank (zero) at the set point
    PRINT     receipt of the current tab
    —  —      the two unlabelled keys: STOP (upper) and MEASURE (lower)

The LCD shows the wavelength, A and %T (live while the program is idle and a zero exists),
and the state of the zero, like the instrument's own display.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..v1200 import WL_MAX, WL_MIN

MONO = "Menlo" if "Menlo" in QFontDatabase.families() else "DejaVu Sans Mono"


class Lcd(QWidget):
    """A blue STN LCD: white 'pixels' on a dark blue background with a faint dot grid."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 116)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(330, 120)
        self.lines = ("λ  ---.- nm", "A  -.---", "T  ---.- %", "")
        self.setToolTip("Подвійний клік — ввести довжину хвилі (SET)")

    def show(self, big: str, a: str, t: str, status: str):
        self.lines = (big, a, t, status)
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        # bezel
        p.setPen(QPen(QColor("#5c6f8c"), 2))
        p.setBrush(QColor("#2c3a5c"))
        p.drawRoundedRect(r, 6, 6)
        glass = r.adjusted(7, 7, -7, -7)
        g = QLinearGradient(glass.topLeft(), glass.bottomLeft())
        g.setColorAt(0, QColor("#4c5f95"))
        g.setColorAt(1, QColor("#36467a"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(glass, 3, 3)
        # faint pixel grid
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        x = glass.left()
        while x < glass.right():
            p.drawLine(int(x), int(glass.top()), int(x), int(glass.bottom()))
            x += 3
        y = glass.top()
        while y < glass.bottom():
            p.drawLine(int(glass.left()), int(y), int(glass.right()), int(y))
            y += 3
        # text
        big, a, t, status = self.lines
        ink = QColor("#eef3ff")
        p.setPen(ink)
        f = QFont(MONO)
        f.setPixelSize(26)
        f.setBold(True)
        p.setFont(f)
        p.drawText(glass.adjusted(10, 4, -8, 0), Qt.AlignLeft | Qt.AlignTop, big)
        f.setPixelSize(19)
        p.setFont(f)
        p.drawText(glass.adjusted(10, 40, -8, 0), Qt.AlignLeft | Qt.AlignTop, a)
        p.drawText(glass.adjusted(165, 40, -8, 0), Qt.AlignLeft | Qt.AlignTop, t)
        f.setPixelSize(13)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#c9d6f5"))
        p.drawText(glass.adjusted(10, 0, -8, -6), Qt.AlignLeft | Qt.AlignBottom, status)
        p.end()


def key(text: str, tip: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("devkey")
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    return b


class DevicePanel(QFrame):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("deviceBody")
        self.actual = None          # wavelength of the instrument
        self.reading = None         # (A, T, saturated)
        self.zero_wl = None
        self.status_extra = ""

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(18)
        name = QVBoxLayout()
        self.name = QLabel("V-1200")
        self.name.setObjectName("deviceName")
        sub = QLabel("Spectrophotometer")
        sub.setObjectName("deviceSub")
        name.addStretch()
        name.addWidget(self.name)
        name.addWidget(sub)
        name.addStretch()
        lay.addLayout(name)

        plate = QFrame()
        plate.setObjectName("devicePlate")
        pl = QHBoxLayout(plate)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(14)
        self.lcd = Lcd()
        self.lcd.clicked.connect(self.set_wl)
        pl.addWidget(self.lcd)

        side = QVBoxLayout()
        self.k_stop = key("—", "STOP: зупинити поточну операцію")
        self.k_meas = key("—", "MEASURE: виміряти зразок (фотометрія) на заданій λ")
        side.addWidget(self.k_stop)
        side.addWidget(self.k_meas)
        hs = QLabel("STOP\nMEAS")
        hs.setObjectName("devhint")
        pl.addLayout(side)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.k_up = key("▲", "λ +1 нм (з Shift +10)")
        self.k_down = key("▼", "λ −1 нм (з Shift −10)")
        self.k_set = key("SET", "Ввести довжину хвилі")
        self.k_goto = key("GOTO λ", "Перевести прилад на задану довжину хвилі")
        self.k_print = key("PRINT", "Чек поточної вкладки (термопринтер або картинка)")
        self.k_zero = key("ZERO", "Нуль (бланк) на заданій довжині хвилі")
        for (r, c), k in {(0, 0): self.k_up, (1, 0): self.k_down, (0, 1): self.k_set, (1, 1): self.k_goto,
                          (0, 2): self.k_print, (1, 2): self.k_zero}.items():
            grid.addWidget(k, r, c)
        pl.addLayout(grid)
        lay.addWidget(plate)

        # the sample compartment lid, like on the instrument
        lid = QFrame()
        lid.setObjectName("deviceLid")
        ll = QVBoxLayout(lid)
        ll.setContentsMargins(14, 10, 14, 10)
        t = QLabel("Кюветне відділення")
        t.setObjectName("deviceSub")
        self.cuv = QLabel("")
        self.cuv.setObjectName("deviceSub")
        self.cuv.setWordWrap(True)
        ll.addWidget(t)
        ll.addStretch()
        ll.addWidget(self.cuv)
        lid.setMinimumWidth(200)
        lid.setToolTip("Матеріал і шлях кювети: Прилад → Кювета…")
        lay.addWidget(lid, 1)

        self.k_up.clicked.connect(lambda: self.step(+1))
        self.k_down.clicked.connect(lambda: self.step(-1))
        self.k_set.clicked.connect(self.set_wl)
        self.k_goto.clicked.connect(win.go_wl)
        self.k_zero.clicked.connect(lambda: win.do_blank())
        self.k_print.clicked.connect(win.print_current)
        self.k_stop.clicked.connect(win.stop)
        self.k_meas.clicked.connect(win.measure_key)
        win.wl_spin.valueChanged.connect(lambda _: self.refresh())
        self.refresh()

    # ----- keys
    def step(self, d: int):
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            d *= 10
        self.win.wl_spin.setValue(max(WL_MIN, min(WL_MAX, self.win.wl_spin.value() + d)))

    def set_wl(self):
        v, ok = QInputDialog.getInt(self, "SET", "Довжина хвилі, нм:", self.win.wl_spin.value(), WL_MIN, WL_MAX, 1)
        if ok:
            self.win.wl_spin.setValue(v)

    def set_enabled(self, ok: bool):
        for k in (self.k_goto, self.k_zero, self.k_meas):
            k.setEnabled(ok)
        self.k_stop.setEnabled(self.win.busy)

    # ----- display
    def set_model(self, model: str | None):
        self.name.setText("V-1200" if not model or "5400" in (model or "") or "V-1200" in (model or "")
                          else model)
        self.refresh()

    def set_state(self, wavelength, zero_wl):
        if wavelength is not None and self.actual is not None and abs(wavelength - self.actual) > 0.01:
            self.reading = None                       # an old reading belongs to another λ
        self.actual = wavelength
        self.zero_wl = zero_wl
        self.refresh()

    def set_reading(self, A: float, T: float, saturated: bool = False):
        self.reading = (A, T, saturated)
        self.refresh()

    def refresh(self):
        w = self.win
        if hasattr(w, "cuvette"):
            self.cuv.setText(f"кювета: {w.cuvette.text()}")
        target = w.wl_spin.value()
        if not w.connected:
            self.lcd.show(f"λ {target:5.1f} nm", "A  -.---", "T  ---.- %", "НЕ ПІДКЛЮЧЕНО")
            return
        act = self.actual
        big = f"λ {act:5.1f} nm" if act is not None else f"λ {target:5.1f} nm"
        if act is not None and abs(act - target) > 0.01:
            big += f" →{target}"
        if self.reading:
            A, T, sat = self.reading
            a = "A  > 3" if math.isinf(A) else f"A {('<' if sat else ' ')}{A:6.3f}"
            t = f"T {T:5.1f} %" if math.isfinite(A) else "T   0.0 %"
        else:
            a, t = "A  -.---", "T  ---.- %"
        zero_ok = self.zero_wl is not None and act is not None and abs(self.zero_wl - act) < 0.01
        status = ("ZERO ✓" if zero_ok else "ZERO —  натисніть ZERO") + ("   ДЕМО" if getattr(w, "demo", False) else "")
        if w.busy:
            status = "BUSY …  " + (w.busy_lbl.text()[:28] if w.busy_lbl.text() else "")
        self.lcd.show(big, a, t, status)
