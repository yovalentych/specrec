"""Main window: toolbar with the connection, working wavelength and blank; three tabs —
photometry, spectrum scan, kinetics."""
from __future__ import annotations

import datetime as dt
import math
import subprocess
import sys
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QDoubleSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import __version__, paths, storage
from ..simulator import SAMPLES, FakeSerial
from ..v1200 import WL_MAX, WL_MIN, InstrumentError, V1200, find_ports
from ..worker import Worker
from . import theme as th
from .icon import make_icon
from .series import Sequence, SeriesDialog

DEMO = "Демо (без приладу)"


from .connection import ConnectionDialog
from .notify import Notifier
from .cuvette import Cuvette, CuvetteDialog
from .common import Tile, fmt_a, fmt_t, hint, make_plot, section
from .kinetics import KineticsTab
from .protocol_tab import ProtocolTab
from .calibration_tab import CalibrationTab


# ---------------------------------------------------------------- photometry
class PhotometryTab(QWidget):
    COLS = ["№", "Час", "Поз.", "Зразок", "λ, нм", "A", "T, %"]

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.rows: list[list] = []
        self.counter = 1

        left = QVBoxLayout()
        left.addWidget(section("Зразок"))
        self.name = QLineEdit("Зразок 1")
        left.addWidget(self.name)
        f = QFormLayout()
        self.n = QSpinBox()
        self.n.setRange(1, 100)
        self.n.setValue(10)
        self.n.setToolTip("Скільки відліків усереднювати для одного виміру")
        f.addRow("Усереднення:", self.n)
        left.addLayout(f)
        self.b_meas = QPushButton("Виміряти  ⏎")
        self.b_meas.setObjectName("primary")
        self.b_meas.setMinimumHeight(40)
        self.b_meas.clicked.connect(lambda: self.measure())
        left.addWidget(self.b_meas)
        self.b_series = QPushButton("Серія з каретки…")
        self.b_series.setToolTip("Бланк у позиції 1, зразки в позиціях 2–4: програма підкаже, коли пересунути каретку")
        self.b_series.clicked.connect(self.series)
        left.addWidget(self.b_series)
        left.addWidget(hint("1. Поставте кювету з бланком (розчинником) і натисніть «Бланк» угорі.\n"
                            "2. Поставте зразок і натисніть «Виміряти» (або Enter).\n"
                            "Бланк дійсний для своєї довжини хвилі: після її зміни зробіть новий."))
        self.tile_a = Tile("Оптична густина", "A")
        self.tile_t = Tile("Пропускання", "T, %")
        left.addWidget(self.tile_a)
        left.addWidget(self.tile_t)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(270)

        right = QVBoxLayout()
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        right.addWidget(self.table)
        bl = QHBoxLayout()
        b_del = QPushButton("Видалити вибрані")
        b_del.clicked.connect(self.delete_selected)
        b_clr = QPushButton("Очистити таблицю")
        b_clr.clicked.connect(self.clear)
        b_exp = QPushButton("Експорт…")
        b_exp.clicked.connect(self.export)
        b_rc = QPushButton("🖨 Чек")
        b_rc.setToolTip("Виміри (вибрані або всі) — на термопринтер або картинкою")
        b_rc.clicked.connect(self.receipt)
        bl.addWidget(b_del)
        bl.addWidget(b_clr)
        bl.addStretch()
        bl.addWidget(b_rc)
        bl.addWidget(b_exp)
        right.addLayout(bl)
        right.addWidget(hint("Кожен вимір одразу дописується у файл photometry.csv у папці даних "
                             "(Файл → Відкрити папку з даними). Видалення з таблиці файл не змінює."))

        lay = QHBoxLayout(self)
        lay.addWidget(lw)
        lay.addLayout(right, 1)

        for key in (Qt.Key_Return, Qt.Key_Enter):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda: self.b_meas.isEnabled() and self.measure())

    def set_enabled(self, ok: bool):
        self.b_meas.setEnabled(ok)
        self.b_series.setEnabled(ok)

    def series(self):
        dlg = SeriesDialog(self.win, self.win.settings, "Фотометрія")
        if not dlg.exec():
            return
        steps = []
        if dlg.blank.isChecked():
            steps.append((1, "бланк", lambda nxt: self.win.do_blank(on_done=nxt)))
        for pos, name in dlg.result_positions():
            steps.append((pos, name, lambda nxt, p=pos, nm=name: self.measure(nm, p, nxt)))
        Sequence(self.win, steps).start()

    def measure(self, name: str | None = None, pos: int | None = None, on_done=None):
        wl = self.win.target_wl()
        n = self.n.value()
        auto_name = name is None
        name = name or self.name.text().strip() or f"Зразок {self.counter}"

        def task(dev, job):
            dev.set_wavelength(wl)
            ref = dev.blank_ref
            if ref is None or ref.wavelength != wl:
                raise InstrumentError(f"Немає бланку на {wl} нм. Поставте кювету з бланком "
                                      f"і натисніть «Бланк».")
            return dev.read(ref, n)

        def done(r):
            self.add(name, r, pos, auto_name)
            if on_done:
                on_done()

        self.win.run(task, done, label=f"Вимір на {wl} нм…")

    def add(self, name: str, r, pos: int | None = None, auto_name: bool = True):
        now = dt.datetime.now().strftime("%H:%M:%S")
        row = [len(self.rows) + 1, now, pos or "", name, r.wavelength, r.A, r.T]
        self.rows.append(row)
        i = self.table.rowCount()
        self.table.insertRow(i)
        for j, v in enumerate([str(row[0]), now, str(pos or ""), name, str(r.wavelength), fmt_a(r), fmt_t(r)]):
            it = QTableWidgetItem(v)
            if j >= 4:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, j, it)
        self.table.scrollToBottom()
        self.tile_a.set(fmt_a(r))
        self.tile_t.set(fmt_t(r))
        storage.append_row(storage.day_dir() / "photometry.csv",
                           ["time", "position", "sample", "wavelength_nm", "A", "T_percent", "energy", "cuvette"],
                           [dt.datetime.now().isoformat(timespec="seconds"), pos or "", name, r.wavelength,
                            r.A, r.T, r.energy, self.win.cuvette.text()])
        if r.saturated:
            self.win.message("Зразок пропускає більше світла, ніж бланк, і сигнал зашкалює: "
                             "A нижче за межу вимірювання. Перевірте бланк.", warn=True)
        elif math.isinf(r.A) or r.A > 3:
            self.win.message("A > 3: світла майже немає, точність низька. Розведіть зразок.", warn=True)
        if not auto_name:
            return
        # next sample name: "Зразок 1" -> "Зразок 2"
        self.counter += 1
        parts = name.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            self.name.setText(f"{parts[0]} {int(parts[1]) + 1}")
        self.name.selectAll()

    def receipt(self):
        from .printer import print_receipt
        sel = sorted({i.row() for i in self.table.selectedIndexes()})
        rows = [self.rows[i] for i in sel] if sel else self.rows
        if not rows:
            return
        lines = []
        for r in rows:
            a = r[5]
            av = f"A = {a:.3f} · T = {r[6]:.1f} %" if isinstance(a, float) and math.isfinite(a) else "A > 3"
            lines.append(("text", f"{r[3]} · {r[4]} нм · {av}"))
        print_receipt(self.win, "Фотометрія", lines)

    def delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for i in rows:
            self.table.removeRow(i)
            del self.rows[i]

    def clear(self):
        self.table.setRowCount(0)
        self.rows.clear()

    def export(self):
        if not self.rows:
            return
        self.win.export_table("photometry", self.COLS, [list(r) for r in self.rows])


