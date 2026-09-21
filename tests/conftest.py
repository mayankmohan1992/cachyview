"""Test bootstrap.

Two things must happen before any third-party import:

1. Qt needs a display; force the offscreen platform so the suite is headless.
2. A foreign PYTHONPATH (another interpreter's site-packages) can shadow
   compiled modules such as Pillow and break collection.  Importing cachyview
   applies its path guard, but pytest may import PIL from a test module first,
   so the guard runs here too.
"""
import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The host's KDE platform-theme plugin crashes Qt under the offscreen platform
# (segfault during posted-event delivery).  Tests don't need it, so neutralise
# it while leaving the machine's real desktop untouched.
os.environ["QT_QPA_PLATFORMTHEME"] = ""

# Qt wrapper objects can be part of a reference cycle that Python's cyclic
# collector destroys while Qt still holds a pointer to them, which segfaults
# the interpreter mid-suite.  Tests are short-lived, so keep the collector off
# and let reference counting free everything deterministically.
gc.disable()

# Isolate persistent UI state from the developer's real config.
os.environ.setdefault("XDG_CONFIG_HOME", os.path.join(
    os.environ.get("TMPDIR", "/tmp"), "cachyview-pytest-config"))

import cachyview  # noqa: E402,F401  (import for its sys.path guard side effect)

# One QApplication for the entire suite.  Creating/destroying multiple
# QApplication instances across test modules in a single process crashes Qt
# (segfault, exit 139) — so every GUI test reuses this single instance.
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    existing = QApplication.instance()
    if existing is None:
        existing = QApplication([])
    yield existing


@pytest.fixture
def pump(app):
    """Process Qt events until *predicate* is true (for async/background work)."""
    import time

    def _pump(predicate, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert predicate(), "condition was not met before the timeout"

    return _pump


@pytest.fixture(autouse=True)
def _drain_threadpool():
    """Let background jobs finish before a test tears down its widgets.

    A worker that outlives the widget it reports to can emit into a destroyed
    QObject, which crashes Qt (segfault, exit 139).  Draining the pool between
    tests keeps the suite deterministic.
    """
    yield
    try:
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(5000)
    except Exception:
        pass
