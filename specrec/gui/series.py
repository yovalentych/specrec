"""Series with the manual multi-cell carriage: position 1 holds the blank, positions 2..N the
samples. The instrument cannot tell which position is in the beam, so the program asks the
operator to move the carriage before every step (with a beep)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QSpinBox, QVBoxLayout,
)

MAX_POS = 4


class SeriesDialog(QDialog):
    def __init__(self, parent, settings, what: str):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Серія з каретки")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{what}</b> для кількох кювет у каретці.<br>"
                             "Позиція 1 — бланк, у решті — зразки. Програма підкаже, коли пересунути каретку."))
        f = QFormLayout()
        self.count = QSpinBox()
        self.count.setRange(2, MAX_POS)
        self.count.setValue(int(settings.value("carriage/count", 3)))
        f.addRow("Позицій у каретці:", self.count)
        f.addRow("Позиція 1:", QLabel("бланк"))
        self.names = []
        for i in range(2, MAX_POS + 1):
            e = QLineEdit(settings.value(f"carriage/name{i}", f"Зразок {i - 1}"))
            self.names.append(e)
            f.addRow(f"Позиція {i}:", e)
        lay.addLayout(f)
        self.blank = QCheckBox("Спершу бланк (позиція 1)")
        self.blank.setChecked(True)
        lay.addWidget(self.blank)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Почати")
        bb.button(QDialogButtonBox.Cancel).setText("Скасувати")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.count.valueChanged.connect(self._show)
        self._show()
        self._form = f

    def _show(self):
        n = self.count.value()
        for i, e in enumerate(self.names, start=2):
            e.setEnabled(i <= n)

    def result_positions(self) -> list[tuple[int, str]]:
        n = self.count.value()
        self.settings.setValue("carriage/count", n)
        out = []
        for i, e in enumerate(self.names[: n - 1], start=2):
            name = e.text().strip() or f"Позиція {i}"
            self.settings.setValue(f"carriage/name{i}", name)
            out.append((i, name))
        return out


def ask_position(parent, pos: int, name: str) -> bool:
    n = getattr(parent, "notifier", None)
    if n:
        n.notify("Каретка", f"Поставте позицію {pos}: {name}", kind="attention", popup=False)
    else:
        QApplication.beep()
    box = QMessageBox(parent)
    box.setWindowTitle("Каретка")
    box.setIcon(QMessageBox.Information)
    box.setText(f"<span style='font-size:16px'>Поставте в промінь <b>позицію {pos}</b>: {name}</span>")
    box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
    box.button(QMessageBox.Ok).setText("Готово")
    box.button(QMessageBox.Cancel).setText("Зупинити серію")
    return box.exec() == QMessageBox.Ok


class Sequence:
    """Steps run one after another: each step is (pos, name, start(on_done)).
    Before a step the operator is asked to move the carriage; the next step starts when
    the previous one calls on_done. An error in the worker simply ends the chain."""

    def __init__(self, parent, steps):
        self.parent = parent
        self.steps = list(steps)

    def start(self):
        self._next()

    def _next(self, *_):
        if not self.steps:
            n = getattr(self.parent, "notifier", None)
            if n:
                n.notify("Серію завершено", "Усі позиції каретки виміряно.", kind="done")
            else:
                QApplication.beep()
            return
        pos, name, fn = self.steps.pop(0)
        if not ask_position(self.parent, pos, name):
            return
        if hasattr(self.parent, "on_position"):
            self.parent.on_position(pos)
        fn(self._next)
