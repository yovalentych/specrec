"""Sounds and notifications: start / end of long measurements, reminders, countdowns.

* sound: macOS system sounds via afplay, Linux freedesktop sounds via paplay/aplay,
  otherwise the Qt beep;
* system notification (macOS Notification Center / Linux desktop) via QSystemTrayIcon,
  so it is seen even when the window is hidden;
* the Dock / taskbar icon asks for attention;
* optionally an in-app window that does not stop the measurement.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

SOUNDS = {
    # kind: (macOS sound, Linux freedesktop sound)
    "tick": ("Tink", "message"),
    "go": ("Hero", "bell"),
    "done": ("Glass", "complete"),
    "attention": ("Ping", "dialog-information"),
    "warn": ("Basso", "dialog-warning"),
}


def play(kind: str = "attention"):
    mac, lin = SOUNDS.get(kind, SOUNDS["attention"])
    try:
        if sys.platform == "darwin":
            f = Path(f"/System/Library/Sounds/{mac}.aiff")
            if f.exists():
                subprocess.Popen(["afplay", str(f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
        elif sys.platform.startswith("linux"):
            for ext in ("oga", "ogg", "wav"):
                f = Path(f"/usr/share/sounds/freedesktop/stereo/{lin}.{ext}")
                player = shutil.which("paplay") or (shutil.which("aplay") if ext == "wav" else None)
                if f.exists() and player:
                    subprocess.Popen([player, str(f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
    except Exception:
        pass
    QApplication.beep()


class Notifier:
    def __init__(self, win, icon):
        self.win = win
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, win)
            self.tray.setToolTip("SpecRec")
            self.tray.messageClicked.connect(self._bring_front)
            self.tray.show()
        self._boxes = []

    @property
    def sound_on(self) -> bool:
        return str(self.win.settings.value("notify/sound", True)).lower() in ("true", "1")

    def sound(self, kind: str):
        if self.sound_on:
            play(kind)

    def notify(self, title: str, text: str, kind: str = "done", popup: bool = True):
        """Sound + system notification + Dock bounce (+ an in-app window that does not block)."""
        self.sound(kind)
        if self.tray is not None:
            self.tray.showMessage(title, text, QSystemTrayIcon.Information, 15000)
        QApplication.alert(self.win, 0)
        if popup:
            box = QMessageBox(QMessageBox.Information, title, text, QMessageBox.Ok, self.win)
            box.setModal(False)
            box.finished.connect(lambda _: self._boxes.remove(box) if box in self._boxes else None)
            self._boxes.append(box)
            box.show()
            box.raise_()

    def _bring_front(self):
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()
