"""Tests for the batch backend."""
import fitz
import pytest
from PIL import Image
from pathlib import Path

from cachyview.backends import batch as b
from cachyview.backends import image as ib, pdf as pb


@pytest.fixture
def workdir(tmp_path):
    # Three images + one small PDF.
    for i in range(3):
        Image.new("RGB", (60, 40), (i * 60, 20, 20)).save(tmp_path / f"img{i}.png")
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "hi", fontsize=20)
    doc.save(tmp_path / "doc.pdf")
    doc.close()
    return tmp_path


def test_image_chain_rotates_and_grayscales(workdir):
    job = b.BatchJob("t", [{"tool": "rotate", "angle": 90},
                            {"tool": "grayscale"}])
    for i in range(3):
        job.add_file(workdir / f"img{i}.png")
    b.run_batch(job)
    assert all(it.status == "done" for it in job.items)
    for it in job.items:
        out = ib.load(it.output)
        assert out.mode == "L", "must be greyscale"
        assert out.size[1] == 60 and out.size[0] == 40, "rotated 90°"


def test_pdf_compress_runs(workdir):
    job = b.BatchJob("t", [{"tool": "compress", "tier": "ebook"}])
    job.add_file(workdir / "doc.pdf")
    b.run_batch(job)
    assert job.items[0].status == "done"
    assert pb.info(job.items[0].output).page_count == 1


def test_output_dir_is_respected(workdir, tmp_path):
    out = tmp_path / "out"
    job = b.BatchJob("t", [{"tool": "grayscale"}], output_dir=out)
    for i in range(3):
        job.add_file(workdir / f"img{i}.png")
    b.run_batch(job)
    assert out.is_dir()
    assert len(list(out.glob("*.png"))) == 3


def test_one_bad_file_does_not_stop_the_batch(workdir):
    job = b.BatchJob("t", [{"tool": "rotate", "angle": 90}])
    job.add_file(workdir / "img0.png")
    job.add_file(workdir / "missing.png")          # does not exist
    job.add_file(workdir / "img1.png")
    b.run_batch(job)
    statuses = {it.source.name: it.status for it in job.items}
    assert statuses["img0.png"] == "done"
    assert statuses["missing.png"] == "failed"
    assert statuses["img1.png"] == "done"


def test_unsupported_type_fails_the_item(workdir):
    (workdir / "note.txt").write_text("x")
    job = b.BatchJob("t", [{"tool": "rotate", "angle": 90}])
    job.add_file(workdir / "note.txt")
    b.run_batch(job)
    assert job.items[0].status == "failed"
    assert "Unsupported" in job.items[0].message


def test_unknown_operation_fails_the_item(workdir):
    job = b.BatchJob("t", [{"tool": "frobnicate"}])
    job.add_file(workdir / "img0.png")
    b.run_batch(job)
    assert job.items[0].status == "failed"
    assert "Unknown" in job.items[0].message


def test_done_items_are_skipped_on_rerun(workdir):
    job = b.BatchJob("t", [{"tool": "grayscale"}])
    job.add_file(workdir / "img0.png")
    b.run_batch(job)
    first = job.items[0].status
    # Re-processing the same job must not touch already-done items.
    b.run_batch(job)
    assert first == "done" and job.items[0].status == "done"


def test_trace_is_captured_on_failure(workdir):
    job = b.BatchJob("t", [{"tool": "frobnicate"}])
    job.add_file(workdir / "img0.png")
    b.run_batch(job)
    assert job.items[0].trace, "a failed item should keep its traceback"
