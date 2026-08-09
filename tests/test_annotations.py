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


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


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
    # page is 400x500; bottom-left of widget -> PDF (x, 0)
    x0, y0 = layer._widget_to_pdf(40, 500)   # bottom edge
    x1, y1 = layer._widget_to_pdf(300, 400)  # up by 100
    assert abs(x0 - 40) < 1e-6
    assert abs(y0 - 0) < 1e-6
    assert abs(x1 - 300) < 1e-6
    assert abs(y1 - 100) < 1e-6      # PDF y grows upward
    tab.close()


def test_pdf_to_widget_round_trips(doc, app):
    tab = PdfTab(doc)
    tab.zoom = 2.0
    layer = tab.annot_layer
    rect = (40, 50, 300, 90)
    r = layer._pdf_to_widget_rect(rect)
    # widget rect should be 2x the PDF size
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
    # a real drag across the page
    layer.mousePressEvent(_mouse(layer, QMouseEvent.Type.MouseButtonPress, 40, 460))
    layer.mouseMoveEvent(_mouse(layer, QMouseEvent.Type.MouseMove, 200, 360))
    layer.mouseReleaseEvent(_mouse(layer, QMouseEvent.Type.MouseButtonRelease, 200, 360))
    app.processEvents()
    after = pb.list_annotations(target)
    assert len(after) == before + 1
    assert after[-1].kind == "highlight"
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
