"""Render each viewer tab to a PNG for visual review.

Usage: python tools/shot.py [outdir]
"""
import os
import sys
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import cachyview first: it strips a foreign PYTHONPATH from sys.path, which
# would otherwise shadow Pillow with a build for a different interpreter.
import cachyview  # noqa: E402,F401

from pathlib import Path  # noqa: E402

from PIL import Image  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from cachyview.ui.main_window import MainWindow  # noqa: E402

out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cachyview-shots")
out_dir.mkdir(parents=True, exist_ok=True)
demo = out_dir / "demo"
demo.mkdir(exist_ok=True)

# --- build sample documents ------------------------------------------------
zip_path = demo / "project.zip"
with zipfile.ZipFile(zip_path, "w") as zf:
    zf.writestr("README.md", "# Project\n\nA sample archive.\n" * 4)
    zf.writestr("src/main.py", "def main():\n    print('hi')\n" * 6)
    zf.writestr("src/util.py", "import os\n" * 10)
    zf.writestr("docs/guide.txt", "Guide contents\n" * 20)
    zf.writestr("assets/logo.txt", "logo\n")

img_path = demo / "gradient.png"
img = Image.new("RGB", (640, 400))
for x in range(640):
    for y in range(400):
        img.putpixel((x, y), (x * 255 // 640, y * 255 // 400, 160))
img.save(img_path)

pdf_path = demo / "report.pdf"
try:
    import fitz
    doc = fitz.open()
    for i in range(5):
        page = doc.new_page()
        page.insert_text((72, 90), "Quarterly Report", fontsize=22)
        page.insert_text((72, 130), f"Page {i + 1} of 5", fontsize=13)
        for line in range(12):
            page.insert_text((72, 170 + line * 18),
                             f"Line {line + 1}: sample body text for review.",
                             fontsize=10)
    doc.save(str(pdf_path))
    doc.close()
except ImportError:
    pdf_path = None

app = QApplication([])
win = MainWindow()
win.resize(1280, 820)
win.show()

targets = [p for p in (zip_path, img_path, pdf_path) if p]
for p in targets:
    win.open_path(p)
app.processEvents()

names = {"project.zip": "archive", "gradient.png": "image", "report.pdf": "pdf"}
for i in range(win.tabs.count()):
    win.tabs.setCurrentIndex(i)
    app.processEvents()
    widget = win.tabs.widget(i)
    label = names.get(getattr(widget, "path", Path("x")).name, f"tab{i}")
    target = out_dir / f"{label}.png"
    win.grab().save(str(target))
    print(f"{target}  ({type(widget).__name__})")

print("tabs:", [win.tabs.tabText(i) for i in range(win.tabs.count())])
