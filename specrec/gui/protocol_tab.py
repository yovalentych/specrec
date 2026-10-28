"""Protocol tab: a guided series by a protocol (protocol.py) — the list of tubes with what to
do next, per-tube timers with notifications, multi-wavelength reads, results with quality
flags and group statistics, autosave and resume."""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .. import storage
from ..protocol import (NAN, Run, copy_to_user, evaluate, import_samples, isnum, load_library,
                        protocols_dir)
from ..v1200 import InstrumentError
from .common import hint, section


def fmt_mmss(sec: float) -> str:
    sec = max(0, int(math.ceil(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_num(v, digits=3, percent=False) -> str:
    if not isnum(v):
        return "—"
    return f"{v * 100:.{digits}f}" if percent else f"{v:.{digits}f}"


class PrepDialog(QDialog):
    """What the protocol is, what to prepare (a checklist), the tubes and the formulas."""

    def __init__(self, parent, p: dict):
        super().__init__(parent)
        self.setWindowTitle(p.get("name", "Протокол"))
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        info = QTextBrowser()
        tubes = "".join(
            f"<li><b>{d['label'].format(i='N', x='x')}</b> — "
            f"{'на серію' if d.get('per') != 'sample' else 'на зразок'}"
            f"{'' if 'count' not in d else ' × ' + str(d['count'])}"
            f"{' (нуль приладу)' if d.get('zero') else ''}: "
            + " → ".join(st.get("do") or (f"вимір {st['read']} при {', '.join(map(str, st['wl']))} нм"
                                         if "read" in st else f"чекати {fmt_mmss(st['wait'])}")
                         for st in d["steps"]) + "</li>"
            for d in p.get("tubes", {}).values())
        formulas = "".join(f"<li><tt>{k} = {v}</tt></li>" for sec in ("series_calc", "sample_calc")
                           for k, v in p.get(sec, {}).items())
        for t, calc in p.get("tube_calc", {}).items():
            formulas += "".join(f"<li><tt>{t}: {k} = {v}</tt></li>" for k, v in calc.items())
        const = ", ".join(f"{k} = {v}" for k, v in p.get("constants", {}).items())
        cal = p.get("calibration")
        cal_txt = (f"<p><b>Калібрування:</b> {', '.join(map(str, cal['x']))} {cal.get('unit', '')} → нахил "
                   f"<tt>{cal.get('prefix', 'cal')}_slope</tt></p>") if cal else ""
        info.setHtml(f"<h3>{p.get('name')}</h3><p><i>{p.get('source', '')}</i></p><p>{p.get('description', '')}</p>"
                     f"<p><b>Пробірки:</b></p><ul>{tubes}</ul>{cal_txt}"
                     f"<p><b>Формули:</b></p><ul>{formulas}</ul><p><b>Сталі:</b> {const or '—'}</p>")
        lay.addWidget(info, 1)
        if p.get("prep"):
            lay.addWidget(section("Підготовка — відмітьте, що готово"))
            self.check = QListWidget()
            for item in p["prep"]:
                it = QListWidgetItem(item)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
                self.check.addItem(it)
            self.check.setMaximumHeight(170)
            lay.addWidget(self.check)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


class ProtocolTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.library: list = []
        self.run: Run | None = None
        self.refs: dict = {}               # wavelength -> Reference (from the zero tube)
        self.session_path: Path | None = None
        self.last_start = None             # epoch of the last tube start (for the stagger hint)
        self.timers: dict[str, float] = {}  # protocol timers: label -> end epoch
        self.busy_uid = None

        # ---- top: choice of protocol
        top = QHBoxLayout()
        top.addWidget(QLabel("Протокол:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(320)
        self.combo.currentIndexChanged.connect(self.protocol_changed)
        top.addWidget(self.combo)
        b = QPushButton("Опис і підготовка…")
        b.clicked.connect(self.show_prep)
        top.addWidget(b)
        b = QPushButton("Змінити (моя копія)…")
        b.setToolTip("Зберегти копію протоколу як файл JSON і відкрити його для редагування "
                     "(об'єми, формули, довжини хвиль, перевірки)")
        b.clicked.connect(self.edit_copy)
        top.addWidget(b)
        b = QPushButton("Папка протоколів")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(protocols_dir()))))
        top.addWidget(b)
        b = QPushButton("⟳")
        b.setToolTip("Перечитати протоколи з папки (після редагування)")
        b.setFixedWidth(34)
        b.clicked.connect(self.reload)
        top.addWidget(b)
        top.addStretch()
        self.session_lbl = hint("")
        top.addWidget(self.session_lbl)

        # ---- left: samples, start, timers
        left = QVBoxLayout()
        left.addWidget(section("Зразки (тварини)"))
        self.samples = QTableWidget(0, 2)
        self.samples.setHorizontalHeaderLabels(["Код", "Група"])
        self.samples.verticalHeader().setVisible(False)
        self.samples.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.samples.itemChanged.connect(self.sample_edited)
        left.addWidget(self.samples, 1)
        row = QHBoxLayout()
        b = QPushButton("+")
        b.setFixedWidth(34)
        b.clicked.connect(lambda: self.add_sample_row("", ""))
        row.addWidget(b)
        b = QPushButton("−")
        b.setFixedWidth(34)
        b.clicked.connect(self.remove_sample_rows)
        row.addWidget(b)
        b = QPushButton("Імпорт із журналу…")
        b.setToolTip("Код і група тварин з Excel (аркуш «Зразки»)")
        b.clicked.connect(self.import_journal)
        row.addWidget(b)
        left.addLayout(row)
        self.b_new = QPushButton("Почати серію")
        self.b_new.setObjectName("primary")
        self.b_new.setMinimumHeight(34)
        self.b_new.clicked.connect(self.new_run)
        left.addWidget(self.b_new)
        b = QPushButton("Продовжити збережену…")
        b.clicked.connect(self.resume)
        left.addWidget(b)
        self.n = QSpinBox()
        self.n.setRange(1, 50)
        self.n.setValue(10)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Усереднення:"))
        r2.addWidget(self.n)
        left.addLayout(r2)
        left.addWidget(section("Таймери протоколу"))
        self.timer_box = QVBoxLayout()
        left.addLayout(self.timer_box)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(290)

        # ---- center: tubes and the action for the selected tube
        center = QVBoxLayout()
        self.head = QLabel("Виберіть протокол, додайте зразки й натисніть «Почати серію».")
        self.head.setWordWrap(True)
        center.addWidget(self.head)
        self.tubes = QTableWidget(0, 5)
        self.tubes.setHorizontalHeaderLabels(["Пробірка", "Зразок", "Що далі", "Таймер", "Виміряно"])
        self.tubes.verticalHeader().setVisible(False)
        self.tubes.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tubes.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tubes.setSelectionMode(QAbstractItemView.SingleSelection)
        hh = self.tubes.horizontalHeader()
        for c, w in ((0, 190), (1, 95), (3, 56), (4, 170)):
            hh.setSectionResizeMode(c, QHeaderView.Interactive)
            self.tubes.setColumnWidth(c, w)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tubes.setWordWrap(False)
        self.tubes.setTextElideMode(Qt.ElideRight)
        self.tubes.itemSelectionChanged.connect(self.update_action)
        center.addWidget(self.tubes, 1)

        act = QFrame()
        act.setObjectName("tile")
        al = QVBoxLayout(act)
        self.act_lbl = QLabel("")
        self.act_lbl.setWordWrap(True)
        self.act_lbl.setStyleSheet("font-size: 16px; font-weight: 600;")
        al.addWidget(self.act_lbl)
        ar = QHBoxLayout()
        self.b_act = QPushButton("—")
        self.b_act.setObjectName("primary")
        self.b_act.setMinimumHeight(42)
        self.b_act.clicked.connect(self.do_action)
        ar.addWidget(self.b_act, 1)
        self.b_redo = QPushButton("Повторити вимір")
        self.b_redo.setToolTip("Стерти останній вимір цієї пробірки й зробити ще раз")
        self.b_redo.clicked.connect(self.redo)
        ar.addWidget(self.b_redo)
        al.addLayout(ar)
        self.auto_next = QCheckBox("Після дії переходити до наступної пробірки")
        self.auto_next.setChecked(True)
        al.addWidget(self.auto_next)
        self.stagger_lbl = hint("")
        al.addWidget(self.stagger_lbl)
        center.addWidget(act)
        for key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            QShortcut(QKeySequence(key), self, activated=lambda: self.b_act.isEnabled() and self.do_action())
        cw = QWidget()
        cw.setLayout(center)

        # ---- right: results
        self.res_tabs = QTabWidget()
        self.res_table = QTableWidget(0, 0)
        self.res_table.verticalHeader().setVisible(False)
        self.res_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.series_view = QTextBrowser()
        self.groups_view = QTextBrowser()
        self.res_tabs.addTab(self.res_table, "Результати")
        self.res_tabs.addTab(self.series_view, "Серія і контроль якості")
        self.res_tabs.addTab(self.groups_view, "Групи")
        rw = QWidget()
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.res_tabs, 1)
        b = QPushButton("Експорт у Excel…")
        b.clicked.connect(self.export)
        rl.addWidget(b)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(cw)
        split.addWidget(rw)
        split.setSizes([700, 460])
        body = QHBoxLayout()
        body.addWidget(lw)
        body.addWidget(split, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(body, 1)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.tick)
        self.clock.start(1000)
        self.reload()
        for code, grp in json.loads(win.settings.value("protocol/samples", "[]") or "[]"):
            self.add_sample_row(code, grp)

    # ---------------------------------------------------------------- library
    def reload(self):
        cur = self.combo.currentData()
        self.library = load_library()
        self.combo.blockSignals(True)
        self.combo.clear()
        for i, (p, path, errs) in enumerate(self.library):
            label = p.get("name", p.get("id"))
            if path:
                label = "✎ " + label
            if errs:
                label += "  ⚠"
            self.combo.addItem(label, i)
        self.combo.blockSignals(False)
        last = cur if cur is not None else self.win.settings.value("protocol/last", "mda")
        idx = next((i for i, (p, _, _) in enumerate(self.library) if p.get("id") == last), 0) \
            if isinstance(last, str) else (last if last is not None and last < len(self.library) else 0)
        self.combo.setCurrentIndex(idx)
        self.protocol_changed()

    def protocol(self) -> dict:
        return self.library[self.combo.currentIndex()][0]

    def protocol_changed(self):
        if not self.library:
            return
        p, path, errs = self.library[self.combo.currentIndex()]
        self.win.settings.setValue("protocol/last", p.get("id"))
        if errs:
            QMessageBox.warning(self, "Протокол з помилками", f"{path}\n\n" + "\n".join(errs))
        # sample inputs as extra columns
        inputs = p.get("inputs", {})
        self.samples.blockSignals(True)
        rows = [(self._cell(r, 0), self._cell(r, 1)) for r in range(self.samples.rowCount())]
        self.samples.setColumnCount(2 + len(inputs))
        self.samples.setHorizontalHeaderLabels(["Код", "Група"] + [v["label"] for v in inputs.values()])
        for r, _ in enumerate(rows):
            for j, (k, v) in enumerate(inputs.items(), 2):
                if self.samples.item(r, j) is None:
                    self.samples.setItem(r, j, QTableWidgetItem(f"{v.get('default', 1):g}"))
        self.samples.blockSignals(False)
        # protocol timers
        while self.timer_box.count():
            w = self.timer_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.timer_widgets = {}
        for tdef in p.get("timers", []):
            rowW = QWidget()
            rl = QHBoxLayout(rowW)
            rl.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(tdef["label"])
            lab.setWordWrap(True)
            cnt = QLabel("")
            cnt.setObjectName("mono")
            btn = QPushButton("Старт")
            btn.setFixedWidth(64)
            btn.clicked.connect(lambda _=False, t=tdef: self.toggle_timer(t))
            rl.addWidget(lab, 1)
            rl.addWidget(cnt)
            rl.addWidget(btn)
            self.timer_box.addWidget(rowW)
            self.timer_widgets[tdef["label"]] = (cnt, btn)
        if not p.get("timers"):
            self.timer_box.addWidget(hint("немає"))

    def show_prep(self):
        PrepDialog(self, self.run.p if self.run else self.protocol()).exec()

    def edit_copy(self):
        p, path, _ = self.library[self.combo.currentIndex()]
        if path is None:
            path = copy_to_user(p)
            QMessageBox.information(self, "Моя копія протоколу",
                                    f"Збережено копію:\n{path}\n\nЗараз вона відкриється в текстовому редакторі. "
                                    "Змініть, збережіть і натисніть ⟳ біля списку протоколів.\n"
                                    "Опис формату — у docs/PROTOCOLS.md.")
            self.reload()
            idx = next(i for i, (_, f, _) in enumerate(self.library) if f == path)
            self.combo.setCurrentIndex(idx)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---------------------------------------------------------------- samples
    def _cell(self, r, c) -> str:
        it = self.samples.item(r, c)
        return it.text().strip() if it else ""

    def add_sample_row(self, code, group):
        self.samples.blockSignals(True)
        r = self.samples.rowCount()
        self.samples.insertRow(r)
        self.samples.setItem(r, 0, QTableWidgetItem(code))
        self.samples.setItem(r, 1, QTableWidgetItem(group))
        for j, v in enumerate(self.protocol().get("inputs", {}).values(), 2) if self.library else []:
            self.samples.setItem(r, j, QTableWidgetItem(f"{v.get('default', 1):g}"))
        self.samples.blockSignals(False)
        self.save_samples()

    def remove_sample_rows(self):
        for r in sorted({i.row() for i in self.samples.selectedIndexes()}, reverse=True):
            self.samples.removeRow(r)
        self.save_samples()

    def save_samples(self):
        rows = [[self._cell(r, 0), self._cell(r, 1)] for r in range(self.samples.rowCount())]
        self.win.settings.setValue("protocol/samples", json.dumps(rows, ensure_ascii=False))

    def sample_rows(self) -> list[dict]:
        inputs = list(self.protocol().get("inputs", {}))
        out = []
        for r in range(self.samples.rowCount()):
            code = self._cell(r, 0)
            if not code:
                continue
            vals = {}
            for j, k in enumerate(inputs, 2):
                try:
                    vals[k] = float(self._cell(r, j).replace(",", "."))
                except ValueError:
                    vals[k] = 1.0
            out.append({"code": code, "group": self._cell(r, 1), "inputs": vals})
        return out

    def sample_edited(self, item):
        self.save_samples()
        if self.run is None:
            return
        # inputs (dilution …) may change during the series: update and recompute
        code = self._cell(item.row(), 0)
        for s in self.run.samples:
            if s["code"] == code:
                for j, k in enumerate(self.run.p.get("inputs", {}), 2):
                    try:
                        s["inputs"][k] = float(self._cell(item.row(), j).replace(",", "."))
                    except ValueError:
                        pass
        self.refresh()

    def import_journal(self):
        path, _ = QFileDialog.getOpenFileName(self, "Журнал з таблицею зразків", str(Path.home() / "Downloads"),
                                              "Excel (*.xlsx)")
        if not path:
            return
        try:
            rows = import_samples(path)
        except Exception as e:
            QMessageBox.warning(self, "Імпорт", str(e))
            return
        self.samples.setRowCount(0)
        for r in rows:
            self.add_sample_row(r["code"], r["group"])
        groups = sorted({r["group"] for r in rows if r["group"]})
        self.win.message(f"Імпортовано {len(rows)} зразків" + (f" (групи: {', '.join(groups)})" if groups else ""))

    # ---------------------------------------------------------------- run
    def new_run(self):
        samples = self.sample_rows()
        if not samples:
            QMessageBox.information(self, "Немає зразків", "Додайте зразки (кнопка «+» або «Імпорт із журналу»).")
            return
        if self.run and any(t.reads for t in self.run.tubes) and QMessageBox.question(
                self, "Нова серія", "Почати нову серію? Поточна вже збережена й її можна продовжити пізніше.") \
                != QMessageBox.Yes:
            return
        p = self.protocol()
        if abs(self.win.cuvette.path_mm - 10) > 0.05 and any("eps" in k for k in p.get("constants", {})):
            if QMessageBox.question(
                    self, "Кювета", f"Формули протоколу з ε розраховані на шлях 10 мм, а зараз вибрано "
                    f"{self.win.cuvette.text()}.\nРезультати треба буде перерахувати (× 10 / шлях).\n\n"
                    "Почати серію все одно?") != QMessageBox.Yes:
                return
        low = [w for w in Run(p, samples[:1]).wavelengths() if w < self.win.cuvette.cutoff]
        if low:
            self.win.message(f"Кювета ({self.win.cuvette.text()}) погано пропускає на {low} нм", warn=True)
        self.run = Run(p, samples)
        self.run.notes = f"кювета: {self.win.cuvette.text()}"
        self.refs = {}
        self.session_path = storage.day_dir() / f"protocol_{p['id']}_{self.run.started:%H%M%S}.json"
        self.last_start = None
        self.autosave()
        self.fill_tubes()
        self.refresh()
        if p.get("prep"):
            PrepDialog(self, p).exec()

    def resume(self):
        path, _ = QFileDialog.getOpenFileName(self, "Продовжити серію", str(storage.day_dir()),
                                              "Серія протоколу (protocol_*.json)")
        if not path:
            return
        try:
            self.run = Run.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
        except Exception as e:
            QMessageBox.warning(self, "Не вдалося відкрити", str(e))
            return
        self.session_path = Path(path)
        self.refs = {}
        zero = self.run.zero_tube()
        if zero is not None:            # the zero of the instrument does not survive a restart
            zero.step, zero.reads = 0, {}
        self.fill_tubes()
        self.refresh()
        self.win.message("Серію відкрито. Спершу знову поставте нуль приладу (перша пробірка).")

    def autosave(self):
        if self.run and self.session_path:
            try:
                self.run.save(self.session_path)
            except OSError as e:
                self.win.message(f"Не вдалося зберегти серію: {e}", warn=True)

    # ---------------------------------------------------------------- tubes table
    def fill_tubes(self):
        self.tubes.setRowCount(0)
        for t in self.run.tubes:
            r = self.tubes.rowCount()
            self.tubes.insertRow(r)
            it = QTableWidgetItem(t.label)
            it.setToolTip(t.label)
            self.tubes.setItem(r, 0, it)
            self.tubes.setItem(r, 1, QTableWidgetItem(t.sample or "серія"))
            for c in (2, 3, 4):
                self.tubes.setItem(r, c, QTableWidgetItem(""))
        self.select(self.run.next_tube())

    def row_of(self, tube) -> int:
        return self.run.tubes.index(tube)

    def select(self, tube):
        if tube is None:
            self.update_action()
            return
        self.tubes.selectRow(self.row_of(tube))
        self.tubes.scrollToItem(self.tubes.item(self.row_of(tube), 0))

    def selected(self):
        rows = {i.row() for i in self.tubes.selectedIndexes()}
        return self.run.tubes[rows.pop()] if self.run and rows else None

    def step_text(self, tube, now) -> tuple[str, str]:
        st = self.run.state(tube, now)
        cur = self.run.current(tube)
        if st == "done":
            return "✓ готово", ""
        if st == "do":
            return f"▶ {cur['do']}", ""
        if st == "read":
            return f"⦿ вимір {cur['read']} при {', '.join(map(str, cur['wl']))} нм", ""
        left = tube.due - now
        return f"⏳ {cur.get('text', 'чекати')}", fmt_mmss(left)

    def refresh_tubes(self):
        if not self.run:
            return
        now = time.time()
        t = self.win.theme
        for r, tube in enumerate(self.run.tubes):
            what, timer = self.step_text(tube, now)
            st = self.run.state(tube, now)
            vals = self.values_text(tube)
            for c, text in ((2, what), (3, timer), (4, vals)):
                it = self.tubes.item(r, c)
                if it.text() != text:
                    it.setText(text)
            col = {"done": t.muted, "wait": t.warn, "ready": t.danger, "read": t.accent, "do": t.text}[st]
            self.tubes.item(r, 2).setForeground(QColor(col))
            self.tubes.item(r, 3).setForeground(QColor(t.warn))

    def values_text(self, tube) -> str:
        parts = []
        for st in self.run.steps(tube):
            if "read" not in st:
                continue
            name = st["read"]
            for w in st["wl"]:
                v = tube.reads.get(f"{name}_{w}")
                if v is not None:
                    parts.append(f"{name}{'' if len(st['wl']) == 1 else '·' + str(w)} = {v:.3f}"
                                 if isnum(v) else f"{name} = —")
        return "   ".join(parts)

    # ---------------------------------------------------------------- the action
    def update_action(self):
        tube = self.selected() if self.run else None
        if tube is None:
            self.act_lbl.setText("Усі пробірки виміряно ✓" if self.run else "")
            self.b_act.setText("—")
            self.b_act.setEnabled(False)
            self.b_redo.setEnabled(False)
            return
        now = time.time()
        st = self.run.state(tube, now)
        cur = self.run.current(tube)
        who = f"{tube.label}" + (f" · {tube.sample}" if tube.sample else "")
        self.b_redo.setEnabled(bool(tube.reads) and self.busy_uid is None)
        if st == "done":
            self.act_lbl.setText(f"{who}: готово")
            self.b_act.setText("Готово ✓")
            self.b_act.setEnabled(False)
        elif st == "do":
            self.act_lbl.setText(f"{who}\n{cur['do']}")
            self.b_act.setText("Зроблено  (Пробіл)")
            self.b_act.setEnabled(self.busy_uid is None)
        elif st == "read":
            zero = self.run.tube_def(tube.type).get("zero")
            self.act_lbl.setText(f"{who}\nПоставте кювету в прилад" + (" — це нуль приладу" if zero else ""))
            self.b_act.setText(f"Виміряти {cur['read']}: {', '.join(map(str, cur['wl']))} нм  (Пробіл)")
            self.b_act.setEnabled(self.win.connected and self.busy_uid is None and not self.win.busy)
        else:
            self.act_lbl.setText(f"{who}\n{cur.get('text', 'чекати')} — ще {fmt_mmss(tube.due - now)}")
            self.b_act.setText("Чекаю…")
            self.b_act.setEnabled(False)

    def do_action(self):
        tube = self.selected()
        if tube is None:
            return
        st = self.run.state(tube)
        if st in ("do", "ready"):
            first = tube.step == 0
            self.run.confirm(tube)
            if first and self.run.p.get("stagger"):
                self.last_start = time.time()
            self.after_change(tube)
        elif st == "read":
            self.measure(tube)

    def measure(self, tube):
        cur = self.run.current(tube)
        wls = sorted(cur["wl"])
        zero = self.run.tube_def(tube.type).get("zero")
        n = self.n.value()
        if not zero:
            missing = [w for w in wls if w not in self.refs]
            if missing:
                QMessageBox.information(self, "Спершу нуль",
                                        f"Немає нуля приладу на {', '.join(map(str, missing))} нм.\n"
                                        f"Виміряйте пробірку «{self.run.zero_tube().label}».")
                self.select(self.run.zero_tube())
                return
        if getattr(self.win, "demo", False) and self.win.sim is not None:
            self.win.sim.custom = {w: (0.0 if zero else self.demo_value(tube, cur["read"], w)) for w in wls}
        refs = self.refs

        def task(dev, job):
            out = {}
            for w in wls:
                dev.set_wavelength(w)
                if zero:
                    refs[w] = dev.quick_reference(n)
                    out[w] = (0.0, False)
                else:
                    r = dev.read(refs[w], n)
                    out[w] = (r.A, r.saturated)
            return out

        def done(out):
            self.busy_uid = None
            if self.win.sim is not None:
                self.win.sim.custom = None
            self.run.record(tube, {w: (a if math.isfinite(a) else NAN) for w, (a, _) in out.items()})
            if zero:
                self.run.refs_ready = True
            sat = [w for w, (_, s) in out.items() if s]
            if sat:
                self.win.message(f"{tube.label}: на {', '.join(map(str, sat))} нм сигнал зашкалює — "
                                 "зразок світліший за нуль, перевірте нульову пробірку", warn=True)
            self.after_change(tube)

        self.busy_uid = tube.uid
        self.update_action()
        self.win.run(task, done, label=f"{tube.label}: {', '.join(map(str, wls))} нм…")

    def redo(self):
        tube = self.selected()
        if tube is None or not tube.reads:
            return
        steps = self.run.steps(tube)
        done_reads = [i for i, st in enumerate(steps[:tube.step]) if "read" in st]
        if not done_reads:
            return
        last = done_reads[-1]
        name = steps[last]["read"]
        tube.reads = {k: v for k, v in tube.reads.items() if not (k == name or k.startswith(name + "_"))}
        tube.step = last
        tube.due = None
        if self.run.tube_def(tube.type).get("zero"):
            self.refs = {}
        self.after_change(tube, move=False)

    def after_change(self, tube, move=True):
        self.autosave()
        self.refresh()
        if move and self.auto_next.isChecked() and self.run.state(tube) not in ("do", "read"):
            nxt = self.run.next_tube()
            if nxt is not None:
                self.select(nxt)
        self.update_action()
        if all(self.run.state(t) == "done" for t in self.run.tubes):
            self.win.notifier.notify("Серію завершено", f"{self.run.p['name']}: усі пробірки виміряно. "
                                     "Результати — праворуч; «Експорт у Excel…» збереже таблицю.", kind="done")

    def demo_value(self, tube, read: str, wl: int) -> float:
        spec = self.run.p.get("demo", {}).get(tube.type, {})
        v = spec.get(f"{read}_{wl}", spec.get(read))
        rnd = random.Random(f"{tube.sample}:{tube.type}:{read}:{wl}:{tube.uid}")
        if isinstance(v, list):
            lo, hi = v
            # one level per sample (so that duplicates agree) plus a little scatter
            base = random.Random(f"{tube.sample}:{tube.type}:{read}:{wl}").uniform(lo, hi)
            return base * (1 + rnd.gauss(0, 0.02))
        if isinstance(v, str):
            return float(evaluate(v, {"x": tube.x or 0.0})) * (1 + rnd.gauss(0, 0.01))
        return rnd.uniform(0.05, 0.3)

    # ---------------------------------------------------------------- clock
    def tick(self):
        now = time.time()
        for label, end in list(self.timers.items()):
            cnt, btn = self.timer_widgets.get(label, (None, None))
            if cnt is None:
                continue
            if now >= end:
                del self.timers[label]
                cnt.setText("")
                btn.setText("Старт")
                self.win.notifier.notify("Таймер", f"{label}: час вийшов", kind="attention")
            else:
                cnt.setText(fmt_mmss(end - now))
        if not self.run:
            return
        for tube in self.run.tick(now):
            nxt = self.run.current(tube)
            what = (nxt.get("do") or f"вимір {nxt.get('read')}") if nxt else "готово"
            self.win.notifier.notify(f"{tube.label}" + (f" · {tube.sample}" if tube.sample else ""),
                                     f"Час: {what}", kind="attention", popup=False)
            self.autosave()
            if self.busy_uid is None and self.auto_next.isChecked():
                self.select(tube)
        stg = self.run.p.get("stagger")
        if stg and self.last_start:
            left = self.last_start + stg - now
            if left > 0:
                self.stagger_lbl.setText(f"Наступну пробірку можна запускати через {fmt_mmss(left)}")
            else:
                if self.stagger_lbl.text().startswith("Наступну пробірку можна запускати через"):
                    self.win.notifier.sound("tick")
                self.stagger_lbl.setText(f"Можна запускати наступну пробірку (зсув {stg} с)")
        self.refresh_tubes()
        self.update_action()

    def toggle_timer(self, tdef):
        label = tdef["label"]
        cnt, btn = self.timer_widgets[label]
        if label in self.timers:
            del self.timers[label]
            cnt.setText("")
            btn.setText("Старт")
        else:
            self.timers[label] = time.time() + float(tdef["seconds"])
            btn.setText("Стоп")
            self.win.notifier.sound("go")

    # ---------------------------------------------------------------- results
    def refresh(self):
        if not self.run:
            return
        self.refresh_tubes()
        try:
            c = self.run.compute()
        except Exception as e:
            self.series_view.setHtml(f"<p style='color:red'>Помилка у формулах протоколу: {e}</p>")
            return
        p = self.run.p
        done = sum(self.run.state(t) == "done" for t in self.run.tubes)
        zero = "нуль ✓" if self.refs else "нуль приладу ще не виміряно"
        self.head.setText(f"<b>{p['name']}</b> · {self.run.started:%d.%m %H:%M} · пробірок {done}/{len(self.run.tubes)} · {zero}")
        self.session_lbl.setText(f"автозбереження: {self.session_path.name}" if self.session_path else "")
        # results
        res = p.get("results", [])
        self.res_table.setColumnCount(2 + len(res) + 1)
        self.res_table.setHorizontalHeaderLabels(["Код", "Група"] + [f"{r['label']}, {r['unit']}".rstrip(", ")
                                                                    for r in res] + ["Прапорці"])
        self.res_table.setRowCount(len(c["samples"]))
        for i, s in enumerate(c["samples"]):
            cells = [s["code"], s["group"]] + [fmt_num(s["res"].get(r["var"]), r.get("digits", 3), r.get("percent"))
                                               for r in res] + ["; ".join(s["flags"]) or ("OK" if s["complete"] else "")]
            for j, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if j == len(cells) - 1 and s["flags"]:
                    it.setForeground(QColor(self.win.theme.danger))
                if 2 <= j < len(cells) - 1:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.res_table.setItem(i, j, it)
        self.res_table.resizeColumnsToContents()
        # series
        sv = "".join(f"<tr><td><tt>{k}</tt></td><td align=right>{fmt_num(v, 4)}</td></tr>"
                     for k, v in c["series"].items() if k not in p.get("constants", {}) and not callable(v))
        fl = "".join(f"<li style='color:#cf2e2e'>{f}</li>" for f in c["series_flags"]) or "<li>OK</li>"
        cal = ""
        fit = getattr(self.run, "cal_fit", None)
        if p.get("calibration"):
            cal = (f"<p><b>Калібрування:</b> {fit.equation(p['calibration'].get('unit', ''))}, "
                   f"R² = {fit.r2:.4f}, n = {fit.n}</p>" if fit else "<p><b>Калібрування:</b> ще замало точок</p>")
        self.series_view.setHtml(f"<h4>Контроль якості серії</h4><ul>{fl}</ul>{cal}"
                                 f"<h4>Показники серії</h4><table>{sv}</table>")
        # groups
        rows = self.run.group_stats(c)
        html = ""
        for row in rows:
            html += f"<h4>{row['label']}, {row['unit']}</h4><table cellpadding=3><tr><th>Група</th><th>n</th>" \
                    "<th>Середнє</th><th>SD</th><th>Зміна</th><th>p (Велч)</th></tr>"
            for g, st in row["groups"].items():
                ch = f"{st['change'] * 100:+.0f} %" if isnum(st.get("change")) else ""
                pv = f"{st['p']:.3f}" if isnum(st.get("p")) else ""
                html += (f"<tr><td>{g}{' (порівняння)' if g == row['ref'] else ''}</td><td>{st['n']}</td>"
                         f"<td>{fmt_num(st['mean'], 3)}</td><td>{fmt_num(st['sd'], 3)}</td><td>{ch}</td><td>{pv}</td></tr>")
            html += "</table>"
        self.groups_view.setHtml(html + "<p><i>t-тест Велча орієнтовний при малих n; дублікати усереднено, "
                                        "n — кількість тварин.</i></p>" if rows else "")

    def export(self):
        if not self.run:
            return
        c = self.run.compute()
        p = self.run.p
        res = p.get("results", [])
        default = str(storage.day_dir() / f"{p['id']}_{self.run.started:%Y%m%d_%H%M}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Експорт", default, "Excel (*.xlsx)")
        if not path:
            return
        head = ["Код", "Група"] + [f"{r['label']}, {r['unit']}".rstrip(", ") for r in res] + \
               list(p.get("inputs", {})) + ["Прапорці"]
        rows = [[s["code"], s["group"]] + [(s["res"].get(r["var"]) * (100 if r.get("percent") else 1))
                                           if isnum(s["res"].get(r["var"])) else None for r in res]
                + [s["inputs"].get(k) for k in p.get("inputs", {})] + ["; ".join(s["flags"])]
                for s in c["samples"]]
        tube_rows = []
        for t in self.run.tubes:
            for k, v in t.reads.items():
                tube_rows.append([t.label, t.sample or "серія", t.type, k, v])
            for k, v in c["tubes"].get(t.uid, {}).items():
                tube_rows.append([t.label, t.sample or "серія", t.type, k, v if isnum(v) else None])
        ser = [[k, v if isnum(v) else None] for k, v in c["series"].items() if not callable(v)] + \
              [["QC", f] for f in c["series_flags"]]
        grp = []
        for row in self.run.group_stats(c):
            for g, st in row["groups"].items():
                grp.append([f"{row['label']}, {row['unit']}", g, st["n"], st["mean"], st["sd"],
                            st.get("change"), st.get("p")])
        storage.write_workbook(path, [
            ("Результати", head, rows),
            ("Пробірки", ["Пробірка", "Зразок", "Тип", "Величина", "Значення"], tube_rows),
            ("Серія", ["Показник", "Значення"], ser),
            ("Групи", ["Показник", "Група", "n", "Середнє", "SD", "Зміна (частка)", "p Велча"], grp),
        ], {"Протокол": p["name"], "Джерело": p.get("source", ""), "Початок": self.run.started.isoformat(timespec="minutes"),
            "Прилад": self.win.model or "", "Примітки": self.run.notes or f"кювета: {self.win.cuvette.text()}"})
        self.win.message(f"Збережено: {path}")
