"""A compact RGB + luma histogram for the image tab."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from ..backends import image as ib

_CHANNELS = (("r", QColor(220, 60, 60)), ("g", QColor(60, 190, 60)),
             ("b", QColor(70, 120, 230)), ("luma", QColor(170, 170, 170)))


class HistogramPanel(QWidget):
    """Draw the per-channel histograms of the current (edited) image."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._data: dict[str, list[int]] | None = None
        self.setMinimumWidth(160)
        self.setMinimumHeight(120)
        self.setToolTip("Histogram (RGB + luma)")

    def set_image(self, img) -> None:
        try:
            self._data = ib.histograms(img) if img is not None else None
        except Exception:
            self._data = None
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        rect = self.rect().adjusted(6, 6, -6, -6)
        if rect.width() <= 4 or rect.height() <= 4:
            painter.end()
            return
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(rect)

        if not self._data:
            painter.setPen(self.palette().text().color())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Histogram")
            painter.end()
            return

        for key, color in _CHANNELS:
            hist = self._data.get(key) or []
            if not hist:
                continue
            # Ignore the extreme bins when scaling: a big spike at 0 or 255
            # would otherwise flatten every other channel.
            peak = max(hist[8:248] or hist) or 1
            poly = QPolygonF()
            for i in range(8, 248):
                x = rect.left() + (i - 8) / 239 * rect.width()
                value = min(hist[i], peak) / peak
                y = rect.bottom() - value * rect.height()
                poly.append(QPointF(x, y))
            painter.setPen(QPen(color, 1))
            painter.drawPolyline(poly)
        painter.end()
