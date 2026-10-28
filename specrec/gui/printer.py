"""Thermal printer: settings dialog, test receipt, and `print_receipt` used by the tabs."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout,
)

from .. import storage
from ..thermal import WIDTHS, candidate_ports, escpos_raster, render, send

NO_PRINTER = "— лише зберегти картинку (PNG) —"


def printer_port(settings) -> str:
    return settings.value("printer/port", "") or ""


def printer_width(settings) -> int:
    try:
        return int(settings.value("printer/width", 384))
    except (TypeError, ValueError):
        return 384


def print_receipt(win, title: str, lines: list[tuple[str, str]]):
    """Header + lines → printer (if set) and a PNG in the data folder; shows a preview."""
    head = [("title", "SpecRec"), ("small", f"{dt.datetime.now():%d.%m.%Y %H:%M} · {win.model or 'без приладу'}"),
            ("small", f"кювета: {win.cuvette.text()}"), ("rule", ""), ("bold", title)]
    img = render(head + lines + [("rule", ""), ("small", "github.com/yovalentych/specrec")], printer_width(win.settings))
    path = storage.day_dir() / f"receipt_{dt.datetime.now():%H%M%S}.png"
    img.save(str(path))
    port = printer_port(win.settings)
    if port:
        data = escpos_raster(img)

        def task(dev, job):
            send(port, data)
        win.worker.submit(task, lambda _: win.message(f"Надруковано · {path.name}"))
        win.message(f"Друк на {port}…")
    else:
        Preview(win, path).exec()


class Preview(QDialog):
    def __init__(self, win, path):
        super().__init__(win)
        self.setWindowTitle("Чек")
        lay = QVBoxLayout(self)
        sc = QScrollArea()
        lab = QLabel()
        lab.setPixmap(QPixmap(str(path)))
        sc.setWidget(lab)
        sc.setMinimumSize(430, 520)
        lay.addWidget(sc)
        lay.addWidget(QLabel(f"Збережено: {path.name}\nПринтер не вибрано: Прилад → Термопринтер…"))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class PrinterDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Термопринтер")
        lay = QVBoxLayout(self)
        f = QFormLayout()
        row = QHBoxLayout()
        self.port = QComboBox()
        self.refresh()
        b = QPushButton("⟳")
        b.setFixedWidth(34)
        b.clicked.connect(self.refresh)
        row.addWidget(self.port, 1)
        row.addWidget(b)
        f.addRow("Порт принтера:", row)
        self.width = QComboBox()
        for k, v in WIDTHS.items():
            self.width.addItem(k, v)
        self.width.setCurrentIndex(max(0, self.width.findData(printer_width(win.settings))))
        f.addRow("Ширина стрічки:", self.width)
        lay.addLayout(f)
        info = QLabel("Принтер спершу треба спарити з комп'ютером (Bluetooth у налаштуваннях системи). "
                      "Принтер із класичним Bluetooth (SPP) після цього з'являється в списку як порт "
                      "(macOS: /dev/cu.<назва>, Linux: /dev/rfcomm0, Windows: COMn).\n"
                      "Програма друкує картинкою через ESC/POS — так кирилиця виходить на будь-якому принтері.\n"
                      "Деякі маленькі принтери працюють лише через Bluetooth LE з власним протоколом "
                      "(«котячі» GB01/MX05, Phomemo, PeriPage) — для них потрібна окрема підтримка; "
                      "напишіть модель.")
        info.setWordWrap(True)
        info.setObjectName("hint")
        lay.addWidget(info)
        b = QPushButton("Тестовий чек")
        b.clicked.connect(self.test)
        lay.addWidget(b)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def refresh(self):
        cur = printer_port(self.win.settings)
        self.port.clear()
        self.port.addItem(NO_PRINTER, "")
        inst = self.win.cur_port
        for p in candidate_ports():
            if p != inst:
                self.port.addItem(p, p)
        i = self.port.findData(cur)
        self.port.setCurrentIndex(max(i, 0))

    def save(self):
        self.win.settings.setValue("printer/port", self.port.currentData() or "")
        self.win.settings.setValue("printer/width", self.width.currentData())

    def test(self):
        self.save()
        print_receipt(self.win, "Тестовий чек", [
            ("text", "Кирилиця: Ґанок, їжак, є, щ"), ("text", "Символи: ± ² ³ µ λ Δ ε ₂ °C"),
            ("text", "A₅₃₂ = 0,123   C = 3,15 мкмоль/л")])

    def accept(self):
        self.save()
        super().accept()
