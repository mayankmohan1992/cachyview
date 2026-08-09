"""Cancellable background jobs on a QThreadPool. UI never blocks."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class JobCancelled(Exception):
    """Raised inside a worker function when the user cancels."""


class JobSignals(QObject):
    progress = pyqtSignal(int, str)      # percent (-1 = indeterminate), message
    finished = pyqtSignal(object)        # result
    failed = pyqtSignal(str, str)        # short message, traceback
    cancelled = pyqtSignal()


class JobContext:
    """Handle passed into the worker function so it can report and cooperate."""

    def __init__(self, signals: JobSignals):
        self._signals = signals
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def check(self) -> None:
        """Call periodically inside long loops."""
        if self._cancel:
            raise JobCancelled()

    def progress(self, percent: int, message: str = "") -> None:
        self.check()
        self._signals.progress.emit(percent, message)


class Job(QRunnable):
    """Runs `fn(ctx, *args, **kwargs)` off the GUI thread."""

    def __init__(self, fn: Callable[..., Any], *args: Any, name: str = "", **kwargs: Any):
        super().__init__()
        self.name = name or getattr(fn, "__name__", "job")
        self.signals = JobSignals()
        self.ctx = JobContext(self.signals)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.ctx.cancel()

    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        try:
            result = self._fn(self.ctx, *self._args, **self._kwargs)
        except JobCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.signals.failed.emit(str(exc) or exc.__class__.__name__,
                                     traceback.format_exc())
        else:
            self.signals.finished.emit(result)


def submit(fn: Callable[..., Any], *args: Any, name: str = "", **kwargs: Any) -> Job:
    """Queue a job on the global pool and return it (for signal wiring/cancel)."""
    job = Job(fn, *args, name=name, **kwargs)
    QThreadPool.globalInstance().start(job)
    return job
