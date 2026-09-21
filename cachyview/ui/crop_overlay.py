"""Interactive crop selection for the image viewer.

The overlay draws a rubber band over the displayed (scaled) pixmap and hands
back a rectangle in *original image pixels*, so cropping is exact regardless of
the current zoom level.

Coordinate spaces
-----------------
* **widget**  - pixels inside the label showing the scaled image.
* **image**   - pixels of the underlying full-resolution image.

``zoom`` converts between them, and every rectangle leaving this module is in
image space.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QWidget

HANDLE = 8          # grab-handle size in widget pixels
MIN_SIZE = 4        # smallest crop, in image pixels


def _rect_from_points(a: QPoint, b: QPoint) -> QRect:
    """Build an inclusive rect from two corners, in any drag direction.

    ``QRect(a, b).normalized()`` is wrong here: for an inverted drag Qt shifts
    both edges inward by one pixel (dragging 200->60 yields left=61, right=199),
    which silently trims the crop.  Sorting the coordinates first avoids that.
    """
    left, right = sorted((a.x(), b.x()))
    top, bottom = sorted((a.y(), b.y()))
    return QRect(QPoint(left, top), QPoint(right, bottom))


class CropOverlay(QWidget):
    """A resizable rubber band drawn on top of the image label."""

    changed = pyqtSignal(QRect)      # emits the selection in IMAGE pixels

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._rect = QRect()          # widget space
        self._origin: QPoint | None = None
        self._mode: str | None = None
        self._grab_offset = QPoint()
        self._zoom = 1.0
        self._image_size = QSize()
        # Set by set_image_rect(): the exact selection in image pixels.
        # Widget-space rects lose precision at low zoom (a 50px crop shown at
        # 28% is 14 widget pixels, which maps back to 47), so when the caller
        # gave us exact coordinates we keep and return them verbatim.
        self._exact: QRect | None = None

    # --- configuration ----------------------------------------------------
    def configure(self, zoom: float, image_size: QSize) -> None:
        self._zoom = max(1e-6, zoom)
        self._image_size = image_size

    def clear(self) -> None:
        self._rect = QRect()
        self._origin = None
        self._exact = None
        self.update()
        self.changed.emit(QRect())

    def has_selection(self) -> bool:
        if self._exact is not None:
            return self._exact.isValid() and not self._exact.isEmpty()
        return self._rect.isValid() and self._rect.width() > 1 and self._rect.height() > 1

    # --- coordinate conversion -------------------------------------------
    def image_rect(self) -> QRect:
        """The selection in original-image pixels, clamped to the image."""
        if self._exact is not None:
            return self._exact
        if not self.has_selection():
            return QRect()
        r = self._rect.normalized()
        left = int(round(r.left() / self._zoom))
        top = int(round(r.top() / self._zoom))
        right = int(round(r.right() / self._zoom))
        bottom = int(round(r.bottom() / self._zoom))

        rect = QRect(QPoint(left, top), QPoint(right, bottom))
        if self._image_size.isValid():
            rect = rect.intersected(QRect(QPoint(0, 0), self._image_size))
        return rect

    def set_image_rect(self, rect: QRect) -> None:
        """Set the selection from image-space coordinates."""
        if not rect.isValid():
            self.clear()
            return
        clamped = rect
        if self._image_size.isValid():
            clamped = rect.intersected(QRect(QPoint(0, 0), self._image_size))
        self._exact = clamped
        self._rect = QRect(
            int(clamped.left() * self._zoom), int(clamped.top() * self._zoom),
            max(1, int(clamped.width() * self._zoom)),
            max(1, int(clamped.height() * self._zoom)))
        self.update()
        self.changed.emit(self.image_rect())

    def select_all(self) -> None:
        if self._image_size.isValid():
            self.set_image_rect(QRect(QPoint(0, 0), self._image_size))

    # --- interaction ------------------------------------------------------
    def _handles(self) -> dict[str, QRect]:
        r = self._rect.normalized()
        h = HANDLE
        return {
            "tl": QRect(r.left() - h // 2, r.top() - h // 2, h, h),
            "tr": QRect(r.right() - h // 2, r.top() - h // 2, h, h),
            "bl": QRect(r.left() - h // 2, r.bottom() - h // 2, h, h),
            "br": QRect(r.right() - h // 2, r.bottom() - h // 2, h, h),
        }

    def _hit(self, pos: QPoint) -> str | None:
        if not self.has_selection():
            return None
        for name, box in self._handles().items():
            if box.contains(pos):
                return name
        if self._rect.normalized().contains(pos):
            return "move"
        return None

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        pos = a0.pos()
        self._exact = None          # the user is now driving the selection
        hit = self._hit(pos)
        if hit == "move":
            self._mode = "move"
            self._grab_offset = pos - self._rect.normalized().topLeft()
        elif hit:
            self._mode = hit
        else:
            self._mode = "new"
            self._origin = pos
            self._rect = QRect(pos, pos)
        self.update()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        pos = self._clamp(a0.pos())

        if self._mode is None:
            hit = self._hit(pos)
            self.setCursor(
                Qt.CursorShape.SizeAllCursor if hit == "move"
                else Qt.CursorShape.SizeFDiagCursor if hit in ("tl", "br")
                else Qt.CursorShape.SizeBDiagCursor if hit in ("tr", "bl")
                else Qt.CursorShape.CrossCursor)
            return

        r = self._rect.normalized()
        if self._mode == "new" and self._origin is not None:
            self._rect = _rect_from_points(self._origin, pos)
        elif self._mode == "move":
            new_top_left = self._clamp_top_left(pos - self._grab_offset, r.size())
            self._rect = QRect(new_top_left, r.size())
        elif self._mode == "tl":
            self._rect = _rect_from_points(pos, r.bottomRight())
        elif self._mode == "tr":
            self._rect = _rect_from_points(QPoint(r.left(), pos.y()),
                                           QPoint(pos.x(), r.bottom()))
        elif self._mode == "bl":
            self._rect = _rect_from_points(QPoint(pos.x(), r.top()),
                                           QPoint(r.right(), pos.y()))
        elif self._mode == "br":
            self._rect = _rect_from_points(r.topLeft(), pos)

        self.update()
        self.changed.emit(self.image_rect())

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        self._mode = None
        if self.has_selection():
            self.changed.emit(self.image_rect())
        self.update()

    def _clamp(self, pos: QPoint) -> QPoint:
        return QPoint(max(0, min(pos.x(), self.width())),
                      max(0, min(pos.y(), self.height())))

    def _clamp_top_left(self, pos: QPoint, size) -> QPoint:
        return QPoint(max(0, min(pos.x(), self.width() - size.width())),
                      max(0, min(pos.y(), self.height() - size.height())))

    # --- painting ---------------------------------------------------------
    def paintEvent(self, a0) -> None:
        if not self.has_selection():
            return
        painter = QPainter(self)
        r = self._rect.normalized()

        # Dim everything outside the selection so the crop reads at a glance.
        shade = QColor(0, 0, 0, 110)
        painter.fillRect(QRect(0, 0, self.width(), r.top()), shade)
        painter.fillRect(QRect(0, r.bottom() + 1, self.width(),
                               self.height() - r.bottom() - 1), shade)
        painter.fillRect(QRect(0, r.top(), r.left(), r.height()), shade)
        painter.fillRect(QRect(r.right() + 1, r.top(),
                               self.width() - r.right() - 1, r.height()), shade)

        painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
        painter.drawRect(r)

        # Rule-of-thirds guides.
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for i in (1, 2):
            x = r.left() + r.width() * i // 3
            y = r.top() + r.height() * i // 3
            painter.drawLine(x, r.top(), x, r.bottom())
            painter.drawLine(r.left(), y, r.right(), y)

        painter.setPen(QPen(QColor(20, 20, 20), 1))
        painter.setBrush(QColor(255, 255, 255))
        for box in self._handles().values():
            painter.drawRect(box)
        painter.end()