# ---------------------------------------------------------------- spectrum
class SpectrumTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.blank: dict[int, object] = {}       # wl -> Reference
        self.blank_time = ""
        self.scans: list[dict] = []              # {name, wl[], A[], T[], item, color, time}
        self.live = None
        self.color_i = 0

        ctl = QVBoxLayout()
        ctl.addWidget(section("Діапазон"))
        g = QGridLayout()
        self.start = QSpinBox()
        self.end = QSpinBox()
        for s in (self.start, self.end):
            s.setRange(WL_MIN, WL_MAX)
            s.setSuffix(" нм")
        self.start.setValue(400)
        self.end.setValue(700)
        self.step = QComboBox()
        for v in (1, 2, 5, 10, 20):
            self.step.addItem(f"{v} нм", v)
        self.step.setCurrentIndex(2)
        self.n = QSpinBox()
        self.n.setRange(1, 50)
        self.n.setValue(5)
        b_min = QPushButton("мін")
        b_min.setToolTip(f"Найменша довжина хвилі приладу: {WL_MIN} нм")
        b_min.clicked.connect(lambda: self.start.setValue(WL_MIN))
        b_max = QPushButton("макс")
        b_max.setToolTip(f"Найбільша довжина хвилі приладу: {WL_MAX} нм")
        b_max.clicked.connect(lambda: self.end.setValue(WL_MAX))
        for b in (b_min, b_max):
            b.setFixedWidth(52)
        g.addWidget(QLabel("Від:"), 0, 0)
        g.addWidget(self.start, 0, 1)
        g.addWidget(b_min, 0, 2)
        g.addWidget(QLabel("До:"), 1, 0)
        g.addWidget(self.end, 1, 1)
        g.addWidget(b_max, 1, 2)
        g.addWidget(QLabel("Крок:"), 2, 0)
        g.addWidget(self.step, 2, 1, 1, 2)
        g.addWidget(QLabel("Усереднення:"), 3, 0)
        g.addWidget(self.n, 3, 1, 1, 2)
        ctl.addLayout(g)
        b_all = QPushButton(f"Весь діапазон ({WL_MIN}–{WL_MAX} нм)")
        b_all.clicked.connect(lambda: (self.start.setValue(WL_MIN), self.end.setValue(WL_MAX)))
        ctl.addWidget(b_all)
        self.est = hint("")
        ctl.addWidget(self.est)
        for w in (self.start, self.end, self.n):
            w.valueChanged.connect(self.update_hint)
        self.step.currentIndexChanged.connect(self.update_hint)

        ctl.addWidget(section("Вимір"))
        self.b_blank = QPushButton("1 · Скан бланку")
        self.b_blank.clicked.connect(lambda: self.scan_blank())
        ctl.addWidget(self.b_blank)
        self.blank_lbl = hint("Бланк-скан: немає")
        ctl.addWidget(self.blank_lbl)
        self.name = QLineEdit("Зразок 1")
        ctl.addWidget(self.name)
        self.b_sample = QPushButton("2 · Скан зразка")
        self.b_sample.setObjectName("primary")
        self.b_sample.clicked.connect(lambda: self.scan_sample())
        ctl.addWidget(self.b_sample)
        self.b_series = QPushButton("Серія з каретки…")
        self.b_series.setToolTip("Бланк-скан у позиції 1, потім скани позицій 2–4")
        self.b_series.clicked.connect(self.series)
        ctl.addWidget(self.b_series)

        ctl.addWidget(section("Спектри"))
        self.list = QListWidget()
        self.list.itemChanged.connect(self.toggle_item)
        self.list.currentRowChanged.connect(lambda _: self.show_peak())
        ctl.addWidget(self.list, 1)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Базова лінія:"))
        self.base = QComboBox()
        self.base.setToolTip("Відняти від усіх спектрів інший спектр, напр. «вода проти води» — "
                             "прибирає різницю кювет / гнізд каретки")
        self.base.addItem("немає", None)
        self.base.currentIndexChanged.connect(lambda _: self.redraw())
        brow.addWidget(self.base, 1)
        ctl.addLayout(brow)
        b_bl = QPushButton("Записати «вода проти води»")
        b_bl.setToolTip("Розчинник і в бланковій, і в зразковій кюветі: цей скан стане базовою лінією")
        b_bl.clicked.connect(self.record_baseline)
        ctl.addWidget(b_bl)
        self.b_bl = b_bl
        bl = QHBoxLayout()
        b_del = QPushButton("Видалити")
        b_del.clicked.connect(self.delete)
        b_exp = QPushButton("Експорт…")
        b_exp.clicked.connect(self.export)
        bl.addWidget(b_del)
        bl.addWidget(b_exp)
        ctl.addLayout(bl)
        cw = QWidget()
        cw.setLayout(ctl)
        cw.setFixedWidth(310)

        right = QVBoxLayout()
        top = QHBoxLayout()
        self.ymode = QComboBox()
        self.ymode.addItems(["Оптична густина A", "Пропускання T, %"])
        self.ymode.currentIndexChanged.connect(self.redraw)
        top.addWidget(QLabel("Показувати:"))
        top.addWidget(self.ymode)
        top.addStretch()
        self.cursor_lbl = QLabel("")
        self.cursor_lbl.setObjectName("mono")
        top.addWidget(self.cursor_lbl)
        right.addLayout(top)
        self.plot = make_plot(win.theme, "Довжина хвилі, нм", "A")
        right.addWidget(self.plot, 1)
        self.peak_lbl = hint("")
        right.addWidget(self.peak_lbl)
        self.vline = pg.InfiniteLine(angle=90, pen=pg.mkPen(win.theme.muted, style=Qt.DashLine))
        self.plot.addItem(self.vline, ignoreBounds=True)
        self.plot.scene().sigMouseMoved.connect(self.mouse_moved)

        lay = QHBoxLayout(self)
        lay.addWidget(cw)
        lay.addLayout(right, 1)
        self.update_hint()

    def wavelengths(self) -> list[int]:
        a, b, s = self.start.value(), self.end.value(), self.step.currentData()
        if b < a:
            a, b = b, a
        return list(range(a, b + 1, s))

    def update_hint(self):
        wls = self.wavelengths()
        sec = len(wls) * (2.2 + 0.045 * self.step.currentData() + 0.4 + 0.01 * self.n.value())
        self.est.setText(f"{len(wls)} точок, приблизно {max(1, round(sec / 60))} хв на один скан")

    def set_enabled(self, ok: bool):
        self.b_blank.setEnabled(ok)
        self.b_sample.setEnabled(ok)
        self.b_series.setEnabled(ok)

    def series(self):
        dlg = SeriesDialog(self.win, self.win.settings, "Спектри")
        if not dlg.exec():
            return
        steps = []
        if dlg.blank.isChecked() or any(w not in self.blank for w in self.wavelengths()):
            steps.append((1, "бланк", lambda nxt: self.scan_blank(nxt)))
        for pos, name in dlg.result_positions():
            steps.append((pos, name, lambda nxt, nm=name: self.scan_sample(nm, nxt)))
        Sequence(self.win, steps).start()

    def next_color(self) -> str:
        c = self.win.theme.channels[self.color_i % len(self.win.theme.channels)]
        self.color_i += 1
        return c

    def check_cutoff(self) -> bool:
        cut = self.win.cuvette.cutoff
        lo = min(self.wavelengths())
        if lo >= cut:
            return True
        return QMessageBox.question(
            self, "Кювета", f"Скан починається з {lo} нм, а кювета ({self.win.cuvette.text()}) пропускає "
            f"приблизно від {cut} нм. Нижче цього значення будуть ненадійні.\n\nПродовжити?\n"
            "(Матеріал кювети: Прилад → Кювета…)") == QMessageBox.Yes

    def scan_blank(self, on_done=None):
        if on_done is None and not self.check_cutoff():
            return
        wls = self.wavelengths()
        n = self.n.value()
        self.blank = {}
        self.blank_lbl.setText("Бланк-скан: виконується…")
        t_begin = time.monotonic()

        def task(dev, job):
            gain = None
            for i, wl in enumerate(wls):
                if job.stopped:
                    break
                dev.set_wavelength(wl)
                ref = dev.quick_reference(n, start_gain=gain)
                gain = ref.gain
                job.progress((i + 1, len(wls), wl, ref))
            return None

        def prog(d):
            i, total, wl, ref = d
            self.blank[wl] = ref
            self.win.set_progress(i, total, f"Бланк: {wl} нм")

        def done(_):
            self.blank_time = dt.datetime.now().strftime("%H:%M")
            ok = len(self.blank) == len(wls)
            self.blank_lbl.setText(f"Бланк-скан: {min(self.blank, default=0)}–{max(self.blank, default=0)} нм, "
                                   f"{self.blank_time}" + ("" if ok else " (перервано)"))
            if not self.blank:
                self.blank_lbl.setText("Бланк-скан: немає")
            if ok and on_done is None and time.monotonic() - t_begin > 20:
                self.win.notifier.notify("Бланк-скан готовий",
                                         "Поставте зразок і натисніть «2 · Скан зразка».", kind="done")
            if on_done and ok:
                on_done()

        self.win.run(task, done, prog, label="Скан бланку…")

    def scan_sample(self, name: str | None = None, on_done=None):
        wls = self.wavelengths()
        missing = [w for w in wls if w not in self.blank]
        if missing:
            QMessageBox.information(self, "Потрібен бланк-скан",
                                    "Для цього діапазону й кроку немає бланк-скану.\n"
                                    "Поставте кювету з бланком і натисніть «1 · Скан бланку».")
            return
        n = self.n.value()
        auto_name = name is None
        name = name or self.name.text().strip() or "Зразок"
        blank = dict(self.blank)
        color = self.next_color()
        scan = {"name": name, "wl": [], "A": [], "T": [], "E": [], "sat": [], "color": color,
                "time": dt.datetime.now(), "item": None}
        scan["item"] = self.plot.plot([], [], pen=pg.mkPen(color, width=2), name=name)
        self.live = scan
        t_begin = time.monotonic()

        def task(dev, job):
            for i, wl in enumerate(wls):
                if job.stopped:
                    break
                dev.set_wavelength(wl)
                job.progress((i + 1, len(wls), dev.read(blank[wl], n)))

        def prog(d):
            i, total, r = d
            scan["wl"].append(r.wavelength)
            scan["A"].append(r.A if not math.isinf(r.A) else np.nan)
            scan["T"].append(r.T)
            scan["E"].append(r.energy)
            scan["sat"].append(r.saturated)
            self.set_curve(scan)
            self.win.set_progress(i, total, f"{name}: {r.wavelength} нм, A = {fmt_a(r)}")

        def done(_):
            self.live = None
            if not scan["wl"]:
                self.plot.removeItem(scan["item"])
                return
            self.scans.append(scan)
            it = QListWidgetItem(f"{name}  ·  {scan['time']:%H:%M}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setForeground(QColor(color))
            self.list.blockSignals(True)
            self.list.addItem(it)
            self.list.blockSignals(False)
            self.list.setCurrentRow(self.list.count() - 1)
            self.fill_base()
            if getattr(self, "_make_baseline", False):
                self._make_baseline = False
                self.base.setCurrentIndex(self.base.findData(len(self.scans) - 1))
                self.win.message("Базову лінію записано: вона віднімається від усіх спектрів (вибір — «Базова лінія»)")
            self.redraw()
            path = storage.day_dir() / f"scan_{scan['time']:%H%M%S}_{storage.safe_name(name)}.csv"
            storage.write_table(path, ["wavelength_nm", "A", "T_percent", "energy", "blank_energy", "gain",
                                       "saturated"],
                                [[w, a, t, e, blank[w].ref, blank[w].gain, int(sat)]
                                 for w, a, t, e, sat in zip(scan["wl"], scan["A"], scan["T"], scan["E"],
                                                            scan["sat"])],
                                {"sample": name, "time": scan["time"].isoformat(timespec="seconds"),
                                 "instrument": self.win.model or "", **self.win.cuvette.meta()})
            self.win.message(f"Спектр збережено: {path.name}")
            if on_done is None and time.monotonic() - t_begin > 20:
                a = np.asarray(scan["A"], float)
                peak = (f"Максимум A = {np.nanmax(a):.3f} при {scan['wl'][int(np.nanargmax(a))]} нм.\n"
                        if not np.all(np.isnan(a)) else "")
                self.win.notifier.notify(f"Спектр готовий: {name}", f"{peak}Файл: {path.name}", kind="done",
                                         popup=False)
            clipped = [w for w, sat in zip(scan["wl"], scan["sat"]) if sat]
            if clipped:
                QMessageBox.warning(
                    self, "Сигнал зашкалює",
                    f"«{name}»: у {len(clipped)} точках ({clipped[0]}–{clipped[-1]} нм) зразок пропускає "
                    "помітно більше світла, ніж бланк, і сигнал упирається в межу приладу. "
                    "A там трохи завищена.\n\nЗазвичай це означає, що бланк був не той "
                    "(поглинав сам) або кювети різні. Зробіть новий бланк-скан з чистим розчинником.")
            if on_done and len(scan["wl"]) == len(wls):
                on_done()
            if not auto_name:
                return
            parts = name.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].isdigit():
                self.name.setText(f"{parts[0]} {int(parts[1]) + 1}")

        self.win.run(task, done, prog, label=f"Скан: {name}…")

    def baseline(self):
        i = self.base.currentData()
        return self.scans[i] if i is not None and 0 <= i < len(self.scans) else None

    def values(self, scan, mode=None):
        """A (minus the baseline, if one is chosen) or %T of a scan."""
        mode = self.ymode.currentIndex() if mode is None else mode
        base = self.baseline()
        a = np.asarray(scan["A"], float)
        if base is not None and base is not scan and base["wl"]:
            a = a - np.interp(scan["wl"], base["wl"], np.asarray(base["A"], float))
        return a if mode == 0 else 100 * 10 ** (-a)

    def set_curve(self, scan):
        scan["item"].setData(scan["wl"], self.values(scan))

    def fill_base(self):
        cur = self.base.currentData()
        self.base.blockSignals(True)
        self.base.clear()
        self.base.addItem("немає", None)
        for i, s in enumerate(self.scans):
            self.base.addItem(s["name"], i)
        j = self.base.findData(cur)
        self.base.setCurrentIndex(max(j, 0))
        self.base.blockSignals(False)

    def record_baseline(self):
        self._make_baseline = True
        self.scan_sample("Базова лінія (вода/вода)")

    def redraw(self):
        base = self.baseline()
        self.plot.setLabel("left", ("A" + (" − базова лінія" if base else "")) if self.ymode.currentIndex() == 0 else "T, %")
        for s in self.scans + ([self.live] if self.live else []):
            self.set_curve(s)
        self.show_peak()

    def toggle_item(self, it: QListWidgetItem):
        s = self.scans[self.list.row(it)]
        s["item"].setVisible(it.checkState() == Qt.Checked)

    def show_peak(self):
        i = self.list.currentRow()
        if not 0 <= i < len(self.scans):
            self.peak_lbl.setText("")
            return
        s = self.scans[i]
        a = self.values(s, 0)
        if np.all(np.isnan(a)):
            return
        k = int(np.nanargmax(a))
        self.peak_lbl.setText(f"{s['name']}: максимум A = {a[k]:.3f} при λ = {s['wl'][k]} нм")

    def mouse_moved(self, pos):
        vb = self.plot.getPlotItem().vb
        if not self.plot.sceneBoundingRect().contains(pos):
            return
        x = vb.mapSceneToView(pos).x()
        self.vline.setPos(x)
        parts = []
        mode = self.ymode.currentIndex()
        for s in self.scans:
            if not s["item"].isVisible() or not s["wl"]:
                continue
            k = int(np.argmin(np.abs(np.asarray(s["wl"]) - x)))
            v = self.values(s)[k]
            parts.append(f"{s['name']}: {v:.3f}" if mode == 0 else f"{s['name']}: {v:.1f} %")
        self.cursor_lbl.setText(f"λ = {x:.0f} нм   " + "   ".join(parts))

    def delete(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.scans):
            if self.base.currentData() == i:
                self.base.setCurrentIndex(0)
            elif self.base.currentData() is not None and self.base.currentData() > i:
                self.base.setCurrentIndex(self.base.currentIndex() - 1)
            self.plot.removeItem(self.scans[i]["item"])
            del self.scans[i]
            self.list.takeItem(i)
            self.fill_base()
            self.redraw()

    def export(self):
        vis = [s for s in self.scans if s["item"].isVisible()]
        if not vis:
            return
        wls = sorted({w for s in vis for w in s["wl"]})
        base = self.baseline()
        suffix = " A − базова лінія" if base else " A"
        header = ["λ, нм"] + [f"{s['name']}{suffix if s is not base else ' A'}" for s in vis]
        rows = []
        for w in wls:
            row = [w]
            for s in vis:
                d = dict(zip(s["wl"], self.values(s, 0)))
                v = d.get(w)
                row.append(None if v is None or (isinstance(v, float) and math.isnan(v)) else v)
            rows.append(row)
        self.win.export_table("spectra", header, rows)


