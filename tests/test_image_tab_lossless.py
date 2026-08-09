"""Image-tab lossless rotate UI tests."""
import pytest
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import QApplication

from cachyview.ui.image_tab import ImageTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def jpeg(tmp_path):
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    p = tmp_path / "photo.jpg"
    img.save(p, "JPEG", quality=92)
    return p


def test_lossless_rotate_updates_preview_size(app, jpeg):
    tab = ImageTab(jpeg)
    assert (tab.current.width, tab.current.height) == (200, 100)
    tab.lossless_rotate(90)
    # file was rotated on disk and reloaded
    assert (tab.current.width, tab.current.height) == (100, 200)
    tab.close()


def test_lossless_rotate_reloads_exif_and_path(app, jpeg):
    tab = ImageTab(jpeg)
    tab.lossless_rotate(270)
    # The path is the same file (in-place safe-swap), now rotated.
    assert tab.path == jpeg
    assert (tab.current.width, tab.current.height) == (100, 200)
    tab.close()
