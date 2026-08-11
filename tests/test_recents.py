"""Tests for the persistent recents / pins store."""
from pathlib import Path

from cachyview.core import recents


def test_remember_pushes_to_front_and_dedups(tmp_path):
    a, b, c = tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "c.pdf"
    for p in (a, b, c, a):
        recents.remember(p)
    state = recents.load()
    assert state["recents"][0] == str(a), "most recent first"
    assert state["recents"].count(str(a)) == 1, "no duplicates"


def test_remember_caps_list(tmp_path, monkeypatch):
    monkeypatch.setattr(recents, "MAX_RECENTS", 3)
    for i in range(6):
        recents.remember(tmp_path / f"f{i}.pdf")
    state = recents.load()
    assert len(state["recents"]) == 3


def test_pin_and_unpin(tmp_path):
    p = tmp_path / "pinned.pdf"
    recents.pin(p)
    assert str(p) in recents.load()["pins"]
    recents.unpin(p)
    assert str(p) not in recents.load()["pins"]


def test_existing_filters_missing_files(tmp_path):
    good = tmp_path / "good.pdf"
    good.write_text("x")
    gone = tmp_path / "gone.pdf"
    state = {"recents": [str(good), str(gone)], "pins": []}
    kept = recents.existing(state)
    assert kept["recents"] == [str(good)]
