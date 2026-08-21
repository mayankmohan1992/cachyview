"""Crop overlay tests.

The overlay's job is coordinate conversion: a rubber band drawn at some zoom
must map back to exact pixels of the original image.  These tests drive real
mouse events and check the resulting crop against the actual pixel data.
"""
import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from cachyview.backends import image as ib
from cachyview.ui.crop_overlay import CropOverlay
from cachyview.ui.image_tab import ImageTab




@pytest.fixture
def overlay(app):
    widget = CropOverlay()
    widget.resize(400, 300)
    widget.configure(1.0, QSize(400, 300))
    return widget


def press(widget, x, y):
    widget.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))


def move(widget, x, y):
    widget.mouseMoveEvent(QMouseEvent(
        QMouseEvent.Type.MouseMove, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))


def release(widget, x, y):
    widget.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))


def drag(widget, x1, y1, x2, y2):
    press(widget, x1, y1)
    move(widget, x2, y2)
    release(widget, x2, y2)


# --- basic selection ------------------------------------------------------

def test_no_selection_initially(overlay):
    assert not overlay.has_selection()
    assert overlay.image_rect() == QRect()


def test_drag_creates_selection(overlay):
    drag(overlay, 50, 40, 150, 140)
    assert overlay.has_selection()
    rect = overlay.image_rect()
    assert rect.left() == 50 and rect.top() == 40
    assert rect.width() == 101 and rect.height() == 101


def test_drag_backwards_is_normalised(overlay):
    drag(overlay, 200, 180, 60, 50)
    rect = overlay.image_rect()
    assert rect.left() == 60 and rect.top() == 50
    assert rect.right() == 200 and rect.bottom() == 180


def test_clear_removes_selection(overlay):
    drag(overlay, 10, 10, 100, 100)
    overlay.clear()
    assert not overlay.has_selection()
    assert overlay.image_rect() == QRect()


def test_select_all_covers_the_image(overlay):
    overlay.select_all()
    rect = overlay.image_rect()
    assert rect.left() == 0 and rect.top() == 0
    assert rect.width() == 400 and rect.height() == 300


# --- zoom mapping (the part that actually breaks) -------------------------

def test_selection_maps_through_zoom_out(app):
    """At 50% zoom a 100px drag must mean 200 image pixels."""
    widget = CropOverlay()
    widget.resize(400, 300)
    widget.configure(0.5, QSize(800, 600))
    drag(widget, 50, 50, 150, 150)
    rect = widget.image_rect()
    assert rect.left() == 100 and rect.top() == 100
    assert rect.width() == 201 and rect.height() == 201


def test_selection_maps_through_zoom_in(app):
    """At 200% zoom a 100px drag means only 50 image pixels."""
    widget = CropOverlay()
    widget.resize(400, 400)
    widget.configure(2.0, QSize(200, 200))
    drag(widget, 40, 40, 140, 140)
    rect = widget.image_rect()
    assert rect.left() == 20 and rect.top() == 20
    assert rect.width() == 51 and rect.height() == 51


def test_selection_is_clamped_to_the_image(app):
    widget = CropOverlay()
    widget.resize(400, 300)
    widget.configure(1.0, QSize(100, 80))
    drag(widget, 0, 0, 399, 299)
    rect = widget.image_rect()
    assert rect.right() < 100 and rect.bottom() < 80


def test_round_trip_image_rect(overlay):
    original = QRect(30, 20, 120, 90)
    overlay.set_image_rect(original)
    assert overlay.image_rect() == original


def test_exact_rect_survives_low_zoom(app):
    """A programmatic crop must not be distorted by the display scale.

    At fit-to-window zoom a 50px selection is only ~14 widget pixels, which
    round-trips back to 47 if widget coordinates are the source of truth.
    """
    widget = CropOverlay()
    widget.resize(56, 28)
    widget.configure(0.28, QSize(200, 100))
    widget.set_image_rect(QRect(0, 0, 50, 50))
    assert widget.image_rect() == QRect(0, 0, 50, 50)


def test_exact_rect_survives_zoom_change(app):
    widget = CropOverlay()
    widget.resize(200, 100)
    widget.configure(1.0, QSize(200, 100))
    widget.set_image_rect(QRect(10, 10, 80, 40))
    widget.configure(0.35, QSize(200, 100))
    assert widget.image_rect() == QRect(10, 10, 80, 40)


