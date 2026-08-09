"""Qt needs a display; force offscreen before any Qt import so the suite is headless."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
