"""The cuvette in use: material and path length. Recorded with every result; used for warnings
(a scan below what the material transmits, a protocol with ε for 10 mm in another cuvette)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)

# material: (name, usable from nm)
MATERIALS = {
    "glass": ("оптичне скло", 340),
    "ps": ("полістирол (PS)", 340),
    "pmma": ("акрил (PMMA)", 300),
    "quartz": ("кварц", 200),
}


class Cuvette:
    def __init__(self, settings):
        self.settings = settings

    @property
    def material(self) -> str:
        m = self.settings.value("cuvette/material", "glass")
        return m if m in MATERIALS else "glass"

    @property
    def path_mm(self) -> float:
        try:
            return float(self.settings.value("cuvette/path_mm", 10))
        except (TypeError, ValueError):
            return 10.0

    @property
    def cutoff(self) -> int:
        return MATERIALS[self.material][1]

    def text(self) -> str:
        return f"{MATERIALS[self.material][0]}, {self.path_mm:g} мм"

    def short(self) -> str:
        names = {"glass": "скло", "ps": "PS", "pmma": "PMMA", "quartz": "кварц"}
        return f"{names[self.material]} {self.path_mm:g} мм"

    def meta(self) -> dict:
        return {"cuvette": self.text()}


class CuvetteDialog(QDialog):
    def __init__(self, parent, cuv: Cuvette):
        super().__init__(parent)
        self.cuv = cuv
        self.setWindowTitle("Кювета")
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.mat = QComboBox()
        for k, (name, cut) in MATERIALS.items():
            self.mat.addItem(f"{name} — від ~{cut} нм", k)
        self.mat.setCurrentIndex(list(MATERIALS).index(cuv.material))
        self.path = QDoubleSpinBox()
        self.path.setRange(1, 100)
        self.path.setDecimals(1)
        self.path.setSuffix(" мм")
        self.path.setValue(cuv.path_mm)
        f.addRow("Матеріал:", self.mat)
        f.addRow("Оптичний шлях:", self.path)
        lay.addLayout(f)
        note = QLabel("Матеріал на розрахунок не впливає, якщо бланк і зразок в однакових кюветах: "
                      "він лише обмежує, з якої довжини хвилі можна міряти.\n"
                      "Шлях потрібен для формул з ε (МДА, SH-групи): вони розраховані на 10 мм. "
                      "Кювета зі звуженням зазвичай теж має шлях 10 мм.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self):
        self.cuv.settings.setValue("cuvette/material", self.mat.currentData())
        self.cuv.settings.setValue("cuvette/path_mm", self.path.value())
        super().accept()
