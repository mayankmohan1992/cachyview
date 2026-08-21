"""Interactive annotation overlay for the PDF canvas.

Parent is the virtualized canvas so geometry matches painted pages.  While the
mode is ``off`` mouse events pass through for text selection and scrolling.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QInputDialog, QWidget

from ..backends import pdf as pb

MIN_DRAG = 4
_FREEHAND = {"sketch"}


class AnnotationLayer(QWidget):
    def __init__(self, tab: "object"):
        super().__init__(tab.strip.canvas)
        self.tab = tab
        self.mode = "off"
        self.color = (1.0, 0.85, 0.2)
        self.show_marks = True
        self._target_page = 1
        self._drag_start: QPoint | None = None
        self._draft: QRect | None = None
        self._freehand: list[QPoint] = []
        self._page_annotations: list[pb.Annotation] = []
        self._selected: pb.Annotation | None = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.show()

    def sync_geometry(self) -> None:
        canvas = self.tab.strip.canvas
        self.setGeometry(0, 0, canvas.width(), canvas.height())

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._draft = None
        self._drag_start = None
        self._freehand = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          mode == "off")
        self.show()
        self.raise_()
        self.update()

    def refresh(self) -> None:
        if self.tab.info is None:
            self._page_annotations = []
        else:
            try:
                all_anns = pb.list_annotations(self.tab.path, self.tab.password)
            except pb.PdfError:
                all_anns = []
            pending = getattr(self.tab, "_pending", [])
            self._page_annotations = list(all_anns) + list(pending)
            if self._selected is not None:
                self._selected = next(
                    (a for a in self._page_annotations
                     if a is self._selected or self._same(a, self._selected)),
                    None)
        self.update()

    @staticmethod
    def _same(a, b) -> bool:
        return a.page == b.page and a.kind == b.kind and a.rect == b.rect

    def try_select(self, x: float, y: float) -> bool:
        """Select the top-most mark under the cursor. Returns True if hit."""
        if not self.show_marks:
            self._selected = None
            self.update()
            return False
        for ann in reversed(self._page_annotations):
            r = self._pdf_to_widget_rect(ann.page, ann.rect).adjusted(-4, -4, 4, 4)
            if r.contains(x, y):
                self._selected = ann
                self.update()
                return True
        self._selected = None
        self.update()
        return False

    def selected(self):
        return self._selected

    def set_show_marks(self, value: bool) -> None:
        self.show_marks = value
        self.update()

    def _widget_to_pdf(self, x: float, y: float) -> tuple[float, float]:
        hit = self.tab.strip.hit_test(x, y)
        if hit is None:
            zoom = self.tab.zoom
            page = self.tab.info.pages[self.tab.page - 1]
            return (x / zoom, page.height - (y / zoom))
        self._target_page = hit[0]
        return hit[1], hit[2]

    def _pdf_to_widget_rect(self, page: int, rect) -> QRectF:
        geom = next((g for g in self.tab.strip._geoms if g.number == page), None)
        if geom is None or self.tab.info is None:
            return QRectF()
        pg = self.tab.info.pages[page - 1]
        zoom = self.tab.zoom
        x0 = geom.x + rect[0] * zoom
        y0 = geom.y + (pg.height - rect[3]) * zoom
        x1 = geom.x + rect[2] * zoom
        y1 = geom.y + (pg.height - rect[1]) * zoom
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def _pdf_to_widget_poly(self, page: int, points) -> list[QPoint]:
        geom = next((g for g in self.tab.strip._geoms if g.number == page), None)
        if geom is None or self.tab.info is None:
            return []
        pg = self.tab.info.pages[page - 1]
        zoom = self.tab.zoom
        out = []
        for x, y in points:
            out.append(QPoint(int(geom.x + x * zoom),
                              int(geom.y + (pg.height - y) * zoom)))
        return out

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is None or self.mode == "off":
            return
        self._drag_start = a0.position().toPoint()
        self._draft = QRect(self._drag_start, QSize(1, 1))
        self._freehand = [self._drag_start]
        hit = self.tab.strip.hit_test(self._drag_start.x(), self._drag_start.y())
        if hit:
            self._target_page = hit[0]
        self.update()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is None or self._drag_start is None:
            return
        pos = a0.position().toPoint()
        if self.mode in _FREEHAND:
            self._freehand.append(pos)
        else:
            self._draft = QRect(self._drag_start, pos).normalized()
        self.update()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is None or self._drag_start is None:
            return
        rect = self._draft
        draft_points = self._freehand[:]
        self._drag_start = None
        self._draft = None

        if self.mode in _FREEHAND:
            self._commit_freehand(draft_points)
            self._freehand = []
            self.update()
            return

        if rect is None or rect.width() < MIN_DRAG or rect.height() < MIN_DRAG:
            self.update()
            return

        x0, y0 = self._widget_to_pdf(rect.left(), rect.bottom())
        x1, y1 = self._widget_to_pdf(rect.right(), rect.top())
        pdf_rect = (x0, y0, x1, y1)
        page = self._target_page

        text = ""
        if self.mode == "note":
            text, ok = QInputDialog.getText(self, "Add note",
                                            "Comment for this note:")
            if not ok:
                self.update()
                return
        elif self.mode == "redact":
            self.tab.page = page
            self.tab.apply_redaction(pdf_rect)
            self.update()
            return

        self.tab.apply_annotation(self.mode, pdf_rect, self.color, text,
                                  page=page)
        self.update()

    def _commit_freehand(self, points: list[QPoint]) -> None:
        if len(points) < 2:
            return
        pdf_pts = [self._widget_to_pdf(p.x(), p.y()) for p in points]
        pdf_rect = (min(p[0] for p in pdf_pts), min(p[1] for p in pdf_pts),
                    max(p[0] for p in pdf_pts), max(p[1] for p in pdf_pts))
        self.tab.apply_annotation(self.mode, pdf_rect, self.color, "", pdf_pts,
                                  page=self._target_page)

    def paintEvent(self, a0) -> None:  # noqa: N802
        if self.mode == "off" and not self.show_marks:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.show_marks:
            for ann in self._page_annotations:
                self._paint_annotation(painter, ann)
        if self._draft is not None and self.mode not in _FREEHAND:
            self._paint_draft_rect(painter)
        elif self._freehand and self.mode in _FREEHAND:
            self._paint_draft_poly(painter)
        painter.end()

    def _paint_annotation(self, painter: QPainter, ann) -> None:
        col = QColor(int(ann.color[0] * 255), int(ann.color[1] * 255),
                     int(ann.color[2] * 255))
        kind = ann.kind
        r = self._pdf_to_widget_rect(ann.page, ann.rect)
        if kind in ("highlight", "underline", "strike"):
            if kind == "highlight":
                col.setAlpha(70)
                painter.fillRect(r, col)
            else:
                painter.setPen(QPen(col, 2))
                y = r.center().y() if kind == "strike" else r.bottom()
                painter.drawLine(int(r.left()), int(y), int(r.right()), int(y))
        elif kind == "note":
            painter.setPen(QPen(col, 2))
            painter.setBrush(col)
            painter.drawRect(int(r.x()), int(r.y()), 12, 12)
        elif kind == "rectangle":
            painter.setPen(QPen(col, 2))
            painter.drawRect(r)
        elif kind == "oval":
            painter.setPen(QPen(col, 2))
            painter.drawEllipse(r)
        if kind in ("line", "arrow", "sketch"):
            pts = self._pdf_to_widget_poly(ann.page, ann.points or [])
            if len(pts) >= 2:
                painter.setPen(QPen(col, 2))
                painter.drawPolyline(*pts)
                if kind == "arrow" and len(pts) >= 2:
                    self._paint_arrow_head(painter, col, pts[-2], pts[-1])
        if self._selected is not None and self._same(ann, self._selected):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(80, 160, 255), 2, Qt.PenStyle.DashLine))
            painter.drawRect(r.adjusted(-3, -3, 3, 3))

    def _paint_draft_rect(self, painter: QPainter) -> None:
        col = QColor(int(self.color[0] * 255), int(self.color[1] * 255),
                     int(self.color[2] * 255))
        r = self._draft
        if self.mode in ("highlight", "underline", "strike"):
            if self.mode == "highlight":
                col.setAlpha(70)
                painter.fillRect(r, col)
            else:
                painter.setPen(QPen(col, 2))
                y = r.center().y() if self.mode == "strike" else r.bottom()
                painter.drawLine(r.left(), int(y), r.right(), int(y))
        elif self.mode == "rectangle":
            painter.setPen(QPen(col, 2))
            painter.drawRect(r)
        elif self.mode == "oval":
            painter.setPen(QPen(col, 2))
            painter.drawEllipse(r)
        elif self.mode in ("line", "arrow"):
            painter.setPen(QPen(col, 2))
            painter.drawLine(r.topLeft(), r.bottomRight())
            if self.mode == "arrow":
                self._paint_arrow_head(painter, col, r.topLeft(), r.bottomRight())

    def _paint_draft_poly(self, painter: QPainter) -> None:
        col = QColor(int(self.color[0] * 255), int(self.color[1] * 255),
                     int(self.color[2] * 255))
        painter.setPen(QPen(col, 2))
        if len(self._freehand) >= 2:
            painter.drawPolyline(*self._freehand)

    @staticmethod
    def _paint_arrow_head(painter: QPainter, col: QColor,
                          tip: QPoint, back: QPoint) -> None:
        import math
        angle = math.atan2(tip.y() - back.y(), tip.x() - back.x())
        size = 10
        for a in (angle + math.radians(150), angle - math.radians(150)):
            hx = tip.x() - int(size * math.cos(a))
            hy = tip.y() - int(size * math.sin(a))
            painter.drawLine(tip, QPoint(hx, hy))
