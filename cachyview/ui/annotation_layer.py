"""Interactive annotation overlay for the PDF page view.

Sits transparently on top of the rendered page and converts a drag rectangle
into a PDF annotation.  While the mode is ``off`` the overlay is hidden and
mouse events fall through to the scroll area, so panning and wheel-zoom keep
working.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QInputDialog, QWidget

from ..backends import pdf as pb

MIN_DRAG = 4  # px — anything smaller is treated as a click, not a selection


class AnnotationLayer(QWidget):
    """A transparent, page-sized overlay that records drag selections."""

    def __init__(self, tab: "object"):
        # Parent is the page label so geometry tracks the rendered pixmap.
        super().__init__(tab.page_label)
        self.tab = tab
        self.mode = "off"            # off | highlight | underline | note
        self.color = (1.0, 0.85, 0.2)
        self.show_marks = True

        self._drag_start: QPoint | None = None
        self._draft: QRect | None = None
        self._page_annotations: list[pb.Annotation] = []

        self.setMouseTracking(True)
        self.hide()

    # --- geometry ---------------------------------------------------------
    def sync_geometry(self) -> None:
        """Match the rendered pixmap exactly (no letterbox padding)."""
        label = self.parentWidget()
        if label is not None:
            self.setGeometry(0, 0, label.width(), label.height())

    # --- mode -------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "off":
            self._draft = None
            self._drag_start = None
            self.hide()
        else:
            self.show()
            self.raise_()
        self.update()

    # --- data -------------------------------------------------------------
    def refresh(self) -> None:
        """Reload the annotations for the current page from the file."""
        if self.tab.info is None:
            self._page_annotations = []
        else:
            try:
                all_anns = pb.list_annotations(self.tab.path, self.tab.password)
            except pb.PdfError:
                all_anns = []
            self._page_annotations = [a for a in all_anns
                                     if a.page == self.tab.page]
        self.update()

    def set_show_marks(self, value: bool) -> None:
        self.show_marks = value
        self.update()

    # --- coordinate mapping ----------------------------------------------
    # The rendered pixmap is ``zoom`` px per PDF point.  PDF y grows upward.
    def _widget_to_pdf(self, x: float, y: float) -> tuple[float, float]:
        zoom = self.tab.zoom
        page = self.tab.info.pages[self.tab.page - 1]
        return (x / zoom, page.height - (y / zoom))

    def _pdf_to_widget_rect(self, rect) -> QRectF:
        zoom = self.tab.zoom
        page = self.tab.info.pages[self.tab.page - 1]
        x0 = rect[0] * zoom
        y0 = (page.height - rect[3]) * zoom
        x1 = rect[2] * zoom
        y1 = (page.height - rect[1]) * zoom
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    # --- interaction ------------------------------------------------------
    def mousePressEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is None or self.mode == "off":
            return
        self._drag_start = a0.position().toPoint()
        self._draft = QRect(self._drag_start, QSize(1, 1))
        self.update()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is None or self._drag_start is None:
            return
        pos = a0.position().toPoint()
        # clamp inside the page
        pos.setX(max(0, min(pos.x(), self.width())))
        pos.setY(max(0, min(pos.y(), self.height())))
        self._draft = QRect(self._drag_start, pos).normalized()
        self.update()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is None or self._drag_start is None:
            return
        rect = self._draft
        self._drag_start = None
        self._draft = None
        if rect is None or rect.width() < MIN_DRAG or rect.height() < MIN_DRAG:
            self.update()
            return

        # bottom-left -> PDF, then top-right -> PDF
        x0, y0 = self._widget_to_pdf(rect.left(), rect.bottom())
        x1, y1 = self._widget_to_pdf(rect.right(), rect.top())
        pdf_rect = (x0, y0, x1, y1)

        text = ""
        if self.mode == "note":
            text, ok = QInputDialog.getText(self, "Add note",
                                            "Comment for this note:")
            if not ok:
                self.update()
                return

        self.tab.apply_annotation(self.mode, pdf_rect, self.color, text)
        self.update()

    # --- painting ---------------------------------------------------------
    def paintEvent(self, a0) -> None:  # noqa: N802
        if self.mode == "off" and not self.show_marks:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.show_marks:
            for ann in self._page_annotations:
                r = self._pdf_to_widget_rect(ann.rect)
                col = QColor(int(ann.color[0] * 255), int(ann.color[1] * 255),
                             int(ann.color[2] * 255))
                if ann.kind == "note":
                    painter.setPen(QPen(col, 2))
                    painter.setBrush(col)
                    painter.drawRect(int(r.x()), int(r.y()), 12, 12)
                else:
                    col.setAlpha(90)
                    painter.fillRect(r, col)
                    painter.setPen(QPen(col.darker(120), 1))
                    painter.drawRect(r)

        if self._draft is not None and self.mode != "off":
            col = QColor(int(self.color[0] * 255), int(self.color[1] * 255),
                         int(self.color[2] * 255))
            col.setAlpha(110)
            painter.fillRect(self._draft, col)
            painter.setPen(QPen(col.darker(120), 1.5))
            painter.drawRect(self._draft)
        painter.end()
