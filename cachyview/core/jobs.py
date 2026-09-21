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
    item = pyqtSignal(object)            # per-item update (e.g. batch rows)


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

    def run(self) -> None:
        try:
            result = self._fn(self.ctx, *self._args, **self._kwargs)
        except JobCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc) or exc.__class__.__name__,
                                     traceback.format_exc())
        else:
            self.signals.finished.emit(result)


# Keep every running job alive until it finishes.  A QRunnable handed to the
# thread pool is owned by C++ from that point; without a Python reference the
# Job (and its JobSignals QObject) can be garbage-collected mid-run, which
# crashes the worker when it emits ("wrapped C/C++ object ... has been
# deleted").  The pool discards the reference on any terminal signal.
_ACTIVE: "set[Job]" = set()


def _retain(job: "Job") -> "Job":
    _ACTIVE.add(job)
    for signal in (job.signals.finished, job.signals.failed,
                   job.signals.cancelled):
        signal.connect(lambda *_a, j=job: _ACTIVE.discard(j))
    return job


def submit(fn: Callable[..., Any], *args: Any, name: str = "", **kwargs: Any) -> Job:
    """Queue a job on the global pool and return it (for signal wiring/cancel)."""
    job = _retain(Job(fn, *args, name=name, **kwargs))
    QThreadPool.globalInstance().start(job)
    return job


def make_job(fn: Callable[..., Any], *args: Any, name: str = "", **kwargs: Any) -> Job:
    """Build a job without starting it, so signals can be wired first."""
    return _retain(Job(fn, *args, name=name, **kwargs))


def start_job(job: Job) -> Job:
    """Start a previously built :func:`make_job` on the global thread pool."""
    QThreadPool.globalInstance().start(job)
    return job
