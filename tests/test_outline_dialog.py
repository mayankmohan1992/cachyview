"""Outline / bookmark editor dialog tests."""
import fitz
import pytest
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from cachyview.backends import pdf as pb
from cachyview.ui.outline_dialog import OutlineDialog




@pytest.fixture
def pdf_file(tmp_path):
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    p = tmp_path / "doc.pdf"
    doc.save(p)
    doc.close()
    return p


def test_dialog_lists_existing_outline(pdf_file, app):
    pb.set_outline(pdf_file, pdf_file, [
        {"title": "A", "page": 1, "level": 0},
        {"title": "B", "page": 2, "level": 0},
    ])
    dlg = OutlineDialog(pdf_file)
    assert dlg.list.count() == 2
    dlg.close()


def test_dialog_save_writes_outline(pdf_file, app):
    dlg = OutlineDialog(pdf_file)
    dlg._add_row("Intro", 1, 0)
    dlg._add_row("Detail", 2, 1)
    dlg._save()
    items = pb.get_outline(pdf_file)
    assert {i["title"] for i in items} == {"Intro", "Detail"}
    assert {(i["title"], i["page"]) for i in items} == {
        ("Intro", 1), ("Detail", 2)}
    dlg.close()


def test_dialog_remove_row(pdf_file, app):
    dlg = OutlineDialog(pdf_file)
    dlg._add_row("Keep", 1, 0)
    dlg._add_row("Drop", 1, 0)
    assert dlg.list.count() == 2
    dlg.list.setCurrentRow(1)
    dlg._remove()
    assert dlg.list.count() == 1
    dlg.close()


def test_dialog_move_reorders(pdf_file, app):
    dlg = OutlineDialog(pdf_file)
    dlg._add_row("First", 1, 0)
    dlg._add_row("Second", 2, 0)
    dlg.list.setCurrentRow(1)
    dlg._move(-1)  # move Second up
    first_title = dlg.list.item(0).data(Qt.ItemDataRole.UserRole)["title"]
    assert first_title == "Second"
    dlg.close()


def test_dialog_loads_selected_into_fields(pdf_file, app):
    dlg = OutlineDialog(pdf_file)
    dlg._add_row("Chapter", 2, 1)
    dlg.list.setCurrentRow(0)
    assert dlg._title.text() == "Chapter"
    assert dlg._page.value() == 2
    assert dlg._level.value() == 1
    dlg.close()


def test_dialog_update_edits_row(pdf_file, app):
    dlg = OutlineDialog(pdf_file)
    dlg._add_row("Draft", 1, 0)
    dlg.list.setCurrentRow(0)
    dlg._update("Final", 2, 1)
    dlg._save()
    items = pb.get_outline(pdf_file)
    assert [(i["title"], i["page"], i["level"]) for i in items] == [
        ("Final", 2, 1)]
    dlg.close()
