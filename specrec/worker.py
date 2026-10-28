"""All instrument traffic runs in one background thread, so the window never freezes
(a wavelength move or a blank takes several seconds).

    worker.submit(fn, on_done, on_progress)

fn(dev, job) runs in the thread; job.progress(data) sends data to on_progress in the GUI
thread, job.stopped tells a long task (scan, kinetics) that the user pressed Stop.
"""
from __future__ import annotations

import queue
import threading
import traceback

from PySide6.QtCore import QThread, Signal

from .v1200 import InstrumentError


class Job:
    def __init__(self, worker: "Worker", on_progress):
        self._w = worker
        self._on_progress = on_progress

    @property
    def stopped(self) -> bool:
        return self._w.stop_requested

    def progress(self, data):
        if self._on_progress:
            self._w.progressed.emit(self._on_progress, data)

    def ask(self, pos: int, name: str):
        """Ask the operator to move the carriage and wait until they confirm (or Stop)."""
        self.wait_gui(("ask", pos, name))

    def wait_gui(self, payload):
        """Send payload to the GUI and wait until it sets worker.confirm (or Stop is pressed)."""
        self._w.confirm.clear()
        self.progress(payload)
        while not self.stopped and not self._w.confirm.wait(0.05):
            pass

    def sleep(self, seconds: float):
        """Wait, but wake up at once when Stop is pressed."""
        import time
        end = time.monotonic() + seconds
        while not self.stopped:
            rest = end - time.monotonic()
            if rest <= 0:
                break
            time.sleep(min(0.05, rest))


class Worker(QThread):
    finished_job = Signal(object, object)   # on_done, result
    progressed = Signal(object, object)     # on_progress, data
    failed = Signal(str)
    busy_changed = Signal(bool)
    state = Signal(object)                  # dict with the instrument state after every job

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dev = None
        self.stop_requested = False
        self.confirm = threading.Event()
        self._q: queue.Queue = queue.Queue()
        self.finished_job.connect(lambda cb, res: self._call(cb, res))
        self.progressed.connect(lambda cb, data: self._call(cb, data))

    def _call(self, cb, arg):
        """Run a GUI callback; an error in it is reported and logged instead of closing the program."""
        if cb is None:
            return
        try:
            cb(arg)
        except Exception as e:
            import sys
            sys.excepthook(type(e), e, e.__traceback__)       # -> crash.log
            self.failed.emit(f"Внутрішня помилка програми: {type(e).__name__}: {e}\n"
                             "Дані вже збережено. Опис помилки записано в SpecRec_data/crash.log.")

    def submit(self, fn, on_done=None, on_progress=None):
        self._q.put((fn, on_done, on_progress))

    def request_stop(self):
        self.stop_requested = True

    def shutdown(self):
        self.stop_requested = True
        self._q.put(None)
        self.wait(5000)

    def run(self):
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, on_done, on_progress = item
            self.stop_requested = False
            self.busy_changed.emit(True)
            try:
                res = fn(self.dev, Job(self, on_progress))
                self.finished_job.emit(on_done, res)
            except InstrumentError as e:
                self.failed.emit(str(e))
            except Exception as e:   # keep the thread alive whatever happens
                traceback.print_exc()
                self.failed.emit(f"{type(e).__name__}: {e}")
            finally:
                d = self.dev
                if d is not None and d.is_open:
                    self.state.emit({"wavelength": d.wavelength, "blank": d.blank_ref, "model": d.model})
                else:
                    self.state.emit(None)
                if self._q.empty():
                    self.busy_changed.emit(False)
        if self.dev is not None:
            self.dev.close()
