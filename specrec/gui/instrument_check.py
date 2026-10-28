"""Instrument check: noise and lamp drift, control filters (photometric accuracy) and wavelength
accuracy with a filter of known peaks. Results go to SpecRec_data/instrument_checks.csv.

Limits are those of the instrument's specification (V-1200 manual):
  stability 0.002 A/h at 500 nm; photometric accuracy ±0.5 %T or ±0.005 A at 1 A;
  wavelength accuracy ±2 nm.
"""
from __future__ import annotations

import datetime as dt
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import storage
from ..v1200 import InstrumentError, absorbance
from .common import hint, make_plot

LOG = "instrument_checks.csv"
LOG_HEAD = ["time", "test", "wavelength_nm", "value", "limit", "result", "details"]


def log(test, wl, value, limit, ok, details=""):
    storage.append_row(storage.paths.data_root() / LOG, LOG_HEAD,
                       [dt.datetime.now().isoformat(timespec="seconds"), test, wl, value, limit,
                        "OK" if ok else "НЕ ВІДПОВІДАЄ", details])


class DriftTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(hint("Прогрів і стабільність. Порожній тримач (або кювета з водою), кришка закрита. "
                           "Програма ставить нуль і стежить, як «пливе» A. Паспорт: ≤ 0,002 A/год на 500 нм. "
                           "Прилад варто прогріти ~30 хв перед роботою — тест покаже, чи він уже стабільний."))
        f = QFormLayout()
        self.wl = QSpinBox()
        self.wl.setRange(325, 1000)
        self.wl.setValue(500)
        self.wl.setSuffix(" нм")
        self.minutes = QDoubleSpinBox()
        self.minutes.setRange(1, 120)
        self.minutes.setValue(10)
        self.minutes.setSuffix(" хв")
        f.addRow("Довжина хвилі:", self.wl)
        f.addRow("Тривалість:", self.minutes)
        lay.addLayout(f)
        self.b = QPushButton("Почати")
        self.b.setObjectName("primary")
        self.b.clicked.connect(self.start)
        lay.addWidget(self.b)
        self.plot = make_plot(win.theme, "Час, хв", "A")
        self.curve = self.plot.plot([], [], pen=pg.mkPen(win.theme.channels[0], width=2), symbol="o", symbolSize=4)
        lay.addWidget(self.plot, 1)
        self.res = QLabel("")
        self.res.setWordWrap(True)
        lay.addWidget(self.res)

    def start(self):
        wl, total = self.wl.value(), self.minutes.value() * 60
        self.t, self.a = [], []

        def task(dev, job):
            dev.set_wavelength(wl)
            ref = dev.quick_reference(20)
            fast = [absorbance(dev.energy(1)[0], ref)[0] for _ in range(30)]      # noise: 30 single readings
            t0 = time.monotonic()
            while not job.stopped and time.monotonic() - t0 < total:
                r = dev.read(ref, 10)
                job.progress((time.monotonic() - t0, r.A))
                job.sleep(5)
            return fast

        def prog(d):
            t, a = d
            self.t.append(t / 60)
            self.a.append(a)
            self.curve.setData(self.t, self.a)
            self.win.set_progress(int(t), int(total), f"Дрейф: {t:.0f} с, A = {a:+.4f}")

        def done(fast):
            noise = float(np.std(fast, ddof=1)) if fast else math.nan
            if len(self.t) < 3:
                self.res.setText(f"Шум (СКВ одного відліку): {noise:.4f} A. Замало точок для дрейфу.")
                return
            k = np.polyfit(self.t, self.a, 1)[0] * 60              # A per hour
            ok = abs(k) <= 0.002
            self.res.setText(f"<b>Дрейф: {k:+.4f} A/год</b> (норма ≤ 0,002) — {'OK' if ok else 'більше норми: прогрійте довше'}"
                             f"<br>Шум одного відліку: ±{noise:.4f} A · розмах за тест {np.ptp(self.a):.4f} A")
            self.res.setTextFormat(Qt.RichText)
            log("дрейф", wl, round(k, 5), 0.002, ok, f"{self.t[-1]:.1f} хв, шум {noise:.5f}")
            log("шум", wl, round(noise, 5), "", True, "СКВ 30 одиночних відліків")

        self.win.run(task, done, prog, label="Перевірка дрейфу…")