# ---------------------------------------------------------------- window
class MainWindow(QMainWindow):
    def __init__(self, autoconnect: bool = True):
        super().__init__()
        self.settings = paths.make_settings()
        self.cuvette = Cuvette(self.settings)
        self.theme = th.THEMES.get(self.settings.value("theme", "light"), th.LIGHT)
        self.model = None
        self.connected = False
        self.busy = False
        self.sim: FakeSerial | None = None

        self.setWindowTitle("SpecRec — спектрофотометр V-1200")
        self.setWindowIcon(make_icon())
        self.resize(1200, 760)

        self.worker = Worker(self)
        self.worker.failed.connect(self.on_error)
        self.worker.busy_changed.connect(self.on_busy)
        self.worker.state.connect(self.on_state)
        self.worker.start()
        self.notifier = Notifier(self, make_icon())
        self._progress_t0 = None

        self.build_toolbar()
        self.tabs = QTabWidget()
        self.photo = PhotometryTab(self)
        self.spec = SpectrumTab(self)
        self.kin = KineticsTab(self)
        self.tabs.addTab(self.photo, "Фотометрія")
        self.tabs.addTab(self.spec, "Спектр")
        self.tabs.addTab(self.kin, "Кінетика")
        self.calib = CalibrationTab(self)
        self.tabs.addTab(self.calib, "Калібрування")
        self.proto = ProtocolTab(self)
        self.tabs.addTab(self.proto, "Протокол")
        self.tabs.setDocumentMode(True)
        # Space / Enter are shortcuts there ("measure", "position ready"): other buttons must not
        # take the focus, or a key press would click them instead
        for tab, keep in ((self.photo, self.photo.b_meas), (self.kin, self.kin.b_ready)):
            for btn in tab.findChildren(QPushButton):
                if btn is not keep:
                    btn.setFocusPolicy(Qt.NoFocus)
        self.setCentralWidget(self.tabs)
        self.build_menu()
        self.statusBar().showMessage(f"Дані зберігаються в {paths.data_root()}")
        self.apply_theme()
        self.update_enabled()
        self.cur_port = None
        self.user_disconnected = False   # «Відключити» pressed: no auto reconnect until the USB changes
        self.seen_ports: set[str] = set()
        self.last_try = 0.0
        self.autoconnect = autoconnect
        self.hotplug_timer = QTimer(self)
        self.hotplug_timer.timeout.connect(self.hotplug)
        if autoconnect:
            QTimer.singleShot(200, self.hotplug)
            self.hotplug_timer.start(2000)
        else:
            self.message("Прилад не підключено.")

    # ----- toolbar / menu
    def build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        self.port = QComboBox()
        self.port.setMinimumWidth(190)
        self.port.setToolTip("Порт приладу. «Демо» — віртуальний прилад для навчання й перевірки програми.")
        tb.addWidget(self.port)
        self.b_conn = QPushButton("Підключити")
        self.b_conn.clicked.connect(self.toggle_connect)
        tb.addWidget(self.b_conn)
        self.pill = QLabel("НЕ ПІДКЛЮЧЕНО")
        self.pill.setObjectName("status")
        tb.addWidget(self.pill)
        tb.addSeparator()

        tb.addWidget(QLabel("λ:"))
        self.wl_spin = QSpinBox()
        self.wl_spin.setRange(WL_MIN, WL_MAX)
        self.wl_spin.setSuffix(" нм")
        self.wl_spin.setValue(int(self.settings.value("wavelength", 540)))
        self.wl_spin.setToolTip("Робоча довжина хвилі для фотометрії та кінетики")
        self.wl_spin.setKeyboardTracking(False)
        tb.addWidget(self.wl_spin)
        self.b_go = QPushButton("Перейти")
        self.b_go.setToolTip("Встановити цю довжину хвилі на приладі")
        self.b_go.clicked.connect(self.go_wl)
        tb.addWidget(self.b_go)
        self.b_blank = QPushButton("Бланк")
        self.b_blank.setObjectName("primary")
        self.b_blank.setToolTip("Поставте кювету з розчинником (бланком) і натисніть: прилад обнулиться "
                                "на цій довжині хвилі")
        self.b_blank.clicked.connect(lambda: self.do_blank())
        tb.addWidget(self.b_blank)
        self.state_lbl = QLabel("")
        self.state_lbl.setObjectName("mono")
        tb.addWidget(self.state_lbl)

        self.demo_box = QWidget()
        dl = QHBoxLayout(self.demo_box)
        dl.setContentsMargins(8, 0, 0, 0)
        dl.addWidget(QLabel("У кюветі:"))
        self.demo_sample = QComboBox()
        for k, (title, _) in SAMPLES.items():
            self.demo_sample.addItem(title, k)
        self.demo_sample.currentIndexChanged.connect(
            lambda: self.sim and self.sim.insert(self.demo_sample.currentData(), restart=not self.busy))
        dl.addWidget(self.demo_sample)
        self.demo_act = tb.addWidget(self.demo_box)
        self.demo_act.setVisible(False)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        tb.addWidget(spacer)
        self.busy_lbl = QLabel("")
        self.busy_lbl.setObjectName("hint")
        tb.addWidget(self.busy_lbl)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(140)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        self.progress.setVisible(False)
        tb.addWidget(self.progress)
        self.b_stop = QPushButton("Стоп")
        self.b_stop.clicked.connect(self.stop)
        tb.addWidget(self.b_stop)
        self.refresh_ports()

    def build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&Файл")
        a = QAction("Зведення по тваринах…", self)
        a.triggered.connect(lambda: self.proto.summary())
        m.addAction(a)
        a = QAction("Відкрити кінетику…", self)
        a.triggered.connect(lambda: (self.tabs.setCurrentWidget(self.kin), self.kin.open_file()))
        m.addAction(a)
        a = QAction("Відкрити папку з даними", self)
        a.triggered.connect(self.open_data)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Вийти", self)
        a.setShortcut(QKeySequence.Quit)
        a.triggered.connect(self.close)
        m.addAction(a)

        m = mb.addMenu("&Прилад")
        a = QAction("Підключення…", self)
        a.triggered.connect(lambda: ConnectionDialog(self).exec())
        m.addAction(a)
        a = QAction("Термопринтер…", self)
        a.triggered.connect(self.printer_settings)
        m.addAction(a)
        a = QAction("Перевірка приладу…", self)
        a.triggered.connect(self.instrument_check)
        m.addAction(a)
        a = QAction("Кювета…", self)
        a.triggered.connect(self.edit_cuvette)
        m.addAction(a)
        self.act_dark = QAction("Переміряти темновий струм (~15 с)", self)
        self.act_dark.triggered.connect(self.remeasure_dark)
        m.addAction(self.act_dark)

        m = mb.addMenu("&Вигляд")
        self.act_theme = QAction("Темна тема", self, checkable=True)
        self.act_theme.setChecked(self.theme.name == "dark")
        self.act_theme.toggled.connect(lambda on: self.set_theme("dark" if on else "light"))
        m.addAction(self.act_theme)
        self.act_sound = QAction("Звукові сигнали", self, checkable=True)
        self.act_sound.setChecked(self.notifier.sound_on)
        self.act_sound.toggled.connect(lambda on: self.settings.setValue("notify/sound", on))
        m.addAction(self.act_sound)

        m = mb.addMenu("&Довідка")
        a = QAction("Про SpecRec", self)
        a.triggered.connect(self.about)
        m.addAction(a)

    def refresh_ports(self):
        cur = self.port.currentText()
        self.port.clear()
        self.port.addItems(find_ports())
        self.port.addItem(DEMO)
        i = self.port.findText(cur)
        if i >= 0:
            self.port.setCurrentIndex(i)

    # ----- theme
    def set_theme(self, name: str):
        self.theme = th.THEMES[name]
        self.settings.setValue("theme", name)
        self.apply_theme()
        QMessageBox.information(self, "Тема", "Графіки змінять кольори після перезапуску програми.")

    def apply_theme(self):
        app = QApplication.instance()
        th.apply_palette(app, self.theme)
        app.setStyleSheet(th.stylesheet(self.theme))
        self.update_pill()

    # ----- helpers used by the tabs
    def target_wl(self) -> int:
        self.settings.setValue("wavelength", self.wl_spin.value())
        return self.wl_spin.value()

    def run(self, fn, on_done=None, on_progress=None, label="Працюю…"):
        if not self.connected:
            self.message("Спершу підключіть прилад (або виберіть демо-режим).", warn=True)
            return
        self.busy_lbl.setText(label)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self._progress_t0 = None
        self.worker.submit(fn, on_done, on_progress)

    def set_progress(self, i: int, total: int, text: str):
        """Progress bar + the time left (estimated from the speed so far)."""
        import time
        now = time.monotonic()
        if self._progress_t0 is None or i <= 1:
            self._progress_t0 = (now, i)
        t0, i0 = self._progress_t0
        if i > i0 and total > i:
            left = (now - t0) / (i - i0) * (total - i)
            text += f"  ·  залишилось ~{int(left // 60)}:{int(left % 60):02d}"
        self.progress.setRange(0, total)
        self.progress.setValue(i)
        self.busy_lbl.setText(text)

    def message(self, text: str, warn: bool = False):
        self.statusBar().showMessage(("⚠ " if warn else "") + text, 15000 if warn else 8000)

    def export_table(self, kind: str, header, rows, meta=None):
        default = str(storage.day_dir() / f"{kind}_{dt.datetime.now():%H%M%S}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Експорт", default,
                                              "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        try:
            storage.write_table(path, header, rows, meta)
            self.message(f"Збережено: {path}")
        except Exception as e:
            QMessageBox.warning(self, "Помилка експорту", str(e))

    def open_data(self):
        d = paths.data_root()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ----- connection
    def auto_enabled(self) -> bool:
        return self.autoconnect and str(self.settings.value("connection/auto", True)).lower() in ("true", "1")

    def hotplug(self):
        """Every 2 s: notice the instrument being plugged in, switched on or pulled out."""
        import time
        ports = set(find_ports())
        changed = ports != self.seen_ports
        self.seen_ports = ports
        if changed and not self.connected:
            self.refresh_ports()
        if self.connected and not getattr(self, "demo", False) and self.cur_port not in ports:
            self.on_unplugged()
            return
        if changed:
            self.user_disconnected = False
        if (not self.connected and not self.busy and ports and self.auto_enabled()
                and not self.user_disconnected and (changed or time.monotonic() - self.last_try > 8)):
            self.last_try = time.monotonic()
            self.auto_connect()
        elif not ports and not self.connected and changed:
            self.message("Прилад не знайдено. Під'єднайте USB і ввімкніть прилад — програма підключиться сама. "
                         "Або виберіть «Демо», щоб спробувати програму.")

    def auto_connect(self):
        """Try the remembered port first, then every likely port; quiet — no error windows."""
        last = self.settings.value("connection/last_port", "")
        ports = find_ports()
        ports.sort(key=lambda p: p != last)

        def task(dev, job):
            if self.worker.dev is not None:
                return None
            for port in ports:
                d = V1200(port)
                try:
                    d.connect()
                except Exception:
                    continue
                self.worker.dev = d
                return port, d.model
            return None

        def done(res):
            if res:
                self.set_connected(True, res[1], port=res[0])
            elif ports:
                self.busy_lbl.setText("")
                self.statusBar().showMessage("USB-порт є, але прилад не відповідає. Він увімкнений? "
                                             "Прилад → Підключення… — перевірити вручну.", 9000)

        self.busy_lbl.setText("Шукаю прилад…")
        self.worker.submit(task, done)

    def on_unplugged(self):
        self.worker.request_stop()
        self.kin.stop_ui()

        def task(dev, job):
            if dev is not None:
                try:
                    dev.ser.close()
                except Exception:
                    pass
            self.worker.dev = None
        self.worker.submit(task, lambda _: None)
        self.set_connected(False)
        self.message("Прилад від'єднано від USB. Під'єднайте знову — програма підключиться сама.", warn=True)

    def toggle_connect(self):
        if self.connected:
            self.user_disconnected = True

            def task(dev, job):
                if dev:
                    dev.close()
                self.worker.dev = None
            self.worker.submit(task, lambda _: self.set_connected(False))
            return
        self.connect_to(self.port.currentText())

    def connect_to(self, port: str):
        """Connect to a chosen port (or the demo), showing errors."""
        demo = port == DEMO
        if demo:
            self.sim = FakeSerial()
            self.sim.insert(self.demo_sample.currentData())
        sim = self.sim if demo else None
        self.user_disconnected = False

        def task(dev, job):
            if dev:
                dev.close()
            self.worker.dev = None
            d = V1200("демо", sim) if demo else V1200(port)
            d.connect()
            self.worker.dev = d
            return d.model

        self.busy_lbl.setText("Підключення…")
        self.worker.submit(task, lambda model: self.set_connected(True, model, demo, port))

    def set_connected(self, on: bool, model: str | None = None, demo: bool = False, port: str | None = None):
        self.connected = on
        self.cur_port = port if on else None
        if on and not demo and port:
            self.settings.setValue("connection/last_port", port)
            if self.port.findText(port) < 0:
                self.refresh_ports()
            self.port.setCurrentText(port)
        self.model = model if on else None
        self.demo = demo and on
        self.demo_act.setVisible(self.demo)
        self.b_conn.setText("Відключити" if on else "Підключити")
        self.port.setEnabled(not on)
        if on:
            self.message(f"Підключено: {model}" + (" — демо-режим, усі дані вигадані" if self.demo else ""))
        self.update_pill()
        self.update_enabled()

    def update_pill(self):
        t = self.theme
        if not self.connected:
            text, col = "НЕ ПІДКЛЮЧЕНО", t.muted
        elif getattr(self, "demo", False):
            text, col = "ДЕМО", t.warn
        else:
            text, col = f"● {self.model}", t.success
        self.pill.setText(text)
        self.pill.setStyleSheet(f"background: {col};")

    DEMO_CARRIAGE = {1: "blank", 2: "red", 3: "blue", 4: "kinetic"}

    def on_position(self, pos: int, carriage: dict | None = None):
        """The operator moved the carriage. In demo mode the virtual cuvette changes too."""
        if getattr(self, "demo", False):
            i = self.demo_sample.findData((carriage or self.DEMO_CARRIAGE).get(pos, "blank"))
            self.demo_sample.setCurrentIndex(i)

    # ----- instrument actions
    def go_wl(self):
        wl = self.target_wl()
        self.run(lambda dev, job: dev.set_wavelength(wl), label=f"Перехід на {wl} нм…")

    def do_blank(self, on_done=None):
        wl = self.target_wl()

        def task(dev, job):
            dev.set_wavelength(wl)
            return dev.blank()

        def done(ref):
            self.message(f"Бланк на {ref.wavelength} нм готовий (підсилення {ref.gain}, сигнал {ref.ref:.0f}).")
            if on_done:
                on_done()
        self.run(task, done, label=f"Бланк на {wl} нм…")

    def remeasure_dark(self):
        self.run(lambda dev, job: dev.remeasure_dark(),
                 lambda d: self.message(f"Темновий струм: {d}"), label="Темновий струм…")

    def stop(self):
        self.worker.request_stop()
        self.kin.stop_ui()

    # ----- worker signals
    def on_error(self, text: str):
        self.busy_lbl.setText("")
        if hasattr(self, "proto"):
            self.proto.busy_uid = None
            if self.sim is not None:
                self.sim.custom = None
        self.kin.stop_ui()
        QMessageBox.warning(self, "Прилад", text)

    def on_busy(self, busy: bool):
        self.busy = busy
        if not busy:
            self.busy_lbl.setText("")
            self.progress.setVisible(False)
        self.update_enabled()

    def on_state(self, st):
        if not st:
            self.state_lbl.setText("")
            return
        wl = st["wavelength"]
        ref = st["blank"]
        b = f"бланк {ref.wavelength} нм" if ref and ref.wavelength == int(wl or 0) else "бланку немає"
        self._state_text = f"  прилад: {wl:.0f} нм · {b}"
        self.state_lbl.setText(f"{self._state_text} · кювета: {self.cuvette.short()}")

    def instrument_check(self):
        from .instrument_check import InstrumentCheckDialog
        InstrumentCheckDialog(self).exec()

    def printer_settings(self):
        from .printer import PrinterDialog
        PrinterDialog(self).exec()

    def edit_cuvette(self):
        if CuvetteDialog(self, self.cuvette).exec():
            self.state_lbl.setText(f"{getattr(self, '_state_text', '')} · кювета: {self.cuvette.short()}")
            self.message(f"Кювета: {self.cuvette.text()}")

    def update_enabled(self):
        ok = self.connected and not self.busy
        for w in (self.b_go, self.b_blank, self.wl_spin):
            w.setEnabled(ok)
        self.act_dark.setEnabled(ok)
        self.b_conn.setEnabled(not self.busy)
        self.b_stop.setEnabled(self.busy)
        for tab in (self.photo, self.spec, self.kin, *([self.calib] if hasattr(self, "calib") else [])):
            tab.set_enabled(ok)
        if hasattr(self, "proto"):
            self.proto.update_action()

    def about(self):
        QMessageBox.about(self, "Про SpecRec",
                          f"<b>SpecRec {__version__}</b><br>Керування спектрофотометром Mapada V-1200 "
                          "(ЭКРОС ПЭ-5400В) через USB: фотометрія, спектри, кінетика.<br><br>"
                          f"Папка даних: {paths.data_root()}<br>Ліцензія MIT.")

    def closeEvent(self, e):
        self.worker.shutdown()
        super().closeEvent(e)