def test_user_drag_overrides_an_exact_rect(overlay):
    overlay.set_image_rect(QRect(0, 0, 50, 50))
    drag(overlay, 100, 100, 200, 200)
    rect = overlay.image_rect()
    assert rect.left() == 100 and rect.top() == 100, \
        "dragging must replace a programmatic selection"


def test_set_image_rect_is_clamped(app):
    widget = CropOverlay()
    widget.resize(100, 100)
    widget.configure(1.0, QSize(100, 100))
    widget.set_image_rect(QRect(50, 50, 500, 500))
    rect = widget.image_rect()
    assert rect.right() < 100 and rect.bottom() < 100


# --- editing an existing selection ----------------------------------------

def test_dragging_inside_moves_the_selection(overlay):
    overlay.set_image_rect(QRect(50, 50, 100, 100))
    press(overlay, 100, 100)      # inside
    move(overlay, 140, 130)
    release(overlay, 140, 130)
    rect = overlay.image_rect()
    assert rect.width() == 100 and rect.height() == 100, "size must be preserved"
    assert rect.left() == 90 and rect.top() == 80


def test_dragging_a_corner_resizes(overlay):
    overlay.set_image_rect(QRect(50, 50, 100, 100))
    press(overlay, 150, 150)      # bottom-right handle
    move(overlay, 250, 220)
    release(overlay, 250, 220)
    rect = overlay.image_rect()
    assert rect.left() == 50 and rect.top() == 50
    assert rect.right() == 250 and rect.bottom() == 220


def test_move_is_clamped_inside_the_widget(overlay):
    overlay.set_image_rect(QRect(0, 0, 100, 100))
    press(overlay, 50, 50)
    move(overlay, -500, -500)
    release(overlay, -500, -500)
    rect = overlay.image_rect()
    assert rect.left() >= 0 and rect.top() >= 0


def test_changed_signal_carries_image_coordinates(overlay):
    seen = []
    overlay.changed.connect(lambda r: seen.append(r))
    drag(overlay, 20, 30, 120, 130)
    assert seen
    assert seen[-1].left() == 20 and seen[-1].top() == 30


# --- end to end through the image tab -------------------------------------

@pytest.fixture
def photo(tmp_path):
    """Left half red, right half blue: cropping is verifiable by colour."""
    img = Image.new("RGB", (200, 100), (220, 20, 20))
    for x in range(100, 200):
        for y in range(100):
            img.putpixel((x, y), (20, 20, 220))
    p = tmp_path / "halves.png"
    img.save(p)
    return p


def test_crop_mode_toggles(app, photo):
    tab = ImageTab(photo)
    assert not tab.canvas.crop_active
    tab.toggle_crop()
    assert tab.canvas.crop_active
    tab.cancel_crop()
    assert not tab.canvas.crop_active


def test_crop_applies_the_selection(app, photo):
    tab = ImageTab(photo)
    tab.canvas.set_zoom(1.0)
    tab.toggle_crop()
    # Select the right (blue) half.
    tab.canvas.crop.set_image_rect(QRect(100, 0, 100, 100))
    tab.toggle_crop()          # second press applies

    assert tab.current.width == 100
    assert tab.current.height == 100
    assert tab.current.getpixel((50, 50)) == (20, 20, 220), "should be the blue half"


def test_crop_without_selection_is_a_no_op(app, photo):
    tab = ImageTab(photo)
    before = (tab.current.width, tab.current.height)
    tab.toggle_crop()
    tab.toggle_crop()          # apply with nothing selected
    assert (tab.current.width, tab.current.height) == before


def test_crop_is_undoable(app, photo):
    tab = ImageTab(photo)
    tab.toggle_crop()
    tab.canvas.crop.set_image_rect(QRect(0, 0, 50, 50))
    tab.toggle_crop()
    assert tab.current.width == 50
    tab.undo()
    assert tab.current.width == 200, "undo must restore the full image"


def test_crop_matches_the_backend_op(photo):
    """The tab's crop must equal a direct backend crop of the same box."""
    direct = ib.apply_ops(ib.load(photo), [ib.Op("crop", {"box": (100, 0, 200, 100)})])
    assert direct.width == 100
    assert direct.getpixel((10, 10)) == (20, 20, 220)


def test_escape_cancels_crop(app, photo):
    from PyQt6.QtGui import QKeyEvent
    tab = ImageTab(photo)
    tab.toggle_crop()
    tab.canvas.crop.set_image_rect(QRect(10, 10, 40, 40))
    tab.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                Qt.KeyboardModifier.NoModifier))
    assert not tab.canvas.crop_active
    assert tab.current.width == 200, "escape must not crop"