class FilterTab(QWidget):
    COLS = ["λ, нм", "A за паспортом", "Виміряно A", "Різниця", "Допуск", "Висновок"]

    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(hint("Фотометрична точність за контрольними світлофільтрами (у комплекті приладу або "
                           "ЕКРОС). Впишіть паспортні A фільтра на кількох довжинах хвиль. Для кожного рядка: "
                           "нуль на порожньому тримачі → вставте фільтр → вимір. "
                           "Допуск приладу: ±0,005 A при A ≈ 1 (або ±0,5 %T)."))
        self.table = QTableWidget(4, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, wl in enumerate((440, 540, 590, 670)):
            self.table.setItem(r, 0, QTableWidgetItem(str(wl)))
            self.table.setItem(r, 1, QTableWidgetItem(""))
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        b = QPushButton("Виміряти вибраний рядок")
        b.setObjectName("primary")
        b.clicked.connect(self.measure)
        row.addWidget(b)
        b = QPushButton("+ рядок")
        b.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        row.addWidget(b)
        lay.addLayout(row)

    def measure(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or [0]
        r = rows[0]
        try:
            wl = int(float(self.table.item(r, 0).text()))
            cert = float(self.table.item(r, 1).text().replace(",", "."))
        except (AttributeError, ValueError):
            QMessageBox.information(self, "Фільтр", "Впишіть λ і паспортне A фільтра в цьому рядку.")
            return
        if QMessageBox.question(self, "Нуль", f"Порожній тримач (без фільтра) на {wl} нм — поставити нуль?") != QMessageBox.Yes:
            return
        holder = {}

        def zero(dev, job):
            dev.set_wavelength(wl)
            holder["ref"] = dev.quick_reference(20)

        def after_zero(_):
            if QMessageBox.question(self, "Фільтр", "Вставте світлофільтр і натисніть «Yes».") != QMessageBox.Yes:
                return

            def read(dev, job):
                dev.set_wavelength(wl)
                return dev.read(holder["ref"], 20)
            self.win.run(read, lambda res: self.show(r, wl, cert, res.A), label="Фільтр…")

        self.win.run(zero, after_zero, label=f"Нуль на {wl} нм…")

    def show(self, r, wl, cert, a):
        diff = a - cert
        # the passport: ±0.005 A at 1 A; above 1 A the tolerance grows in proportion (±0.5 %)
        tol = 0.005 * max(cert, 1.0)
        ok = abs(diff) <= tol
        for c, v in enumerate([f"{a:.4f}", f"{diff:+.4f}", f"±{tol:.4f}", "OK" if ok else "поза допуском"], 2):
            self.table.setItem(r, c, QTableWidgetItem(v))
        log("світлофільтр", wl, round(a, 5), round(tol, 5), ok, f"паспорт {cert}")


class WavelengthTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(hint("Точність довжини хвилі: фільтр із відомими смугами (гольмієвий, дидимовий) або "
                           "розчин із відомим максимумом. Програма сканує ділянку з кроком 1 нм "
                           "(нуль на порожньому тримачі), знаходить максимум поглинання і порівнює з "
                           "паспортним. Допуск приладу ±2 нм."))
        f = QFormLayout()
        self.peak = QDoubleSpinBox()
        self.peak.setRange(330, 1000)
        self.peak.setValue(536.0)
        self.peak.setSuffix(" нм")
        self.half = QSpinBox()
        self.half.setRange(5, 50)
        self.half.setValue(15)
        self.half.setSuffix(" нм")
        f.addRow("Паспортний максимум:", self.peak)
        f.addRow("Шукати в межах ±:", self.half)
        lay.addLayout(f)
        b = QPushButton("Почати")
        b.setObjectName("primary")
        b.clicked.connect(self.start)
        lay.addWidget(b)
        self.plot = make_plot(win.theme, "Довжина хвилі, нм", "A")
        self.curve = self.plot.plot([], [], pen=pg.mkPen(win.theme.channels[0], width=2), symbol="o", symbolSize=4)
        lay.addWidget(self.plot, 1)
        self.res = QLabel("")
        lay.addWidget(self.res)

    def start(self):
        c, h = self.peak.value(), self.half.value()
        wls = list(range(int(c - h), int(c + h) + 1))
        refs = {}
        if QMessageBox.question(self, "Нуль", "Порожній тримач — записати нуль по всій ділянці?") != QMessageBox.Yes:
            return

        def zero(dev, job):
            g = None
            for i, wl in enumerate(wls):
                if job.stopped:
                    return
                dev.set_wavelength(wl)
                refs[wl] = dev.quick_reference(5, start_gain=g)
                g = refs[wl].gain
                job.progress((i + 1, len(wls)))

        def after(_):
            if len(refs) < len(wls) or QMessageBox.question(self, "Фільтр", "Вставте фільтр і натисніть «Yes».") != QMessageBox.Yes:
                return
            self.x, self.y = [], []

            def scan(dev, job):
                for i, wl in enumerate(wls):
                    if job.stopped:
                        return
                    dev.set_wavelength(wl)
                    job.progress((i + 1, len(wls), wl, dev.read(refs[wl], 5).A))

            def prog(d):
                i, n, wl, a = d
                self.x.append(wl)
                self.y.append(a)
                self.curve.setData(self.x, self.y)
                self.win.set_progress(i, n, f"Скан фільтра: {wl} нм")

            self.win.run(scan, self.result, prog, label="Скан фільтра…")

        self.win.run(zero, after, lambda d: self.win.set_progress(d[0], d[1], "Нуль по ділянці…"),
                     label="Нуль по ділянці…")

    def result(self, _):
        if len(self.x) < 5:
            return
        x, y = np.asarray(self.x, float), np.asarray(self.y, float)
        k = int(np.nanargmax(y))
        # parabola through the top 5 points for sub-nm position
        lo, hi = max(0, k - 2), min(len(x), k + 3)
        q = np.polyfit(x[lo:hi], y[lo:hi], 2)
        peak = -q[1] / (2 * q[0]) if q[0] < 0 else x[k]
        dev = peak - self.peak.value()
        ok = abs(dev) <= 2
        self.res.setText(f"Максимум {peak:.1f} нм, паспорт {self.peak.value():.1f} нм → {dev:+.1f} нм "
                         f"(допуск ±2) — {'OK' if ok else 'поза допуском'}")
        log("довжина хвилі", round(self.peak.value(), 1), round(peak, 2), 2, ok, f"відхилення {dev:+.2f} нм")


class InstrumentCheckDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("Перевірка приладу")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(DriftTab(win), "Прогрів і дрейф")
        tabs.addTab(FilterTab(win), "Світлофільтри (точність A)")
        tabs.addTab(WavelengthTab(win), "Довжина хвилі")
        lay.addWidget(tabs)
        row = QHBoxLayout()
        row.addWidget(hint(f"Усі результати дописуються в SpecRec_data/{LOG}"))
        b = QPushButton("Закрити")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)
        if not win.connected:
            QMessageBox.information(self, "Прилад", "Підключіть прилад (або демо-режим), щоб виконати перевірку.")
