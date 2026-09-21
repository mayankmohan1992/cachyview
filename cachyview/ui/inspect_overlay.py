"""Measurement & inspection overlay for the image canvas.

Lives on the canvas QLabel (exactly like CropOverlay) and supports three
non-destructive inspection tools that never touch the image bytes:

* **picker**  — hover reports the colour under the cursor (RGBA + hex) and a
  click copies it to the clipboard;
* **ruler**    — drag from A to B to measure the distance in image pixels and
  the on-screen pixels;
* **magnifier**— a lens that follows the cursor showing a zoomed-in region so
  fine detail is visible without leaving the tab.

All three are driven by mouse events on the overlay and emit a single
``readout`` signal with a human string, so the tab can show it in its status
bar.  The image rectangle (in image-pixel space) is supplied by ``configure``.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, QPoint
from PyQt6.QtGui import (QColor, QPainter, QPen, QPixmap)
from PyQt6.QtWidgets import QWidget


class InspectOverlay(QWidget):
    """Transparent overlay providing picker / ruler / magnifier."""

    readout = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mode = "off"
        self._zoom = 1.0
        self._image_size = (1, 1)
        self._drag_start: QPoint | None = None
        self._drag_now: QPoint | None = None
        self._last_image_pt: QPoint | None = None
        self.hide()

    # --- configuration ---------------------------------------------------
    def configure(self, zoom: float, image_size) -> None:
        """Track the canvas zoom and the source image dimensions.

        *image_size* may be a ``PIL.Image`` (``.width``/``.height`` attributes)
        or a Qt size-like object (``.width()``/``.height()`` methods).
        """
        self._zoom = zoom
        w = image_size.width() if callable(getattr(image_size, "width", None)) \
            else image_size.width
        h = image_size.height() if callable(getattr(image_size, "height", None)) \
            else image_size.height
        self._image_size = (w, h)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == "off":
            self.hide()
        else:
            self.show()
            self.raise_()
            self._emit_readout()

    @property
    def active(self) -> bool:
        return self._mode != "off"

    # --- coordinate helpers ---------------------------------------------
    def _to_image(self, widget_pt: QPoint) -> QPoint:
        """Map a widget-local point to source-image pixel coordinates."""
        return QPoint(
            int(widget_pt.x() / self._zoom),
            int(widget_pt.y() / self._zoom))

    def _image_pixel(self, widget_pt: QPoint):
        """Return the (r, g, b, a) tuple at a widget point, or None."""
        ip = self._to_image(widget_pt)
        w, h = self._image_size
        if 0 <= ip.x() < w and 0 <= ip.y() < h:
            return ip.x(), ip.y()
        return None

    # --- events -----------------------------------------------------------
    def mousePressEvent(self, a0) -> None:
        if self._mode == "ruler" and a0 is not None:
            self._drag_start = a0.position().toPoint()
            self._drag_now = self._drag_start
        elif self._mode == "picker" and a0 is not None:
            self._copy_color(a0.position().toPoint())
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0) -> None:
        if a0 is not None:
            pos = a0.position().toPoint()
            self._last_image_pt = self._to_image(pos)
            if self._mode == "ruler" and self._drag_start is not None:
                self._drag_now = pos
                self.update()
            self._emit_readout()
        super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0) -> None:
        if self._mode == "ruler":
            self._drag_start = None
            self._drag_now = None
            self.update()
        super().mouseReleaseEvent(a0)

    def _copy_color(self, widget_pt: QPoint) -> None:
        px = self._image_pixel(widget_pt)
        if px is None:
            return
        x, y = px
        color = self._color_at(x, y)
        if color is None:
            return
        hexv = "#%02X%02X%02X" % (color[0], color[1], color[2])
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(hexv)
            self.readout.emit(f"Copied {hexv} from ({x}, {y})")
        except Exception:
            self.readout.emit(hexv)

    def _color_at(self, x: int, y: int):
        """Read pixel colour via the host tab's current image."""
        host = self.parent()
        while host is not None and not hasattr(host, "current"):
            host = host.parent()
        img = getattr(host, "current", None)
        if img is None:
            return None
        try:
            return img.getpixel((x, y))
        except Exception:
            return None

    def _emit_readout(self) -> None:
        if self._mode == "picker" and self._last_image_pt is not None:
            x, y = self._last_image_pt.x(), self._last_image_pt.y()
            color = self._color_at(x, y)
            if color is not None:
                hexv = "#%02X%02X%02X" % (color[0], color[1], color[2])
                self.readout.emit(f"({x}, {y})  {hexv}  rgba{color}")
        elif self._mode == "ruler" and self._drag_start and self._drag_now:
            a = self._to_image(self._drag_start)
            b = self._to_image(self._drag_now)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            dist = (dx * dx + dy * dy) ** 0.5
            self.readout.emit(
                f"Δ ({dx}, {dy})  ·  {dist:.1f} px image  ·  "
                f"{dist * self._zoom:.1f} px screen")

    # --- rendering --------------------------------------------------------
    def paintEvent(self, a0) -> None:
        if not self.active:
            return
        painter = QPainter(self)
        pen = QPen(QColor(255, 64, 129), 2)
        painter.setPen(pen)
        if self._mode == "ruler" and self._drag_start and self._drag_now:
            painter.drawLine(self._drag_start, self._drag_now)
            painter.drawEllipse(self._drag_start, 4, 4)
            painter.drawEllipse(self._drag_now, 4, 4)
        painter.end()

    def magnifier_pixmap(self, cx: int, cy: int, size: int = 160,
                         factor: int = 4) -> QPixmap | None:
        """Return a zoomed region centred on image pixel (cx, cy)."""
        host = self.parent()
        while host is not None and not hasattr(host, "current"):
            host = host.parent()
        img = getattr(host, "current", None)
        if img is None:
            return None
        half = size // (2 * factor)
        box = (max(0, cx - half), max(0, cy - half),
               min(img.width, cx + half), min(img.height, cy + half))
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        region = img.crop(box).resize((size, size))
        from cachyview.ui.image_tab import pil_to_qpixmap
        return pil_to_qpixmap(region)
