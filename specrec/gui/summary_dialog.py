"""Summary over series: one row per animal from all assays, per mg protein, group statistics
(Welch and Mann–Whitney), a dot plot, export to Excel."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import paths, storage
from ..protocol import isnum
from ..summary import build, load_runs
from .common import hint, section
from .groupplot import GroupPlot


def find_sessions() -> list[Path]:
    root = paths.data_root()
    return sorted(root.glob("*/protocol_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


class SummaryDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Зведення по тваринах")
        self.resize(1150, 760)
        self.data = None

        left = QVBoxLayout()
        left.addWidget(section("Серії"))
        self.files = QListWidget()
        self.files.itemChanged.connect(lambda _: self.recompute())
        left.addWidget(self.files, 1)
        left.addWidget(hint("За замовчуванням — остання серія кожного протоколу. Якщо тварину міряли "
                            "в кількох серіях одного аналізу, береться пізніша."))
        b = QPushButton("Додати файл…")
        b.clicked.connect(self.add_file)
        left.addWidget(b)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(300)

        right = QVBoxLayout()
        self.table = QTableWidget(0, 0)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right.addWidget(self.table, 3)
        self.stats = QTableWidget(0, 0)
        self.stats.verticalHeader().setVisible(False)
        self.stats.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right.addWidget(self.stats, 2)
        pr = QHBoxLayout()
        pr.addWidget(QLabel("Графік:"))
        self.col = QComboBox()
        self.col.currentIndexChanged.connect(self.draw)
        pr.addWidget(self.col, 1)
        b = QPushButton("Експорт у Excel…")
        b.clicked.connect(self.export)
        pr.addWidget(b)
        right.addLayout(pr)
        self.plot = GroupPlot(win.theme)
        self.plot.setMinimumHeight(220)
        right.addWidget(self.plot, 2)
        self.note = hint("")
        right.addWidget(self.note)
        rw = QWidget()
        rw.setLayout(right)

        lay = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(lw)
        split.addWidget(rw)
        lay.addWidget(split)
        self.fill_files()

    def fill_files(self, extra: Path | None = None):
        self.files.blockSignals(True)
        seen = set()
        for f in ([extra] if extra else []) + find_sessions():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                pid, name = d["protocol"]["id"], d["protocol"]["name"]
                started = dt.datetime.fromisoformat(d["started"])
            except Exception:
                continue
            it = QListWidgetItem(f"{name}\n{started:%d.%m.%Y %H:%M} · {len(d['samples'])} зразків")
            it.setData(Qt.UserRole, str(f))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if pid not in seen or f == extra else Qt.Unchecked)
            seen.add(pid)
            self.files.addItem(it)
        self.files.blockSignals(False)
        self.recompute()

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Серія", str(paths.data_root()), "Серія (protocol_*.json)")
        if path:
            self.fill_files(Path(path))

    def recompute(self):
        files = [self.files.item(i).data(Qt.UserRole) for i in range(self.files.count())
                 if self.files.item(i).checkState() == Qt.Checked]
        self.data = d = build(load_runs(files))
        cols = d["columns"]
        self.table.setColumnCount(2 + len(cols))
        self.table.setHorizontalHeaderLabels(["Код", "Група"] + [f"{l}, {u}" for l, u in cols])
        self.table.setRowCount(len(d["animals"]))
        for i, a in enumerate(d["animals"]):
            cells = [a["code"], a["group"]] + [self.fmt(a["values"].get(l)) for l, _ in cols]
            for j, t in enumerate(cells):
                it = QTableWidgetItem(t)
                if j >= 2:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        # stats: rows = indicator × group
        heads = ["Показник", "Група", "n", "Середнє", "SD", "Зміна", "p Велча", "p Манна–Вітні"]
        rows = []
        for st in d["stats"]:
            for g, v in st["groups"].items():
                rows.append([f"{st['label']}, {st['unit']}", g + (" (порівняння)" if g == st["ref"] else ""),
                             str(v["n"]), self.fmt(v["mean"]), self.fmt(v["sd"]),
                             f"{v['change'] * 100:+.0f} %" if isnum(v.get("change")) else "",
                             f"{v['p']:.3f}" if isnum(v.get("p")) else "",
                             f"{v['p_mw']:.3f}" if isnum(v.get("p_mw")) else ""])
        self.stats.setColumnCount(len(heads))
        self.stats.setHorizontalHeaderLabels(heads)
        self.stats.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, t in enumerate(r):
                it = QTableWidgetItem(t)
                if j in (6, 7) and t and float(t) < 0.05:
                    it.setForeground(QColor(self.win.theme.success))
                self.stats.setItem(i, j, it)
        self.stats.resizeColumnsToContents()
        self.stats.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        cur = self.col.currentText()
        self.col.blockSignals(True)
        self.col.clear()
        self.col.addItems([f"{l}, {u}" for l, u in cols])
        i = self.col.findText(cur)
        self.col.setCurrentIndex(max(i, 0))
        self.col.blockSignals(False)
        self.note.setText((f"На мг білка — за «{d['protein']}». " if d["protein"] else
                           "Немає серії білка — значень на мг білка немає. ")
                          + "p < 0,05 виділено зеленим. При n ≈ 5 на групу обидва тести орієнтовні.")
        self.draw()

    @staticmethod
    def fmt(v):
        if not isnum(v):
            return "—"
        return f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"

    def draw(self):
        if not self.data or not self.data["columns"]:
            self.plot.clear()
            return
        i = self.col.currentIndex()
        label, unit = self.data["columns"][max(i, 0)]
        groups = {g: [a["values"].get(label) for a in self.data["animals"] if a["group"] == g]
                  for g in self.data["groups"]}
        self.plot.show_groups(groups, label, unit)

    def export(self):
        if not self.data:
            return
        d = self.data
        default = str(storage.day_dir() / f"zvedennia_{dt.datetime.now():%Y%m%d_%H%M}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Експорт", default, "Excel (*.xlsx)")
        if not path:
            return
        cols = d["columns"]
        rows = [[a["code"], a["group"]] + [a["values"].get(l) for l, _ in cols] for a in d["animals"]]
        st = [[f"{s['label']}, {s['unit']}", g, v["n"], v["mean"], v["sd"], v.get("change"), v.get("p"), v.get("p_mw")]
              for s in d["stats"] for g, v in s["groups"].items()]
        storage.write_workbook(path, [
            ("Тварини", ["Код", "Група"] + [f"{l}, {u}" for l, u in cols], rows),
            ("Групи", ["Показник", "Група", "n", "Середнє", "SD", "Зміна (частка)", "p Велча", "p Манна–Вітні"], st),
        ], {"Зведення": dt.datetime.now().isoformat(timespec="minutes"),
            "Білок для перерахунку": d["protein"] or "—"})
        self.win.message(f"Збережено: {path}")
