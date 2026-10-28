"""Scripted demo scenarios (used for screenshots and smoke tests)."""
from __future__ import annotations

from PySide6.QtCore import QTimer


def _chain(win, steps):
    """Run steps one after another, each when the worker is idle."""
    steps = list(steps)

    def nxt():
        if not steps:
            return
        if win.busy:
            QTimer.singleShot(150, nxt)
            return
        step = steps.pop(0)
        step()
        QTimer.singleShot(300, nxt)
    nxt()


def _sample(win, key):
    if not getattr(win, "demo", False):
        return
    i = win.demo_sample.findData(key)
    win.demo_sample.setCurrentIndex(i)


def run_script(win, name: str):
    if name == "photo":
        win.tabs.setCurrentWidget(win.photo)
        steps = [lambda: _sample(win, "blank"), win.do_blank]
        for key in ("red", "blue", "red", "dense"):
            steps += [lambda k=key: _sample(win, k), win.photo.measure]
        _chain(win, steps)
    elif name == "spectrum":
        win.tabs.setCurrentWidget(win.spec)
        win.spec.step.setCurrentIndex(3)   # 10 nm
        _chain(win, [lambda: _sample(win, "blank"), win.spec.scan_blank,
                     lambda: _sample(win, "red"), win.spec.scan_sample,
                     lambda: _sample(win, "blue"), win.spec.scan_sample])
    elif name in ("series", "spectrum-series"):
        from .gui import series
        series.ask_position = lambda *a: True          # the "operator" always confirms
        series.SeriesDialog.exec = lambda self: True
        if name == "series":
            win.tabs.setCurrentWidget(win.photo)
            win.photo.series()
        else:
            win.tabs.setCurrentWidget(win.spec)
            win.spec.step.setCurrentIndex(4)            # 20 nm
            win.spec.series()
    elif name == "kinetics-multi":
        from .gui import kinetics, series
        series.SeriesDialog.exec = lambda self: True
        orig = kinetics.KineticsTab.ask

        def ask(self, pos, nm):                       # the "operator" moves the carriage in 0.3 s
            orig(self, pos, nm)
            QTimer.singleShot(300, self.confirm)
        kinetics.KineticsTab.ask = ask
        win.tabs.setCurrentWidget(win.kin)
        win.kin.interval.setValue(3)
        win.kin.duration.setValue(0.6)
        win.kin.start_multi()
    elif name.startswith("open:"):
        win.tabs.setCurrentWidget(win.kin)
        win.kin.open_file(name[5:])
    elif name == "kinetics-timer":
        win.tabs.setCurrentWidget(win.kin)
        win.kin.interval.setValue(2)
        win.kin.duration.setValue(0.6)
        win.kin.countdown.setValue(3)
        win.kin.prep_text.setText("додайте H₂O₂ і перемішайте")
        win.kin.remind.setPlainText("0:12 — додати інгібітор")
        _chain(win, [lambda: _sample(win, "blank"), win.do_blank,
                     lambda: _sample(win, "kinetic"), win.kin.start])
    elif name.startswith("protocol:"):
        # protocol:<id>[:fast] — a whole series in demo mode, the "operator" presses every button
        from .gui import protocol_tab
        protocol_tab.PrepDialog.exec = lambda self: 0
        _, pid, *rest = name.split(":")
        tab = win.proto
        win.tabs.setCurrentWidget(tab)
        ids = [q["id"] for q, _f, _e in tab.library]
        i = ids.index(pid)
        tab.combo.setCurrentIndex(i)
        if rest and rest[0] == "fast":                 # shorten the waits to 3 s
            for d in tab.library[i][0]["tubes"].values():
                for st in d["steps"]:
                    if "wait" in st:
                        st["wait"] = 3
        tab.samples.setRowCount(0)
        for code, grp in (("Контроль_1", "К"), ("Контроль_2", "К"), ("Контроль_3", "К"),
                          ("DOX_1", "DOX"), ("DOX_2", "DOX"), ("DOX_3", "DOX")):
            tab.add_sample_row(code, grp)
        tab.new_run()

        def press():
            if tab.run and all(tab.run.state(t) == "done" for t in tab.run.tubes):
                return
            if not win.busy and tab.b_act.isEnabled():
                tab.do_action()
            elif not win.busy and tab.run:
                nxt = tab.run.next_tube()
                if nxt is not None and tab.selected() is not nxt:
                    tab.select(nxt)
            QTimer.singleShot(120, press)
        QTimer.singleShot(500, press)
    elif name == "calibration":
        run_calibration_demo(win)
    elif name == "kinetics":
        win.tabs.setCurrentWidget(win.kin)
        win.kin.interval.setValue(1)
        win.kin.duration.setValue(0.3)
        _chain(win, [lambda: _sample(win, "blank"), win.do_blank,
                     lambda: _sample(win, "kinetic"), win.kin.start])


def run_calibration_demo(win):
    """Calibration tab in demo mode: 5 standards, 3 samples (A typed in)."""
    tab = win.calib
    win.tabs.setCurrentWidget(tab)
    tab.levels.setText("0, 5, 10, 20, 40")
    tab.std.setRowCount(0)
    import random
    rnd = random.Random(1)
    for c in (0, 5, 10, 20, 40):
        tab.add_row(c, [0.012 + 0.0241 * c + rnd.gauss(0, 0.004) for _ in range(2)])
    tab.add_row(30, [0.95], use=False)        # an outlier switched off
    tab.recompute()
    for name, a in (("Зразок 1", 0.31), ("Зразок 2", 0.62), ("Зразок 3", 1.20)):
        tab.s_name.setText(name)
        tab.add_sample(name, a, 2.0)
