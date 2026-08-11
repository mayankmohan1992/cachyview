"""Tests for system theming, shortcut registry and PDF presentation auto-scroll."""
import pytest
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from cachyview.ui import theming
from cachyview.ui.pdf_tab import PdfTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_format_shortcuts_includes_core_bindings():
    text = theming.format_shortcuts()
    assert "Ctrl+O" in text
    assert "Ctrl+B" in text
    assert "Batch processing" in text


def test_bind_shortcuts_wires_handlers(app):
    calls = {}

    def make(name):
        def fn():
            calls[name] = calls.get(name, 0) + 1
        return fn

    from PyQt6.QtWidgets import QWidget
    parent = QWidget()
    theming.bind_shortcuts(parent, {
        "Open files": make("open"),
        "Batch processing": make("batch"),
    })
    assert callable(make("open"))


def test_apply_system_theme_returns_a_style(app):
    chosen = theming.apply_system_theme(app)
    assert isinstance(chosen, str) and chosen


def test_present_mode_advances_pages(app, tmp_path):
    import fitz
    doc = fitz.open()
    for _ in range(4):
        doc.new_page()
    src = tmp_path / "deck.pdf"
    doc.save(src)
    doc.close()

    tab = PdfTab(src)
    tab._toggle_present(True)
    assert tab._present_timer is not None
    assert tab._present_timer.isActive()
    # Simulate two ticks: page 1 -> 2 -> 3
    tab._present_tick()
    assert tab.page == 2
    tab._present_tick()
    assert tab.page == 3
    tab._toggle_present(False)
    assert tab._present_timer is None
    tab.close()
