"""Render the running UI to a PNG so the layout can be visually verified."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from cachyview.ui.main_window import MainWindow  # noqa: E402

app = QApplication([])
win = MainWindow(["docs/PLAN.md", "cachyview/core/mime.py", "README.md"])
win.resize(1280, 820)
win.show()
app.processEvents()
win.tabs.setCurrentIndex(1)
app.processEvents()

out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cachyview_shot.png"
win.grab().save(out)
print(f"saved {out}")
print(f"tabs: {[win.tabs.tabText(i) for i in range(win.tabs.count())]}")
