"""Annotation UI tests: coordinate mapping and PdfTab wiring."""
import fitz
import pytest
from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, QPointF, QRect
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtWidgets import QApplication

from cachyview.backends import pdf as pb
from cachyview.ui.annotation_layer import AnnotationLayer
from cachyview.ui.pdf_tab import PdfTab




@pytest.fixture
def doc(tmp_path):
    d = fitz.open()
    p = d.new_page(width=400, height=500)
    p.insert_text((50, 80), "Page 1 text here", fontsize=20)
    path = tmp_path / "doc.pdf"
    d.save(str(path))
    d.close()
    return path


def _mouse(widget, kind, x, y):
    evt = QMouseEvent(
        kind, QPointF(x, y), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    return evt


def test_layer_maps_widget_to_pdf_points(doc, app):
    tab = PdfTab(doc)
    tab.zoom = 1.0
    layer = tab.annot_layer
    g = tab.strip._geoms[0]
    x0, y0 = layer._widget_to_pdf(g.x + 40, g.y + 500)
    x1, y1 = layer._widget_to_pdf(g.x + 300, g.y + 400)
    assert abs(x0 - 40) < 1e-6
    assert abs(y0 - 0) < 1e-6
    assert abs(x1 - 300) < 1e-6
    assert abs(y1 - 100) < 1e-6
    tab.close()


def test_pdf_to_widget_round_trips(doc, app):
    tab = PdfTab(doc)
    tab.zoom = 2.0
    tab.strip.set_zoom(2.0)
    layer = tab.annot_layer
    rect = (40, 50, 300, 90)
    r = layer._pdf_to_widget_rect(1, rect)
    assert abs(r.width() - (300 - 40) * 2) < 1e-6
    assert abs(r.height() - (90 - 50) * 2) < 1e-6
    tab.close()


def test_apply_annotation_writes_into_file(doc, app, tmp_path):
    import shutil
    target = tmp_path / "annotated.pdf"
    shutil.copy(doc, target)
    tab = PdfTab(target)
    tab.go_to(1)
    before = len(pb.list_annotations(target))
    # simulate a drag-select on the page
    layer = tab.annot_layer
    layer.set_mode("highlight")
    layer.sync_geometry()
    g = tab.strip._geoms[0]
    layer.mousePressEvent(_mouse(layer, QMouseEvent.Type.MouseButtonPress, g.x + 40, g.y + 460))
    layer.mouseMoveEvent(_mouse(layer, QMouseEvent.Type.MouseMove, g.x + 200, g.y + 360))
    layer.mouseReleaseEvent(_mouse(layer, QMouseEvent.Type.MouseButtonRelease, g.x + 200, g.y + 360))
    app.processEvents()
    tab.save()
    after = pb.list_annotations(target)
    assert len(after) == before + 1
    assert after[-1].kind == "highlight"
    tab.close()


def test_pending_annotation_dropped_when_page_deleted(tmp_path, app):
    d = fitz.open()
    d.new_page()
    d.new_page()
    src = tmp_path / "two.pdf"
    d.save(src)
    d.close()
    tab = PdfTab(src)
    tab.apply_annotation("highlight", (10, 10, 40, 40), (1, 1, 0), "", page=1)
    tab.apply_annotation("rectangle", (10, 10, 40, 40), (1, 0, 0), "", page=2)
    assert [a.page for a in tab._pending] == [1, 2]
    tab._drop_pending_on_pages([1])
    assert [a.page for a in tab._pending] == [1]
    assert tab._pending[0].kind == "rectangle"
    tab.close()


def test_undo_removes_last_pending_annotation(doc, app):
    tab = PdfTab(doc)
    tab.apply_annotation("highlight", (10, 10, 40, 40), (1, 1, 0), "")
    assert tab._pending
    tab.undo()
    assert not tab._pending
    tab.close()


def test_select_and_recolor_pending(doc, app):
    tab = PdfTab(doc)
    tab.apply_annotation("rectangle", (40, 50, 120, 90), (1.0, 0.85, 0.2), "")
    tab.annot_layer.refresh()
    g = tab.strip._geoms[0]
    # centre of the rect in widget space at zoom 1: x=80, y = 500-90=410 ... 
    # wait page 500 tall, y_widget = g.y + (500-90)*1 = g.y+410
    hit = tab.annot_layer.try_select(g.x + 80, g.y + 410)
    assert hit
    assert tab.annot_layer.selected() is not None
    tab._recolor_annotation(tab.annot_layer.selected(), (0.0, 0.0, 1.0))
    assert tab._pending[0].color[2] == 1.0
    tab.close()


def test_annotation_mode_off_hides_layer(doc, app):
    tab = PdfTab(doc)
    layer = tab.annot_layer
    layer.set_mode("highlight")
    assert layer.mode == "highlight"
    if tab.isVisible():
        assert layer.isVisible()
    layer.set_mode("off")
    assert layer.mode == "off"
    tab.close()


def test_escape_exits_annotation_mode(doc, app):
    from PyQt6.QtGui import QKeyEvent
    tab = PdfTab(doc)
    layer = tab.annot_layer
    layer.set_mode("highlight")
    tab.annot_btn.setChecked(True)
    tab.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                Qt.KeyboardModifier.NoModifier))
    assert layer.mode == "off"
    assert not tab.annot_btn.isChecked()
    tab.close()


def test_redact_removes_text_when_confirmed(doc, app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    # Auto-confirm the destructive action.
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    tab = PdfTab(doc)
    # A rect covering the text region on page 1.
    tab.apply_redaction((40, 70, 360, 110))
    remaining = fitz.open(tab.path).get_page_text(0)
    assert "Page 1 text here" not in remaining, "redacted text must be gone"
    tab.close()


def test_redact_aborts_when_declined(doc, app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.No)
    tab = PdfTab(doc)
    tab.apply_redaction((40, 70, 360, 110))
    remaining = fitz.open(tab.path).get_page_text(0)
    assert "Page 1 text here" in remaining, "declined redaction keeps text"
    tab.close()

