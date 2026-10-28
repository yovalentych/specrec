"""Where settings and data are stored: normal or portable mode (same scheme as LangRec).

Portable mode is on when `portable.txt` lies next to the program (the portable builds
ship with it). Then settings and measurements go to <program folder>/SpecRec_data/,
so the program can live on a USB stick and leaves nothing behind on the computer.
Otherwise: system settings, data in ~/Documents/SpecRec_data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:          # SpecRec.app/Contents/MacOS/SpecRec
            if parent.suffix == ".app":
                return parent.parent
        return exe.parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    return (app_dir() / "portable.txt").exists()


def data_root() -> Path:
    override = os.environ.get("SPECREC_DATA")       # used by the tests
    if override:
        return Path(override)
    if is_portable():
        return app_dir() / "SpecRec_data"
    return Path.home() / "Documents" / "SpecRec_data"


def make_settings():
    from PySide6.QtCore import QSettings
    if os.environ.get("SPECREC_DATA") or is_portable():
        root = data_root()
        root.mkdir(parents=True, exist_ok=True)
        return QSettings(str(root / "settings.ini"), QSettings.IniFormat)
    return QSettings("SpecRec", "SpecRec")
