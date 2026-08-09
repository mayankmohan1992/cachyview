"""Headless GUI smoke test: real QApplication, real tabs, real widgets."""
import pytest

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

from cachyview.core.mime import Kind
from cachyview.ui.main_window import MainWindow, PlaceholderTab
from cachyview.ui.text_tab import TextTab


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    w = MainWindow()
    yield w
    w.tabs.clear()
    w.deleteLater()


def test_opens_text_file(win, tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("import os\nprint('hi')\n")
    win.open_path(f)
    assert win.tabs.count() == 1
    tab = win.tabs.widget(0)
    assert isinstance(tab, TextTab)
    assert "print('hi')" in tab.editor.toPlainText()
    assert win.tabs.tabText(0) == "hello.py"


def test_edit_marks_modified_and_saves(win, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("original\n")
    win.open_path(f)
    tab = win.tabs.widget(0)
    assert not tab.is_modified()
    # Simulate real editing (setPlainText is a reload and resets the dirty flag).
    cursor = tab.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.insertText("edited content\n")
    assert tab.is_modified()
    assert win.tabs.tabText(0).endswith("•")
    assert tab.save()
    assert f.read_text() == "edited content\n"
    assert not tab.is_modified()


def test_duplicate_open_focuses_existing_tab(win, tmp_path):
    f = tmp_path / "one.txt"
    f.write_text("x")
    win.open_path(f)
    win.open_path(f)
    assert win.tabs.count() == 1


def test_pdf_routes_to_placeholder(win, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\ntrailer\n")
    win.open_path(f)
    tab = win.tabs.widget(0)
    assert isinstance(tab, PlaceholderTab)


def test_json_pretty_print(win, tmp_path):
    f = tmp_path / "d.json"
    f.write_text('{"b":2,"a":[1,2]}')
    win.open_path(f)
    tab = win.tabs.widget(0)
    tab.reformat("json")
    assert '\n  "b": 2' in tab.editor.toPlainText()


def test_find_moves_cursor(win, tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("alpha\nbeta\ngamma\n")
    win.open_path(f)
    tab = win.tabs.widget(0)
    tab.find_input.setText("gamma")
    tab.find_next()
    assert tab.editor.textCursor().selectedText() == "gamma"


def test_close_tab_without_changes(win, tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("x")
    win.open_path(f)
    win.close_tab(0)
    assert win.tabs.count() == 0


def test_line_number_gutter_has_width(win, tmp_path):
    f = tmp_path / "many.txt"
    f.write_text("\n".join(str(i) for i in range(500)))
    win.open_path(f)
    assert win.tabs.widget(0).editor.line_number_width() > 20
