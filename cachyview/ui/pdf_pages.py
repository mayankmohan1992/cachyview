"""Virtualized PDF canvas: continuous, single-page and facing layouts."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QColor, QDesktopServices, QImage, QMouseEvent,
                         QPainter, QPen, QPixmap, QWheelEvent)
from PyQt6.QtWidgets import QApplication, QMessageBox, QScrollArea, QWidget

from ..backends import pdf as pb

GAP = 10
PAD = 16
ZOOMS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]

CONTINUOUS = "continuous"
SINGLE = "single"
FACING = "facing"


@dataclass
class PageRect:
    number: int
    x: int
    y: int
    w: int
    h: int

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h

    def rect(self) -> QRect:
        return QRect(self.x, self.y, self.w, self.h)


class _Canvas(QWidget):
    def __init__(self, view: "ContinuousPdfView"):
        super().__init__(view)
        self._view = view
        self.setMouseTracking(True)

    def paintEvent(self, a0) -> None:
        self._view.paint_canvas(self, a0)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        self._view.on_mouse_press(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        self._view.on_mouse_move(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        self._view.on_mouse_release(a0)


class ContinuousPdfView(QScrollArea):
    page_changed = pyqtSignal(int)
    need_render = pyqtSignal(int, int)
    zoom_requested = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab = parent
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.canvas = _Canvas(self)
        self.setWidget(self.canvas)
        self.zoom = 1.0
        self.layout_mode = CONTINUOUS
        self.invert = False
        self._current = 1
        self._info: pb.PdfInfo | None = None
        self._geoms: list[PageRect] = []
        self._pixmaps: dict[int, tuple[QPixmap, int]] = {}
        self._words: dict[int, list] = {}
        self._links: dict[int, list] = {}
        self._sel_page: int | None = None
        self._sel_start: QPoint | None = None
        self._sel_words: list[tuple] = []
        self._search_rects: list[tuple[int, tuple]] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._request_visible)
        bar = self.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(lambda _v: self._timer.start())

    def current_dpi(self) -> int:
        dpr = float(self.devicePixelRatioF() or 1.0)
        return max(36, int(72 * self.zoom * dpr))

    def load(self, info: pb.PdfInfo, zoom: float) -> None:
        self._info = info
        self.zoom = zoom
        self._current = 1
        self._pixmaps.clear()
        self._words.clear()
        self._links.clear()
        self._sel_words = []
        self._rebuild()
        QTimer.singleShot(0, self._request_visible)
        self._request_visible()

    def set_layout_mode(self, mode: str) -> None:
        if mode not in (CONTINUOUS, SINGLE, FACING):
            return
        self.layout_mode = mode
        self._rebuild()
        self.scroll_to(self._current)
        self._request_visible()

    def set_zoom(self, zoom: float, *, anchor=None) -> None:
        old = self.zoom
        self.zoom = max(0.1, min(4.0, zoom))
        if abs(self.zoom - old) < 1e-6:
            return
        ax, ay = None, None
        if anchor is not None:
            ax, ay = anchor
        frac = None
        bar = self.verticalScrollBar()
        if bar is not None and bar.maximum() > 0 and ax is None:
            frac = bar.value() / bar.maximum()
        self._rebuild()
        if ax is not None and ay is not None and old > 0:
            ratio = self.zoom / old
            if bar is not None:
                bar.setValue(int(ay * ratio - (ay - (bar.value() if bar else 0))))
                hbar = self.horizontalScrollBar()
                if hbar is not None:
                    hbar.setValue(int(ax * ratio - (ax - hbar.value())))
        elif frac is not None and bar is not None:
            bar.setValue(int(frac * bar.maximum()))
        self._request_visible()

    def show_pixmap(self, page: int, pixmap: QPixmap, dpi: int) -> None:
        dpr = float(self.devicePixelRatioF() or 1.0)
        pixmap.setDevicePixelRatio(dpr)
        if self.invert:
            image = pixmap.toImage()
            image.invertPixels(QImage.InvertMode.InvertRgb)
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(dpr)
        self._pixmaps[page] = (pixmap, dpi)
        self.canvas.update()

    def set_invert(self, on: bool) -> None:
        """Invert rendered colours for dark-mode reading (view only)."""
        self.invert = bool(on)
        self._pixmaps.clear()
        self.canvas.update()
        self._request_visible()

    def has_pixmap(self, page: int) -> bool:
        got = self._pixmaps.get(page)
        return got is not None and not got[0].isNull()

    def scroll_to(self, page: int) -> None:
        if self._info is None:
            return
        page = max(1, min(page, self._info.page_count))
        if self.layout_mode == SINGLE:
            self._current = page
            self._rebuild()
            self.page_changed.emit(page)
            self._request_visible()
            return
        geom = next((g for g in self._geoms if g.number == page), None)
        if geom is None:
            return
        self.ensureVisible(geom.x + geom.w // 2, geom.y + 8, 1, 1)
        if page != self._current:
            self._current = page
            self.page_changed.emit(page)

    def current_page(self) -> int:
        return self._current

    def set_search_hits(self, hits: list[tuple[int, tuple]]) -> None:
        self._search_rects = hits
        self.canvas.update()

    def hit_test(self, x: float, y: float) -> tuple[int, float, float, PageRect] | None:
        if self._info is None:
            return None
        for g in self._geoms:
            if g.contains(x, y):
                page = self._info.pages[g.number - 1]
                pdf_x = (x - g.x) / self.zoom
                pdf_y = page.height - (y - g.y) / self.zoom
                return g.number, pdf_x, pdf_y, g
        return None

    def page_local(self, page: int, x: float, y: float) -> tuple[float, float] | None:
        geom = next((g for g in self._geoms if g.number == page), None)
        if geom is None:
            return None
        return x - geom.x, y - geom.y

    def _page_size(self, page) -> tuple[int, int]:
        return (max(40, round(page.width * self.zoom)),
                max(40, round(page.height * self.zoom)))

    def _rebuild(self) -> None:
        self._geoms = []
        if self._info is None or not self._info.pages:
            self.canvas.resize(1, 1)
            return
        pages = self._info.pages
        if self.layout_mode == SINGLE:
            p = pages[self._current - 1]
            w, h = self._page_size(p)
            self._geoms.append(PageRect(p.number, PAD, PAD, w, h))
            self.canvas.resize(w + 2 * PAD, h + 2 * PAD)
            self.canvas.update()
            return
        if self.layout_mode == FACING:
            y = PAD
            max_w = 0
            spreads: list[tuple[object | None, object]] = []
            spreads.append((None, pages[0]))
            i = 1
            while i < len(pages):
                left = pages[i]
                right = pages[i + 1] if i + 1 < len(pages) else None
                spreads.append((left, right))
                i += 2
            for left, right in spreads:
                lw = lh = 0
                rw = rh = 0
                if left is not None:
                    lw, lh = self._page_size(left)
                if right is not None:
                    rw, rh = self._page_size(right)
                if left is None:
                    lw = rw
                row_h = max(lh, rh, 40)
                x = PAD
                if left is not None:
                    self._geoms.append(PageRect(left.number, x, y, lw, lh))
                x += max(lw, 40) + GAP
                if right is not None:
                    self._geoms.append(PageRect(right.number, x, y, rw, rh))
                    max_w = max(max_w, x + rw + PAD)
                y += row_h + GAP
            self.canvas.resize(max(max_w, 200), y + PAD)
            self.canvas.update()
            return
        y = PAD
        max_w = 0
        for p in pages:
            w, h = self._page_size(p)
            self._geoms.append(PageRect(p.number, PAD, y, w, h))
            max_w = max(max_w, w + 2 * PAD)
            y += h + GAP
        self.canvas.resize(max_w, y + PAD)
        self.canvas.update()

    def _request_visible(self) -> None:
        if not self._geoms:
            return
        port = self.viewport()
        if port is None:
            return
        top = self.verticalScrollBar().value() if self.verticalScrollBar() else 0
        height = port.height() or 800
        bottom = top + height
        dpi = self.current_dpi()
        best, best_area = self._current, -1
        for g in self._geoms:
            overlap = min(bottom, g.y + g.h) - max(top, g.y)
            if overlap > 0:
                if overlap > best_area:
                    best_area, best = overlap, g.number
                cached = self._pixmaps.get(g.number)
                if cached is None or cached[1] != dpi:
                    self.need_render.emit(g.number, dpi)
        if best_area > 0 and best != self._current:
            self._current = best
            self.page_changed.emit(best)
        elif best_area < 0 and self._geoms:
            # Nothing overlapped (first show): still rasterise page 1 / current.
            target = self._geoms[0].number
            self.need_render.emit(target, dpi)
            if self.layout_mode != SINGLE:
                for g in self._geoms[1:3]:
                    self.need_render.emit(g.number, dpi)

    def showEvent(self, a0) -> None:
        super().showEvent(a0)
        self._request_visible()

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        self._timer.start()

    def wheelEvent(self, a0: QWheelEvent | None) -> None:
        if a0 is None:
            return
        if a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = a0.angleDelta().y()
            nxt = self.zoom
            if delta > 0:
                nxt = next((z for z in ZOOMS if z > self.zoom + 1e-6), ZOOMS[-1])
            else:
                nxt = next((z for z in reversed(ZOOMS) if z < self.zoom - 1e-6),
                           ZOOMS[0])
            pos = a0.position()
            canvas_pt = self.canvas.mapFrom(self.viewport(), pos.toPoint())
            self.set_zoom(nxt, anchor=(canvas_pt.x(), canvas_pt.y()))
            self.zoom_requested.emit(self.zoom)
            a0.accept()
            return
        super().wheelEvent(a0)

    def paint_canvas(self, widget: QWidget, event) -> None:
        painter = QPainter(widget)
        painter.fillRect(event.rect() if event else widget.rect(),
                         widget.palette().window())
        if self._info is None:
            painter.end()
            return
        clip = event.rect() if event is not None else widget.rect()
        for g in self._geoms:
            if not clip.intersects(g.rect()):
                continue
            painter.fillRect(g.rect(), QColor(255, 255, 255))
            cached = self._pixmaps.get(g.number)
            if cached is not None:
                pix, _dpi = cached
                painter.drawPixmap(g.rect(), pix)
            else:
                painter.setPen(QColor(180, 180, 180))
                painter.drawText(g.rect(), Qt.AlignmentFlag.AlignCenter,
                                 str(g.number))
            painter.setPen(QPen(QColor(200, 200, 200), 1))
            painter.drawRect(g.rect())
            for page, rect in self._search_rects:
                if page == g.number:
                    painter.fillRect(self._pdf_rect_on_page(g, rect),
                                     QColor(255, 220, 0, 80))
            if self._sel_page == g.number:
                for wr in self._sel_words:
                    painter.fillRect(self._pdf_rect_on_page(g, wr[:4]),
                                     QColor(80, 140, 255, 80))
        painter.end()

    def _pdf_rect_on_page(self, g: PageRect, rect) -> QRectF:
        page = self._info.pages[g.number - 1]
        x0, y0, x1, y1 = rect
        wx0 = g.x + x0 * self.zoom
        wy0 = g.y + (page.height - y1) * self.zoom
        wx1 = g.x + x1 * self.zoom
        wy1 = g.y + (page.height - y0) * self.zoom
        return QRectF(wx0, wy0, wx1 - wx0, wy1 - wy0)

    def on_mouse_press(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        tab = self.tab
        annot = getattr(tab, "annot_layer", None)
        if annot is not None and annot.mode != "off":
            return
        if annot is not None and a0.button() == Qt.MouseButton.LeftButton:
            if annot.try_select(a0.position().x(), a0.position().y()):
                a0.accept()
                return
        if getattr(tab, "_placing_signature", None) is not None:
            hit = self.hit_test(a0.position().x(), a0.position().y())
            if hit is not None:
                page, _px, _py, g = hit
                local = QPoint(int(a0.position().x() - g.x),
                               int(a0.position().y() - g.y))
                tab.page = page
                tab._place_signature_at(local)
                tab._placing_signature = None
            return
        self._sel_start = a0.position().toPoint()
        self._sel_words = []
        hit = self.hit_test(self._sel_start.x(), self._sel_start.y())
        self._sel_page = hit[0] if hit else None
        if self._sel_page:
            self._ensure_words(self._sel_page)

    def on_mouse_move(self, a0: QMouseEvent | None) -> None:
        if a0 is None or self._sel_start is None or self._sel_page is None:
            return
        tab = self.tab
        annot = getattr(tab, "annot_layer", None)
        if annot is not None and annot.mode != "off":
            return
        self._sel_words = self._words_in_rect(
            self._sel_page, self._sel_start, a0.position().toPoint())
        self.canvas.update()

    def on_mouse_release(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            self._sel_start = None
            return
        tab = self.tab
        annot = getattr(tab, "annot_layer", None)
        if annot is not None and annot.mode != "off":
            self._sel_start = None
            return
        if self._sel_page and self._sel_start is not None:
            self._sel_words = self._words_in_rect(
                self._sel_page, self._sel_start, a0.position().toPoint())
            text = " ".join(w[4] for w in self._sel_words)
            if text:
                QApplication.clipboard().setText(text)
                if hasattr(tab, "status"):
                    tab.status.setText(f"Copied {len(self._sel_words)} word(s).")
            else:
                # A plain click (no selection) may land on a link.
                self._open_link_at(a0.position().toPoint())
        self._sel_start = None
        self.canvas.update()

    def _open_link_at(self, pt: QPoint) -> None:
        """Activate a link under *pt*, confirming before opening a URI."""
        path = getattr(self.tab, "path", None)
        if path is None or self._info is None:
            return
        hit = self.hit_test(pt.x(), pt.y())
        if hit is None:
            return
        page, pdf_x, pdf_y, _g = hit
        links = self._links.get(page)
        if links is None:
            try:
                links = pb.links(path, page,
                                 getattr(self.tab, "password", None))
            except pb.PdfError:
                links = []
            self._links[page] = links
        for link in links:
            x0, y0, x1, y1 = link["rect"]
            if x0 <= pdf_x <= x1 and y0 <= pdf_y <= y1:
                self._activate_link(link)
                return

    def _activate_link(self, link: dict) -> None:
        if link.get("kind") == "page":
            self.scroll_to(link["page"])
            return
        uri = link.get("uri", "")
        scheme = uri.split(":", 1)[0].lower() if ":" in uri else ""
        if scheme not in ("http", "https", "mailto", "file"):
            QMessageBox.warning(
                self, "Blocked link",
                f"Refusing to open a '{scheme or 'unknown'}' link.")
            return
        reply = QMessageBox.question(
            self, "Open external link?",
            f"Open this link in your browser?\n\n{uri}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(uri))

    def _ensure_words(self, page: int) -> None:
        if page in self._words:
            return
        tab = self.tab
        path = getattr(tab, "path", None)
        password = getattr(tab, "password", None)
        if path is None:
            self._words[page] = []
            return
        try:
            self._words[page] = pb.page_words(path, page, password)
        except pb.PdfError:
            self._words[page] = []

    def _words_in_rect(self, page: int, a: QPoint, b: QPoint) -> list:
        geom = next((g for g in self._geoms if g.number == page), None)
        if geom is None or self._info is None:
            return []
        box = QRect(a, b).normalized()
        hits = []
        for w in self._words.get(page, []):
            r = self._pdf_rect_on_page(geom, w[:4]).toRect()
            if r.intersects(box):
                hits.append(w)
        return hits
