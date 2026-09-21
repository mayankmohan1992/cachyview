"""Draw markup on an image (Preview-style), recorded as image-space points."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QInputDialog, QWidget


class MarkupOverlay(QWidget):
    committed = pyqtSignal(str, list, str, str)  # kind, points, color, text

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.mode = "off"
        self.color = "#ff3333"
        self._zoom = 1.0
        self._start: QPoint | None = None
        self._now: QPoint | None = None
        self._free: list[QPoint] = []
        self.hide()
        self.setMouseTracking(True)

    def configure(self, zoom: float) -> None:
        self._zoom = max(1e-6, zoom)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._start = self._now = None
        self._free = []
        if mode == "off":
            self.hide()
        else:
            self.show()
            self.raise_()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event is None or self.mode == "off":
            return
        self._start = event.pos()
        self._now = event.pos()
        self._free = [event.pos()]
        if self.mode == "text":
            text, ok = QInputDialog.getText(self, "Text", "Caption:")
            if ok and text:
                pts = [self._to_image(event.pos())]
                self.committed.emit("text", pts, self.color, text)
            self._start = None
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if event is None or self._start is None:
            return
        self._now = event.pos()
        if self.mode in ("freehand", "arrow", "line"):
            self._free.append(event.pos())
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._start is None or event is None:
            return
        end = event.pos()
        kind = self.mode
        if kind == "text":
            self._start = None
            return
        if kind == "freehand":
            pts = [self._to_image(p) for p in self._free]
        else:
            pts = [self._to_image(self._start), self._to_image(end)]
        self.committed.emit(kind, pts, self.color, "")
        self._start = self._now = None
        self._free = []
        self.update()

    def _to_image(self, pos: QPoint) -> tuple[int, int]:
        return (int(pos.x() / self._zoom), int(pos.y() / self._zoom))

    def paintEvent(self, event) -> None:
        if self._start is None or self._now is None:
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor(self.color), 2))
        if self.mode in ("rectangle", "highlight"):
            painter.drawRect(self._start.x(), self._start.y(),
                             self._now.x() - self._start.x(),
                             self._now.y() - self._start.y())
        elif self.mode == "oval":
            painter.drawEllipse(self._start.x(), self._start.y(),
                                self._now.x() - self._start.x(),
                                self._now.y() - self._start.y())
        else:
            painter.drawLine(self._start, self._now)
        painter.end()
