"""PdfTab Preview-style inline editing tests.

These verify the new toolbar edits the open file IN PLACE (no extra tab opens)
and that the heavy operations are reachable from the overflow menu.
"""
import fitz
import pytest
from pathlib import Path

from PyQt6.QtCore import QEventLoop
from PyQt6.QtWidgets import QApplication

from cachyview.ui.pdf_tab import PdfTab
from cachyview.backends import pdf as pb
from cachyview.ui.pdf_tools import _run_in_place




@pytest.fixture
def pdf_file(tmp_path):
    doc = fitz.open()
    for i in range(3):
        doc.new_page()
    p = tmp_path / "doc.pdf"
    doc.save(p)
    doc.close()
    return p


def _wait(job) -> None:
    loop = QEventLoop()
    job.signals.finished.connect(loop.quit)
    job.signals.failed.connect(lambda *_: loop.quit())
    loop.exec()


def test_rotate_current_edits_in_place(app, pdf_file):
    tab = PdfTab(pdf_file)
    job = tab.rotate_current(90)
    _wait(job)
    doc = fitz.open(pdf_file)
    assert int(doc[0].rotation) == 90
    doc.close()
    tab.close()


def test_delete_current_removes_a_page(app, pdf_file):
    assert pb.info(pdf_file).page_count == 3
    tab = PdfTab(pdf_file)
    job = tab.delete_current()
    _wait(job)
    assert pb.info(pdf_file).page_count == 2
    tab.close()


def test_insert_after_adds_a_page(app, pdf_file, tmp_path):
    extra = tmp_path / "extra.pdf"
    d = fitz.open()
    d.new_page()
    d.save(extra)
    d.close()
    assert pb.info(pdf_file).page_count == 3
    tab = PdfTab(pdf_file)
    job = _run_in_place(
        tab, "Inserting",
        lambda tmp, ctx: pb.insert_pages(
            pdf_file, tmp, extra, after=tab.page, password=tab.password))
    _wait(job)
    assert pb.info(pdf_file).page_count == 4
    tab.close()


def test_toolbar_has_no_dropdown_selector(app, pdf_file):
    tab = PdfTab(pdf_file)
    assert tab.annot_btn is not None
    assert tab.present_btn is not None
    # The old dropdown tool selector is gone; heavy ops are in a menu.
    assert not hasattr(tab, "tool_box")
    tab.close()
