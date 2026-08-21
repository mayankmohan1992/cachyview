"""PdfTab Preview-style UX tests: sidebar, zoom slider, annotate menu, thumbs."""
import fitz
import pytest
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QPoint, Qt
from PyQt6.QtGui import QImage, QMouseEvent
from PyQt6.QtWidgets import QApplication

from cachyview.ui.pdf_tab import PdfTab
from cachyview.ui import pdf_tab as pdf_tab_module




@pytest.fixture
def doc(tmp_path):
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=400, height=500)
    p = tmp_path / "doc.pdf"
    d.save(p)
    d.close()
    return p


def test_sidebar_has_contents_tab(doc, app):
    tab = PdfTab(doc)
    assert tab.side_tabs.count() == 2
    assert tab.side_tabs.tabText(0) == "Pages"
    assert tab.side_tabs.tabText(1) == "Contents"
    tab.side_tabs.setCurrentIndex(1)
    assert tab.side_tabs.currentIndex() == 1
    tab.close()


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


def test_outline_click_jumps_to_page(tmp_path, app):
    d = fitz.open()
    for _ in range(4):
        d.new_page(width=200, height=200)
    d.set_toc([(1, "Chapter two", 2), (1, "Chapter four", 4)])
    src = tmp_path / "toc.pdf"
    d.save(src)
    d.close()
    tab = PdfTab(src)
    assert tab.outline.count() == 2
    tab.outline.itemClicked.emit(tab.outline.item(0))
    assert tab.page == 2
    tab.outline.itemClicked.emit(tab.outline.item(1))
    assert tab.page == 4
    tab.close()


def test_first_page_renders_without_thumb_click(doc, app):
    tab = PdfTab(doc)
    QApplication.processEvents()
    assert tab.strip.has_pixmap(1)
    pix = tab.page_label.pixmap()
    assert pix is not None and not pix.isNull()
    tab.close()


def test_layout_modes_rebuild(doc, app):
    tab = PdfTab(doc)
    tab.strip.set_layout_mode("single")
    assert tab.strip.layout_mode == "single"
    assert len(tab.strip._geoms) == 1
    tab.strip.set_layout_mode("facing")
    assert tab.strip._geoms
    tab.strip.set_layout_mode("continuous")
    assert len(tab.strip._geoms) == 3
    tab.close()


def test_text_select_copies_words(tmp_path, app):
    d = fitz.open()
    page = d.new_page(width=400, height=400)
    page.insert_text((50, 80), "HelloWorld", fontsize=20)
    src = tmp_path / "words.pdf"
    d.save(src)
    d.close()
    tab = PdfTab(src)
    QApplication.processEvents()
    view = tab.strip
    view._ensure_words(1)
    words = view._words.get(1) or []
    assert words, "MuPDF should return word boxes"
    g = view._geoms[0]
    view._sel_page = 1
    view._sel_words = view._words_in_rect(
        1, QPoint(g.x, g.y), QPoint(g.x + g.w, g.y + g.h))
    assert view._sel_words
    tab.close()
