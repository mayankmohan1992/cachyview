"""Batch panel UI tests."""
import fitz
import pytest
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from cachyview.backends import batch as b
from cachyview.ui.batch_panel import BatchPanel
from cachyview.backends import image as ib




@pytest.fixture
def workdir(tmp_path):
    for i in range(3):
        from PIL import Image
        Image.new("RGB", (60, 40), (i * 60, 20, 20)).save(tmp_path / f"img{i}.png")
    return tmp_path


def test_panel_builds_a_job(workdir, app):
    panel = BatchPanel()
    panel.files.addItem(str(workdir / "img0.png"))
    # Add a rotation op.
    panel.ops.setCurrentIndex(5)   # Image -> Rotate 90
    panel._add_op()
    assert panel.op_list.count() == 1
    job = panel._build_job()
    assert job is not None
    assert len(job.items) == 1
    assert job.operations[0]["tool"] == "rotate"


def test_panel_rejects_empty(workdir, app):
    panel = BatchPanel()
    assert panel._build_job() is None, "no files -> no job"
    panel.files.addItem(str(workdir / "img0.png"))
    assert panel._build_job() is None, "files but no ops -> no job"


def test_panel_runs_and_updates_rows(workdir, app):
    panel = BatchPanel()
    for i in range(3):
        panel.files.addItem(str(workdir / f"img{i}.png"))
    panel.ops.setCurrentIndex(5)   # rotate
    panel._add_op()

    finished = []
    panel.job_started.connect(lambda _j: None)
    panel.start()
    # The async job runs on the thread pool; pump the event loop until done.
    from PyQt6.QtCore import QTimer
    import time
    deadline = time.time() + 10
    while time.time() < deadline:
        app.processEvents()
        if panel._job is not None and all(it.status in ("done", "failed") for it in panel._job.items):
            break
        time.sleep(0.02)

    app.processEvents()
    assert panel._job is not None
    assert all(it.status == "done" for it in panel._job.items)
    # The table reflects per-row status.
    assert panel.table.rowCount() == 3
    for r in range(3):
        assert panel.table.item(r, 1).text() == "done"


def test_panel_shows_failure_in_red(workdir, app):
    panel = BatchPanel()
    (workdir / "note.txt").write_text("x")
    panel.files.addItem(str(workdir / "note.txt"))
    panel.ops.setCurrentIndex(5)   # rotate (image op on a .txt)
    panel._add_op()
    panel.start()
    import time
    deadline = time.time() + 10
    while time.time() < deadline:
        app.processEvents()
        if panel._job and panel._job.items[0].status in ("done", "failed"):
            break
        time.sleep(0.02)
    # The row colour is applied via a queued signal; flush it.
    app.processEvents()
    assert panel._job.items[0].status == "failed"
    # The status cell is coloured red.
    assert panel.table.item(0, 1).foreground().color().red() > 128
