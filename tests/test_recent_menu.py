"""UI test: opening files populates the Recent menu."""
import pytest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from cachyview.ui.main_window import MainWindow
from cachyview.core import recents




@pytest.fixture(autouse=True)
def clean_store(tmp_path, monkeypatch):
    # Point the store at a temp dir so tests don't touch real config.
    store = tmp_path / "cfg"
    store.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(recents, "_store_dir", lambda: store)
    yield
    recents.save({"recents": [], "pins": []})


@pytest.fixture
def pdf_file(tmp_path):
    import fitz
    doc = fitz.open()
    doc.new_page()
    src = tmp_path / "doc.pdf"
    doc.save(src)
    doc.close()
    return src


def test_recent_menu_populates_after_open(app, pdf_file):
    win = MainWindow()
    win.open_path(pdf_file)
    labels = [act.text() for act in win.recent_menu.actions()]
    assert any(pdf_file.name in lab for lab in labels), labels
    win.close()


def test_recent_menu_empty_state(app):
    win = MainWindow()
    win._fill_recent_menu()
    labels = [act.text() for act in win.recent_menu.actions()]
    assert "(no recent files)" in labels
    win.close()


def test_session_restore_reopens_files(app, tmp_path):
    import fitz
    files = []
    for i in range(2):
        d = fitz.open(); d.new_page(); p = tmp_path / f"f{i}.pdf"
        d.save(p); d.close(); files.append(p)
    win = MainWindow()
    for f in files:
        win.open_path(f)
    win.save_session()
    win.close()

    win2 = MainWindow()
    win2.restore_session()
    opened = [win2.tabs.tabText(i) for i in range(win2.tabs.count())]
    assert any(files[0].name in t for t in opened)
    win2.close()


def test_tab_context_menu_pins_and_unpins(app, pdf_file):
    win = MainWindow()
    win.open_path(pdf_file)
    win._toggle_pin(pdf_file, True)
    assert str(pdf_file) in recents.load()["pins"]
    win._toggle_pin(pdf_file, False)
    assert str(pdf_file) not in recents.load()["pins"]
    win.close()

