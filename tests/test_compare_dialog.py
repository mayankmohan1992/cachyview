"""Compare dialog tests."""
import fitz
import pytest
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QPoint
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from cachyview.backends import pdf as pb
from cachyview.ui.compare_dialog import CompareDialog




def _make(text, tmp_path, name):
    p = tmp_path / name
    doc = fitz.open()
    pg = doc.new_page(width=400, height=400)
    pg.insert_text((40, 40), text, fontsize=24)
    doc.save(p)
    doc.close()
    return p


def test_compare_lists_changed_pages(app, tmp_path):
    a = _make("Original", tmp_path, "a.pdf")
    b = _make("Revised!", tmp_path, "b.pdf")
    dlg = CompareDialog()
    dlg.a = str(a)
    dlg.b = str(b)
    dlg._compare()
    assert dlg.list.count() == 1
    text = dlg.list.item(0).text()
    assert "CHANGED" in text
    dlg.close()


def test_compare_identical_reports_same(app, tmp_path):
    a = _make("Same", tmp_path, "a.pdf")
    b = _make("Same", tmp_path, "b.pdf")
    dlg = CompareDialog()
    dlg.a = str(a)
    dlg.b = str(b)
    dlg._compare()
    assert "same" in dlg.list.item(0).text()
    dlg.close()


def test_compare_requires_both_files(app, tmp_path):
    dlg = CompareDialog()
    dlg.a = str(_make("x", tmp_path, "a.pdf"))
    dlg.b = None
    dlg._compare()
    assert "Pick both" in dlg.status.text()
    dlg.close()
