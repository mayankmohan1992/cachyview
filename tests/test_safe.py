"""Tests for atomic in-place replacement."""
import pytest
from pathlib import Path

from cachyview.core.safe import replace_in_place, safe_backup_path


def test_replace_writes_new_content(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("original")
    replace_in_place(target, lambda t: (Path(t).write_text("new"), None)[1])
    assert target.read_text() == "new"


def test_replace_keeps_backup(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("original")
    replace_in_place(target, lambda t: (Path(t).write_text("new"), None)[1])
    backup = safe_backup_path(target)
    assert backup.exists()
    assert backup.read_text() == "original"


def test_replace_failure_leaves_original(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("original")

    def boom(t):
        Path(t).write_text("partial")
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError):
        replace_in_place(target, boom)
    assert target.read_text() == "original"


def test_replace_failure_leaves_no_temp_file(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("original")

    def boom(t):
        Path(t).write_text("partial")
        raise RuntimeError()

    with pytest.raises(RuntimeError):
        replace_in_place(target, boom)
    assert not list(tmp_path.glob("*.cachyview-tmp-*"))


def test_replace_refuses_empty_output(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("original")

    def empty(t):
        Path(t).write_text("")  # simulates a failed write

    with pytest.raises(OSError):
        replace_in_place(target, empty)
    assert target.read_text() == "original"


def test_replace_missing_target_writes_directly(tmp_path):
    target = tmp_path / "new.txt"
    replace_in_place(target, lambda t: (Path(t).write_text("created"), None)[1])
    assert target.read_text() == "created"
    # No backup when there was nothing to back up.
    assert not safe_backup_path(target).exists()
