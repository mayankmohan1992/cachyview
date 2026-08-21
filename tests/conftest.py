"""Test bootstrap.

Two things must happen before any third-party import:

1. Qt needs a display; force the offscreen platform so the suite is headless.
2. A foreign PYTHONPATH (another interpreter's site-packages) can shadow
   compiled modules such as Pillow and break collection.  Importing cachyview
   applies its path guard, but pytest may import PIL from a test module first,
   so the guard runs here too.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
