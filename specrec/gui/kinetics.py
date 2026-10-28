"""Kinetics: A(t) at a fixed wavelength.

* one cuvette: a reading every <interval> seconds;
* several cuvettes in the carriage: every cycle the program asks for position 2, 3, ...
  (sound + banner, the operator moves the carriage and presses Space); every sample gets
  its own curve;
* a countdown before the start ("add the reagent now"), a clock while recording,
  reminders at set minutes, markers (M) and a notification at the end;
* automatic analysis of every curve (analysis.py): curve type, initial rate, linear range,
  plateau; the model is drawn on the plot;
* saved files can be opened again for analysis without the instrument.

A manual rate ΔA/min is also computed over the region dragged on the plot.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import re
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .. import storage
from ..analysis import analyze, report_lines
from ..v1200 import InstrumentError
from .common import fmt_a, hint, make_plot, section
from .series import SeriesDialog

# demo mode: what the virtual carriage holds during kinetics
DEMO_CARRIAGE = {1: "blank", 2: "kinetic", 3: "kinetic_slow", 4: "red"}


def fit_line(t: np.ndarray, a: np.ndarray):
    """Slope, intercept, R² of a straight line through the points (NaN dropped)."""
    m = ~np.isnan(a)
    t, a = t[m], a[m]
    if len(t) < 2 or np.ptp(t) == 0:
        return None
    k, b = np.polyfit(t, a, 1)
    ss = np.sum((a - a.mean()) ** 2)
    r2 = 1 - np.sum((a - (k * t + b)) ** 2) / ss if ss > 0 else 1.0
    return k, b, r2, t[0], t[-1], len(t)


def parse_reminders(text: str) -> list[tuple[float, str]]:
    """Lines like "5 — додати інгібітор", "2:30 перемішати", "8.5 хв: ..." -> [(minutes, text)]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+(?:[.,]\d+)?)(?::(\d{1,2}))?\s*(?:хв|min|m)?\.?\s*[—–:\-]?\s*(.*)$", line)
        if not m or not line.strip():
            continue
        minutes = float(m.group(1).replace(",", "."))
        if m.group(2):
            minutes = int(float(m.group(1))) + int(m.group(2)) / 60
        out.append((minutes, m.group(3).strip() or "нагадування"))
    return sorted(out)


def fmt_mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def load_kinetics(path: str | Path) -> tuple[dict, list[dict]]:
    """Read a kinetics CSV written by SpecRec (old two-column or long format)."""
    meta, rows, header = {}, [], None
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if not row:
                continue
            if header is None and row[0].startswith("#"):
                meta[row[0].lstrip("# ").strip()] = row[1] if len(row) > 1 else ""
                continue
            if header is None:
                header = [h.strip() for h in row]
                continue
            rows.append(dict(zip(header, row)))
    if not header or "time_s" not in header or "A" not in header:
        raise ValueError("Це не файл кінетики SpecRec (немає стовпців time_s і A)")
    series: dict[str, dict] = {}
    for r in rows:
        name = r.get("sample") or meta.get("sample") or Path(path).stem
        pos = r.get("position") or ""
        s = series.setdefault(name, {"name": name, "pos": int(pos) if pos.isdigit() else None,
                                     "t": [], "a": []})
        a = r["A"].strip()
        s["t"].append(float(r["time_s"]) / 60)
        s["a"].append(float(a) if a not in ("", "inf", "nan") else np.nan)
    return meta, list(series.values())


def parse_markers(text: str) -> list[tuple[float, str]]:
    out = []
    for part in text.split(";"):
        m = re.match(r"\s*([\d.]+)\s*хв:\s*(.*)", part)
        if m:
            out.append((float(m.group(1)), m.group(2).strip()))
    return out


class KineticsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.series: list[dict] = []     # {name, pos, t[min], a[], curve, fit, model, color, result}
        self.meta: dict = {}
        self.markers: list[tuple[float, str]] = []
        self.marker_items = []
        self.user_region = False
        self.waiting_pos = None
        self.running = False
        self.run_t0 = None               # time.monotonic() of the first point
        self.run_total = 0.0
        self.run_interval = 1.0
        self.reminders: list[tuple[float, str]] = []
        self.countdown_left = 0
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.tick)
        self._last_analysis = 0.0

        ctl = QVBoxLayout()
        ctl.addWidget(section("Параметри"))
        f = QFormLayout()
        self.interval = QDoubleSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setValue(float(win.settings.value("kinetics/interval", 30)))
        self.interval.setSuffix(" с")
        self.interval.setToolTip("Як часто вимірювати. Для каретки — тривалість одного циклу по всіх позиціях.\n"
                                 "1 с — практично безперервний запис.")
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.2, 1440)
        self.duration.setValue(float(win.settings.value("kinetics/duration", 10)))
        self.duration.setSuffix(" хв")
        self.n = QSpinBox()
        self.n.setRange(1, 100)
        self.n.setValue(5)
        self.n.setToolTip("Скільки швидких відліків (~0,02 с кожен) усереднити в одній точці")
        f.addRow("Інтервал:", self.interval)
        f.addRow("Тривалість:", self.duration)
        f.addRow("Усереднення:", self.n)
        ctl.addLayout(f)
        self.points_lbl = hint("")
        ctl.addWidget(self.points_lbl)
        self.interval.valueChanged.connect(self.update_points)
        self.duration.valueChanged.connect(self.update_points)

        ctl.addWidget(section("Таймер і нагадування"))
        f2 = QFormLayout()
        self.countdown = QSpinBox()
        self.countdown.setRange(0, 600)
        self.countdown.setSuffix(" с")
        self.countdown.setSpecialValueText("без відліку")
        self.countdown.setValue(int(win.settings.value("kinetics/countdown", 0)))
        self.countdown.setToolTip("Зворотний відлік перед першою точкою: на «0» запис почнеться (t = 0)")
        self.prep_text = QLineEdit(win.settings.value("kinetics/prep", ""))
        self.prep_text.setPlaceholderText("напр.: додайте H₂O₂ і перемішайте")
        f2.addRow("Відлік:", self.countdown)
        f2.addRow("Що зробити:", self.prep_text)
        ctl.addLayout(f2)
        self.remind = QPlainTextEdit(win.settings.value("kinetics/reminders", ""))
        self.remind.setPlaceholderText("Нагадування під час запису, по рядку:\n"
                                       "5 — додати інгібітор\n8:30 — перемішати")
        self.remind.setFixedHeight(62)
        ctl.addWidget(self.remind)

        self.name = QLineEdit("Кінетика 1")
        ctl.addWidget(self.name)
        self.b_start = QPushButton("Старт (одна кювета)")
        self.b_start.setObjectName("primary")
        self.b_start.setMinimumHeight(34)
        self.b_start.clicked.connect(lambda: self.start())
        ctl.addWidget(self.b_start)
        self.b_multi = QPushButton("Старт з каретки…")
        self.b_multi.setToolTip("Кілька кювет: щоциклу програма просить поставити позиції 2, 3, … по черзі")
        self.b_multi.clicked.connect(self.start_multi)
        ctl.addWidget(self.b_multi)

        # clock while recording
        self.clock_box = QFrame()
        self.clock_box.setObjectName("tile")
        cl = QVBoxLayout(self.clock_box)
        self.clock_lbl = QLabel("00:00")
        self.clock_lbl.setObjectName("tileValue")
        self.clock_lbl.setStyleSheet("font-size: 30px;")
        self.clock_sub = hint("")
        self.b_mark = QPushButton("Позначка  (M)")
        self.b_mark.setToolTip("Поставити позначку на графіку в цей момент (напр. «додав реагент»)")
        self.b_mark.clicked.connect(lambda: self.add_marker())
        cl.addWidget(self.clock_lbl)
        cl.addWidget(self.clock_sub)
        cl.addWidget(self.b_mark)
        self.clock_box.setVisible(False)
        ctl.addWidget(self.clock_box)
        QShortcut(QKeySequence(Qt.Key_M), self, activated=lambda: self.running and self.add_marker())

        # banner: carriage position or countdown
        self.banner = QFrame()
        self.banner.setObjectName("tile")
        bl = QVBoxLayout(self.banner)
        self.banner_lbl = QLabel("")
        self.banner_lbl.setWordWrap(True)
        self.banner_lbl.setStyleSheet("font-size: 17px; font-weight: 600;")
        bl.addWidget(self.banner_lbl)
        self.b_ready = QPushButton("Готово  (Пробіл)")
        self.b_ready.setObjectName("primary")
        self.b_ready.setMinimumHeight(40)
        self.b_ready.clicked.connect(self.confirm)
        bl.addWidget(self.b_ready)
        self.banner.setVisible(False)
        ctl.addWidget(self.banner)
        for key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda: self.waiting_pos is not None and self.confirm())

        ctl.addWidget(hint("Одна кювета: бланк угорі → зразок → «Старт».\n"
                           "Каретка: позиція 1 — бланк, 2–4 — зразки; після сигналу пересуньте "
                           "каретку й натисніть Пробіл.\n"
                           "Виділена ділянка на графіку — ручний розрахунок швидкості."))
        ctl.addWidget(section("Ручна швидкість, ΔA/хв"))
        self.rate = QLabel("—")
        self.rate.setWordWrap(True)
        self.rate.setTextFormat(Qt.RichText)
        ctl.addWidget(self.rate)
        self.rate_hint = hint("")
        ctl.addWidget(self.rate_hint)
        ctl.addStretch()
        row = QHBoxLayout()
        b_open = QPushButton("Відкрити…")
        b_open.setToolTip("Відкрити збережену кінетику (CSV) для аналізу")
        b_open.clicked.connect(lambda: self.open_file())
        b_exp = QPushButton("Експорт…")
        b_exp.clicked.connect(self.export)
        row.addWidget(b_open)
        row.addWidget(b_exp)
        ctl.addLayout(row)
        cw = QWidget()
        cw.setLayout(ctl)
        scroll = QScrollArea()
        scroll.setWidget(cw)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(290)

        t = win.theme
        self.plot = make_plot(t, "Час, хв", "A")
        acc = QColor(t.accent)
        self.region = pg.LinearRegionItem([0, 1], brush=pg.mkBrush(acc.red(), acc.green(), acc.blue(), 30))
        self.region.setZValue(-10)
        self.region.setVisible(False)
        self.region.sigRegionChanged.connect(self.update_rate)
        self.region.sigRegionChangeFinished.connect(lambda: setattr(self, "user_region", True))
        self.plot.addItem(self.region)
        self.title = hint("")

        # automatic analysis under the plot
        an = QFrame()
        an.setObjectName("tile")
        al = QVBoxLayout(an)
        top = QHBoxLayout()
        top.addWidget(section("Автоаналіз"))
        top.addStretch()
        self.show_model = QCheckBox("модель на графіку")
        self.show_model.setChecked(True)
        self.show_model.toggled.connect(self.draw_models)
        top.addWidget(self.show_model)
        b_an = QPushButton("Аналізувати")
        b_an.setToolTip("Перерахувати; виділена ділянка стане лінійною ділянкою першої кривої")
        b_an.clicked.connect(lambda: self.run_analysis(set_region=True))
        top.addWidget(b_an)
        al.addLayout(top)
        self.analysis_lbl = QLabel("Тут з'явиться аналіз кривої: тип (пряма, вихід на плато, лаг-фаза), "
                                   "початкова швидкість, лінійна ділянка, плато.")
        self.analysis_lbl.setWordWrap(True)
        self.analysis_lbl.setTextFormat(Qt.RichText)
        self.analysis_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        al.addWidget(self.analysis_lbl)

        right = QVBoxLayout()
        right.addWidget(self.title)
        right.addWidget(self.plot, 1)
        right.addWidget(an)
        lay = QHBoxLayout(self)
        lay.addWidget(scroll)
        lay.addLayout(right, 1)
        self.update_points()

    # ----- state
    def set_enabled(self, ok: bool):
        self.b_start.setEnabled(ok)
        self.b_multi.setEnabled(ok)

    def update_points(self):
        n = int(self.duration.value() * 60 // self.interval.value()) + 1
        self.points_lbl.setText(f"{n} точок на кожну кювету")

    def clear(self):
        for s in self.series:
            for key in ("curve", "fit", "model"):
                self.plot.removeItem(s[key])
        for it in self.marker_items:
            self.plot.removeItem(it)
        self.marker_items = []
        self.markers = []
        self.series = []
        self.user_region = False
        self.region.setVisible(False)
        self.rate.setText("—")
        self.rate_hint.setText("")
        self.title.setText("")
        self.analysis_lbl.setText("")

    def add_series(self, name: str, pos=None, t=None, a=None) -> dict:
        color = self.win.theme.channels[len(self.series) % len(self.win.theme.channels)]
        s = {"name": name, "pos": pos, "t": list(t or []), "a": list(a or []), "color": color, "result": None}
        s["curve"] = self.plot.plot(s["t"], s["a"], pen=pg.mkPen(color, width=2), symbol="o", symbolSize=5,
                                    symbolBrush=color, symbolPen=None, name=name)
        s["fit"] = self.plot.plot([], [], pen=pg.mkPen(color, width=1.2, style=Qt.DashLine))
        s["model"] = self.plot.plot([], [], pen=pg.mkPen(self.win.theme.text, width=1.6, style=Qt.DotLine))
        self.series.append(s)
        return s

    def full_region(self):
        ts = [x for s in self.series for x in s["t"]]
        if len(ts) >= 2 and not self.user_region:
            self.region.blockSignals(True)
            self.region.setRegion([min(ts), max(ts)])
            self.region.blockSignals(False)
            self.region.setVisible(True)

    # ----- runs
    def _params(self):
        st = self.win.settings
        st.setValue("kinetics/interval", self.interval.value())
        st.setValue("kinetics/duration", self.duration.value())
        st.setValue("kinetics/countdown", self.countdown.value())
        st.setValue("kinetics/prep", self.prep_text.text())
        st.setValue("kinetics/reminders", self.remind.toPlainText())
        return self.win.target_wl(), self.interval.value(), self.duration.value() * 60, self.n.value()

    def start(self, positions=None, blank_first=False):
        """positions: None — one cuvette; otherwise [(pos, name), ...] in the carriage."""
        wl, interval, total, n = self._params()
        ncycles = int(total // interval) + 1
        multi = positions is not None
        if not multi:
            positions = [(None, self.name.text().strip() or "Кінетика")]
        countdown = self.countdown.value()
        prep = self.prep_text.text().strip()
        self.reminders = parse_reminders(self.remind.toPlainText())
        self.clear()
        idx = {}
        for pos, name in positions:
            idx[pos] = len(self.series)
            self.add_series(name, pos)
        started = dt.datetime.now()
        self.meta = {"wavelength_nm": wl, "interval_s": interval, "start": started.isoformat(timespec="seconds"),
                     "mode": "carriage" if multi else "single cuvette",
                     "instrument": self.win.model or "", **self.win.cuvette.meta()}
        if not multi:
            self.meta["sample"] = positions[0][1]
        self.title.setText(f"λ = {wl} нм · {started:%H:%M:%S}")
        self.run_total, self.run_interval, self.run_t0 = (ncycles - 1) * interval, interval, None
        self.running = True
        t_begin = time.monotonic()

        def task(dev, job):
            dev.set_wavelength(wl)
            if blank_first:
                job.ask(1, "бланк")
                if job.stopped:
                    return "stopped"
                dev.blank()
            ref = dev.blank_ref
            if ref is None or ref.wavelength != wl:
                raise InstrumentError(f"Немає бланку на {wl} нм. Поставте кювету з бланком "
                                      f"і натисніть «Бланк».")
            if countdown > 0:
                job.wait_gui(("countdown", countdown, prep))
                if job.stopped:
                    return "stopped"
            t0 = None
            for cycle in range(ncycles):
                if t0 is not None:
                    job.sleep(t0 + cycle * interval - time.monotonic())
                for pos, name in positions:
                    if job.stopped:
                        return "stopped"
                    if multi:
                        job.ask(pos, name)
                        if job.stopped:
                            return "stopped"
                    now = time.monotonic()
                    if t0 is None:
                        t0 = now
                    r = dev.read(ref, n)
                    job.progress(("data", pos, now - t0, r, cycle + 1, ncycles, now))
            return "done"

        def prog(d):
            if d[0] == "ask":
                self.ask(d[1], d[2])
                return
            if d[0] == "countdown":
                self.start_countdown(d[1], d[2])
                return
            _, pos, t, r, cycle, ncyc, now = d
            if self.run_t0 is None:
                self.run_t0 = now
                self.clock_box.setVisible(True)
                self.clock.start(250)
                self.win.notifier.sound("go")
            s = self.series[idx[pos]]
            s["t"].append(t / 60)
            s["a"].append(r.A if not math.isinf(r.A) else np.nan)
            s["curve"].setData(s["t"], s["a"])
            self.full_region()
            self.update_rate()
            if time.monotonic() - self._last_analysis > 3:
                self.run_analysis()
            self.win.set_progress(cycle, ncyc, f"{s['name']}: {t:.0f} с, A = {fmt_a(r)}")

        def done(result):
            self.finish_run()
            if not any(s["t"] for s in self.series):
                return
            self.run_analysis(set_region=True)
            self.meta.update(self.markers_meta())
            self.meta.update(self.analysis_meta())
            path = storage.day_dir() / (f"kinetics_{started:%H%M%S}_"
                                        f"{storage.safe_name(self.series[0]['name'] if not multi else 'carriage')}.csv")
            storage.write_table(path, ["time_s", "position", "sample", "A"], self.long_rows(), self.meta)
            self.win.message(f"Кінетику збережено: {path.name}")
            lines = [f"{s['name']}: {s['result'].summary}" for s in self.series if s["result"]]
            took = time.monotonic() - t_begin
            title = "Кінетику завершено" if result == "done" else "Кінетику зупинено"
            self.win.notifier.notify(title, "\n\n".join(lines) + f"\n\nФайл: {path.name}",
                                     kind="done", popup=took > 20)
            if not multi:
                parts = self.name.text().rsplit(" ", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    self.name.setText(f"{parts[0]} {int(parts[1]) + 1}")

        self.win.run(task, done, prog, label=f"Кінетика на {wl} нм…")

    def start_multi(self):
        dlg = SeriesDialog(self.win, self.win.settings, "Кінетика")
        if not dlg.exec():
            return
        self.start(dlg.result_positions(), blank_first=dlg.blank.isChecked())

    def finish_run(self):
        self.running = False
        self.clock.stop()
        self.clock_box.setVisible(False)
        self.hide_banner()

    # ----- countdown and clock
    def start_countdown(self, seconds: int, prep: str):
        self.countdown_left = seconds
        self.countdown_prep = prep
        self.waiting_pos = "countdown"
        self.b_ready.setText("Почати зараз  (Пробіл)")
        self.banner.setVisible(True)
        self.b_ready.setFocus()
        self.win.notifier.notify("Підготуйтеся", (prep or "Запис почнеться після відліку") +
                                 f"\n\nСтарт через {seconds} с", kind="attention", popup=False)
        self._countdown_step()

    def _countdown_step(self):
        if self.waiting_pos != "countdown":
            return
        left = self.countdown_left
        what = f"<br><span style='font-size:14px'>{self.countdown_prep}</span>" if self.countdown_prep else ""
        self.banner_lbl.setText(f"Старт через <span style='font-size:30px'>{left}</span> с{what}")
        self.win.busy_lbl.setText(f"Відлік: {left} с")
        if left <= 0:
            self.confirm()
            return
        if left <= 3:
            self.win.notifier.sound("tick")
        self.countdown_left -= 1
        QTimer.singleShot(1000, self._countdown_step)

    def tick(self):
        if self.run_t0 is None:
            return
        el = time.monotonic() - self.run_t0
        nxt = self.run_interval - (el % self.run_interval)
        self.clock_lbl.setText(f"{fmt_mmss(el)} / {fmt_mmss(self.run_total)}")
        left = self.run_total - el
        sub = f"залишилось {fmt_mmss(left)}" if left > 0 else "остання точка"
        if self.run_interval >= 3 and left > 0:
            sub += f" · наступна точка через {int(nxt)} с"
        if self.reminders:
            sub += f"\nнагадування: {fmt_mmss(self.reminders[0][0] * 60)} — {self.reminders[0][1]}"
        self.clock_sub.setText(sub)
        while self.reminders and el >= self.reminders[0][0] * 60:
            minutes, text = self.reminders.pop(0)
            self.add_marker(text, minutes)
            self.win.notifier.notify(f"Нагадування · {fmt_mmss(minutes * 60)}", text, kind="attention")

    def add_marker(self, text: str | None = None, minutes: float | None = None):
        if minutes is None:
            if self.run_t0 is None:
                return
            minutes = (time.monotonic() - self.run_t0) / 60
        text = text or f"позначка {len(self.markers) + 1}"
        self.markers.append((minutes, text))
        self._draw_marker(minutes, text)
        self.win.message(f"Позначка {fmt_mmss(minutes * 60)}: {text}")

    def _draw_marker(self, minutes: float, text: str):
        line = pg.InfiniteLine(minutes, angle=90, pen=pg.mkPen(self.win.theme.warn, width=1.5, style=Qt.DashLine),
                               label=text, labelOpts={"position": 0.93, "color": self.win.theme.warn,
                                                      "movable": True, "fill": self.win.theme.plot_bg})
        self.plot.addItem(line)
        self.marker_items.append(line)

    def markers_meta(self) -> dict:
        if not self.markers:
            return {}
        return {"markers": "; ".join(f"{m:.2f} хв: {t}" for m, t in self.markers)}

    # ----- carriage prompt
    def ask(self, pos: int, name: str):
        self.waiting_pos = pos
        self.win.notifier.sound("attention")
        self.b_ready.setText("Готово  (Пробіл)")
        self.banner_lbl.setText(f"Поставте позицію {pos}:\n{name}")
        self.banner.setVisible(True)
        self.b_ready.setFocus()
        self.win.busy_lbl.setText(f"Чекаю позицію {pos}…")

    def confirm(self):
        if self.waiting_pos is None:
            return
        if isinstance(self.waiting_pos, int):
            self.win.on_position(self.waiting_pos, DEMO_CARRIAGE)
        self.waiting_pos = None
        self.banner.setVisible(False)
        self.win.worker.confirm.set()

    def hide_banner(self):
        self.waiting_pos = None
        self.banner.setVisible(False)

    def stop_ui(self):
        """Stop pressed or an error: hide prompts and the clock."""
        self.finish_run()

    # ----- analysis
    def run_analysis(self, set_region: bool = False):
        self._last_analysis = time.monotonic()
        blocks = []
        for s in self.series:
            if len(s["t"]) < 4:
                s["result"] = None
                continue
            r = analyze(s["t"], s["a"])
            s["result"] = r
            lines = report_lines(r)
            blocks.append(f"<span style='color:{s['color']}'>■</span> <b>{s['name']}</b> — {lines[0]}"
                          + "".join(f"<br>&nbsp;&nbsp;• {ln}" for ln in lines[1:]))
        self.analysis_lbl.setText("<br><br>".join(blocks) or "Замало точок для аналізу.")
        self.draw_models()
        first = next((s["result"] for s in self.series if s["result"]), None)
        if set_region and first is not None and first.lin_range and first.kind in ("plateau", "linear"):
            lo, hi = first.lin_range
            self.region.setRegion([lo, hi])
            self.region.setVisible(True)
            self.user_region = True
            self.update_rate()

    def draw_models(self):
        for s in self.series:
            r = s.get("result")
            if r is not None and self.show_model.isChecked() and r.kind != "flat":
                s["model"].setData(r.model_t, r.model_a)
            else:
                s["model"].setData([], [])

    def analysis_meta(self) -> dict:
        out = {}
        for s in self.series:
            if s.get("result"):
                out[f"analysis {s['name']}"] = " | ".join(report_lines(s["result"]))
        return out

    def update_rate(self):
        lo, hi = self.region.getRegion()
        lines, info = [], ""
        for s in self.series:
            t, a = np.asarray(s["t"], float), np.asarray(s["a"], float)
            m = (t >= lo - 1e-9) & (t <= hi + 1e-9)
            res = fit_line(t[m], a[m]) if m.any() else None
            if res is None:
                s["fit"].setData([], [])
                continue
            k, b, r2, t1, t2, npts = res
            s["fit"].setData([t1, t2], [k * t1 + b, k * t2 + b])
            s["rate"] = (k, r2, npts)
            lines.append(f"<span style='color:{s['color']}'>■</span> {s['name']}: "
                         f"<b style='font-family:Menlo,monospace'>{k:+.4f}</b> "
                         f"<span style='color:gray'>(R² {r2:.3f})</span>")
            info = f"ділянка {t1:.2f}–{t2:.2f} хв"
        self.rate.setText("<br>".join(lines) or "—")
        self.rate_hint.setText(info)

    def long_rows(self) -> list[list]:
        rows = [[t * 60, s["pos"] or "", s["name"], a] for s in self.series for t, a in zip(s["t"], s["a"])]
        return sorted(rows, key=lambda r: r[0])

    def open_file(self, path: str | None = None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Відкрити кінетику", str(storage.day_dir().parent),
                                                  "Кінетика SpecRec (kinetics_*.csv *.csv)")
            if not path:
                return
        try:
            meta, series = load_kinetics(path)
        except Exception as e:
            QMessageBox.warning(self, "Не вдалося відкрити", str(e))
            return
        self.clear()
        self.meta = {k: v for k, v in meta.items() if not k.startswith("analysis ")}
        for s in series:
            self.add_series(s["name"], s["pos"], s["t"], s["a"])
        for m, text in parse_markers(meta.get("markers", "")):
            self.markers.append((m, text))
            self._draw_marker(m, text)
        self.full_region()
        self.run_analysis(set_region=True)
        wl = meta.get("wavelength_nm", "?")
        self.title.setText(f"Файл: {Path(path).name} · λ = {wl} нм · старт {meta.get('start', '?')}")

    def export(self):
        if not self.series:
            return
        rows = [[t, round(t / 60, 4), p, name, a] for t, p, name, a in self.long_rows()]
        rates = {f"ΔA/хв {s['name']}": f"{s['rate'][0]:.5f} (R² {s['rate'][1]:.4f}, {s['rate'][2]} точок)"
                 for s in self.series if "rate" in s}
        lo, hi = self.region.getRegion()
        meta = dict(self.meta, **rates, **({"ділянка, хв": f"{lo:.2f}–{hi:.2f}"} if rates else {}),
                    **self.markers_meta(), **self.analysis_meta())
        self.win.export_table("kinetics", ["Час, с", "Час, хв", "Поз.", "Зразок", "A"], rows, meta)
