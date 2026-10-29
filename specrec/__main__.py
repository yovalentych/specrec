"""Entry point: `python -m specrec`, or the built SpecRec.app / SpecRec.exe.

Optional arguments (for testing and screenshots):
  --demo               connect to the virtual instrument at start
  --theme light|dark
  --screenshot FILE    after --after seconds save a screenshot and quit
  --script NAME        with --demo: run a demo scenario before the screenshot (photo|spectrum|kinetics)
"""
from __future__ import annotations

import argparse
import sys


_crash_file = None


def _install_crash_log():
    """Write the reason of a crash to SpecRec_data/crash.log: Python errors (also those inside
    Qt slots), Qt warnings and hard crashes (segfaults) via faulthandler."""
    global _crash_file
    import datetime as dt
    import faulthandler
    import traceback

    from . import __version__, paths
    try:
        root = paths.data_root()
        root.mkdir(parents=True, exist_ok=True)
        _crash_file = open(root / "crash.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    _crash_file.write(f"\n=== SpecRec {__version__} started {dt.datetime.now():%Y-%m-%d %H:%M:%S} "
                      f"on {sys.platform} ===\n")
    faulthandler.enable(_crash_file, all_threads=True)

    def hook(etype, value, tb):
        _crash_file.write(f"--- {dt.datetime.now():%H:%M:%S} Python error\n")
        _crash_file.write("".join(traceback.format_exception(etype, value, tb)))
        sys.__excepthook__(etype, value, tb)
    sys.excepthook = hook

    import threading
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    def qt_handler(mode, ctx, msg):
        if mode != QtMsgType.QtDebugMsg and not any(x in msg for x in ("propagateSizeHints", "font family")):
            _crash_file.write(f"--- {dt.datetime.now():%H:%M:%S} Qt: {msg}\n")
        sys.stderr.write(msg + "\n")
    qInstallMessageHandler(qt_handler)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="specrec")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--theme", choices=["device", "light", "dark"])
    ap.add_argument("--screenshot")
    ap.add_argument("--after", type=float, default=5.0)
    ap.add_argument("--script")
    args, _ = ap.parse_known_args(argv)   # macOS may pass -psn_...

    _install_crash_log()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("SpecRec")
    app.setOrganizationName("SpecRec")
    app.setStyle("Fusion")

    from .gui import theme as th
    from .gui.main_window import DEMO, MainWindow
    win = MainWindow(autoconnect=not args.demo)
    if args.theme:
        win.theme = th.THEMES[args.theme]
        win.apply_theme()
    win.show()

    if args.demo:
        win.port.setCurrentText(DEMO)
        QTimer.singleShot(100, win.toggle_connect)
    if args.script:
        from .demo_script import run_script
        QTimer.singleShot(1500 if args.demo else 3000, lambda: run_script(win, args.script))
    if args.screenshot:
        def shot():
            win.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(int(args.after * 1000), shot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
