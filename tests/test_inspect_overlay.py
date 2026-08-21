"""Tests for the image inspection overlay (picker / ruler / magnifier)."""
import pytest
from pathlib import Path
from PIL import Image

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

from cachyview.ui.image_tab import ImageTab
from cachyview.ui.inspect_overlay import InspectOverlay




@pytest.fixture
def image_file(tmp_path):
    img = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    # put a red pixel at (10, 20) and a blue pixel at (50, 40)
    img.putpixel((10, 20), (255, 0, 0, 255))
    img.putpixel((50, 40), (0, 0, 255, 255))
    p = tmp_path / "img.png"
    img.save(p)
    return p


def test_overlay_maps_widget_to_image_at_zoom(app, image_file):
    tab = ImageTab(image_file)
    ov = tab.canvas.inspect
    from PIL import Image as _Im
    ov.configure(zoom=2.0, image_size=_Im.new("RGBA", (100, 80)))  # 2x on-screen
    # widget point (20, 40) -> image pixel (10, 20)
    img_pt = ov._to_image(QPoint(20, 40))
    assert (img_pt.x(), img_pt.y()) == (10, 20)
    tab.close()


def test_picker_reads_pixel_color(app, image_file):
    tab = ImageTab(image_file)
    ov = tab.canvas.inspect
    ov.configure(zoom=1.0, image_size=tab.current)
    color = ov._color_at(10, 20)
    assert color[:3] == (255, 0, 0)
    assert ov._color_at(50, 40)[:3] == (0, 0, 255)
    tab.close()


def test_ruler_measures_distance(app, image_file):
    tab = ImageTab(image_file)
    ov = tab.canvas.inspect
    ov.configure(zoom=1.0, image_size=tab.current)
    ov.set_mode("ruler")
    ov._drag_start = QPoint(0, 0)
    ov._drag_now = QPoint(30, 40)  # image-space dx=30, dy=40 -> 50px
    a = ov._to_image(ov._drag_start)
    b = ov._to_image(ov._drag_now)
    import math
    dist = math.hypot(b.x() - a.x(), b.y() - a.y())
    assert round(dist) == 50
    ov.set_mode("off")
    tab.close()


def test_magnifier_returns_zoomed_region(app, image_file):
    tab = ImageTab(image_file)
    ov = tab.canvas.inspect
    ov.configure(zoom=1.0, image_size=tab.current)
    pix = ov.magnifier_pixmap(50, 40, size=160, factor=4)
    assert pix is not None
    assert (pix.width(), pix.height()) == (160, 160)
    tab.close()


def test_set_inspect_mode_toggles_overlay(app, image_file):
    tab = ImageTab(image_file)
    tab.set_inspect_mode("picker")
    assert tab.canvas.inspect.active
    assert tab.canvas.inspect.mode == "picker"
    # turning the same mode on again switches it off
    tab.set_inspect_mode("picker")
    assert not tab.canvas.inspect.active
    tab.close()
