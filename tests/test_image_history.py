"""Image edit-history persistence tests."""
from pathlib import Path

from PIL import Image

from cachyview.backends import image as ib
from cachyview.core import image_history as ih


def _make(path: Path, w=40, h=30) -> None:
    Image.new("RGB", (w, h), (120, 80, 40)).save(path)


def test_remember_round_trips_ops(tmp_path):
    src = tmp_path / "photo.jpg"
    _make(src)
    ops = [ib.Op("rotate", {"angle": 90}), ib.Op("grayscale", {})]
    ih.remember(src, ops)
    loaded = ih.load(src)
    assert [o.name for o in loaded] == ["rotate", "grayscale"]
    assert loaded[0].args == {"angle": 90}


def test_clear_removes_stack(tmp_path):
    src = tmp_path / "photo.jpg"
    _make(src)
    ih.remember(src, [ib.Op("rotate", {"angle": 180})])
    assert ih.load(src)
    ih.clear(src)
    assert ih.load(src) == []


def test_empty_stack_not_stored(tmp_path):
    src = tmp_path / "photo.jpg"
    _make(src)
    ih.remember(src, [])
    assert ih.load(src) == []


def test_load_unknown_path_is_empty(tmp_path):
    assert ih.load(tmp_path / "nope.png") == []
