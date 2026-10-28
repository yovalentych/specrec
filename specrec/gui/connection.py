"""Connection dialog: the list of USB serial ports, a check of each one, auto-connect and
per-OS hints. The automatic part (hot-plug) lives in MainWindow."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from ..v1200 import V1200, list_candidates

DEMO_ITEM = "__demo__"


def os_hint() -> str:
    if sys.platform == "darwin":
        return ("<b>macOS:</b> драйвер не потрібен, прилад з'являється як <tt>/dev/cu.usbserial-…</tt>.")
    if sys.platform.startswith("win"):
        return ("<b>Windows:</b> прилад з'являється як <tt>COM3</tt>, <tt>COM4</tt>… Якщо порту немає, "
                "встановіть драйвер <b>Silicon Labs CP210x</b> (silabs.com → CP210x USB to UART VCP drivers).")
    return ("<b>Linux:</b> прилад з'являється як <tt>/dev/ttyUSB0</tt>. Якщо пише «немає доступу», "
            "один раз виконайте <tt>sudo usermod -aG dialout $USER</tt> і перезайдіть у систему.")


def probe(port: str):
    """Runs in the worker thread: does a V-1200 answer on this port?"""
    d = V1200(port)
    try:
        info = d.connect()
        return True, f"✓ {info['model']}, зараз {info['wavelength']:.0f} нм"
    except Exception as e:
        return False, f"✗ {e}"
    finally:
        d.close()


class ConnectionDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Підключення приладу")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Порти USB. Спектрофотометр має чип <b>Silicon Labs CP210x</b> — "
                             "такі порти позначені ★ і перевіряються першими."))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.connect_selected())
        lay.addWidget(self.list, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        row = QHBoxLayout()
        b = QPushButton("Оновити")
        b.clicked.connect(self.refresh)
        row.addWidget(b)
        self.b_probe = QPushButton("Перевірити")
        self.b_probe.setToolTip("Спитати пристрій на цьому порту, чи він спектрофотометр")
        self.b_probe.clicked.connect(self.probe_selected)
        row.addWidget(self.b_probe)
        row.addStretch()
        self.b_conn = QPushButton("Підключити")
        self.b_conn.setObjectName("primary")
        self.b_conn.clicked.connect(self.connect_selected)
        row.addWidget(self.b_conn)
        lay.addLayout(row)

        self.auto = QCheckBox("Підключатися автоматично (коли прилад під'єднано або ввімкнено)")
        self.auto.setChecked(win.auto_enabled())
        self.auto.toggled.connect(lambda on: win.settings.setValue("connection/auto", on))
        lay.addWidget(self.auto)
        hint = QLabel(os_hint())
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setObjectName("hint")
        lay.addWidget(hint)
        close = QPushButton("Закрити")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignRight)
        self.refresh()

    def refresh(self):
        self.list.clear()
        cur = self.win.cur_port if self.win.connected else None
        for p in list_candidates():
            text = f"{'★ ' if p.likely else '    '}{p.device}  —  {p.description}"
            if p.device == cur:
                text += "   (підключено)"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, p.device)
            self.list.addItem(it)
        it = QListWidgetItem("    Демо (віртуальний прилад, без USB)")
        it.setData(Qt.UserRole, DEMO_ITEM)
        self.list.addItem(it)
        self.list.setCurrentRow(0)
        n = self.list.count() - 1
        self.status.setText("USB-портів не знайдено. Перевірте кабель і чи ввімкнено прилад."
                            if n == 0 else f"Знайдено портів: {n}.")

    def selected(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def probe_selected(self):
        port = self.selected()
        if not port or port == DEMO_ITEM:
            return
        if self.win.connected and port == self.win.cur_port:
            self.status.setText(f"✓ Уже підключено: {self.win.model}")
            return
        if self.win.busy:
            self.status.setText("Прилад зайнятий вимірюванням, спробуйте пізніше.")
            return
        self.status.setText(f"Перевіряю {port}…")
        self.win.worker.submit(lambda dev, job: probe(port), lambda r: self.status.setText(r[1]))

    def connect_selected(self):
        port = self.selected()
        if not port:
            return
        from .main_window import DEMO
        self.win.connect_to(DEMO if port == DEMO_ITEM else port)
        self.accept()
