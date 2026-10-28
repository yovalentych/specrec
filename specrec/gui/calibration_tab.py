"""Calibration tab: standards (measured or typed in, with replicates), a model, the equation
with R², LOD and LOQ, the plot, and concentrations of unknown samples with their error and a
range check. A calibration can be saved and loaded again."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import storage
from ..calib import MODELS, fit_calibration, range_note
from ..v1200 import InstrumentError
from .common import hint, make_plot, section

MAX_REP = 3


def _num(text: str):
    try:
        return float(str(text).replace(",", ".").strip())
    except ValueError:
        return None


class CalibrationTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.fit = None
        self._busy_fill = False

        # ---- left: standards
        left = QVBoxLayout()
        left.addWidget(section("Стандарти"))
        f = QFormLayout()
        self.unit = QLineEdit(win.settings.value("calib/unit", "мкМ"))
        self.unit.editingFinished.connect(self.recompute)
        self.levels = QLineEdit(win.settings.value("calib/levels", "0, 5, 10, 20, 40"))
        self.levels.setToolTip("Концентрації стандартів через кому або крапку з комою")
        self.model = QComboBox()
        for k, v in MODELS.items():
            self.model.addItem(v, k)
        self.model.currentIndexChanged.connect(self.recompute)
        self.n = QSpinBox()
        self.n.setRange(1, 50)
        self.n.setValue(10)
        f.addRow("Одиниці:", self.unit)
        f.addRow("Концентрації:", self.levels)
        f.addRow("Модель:", self.model)
        f.addRow("Усереднення:", self.n)
        left.addLayout(f)
        b = QPushButton("Створити рядки стандартів")
        b.clicked.connect(self.make_rows)
        left.addWidget(b)

        self.std = QTableWidget(0, 2 + MAX_REP + 2)
        self.std.setHorizontalHeaderLabels(["✓", "C"] + [f"A{i}" for i in range(1, MAX_REP + 1)] + ["Середнє", "SD"])
        self.std.verticalHeader().setVisible(False)
        self.std.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.std.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.std.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.std.itemChanged.connect(lambda _: self.recompute())
        self.std.setToolTip("A можна вписати вручну. Зніміть ✓, щоб не враховувати стандарт (викид).")
        left.addWidget(self.std, 1)
        row = QHBoxLayout()
        self.b_meas = QPushButton("Виміряти вибраний")
        self.b_meas.setObjectName("primary")
        self.b_meas.setToolTip("Вимір на довжині хвилі з панелі вгорі проти бланку (кнопка «Бланк»); "
                               "заповнює наступний вільний повтор")
        self.b_meas.clicked.connect(self.measure_std)
        row.addWidget(self.b_meas)
        b = QPushButton("+")
        b.setFixedWidth(30)
        b.clicked.connect(lambda: self.add_row(None))
        row.addWidget(b)
        b = QPushButton("−")
        b.setFixedWidth(30)
        b.clicked.connect(self.del_rows)
        row.addWidget(b)
        left.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("Зберегти калібрування…")
        b.clicked.connect(self.save)
        row.addWidget(b)
        b = QPushButton("Відкрити…")
        b.clicked.connect(self.load)
        row.addWidget(b)
        left.addLayout(row)
        left.addWidget(hint("1. Бланк угорі на робочій λ.  2. Стандарти: виберіть рядок, поставте кювету, "
                            "«Виміряти вибраний» (або Пробіл).  3. Зразки — праворуч."))
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(400)

        # ---- right: plot, equation, samples
        right = QVBoxLayout()
        self.plot = make_plot(win.theme, "Концентрація", "A")
        self.plot.setMinimumHeight(260)
        right.addWidget(self.plot, 3)
        self.eq = QLabel("Додайте щонайменше 3 стандарти.")
        self.eq.setTextFormat(Qt.RichText)
        self.eq.setWordWrap(True)
        self.eq.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.eq)
        right.addWidget(section("Зразки"))
        sr = QHBoxLayout()
        self.s_name = QLineEdit("Зразок 1")
        self.s_dil = QDoubleSpinBox()
        self.s_dil.setRange(0.001, 100000)
        self.s_dil.setValue(1)
        self.s_dil.setPrefix("розв. × ")
        self.b_smeas = QPushButton("Виміряти зразок")
        self.b_smeas.setObjectName("primary")
        self.b_smeas.clicked.connect(self.measure_sample)
        self.s_manual = QLineEdit()
        self.s_manual.setPlaceholderText("або A вручну ⏎")
        self.s_manual.setFixedWidth(120)
        self.s_manual.returnPressed.connect(self.manual_sample)
        sr.addWidget(self.s_name, 1)
        sr.addWidget(self.s_dil)
        sr.addWidget(self.b_smeas)
        sr.addWidget(self.s_manual)
        right.addLayout(sr)
        self.smp = QTableWidget(0, 6)
        self.smp.setHorizontalHeaderLabels(["Зразок", "A", "C", "± SE", "C × розв.", "Примітка"])
        self.smp.verticalHeader().setVisible(False)
        self.smp.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.smp.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right.addWidget(self.smp, 2)
        row = QHBoxLayout()
        b = QPushButton("Видалити зразок")
        b.clicked.connect(lambda: [self.smp.removeRow(r) for r in sorted(
            {i.row() for i in self.smp.selectedIndexes()}, reverse=True)])
        row.addWidget(b)
        row.addStretch()
        b = QPushButton("🖨 Чек")
        b.clicked.connect(self.receipt)
        row.addWidget(b)
        b = QPushButton("Експорт у Excel…")
        b.clicked.connect(self.export)
        row.addWidget(b)
        right.addLayout(row)
        rw = QWidget()
        rw.setLayout(right)

        lay = QHBoxLayout(self)
        lay.addWidget(lw)
        lay.addWidget(rw, 1)
        self.make_rows()

    # ----- standards table
    def set_enabled(self, ok: bool):
        self.b_meas.setEnabled(ok)
        self.b_smeas.setEnabled(ok)

    def add_row(self, c, values=(), use=True):
        self._busy_fill = True
        r = self.std.rowCount()
        self.std.insertRow(r)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        chk.setCheckState(Qt.Checked if use else Qt.Unchecked)
        self.std.setItem(r, 0, chk)
        self.std.setItem(r, 1, QTableWidgetItem("" if c is None else f"{c:g}"))
        for j in range(MAX_REP):
            v = values[j] if j < len(values) else None
            self.std.setItem(r, 2 + j, QTableWidgetItem("" if v is None else f"{v:.4f}"))
        for j in (2 + MAX_REP, 3 + MAX_REP):
            it = QTableWidgetItem("")
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.std.setItem(r, j, it)
        self._busy_fill = False

    def make_rows(self):
        vals = [_num(x) for x in self.levels.text().replace(";", ",").split(",")]
        vals = [v for v in vals if v is not None]
        if not vals:
            return
        if any(self.points()[1]) and QMessageBox.question(
                self, "Стандарти", "Замінити наявні стандарти (виміряні значення зникнуть)?") != QMessageBox.Yes:
            return
        self.win.settings.setValue("calib/levels", self.levels.text())
        self.std.setRowCount(0)
        for v in vals:
            self.add_row(v)
        self.std.selectRow(0)
        self.recompute()

    def del_rows(self):
        for r in sorted({i.row() for i in self.std.selectedIndexes()}, reverse=True):
            self.std.removeRow(r)
        self.recompute()

    def rows(self):
        out = []
        for r in range(self.std.rowCount()):
            c = _num(self.std.item(r, 1).text()) if self.std.item(r, 1) else None
            a = [_num(self.std.item(r, 2 + j).text()) for j in range(MAX_REP) if self.std.item(r, 2 + j)]
            a = [x for x in a if x is not None]
            use = self.std.item(r, 0).checkState() == Qt.Checked if self.std.item(r, 0) else True
            out.append((r, c, a, use))
        return out

    def points(self):
        xs, ys = [], []
        for _, c, a, use in self.rows():
            if use and c is not None:
                for v in a:
                    xs.append(c)
                    ys.append(v)
        return xs, ys

    # ----- measuring
    def _measure(self, on_done):
        wl = self.win.target_wl()
        n = self.n.value()

        def task(dev, job):
            dev.set_wavelength(wl)
            ref = dev.blank_ref
            if ref is None or ref.wavelength != wl:
                raise InstrumentError(f"Немає бланку на {wl} нм. Поставте кювету з бланком і натисніть «Бланк».")
            return dev.read(ref, n)
        self.win.run(task, on_done, label=f"Вимір на {wl} нм…")

    def measure_std(self):
        rows = sorted({i.row() for i in self.std.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Стандарт", "Виберіть рядок стандарту.")
            return
        r = rows[0]

        def done(res):
            if math.isinf(res.A):
                self.win.message("A > 3 — стандарт задуже концентрований", warn=True)
                return
            for j in range(MAX_REP):
                it = self.std.item(r, 2 + j)
                if not it.text().strip():
                    it.setText(f"{res.A:.4f}")
                    break
            else:
                self.win.message("Усі повтори цього стандарту вже заповнені — очистіть клітинку для нового", warn=True)
            if r + 1 < self.std.rowCount():      # next standard (for replicates select the row again)
                self.std.selectRow(r + 1)
        self._measure(done)

    def measure_sample(self):
        name = self.s_name.text().strip() or "Зразок"
        self._measure(lambda res: self.add_sample(name, res.A, self.s_dil.value()))

    def manual_sample(self):
        a = _num(self.s_manual.text())
        if a is None:
            return
        self.add_sample(self.s_name.text().strip() or "Зразок", a, self.s_dil.value())
        self.s_manual.clear()

    def add_sample(self, name, A, dil):
        r = self.smp.rowCount()
        self.smp.insertRow(r)
        it = QTableWidgetItem(name)
        it.setData(Qt.UserRole, (A, dil))
        self.smp.setItem(r, 0, it)
        for c in range(1, 6):
            self.smp.setItem(r, c, QTableWidgetItem(""))
        parts = name.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            self.s_name.setText(f"{parts[0]} {int(parts[1]) + 1}")
        self.update_samples()
        storage.append_row(storage.day_dir() / "calibration_samples.csv",
                           ["time", "sample", "A", "dilution", "C", "unit", "equation"],
                           [dt.datetime.now().isoformat(timespec="seconds"), name, A, dil,
                            self.conc(A)[0] * dil if self.fit else None, self.unit.text(),
                            self.fit.equation() if self.fit else ""])

    def conc(self, A):
        if not self.fit:
            return float("nan"), None
        return self.fit.conc(A)

    # ----- results
    def recompute(self):
        if self._busy_fill:
            return
        self._busy_fill = True
        for r, c, a, use in self.rows():
            m = np.mean(a) if a else None
            sd = np.std(a, ddof=1) if len(a) > 1 else None
            self.std.item(r, 2 + MAX_REP).setText("" if m is None else f"{m:.4f}")
            self.std.item(r, 3 + MAX_REP).setText("" if sd is None else f"{sd:.4f}")
        self._busy_fill = False
        self.win.settings.setValue("calib/unit", self.unit.text())
        xs, ys = self.points()
        unit = self.unit.text().strip()
        try:
            self.fit = fit_calibration(xs, ys, self.model.currentData())
        except ValueError as e:
            self.fit = None
            self.eq.setText(str(e))
        else:
            f = self.fit
            warn = "" if f.r2 >= 0.99 else " <span style='color:#cf2e2e'>— R² < 0,99, перевірте стандарти</span>"
            lod = (f"LOD = {f.lod:.3g} {unit}, LOQ = {f.loq:.3g} {unit}" if f.lod is not None else "")
            self.eq.setText(f"<b style='font-size:15px'>{f.equation(unit)}</b><br>R² = {f.r2:.4f}{warn} · "
                            f"s(y/x) = {f.s_yx:.4f} · n = {f.n} · діапазон {f.c_min:g}–{f.c_max:g} {unit}<br>{lod}")
        self.plot.setLabel("bottom", f"Концентрація, {unit}" if unit else "Концентрація")
        self.update_samples()

    def draw(self):
        self.plot.clear()
        t = self.win.theme
        xs, ys = self.points()
        if xs:
            self.plot.plot(xs, ys, pen=None, symbol="o", symbolSize=7, symbolBrush=t.channels[0],
                           symbolPen=None, name="стандарти")
        off = [(c, v) for _, c, a, use in self.rows() if not use and c is not None for v in a]
        if off:
            self.plot.plot([p[0] for p in off], [p[1] for p in off], pen=None, symbol="x", symbolSize=9,
                           symbolPen=pg.mkPen(t.muted, width=2), name="вимкнені")
        if self.fit:
            lo, hi = self.fit.c_min, self.fit.c_max
            span = hi - lo or 1
            cx = np.linspace(lo - 0.05 * span, hi + 0.05 * span, 100)
            self.plot.plot(cx, self.fit.predict_a(cx), pen=pg.mkPen(t.channels[1], width=2), name="модель")
            pts = []
            for r in range(self.smp.rowCount()):
                A, dil = self.smp.item(r, 0).data(Qt.UserRole)
                c, _ = self.conc(A)
                if math.isfinite(c):
                    pts.append((c, A))
            if pts:
                self.plot.plot([p[0] for p in pts], [p[1] for p in pts], pen=None, symbol="d", symbolSize=10,
                               symbolBrush=t.channels[2], symbolPen=None, name="зразки")

    def update_samples(self):
        for r in range(self.smp.rowCount()):
            A, dil = self.smp.item(r, 0).data(Qt.UserRole)
            c, se = self.conc(A)
            note = range_note(self.fit, c) if self.fit else "немає калібрування"
            vals = [f"{A:.4f}", f"{c:.3g}" if math.isfinite(c) else "—",
                    f"{se:.2g}" if se is not None and math.isfinite(c) else "",
                    f"{c * dil:.4g}" if math.isfinite(c) else "—", note]
            for j, v in enumerate(vals, 1):
                it = self.smp.item(r, j)
                it.setText(v)
                if j == 5:
                    it.setForeground(QColor(self.win.theme.danger if v else self.win.theme.text))
        self.draw()

    def receipt(self):
        from .printer import print_receipt
        lines = []
        if self.fit:
            f = self.fit
            lines += [("text", f.equation(self.unit.text())), ("small", f"R² = {f.r2:.4f}, n = {f.n}")]
            if f.lod is not None:
                lines.append(("small", f"LOD {f.lod:.3g}, LOQ {f.loq:.3g} {self.unit.text()}"))
        for r in range(self.smp.rowCount()):
            lines.append(("text", f"{self.smp.item(r, 0).text()}: A {self.smp.item(r, 1).text()} → "
                                  f"{self.smp.item(r, 4).text()} {self.unit.text()}"))
            if self.smp.item(r, 5).text():
                lines.append(("small", f"⚠ {self.smp.item(r, 5).text()}"))
        print_receipt(self.win, f"Калібрування, {self.win.wl_spin.value()} нм", lines)

    # ----- save / load / export
    def state(self) -> dict:
        return {"format": "specrec-calibration/1", "unit": self.unit.text(), "model": self.model.currentData(),
                "wavelength_nm": self.win.wl_spin.value(), "saved": dt.datetime.now().isoformat(timespec="seconds"),
                "standards": [{"C": c, "A": a, "use": use} for _, c, a, use in self.rows()],
                "cuvette": self.win.cuvette.text(),
                "equation": self.fit.equation(self.unit.text()) if self.fit else "",
                "r2": self.fit.r2 if self.fit else None}

    def save(self):
        default = str(storage.day_dir() / f"calibration_{dt.datetime.now():%H%M}.json")
        path, _ = QFileDialog.getSaveFileName(self, "Зберегти калібрування", default, "Калібрування (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.state(), ensure_ascii=False, indent=1), encoding="utf-8")
            self.win.message(f"Калібрування збережено: {path}")

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Відкрити калібрування", str(storage.day_dir().parent),
                                              "Калібрування (*.json)")
        if not path:
            return
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            self.unit.setText(d.get("unit", ""))
            i = self.model.findData(d.get("model", "linear"))
            self.model.setCurrentIndex(max(i, 0))
            self.std.setRowCount(0)
            for s in d["standards"]:
                self.add_row(s["C"], s["A"], s.get("use", True))
        except Exception as e:
            QMessageBox.warning(self, "Не вдалося відкрити", str(e))
            return
        if d.get("wavelength_nm"):
            self.win.message(f"Калібрування на {d['wavelength_nm']} нм — встановіть ту саму довжину хвилі й бланк")
        self.recompute()

    def export(self):
        default = str(storage.day_dir() / f"calibration_{dt.datetime.now():%H%M}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Експорт", default, "Excel (*.xlsx)")
        if not path:
            return
        unit = self.unit.text()
        std_rows = [[c, *(a + [None] * (MAX_REP - len(a))), (np.mean(a) if a else None), "так" if use else "ні"]
                    for _, c, a, use in self.rows()]
        smp = []
        for r in range(self.smp.rowCount()):
            A, dil = self.smp.item(r, 0).data(Qt.UserRole)
            c, se = self.conc(A)
            smp.append([self.smp.item(r, 0).text(), A, c, se, dil, c * dil, self.smp.item(r, 5).text()])
        meta = {"Рівняння": self.fit.equation(unit) if self.fit else "", "R²": self.fit.r2 if self.fit else "",
                "LOD": self.fit.lod if self.fit else "", "LOQ": self.fit.loq if self.fit else "",
                "λ, нм": self.win.wl_spin.value(), "Одиниці": unit, "Кювета": self.win.cuvette.text()}
        storage.write_workbook(path, [
            ("Стандарти", [f"C, {unit}"] + [f"A{i}" for i in range(1, MAX_REP + 1)] + ["Середнє", "Враховано"], std_rows),
            ("Зразки", ["Зразок", "A", f"C, {unit}", "± SE", "Розведення", f"C × розв., {unit}", "Примітка"], smp),
        ], meta)
        self.win.message(f"Збережено: {path}")
