"""ImageToPdfDialog ordering test: the grid order drives the PDF page order."""
import fitz
import pytest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from cachyview.ui.image_to_pdf import ImageToPdfDialog
from cachyview.backends import image as ib


@pytest.fixture(scope="module")
def app():
    return QApplication([])


@pytest.fixture
def imgs(tmp_path):
    paths = []
    for i, c in enumerate((255, 0, 0), start=1):
        p = tmp_path / f"img{i}.png"
        from PIL import Image
        Image.new("RGB", (40, 40), (c, c, c)).save(p)
        paths.append(p)
    return paths


def test_ordered_paths_follows_grid(imgs, app):
    dlg = ImageToPdfDialog(initial=[str(p) for p in imgs])
    # move last item to the top via the public shift helper
    dlg.grid.setCurrentRow(dlg.grid.count() - 1)
    dlg._shift(-(dlg.grid.count() - 1))
    order = dlg.ordered_paths()
    assert Path(order[0]).name == "img3.png"
    assert len(order) == 3


def test_create_produces_pdf(imgs, tmp_path, app, monkeypatch):
    out = tmp_path / "album.pdf"
    dlg = ImageToPdfDialog(initial=[str(p) for p in imgs])
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(out), ""))
    # bypass the modal exec; call the worker directly
    ib.images_to_pdf(dlg.ordered_paths(), out)
    assert out.is_file()
    d = fitz.open(out)
    assert d.page_count == 3
    d.close()
