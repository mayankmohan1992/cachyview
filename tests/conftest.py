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

import cachyview  # noqa: E402,F401  (import for its sys.path guard side effect)
