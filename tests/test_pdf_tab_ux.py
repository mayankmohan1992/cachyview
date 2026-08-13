"""PdfTab Preview-style UX tests: sidebar, zoom slider, annotate menu, thumbs."""
import fitz
import pytest
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QPoint, Qt
from PyQt6.QtGui import QImage, QMouseEvent
from PyQt6.QtWidgets import QApplication

from cachyview.ui.pdf_tab import PdfTab
from cachyview.ui import pdf_tab as pdf_tab_module


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def doc(tmp_path):
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=400, height=500)
    p = tmp_path / "doc.pdf"
    d.save(p)
    d.close()
    return p


def test_sidebar_toggle(doc, app):
    tab = PdfTab(doc)
    tab.show()
    assert tab._side.isVisible()
    assert tab.sidebar_btn.isChecked()
    tab._toggle_sidebar()
    assert not tab._side.isVisible()
    assert not tab.sidebar_btn.isChecked()
    tab._toggle_sidebar()
    assert tab._side.isVisible()
    tab.close()


def test_zoom_slider_drives_render(doc, app):
    tab = PdfTab(doc)
    tab._on_zoom_slider(250)
    assert abs(tab.zoom - 2.5) < 1e-6
    tab.zoom_out()
    assert tab.zoom_slider.value() == int(tab.zoom * 100)
    tab.close()


def test_annotate_menu_lists_shapes(doc, app):
    tab = PdfTab(doc)
    labels = [a.text() for a in tab.annot_menu.actions() if a.text()]
    for expected in ("Highlight", "Underline", "Strikethrough", "Rectangle",
                     "Oval", "Line", "Arrow", "Sketch", "Note",
                     "Redact (permanent)", "None (off)"):
        assert expected in labels, f"missing {expected}"
    tab.close()


def test_thumbnail_multiselect_delete(doc, app):
    from PyQt6.QtCore import QItemSelectionModel
    tab = PdfTab(doc)
    tab.thumbs.setSelectionMode(tab.thumbs.SelectionMode.ExtendedSelection)
    sel = tab.thumbs.selectionModel()
    for r in (0, 2):
        idx = tab.thumbs.model().index(r, 0)
        sel.select(idx, QItemSelectionModel.SelectionFlag.Select
                   | QItemSelectionModel.SelectionFlag.Rows)
    assert sorted(tab._selected_pages()) == [1, 3]
    job = tab.delete_pages([1, 3])
    loop = QEventLoop()
    job.signals.finished.connect(loop.quit)
    job.signals.failed.connect(lambda *_: loop.quit())
    loop.exec()
    assert fitz.open(doc).page_count == 1
    tab.close()


def test_sign_captures_and_places(doc, app, monkeypatch, tmp_path):
    sig = tmp_path / "sig.png"
    img = QImage(200, 80, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    img.save(str(sig), "PNG")

    from cachyview.ui.signature_dialog import SignatureDialog

    class FakeDlg(SignatureDialog):
        def exec(self):  # noqa: N802
            self.result_path = sig
            return self.DialogCode.Accepted

    monkeypatch.setattr(SignatureDialog, "__init__", lambda self: None)
    monkeypatch.setattr(
        "cachyview.ui.signature_dialog.SignatureDialog",
        lambda *a, **k: FakeDlg())
    tab = PdfTab(doc)
    tab.go_to(1)
    tab.sign()
    assert tab._placing_signature == sig
    w = tab.page_label.width() or 400
    h = tab.page_label.height() or 500
    tab._place_signature_at(QPoint(w // 2, h // 2))
    doc2 = fitz.open(doc)
    stamped = any(p.get_images() for p in doc2)
    doc2.close()
    assert stamped, "signature image should be stamped into the PDF"
    tab.close()


def test_ranges_label():
    assert pdf_tab_module._ranges_label([1]) == "1"
    assert pdf_tab_module._ranges_label([1, 2, 3]) == "1-3"
    assert pdf_tab_module._ranges_label([1, 3, 4, 5, 7]) == "1,3-5,7"
    assert pdf_tab_module._ranges_label([]) == ""
