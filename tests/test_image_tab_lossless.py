"""Image-tab lossless rotate UI tests."""
import pytest
from pathlib import Path
from PIL import Image

from PyQt6.QtWidgets import QApplication

from cachyview.ui.image_tab import ImageTab




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


def test_edit_history_persists_across_reopen(app, jpeg, tmp_path, monkeypatch):
    # Isolate the history store so the test doesn't touch the real config.
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    from cachyview.core import image_history as ih

    tab = ImageTab(jpeg)
    tab.add_op("rotate", angle=90)
    tab.add_op("grayscale")
    assert len(tab.ops) == 2
    tab.close()

    # A fresh tab on the same file should replay the stored stack.
    tab2 = ImageTab(jpeg)
    assert len(tab2.ops) == 2
    assert [o.name for o in tab2.ops] == ["rotate", "grayscale"]
    assert tab2.current.mode == "L"  # grayscale applied
    tab2.close()

    # Saving As bakes the edits and clears the persisted stack.
    out = tmp_path / "baked.jpg"
    tab3 = ImageTab(jpeg)
    tab3.add_op("rotate", angle=90)
    tab3._write(out)  # exercise the real write path without the file dialog
    assert ih.load(jpeg) == []
    tab3.close()
