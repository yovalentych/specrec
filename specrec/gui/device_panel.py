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

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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


def wl_rgb(nm: float) -> QColor:
    """Approximate colour of light (Bruton); outside 380–750 nm a neutral grey (UV / near IR)."""
    if nm < 380 or nm > 750:
        return QColor(120, 120, 135) if nm < 380 else QColor(105, 85, 85)
    if nm < 440:
        r, g, b = -(nm - 440) / 60, 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / 50, 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, -(nm - 510) / 20
    elif nm < 580:
        r, g, b = (nm - 510) / 70, 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, -(nm - 645) / 65, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    f = 0.3 + 0.7 * (nm - 380) / 40 if nm < 420 else (0.3 + 0.7 * (750 - nm) / 50 if nm > 700 else 1.0)
    return QColor(int(255 * (r * f) ** 0.8), int(255 * (g * f) ** 0.8), int(255 * (b * f) ** 0.8))


class SpectrumBar(QWidget):
    """The working range of the instrument as a strip of colour; markers for the current and the
    set wavelength; the part the cuvette does not transmit is shaded. Click = set λ."""
    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 56)
        self.setFixedHeight(56)
        self.actual = None
        self.target = 540
        self.cutoff = WL_MIN
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Робочий діапазон приладу: {WL_MIN}–{WL_MAX} нм. Клік — задати довжину хвилі.")

    def set_values(self, actual, target, cutoff):
        self.actual, self.target, self.cutoff = actual, target, cutoff
        self.update()

    def _x(self, nm):
        return 14 + (nm - WL_MIN) / (WL_MAX - WL_MIN) * (self.width() - 28)

    def _nm(self, x):
        return round(WL_MIN + (x - 14) / (self.width() - 28) * (WL_MAX - WL_MIN))

    def mousePressEvent(self, e):
        self.picked.emit(max(WL_MIN, min(WL_MAX, self._nm(e.position().x()))))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        top, h = 22, 14
        for x in range(int(self._x(WL_MIN)), int(self._x(WL_MAX)) + 1):
            p.setPen(wl_rgb(self._nm(x)))
            p.drawLine(x, top, x, top + h)
        if self.cutoff > WL_MIN:                       # what the cuvette does not transmit
            p.fillRect(QRectF(self._x(WL_MIN), top, self._x(self.cutoff) - self._x(WL_MIN), h), QColor(0, 0, 0, 120))
        p.setPen(QPen(QColor("#3e4f66"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(self._x(WL_MIN), top, self._x(WL_MAX) - self._x(WL_MIN), h))
        f = QFont()
        f.setPixelSize(10)
        p.setFont(f)
        for nm in (325, 400, 500, 600, 700, 800, 900, 1000):
            x = self._x(nm)
            p.drawLine(int(x), top + h, int(x), top + h + 3)
            p.drawText(QRectF(x - 22, top + h + 3, 44, 12), Qt.AlignHCenter, str(nm))
        p.drawText(QRectF(self._x(WL_MIN), 0, 60, 12), Qt.AlignLeft, "УФ")
        p.drawText(QRectF(self._x(380), 0, self._x(750) - self._x(380), 12), Qt.AlignHCenter, "видиме світло")
        p.drawText(QRectF(self._x(760), 0, self._x(WL_MAX) - self._x(760), 12), Qt.AlignRight, "ближній ІЧ")

        def tri(nm, fill):
            x = self._x(nm)
            path = [QPointF(x, top + h - 2), QPointF(x - 6, top - 8), QPointF(x + 6, top - 8)]
            p.setPen(QPen(QColor("#26313f"), 1.4))
            p.setBrush(fill)
            p.drawPolygon(path)
        if self.target is not None:
            tri(self.target, Qt.NoBrush)
        if self.actual is not None:
            tri(self.actual, QColor("#ffffff"))
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
        row = QHBoxLayout()
        lab = QLabel("λ:")
        lab.setObjectName("deviceName")
        lab.setStyleSheet("font-size: 22px;")
        row.addWidget(lab)
        spin = win.wl_spin                          # the one working wavelength of the program
        spin.setObjectName("wlInput")
        spin.setToolTip(f"Вписати довжину хвилі ({WL_MIN}–{WL_MAX} нм) і натиснути Enter — прилад перейде на неї")
        spin.setFixedWidth(130)
        spin.lineEdit().returnPressed.connect(win.go_wl)
        row.addWidget(spin)
        self.k_go2 = key("GOTO ⏎", "Перейти на цю довжину хвилі")
        self.k_go2.clicked.connect(win.go_wl)
        row.addWidget(self.k_go2)
        row.addStretch()
        rng = QLabel(f"робочий діапазон\n{WL_MIN}–{WL_MAX} нм")
        rng.setObjectName("deviceSub")
        rng.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(rng)
        ll.addLayout(row)
        self.bar = SpectrumBar()
        self.bar.picked.connect(spin.setValue)
        ll.addWidget(self.bar)
        self.cuv = QLabel("")
        self.cuv.setObjectName("deviceSub")
        self.cuv.setWordWrap(True)
        ll.addWidget(self.cuv)
        lid.setMinimumWidth(330)
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
        for k in (self.k_goto, self.k_zero, self.k_meas, self.k_go2):
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
            cut = w.cuvette.cutoff
            note = f" — нижче ~{cut} нм не пропускає (затінено)" if cut > WL_MIN else ""
            self.cuv.setText(f"кювета: {w.cuvette.text()}{note}")
            self.bar.set_values(self.actual if w.connected else None, w.wl_spin.value(), cut)
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
