"""Background thumbnail rendering for the PDF sidebar.

Rendering every page up front is unacceptable on a large document, so pages
are rendered on demand: the list view asks for the pages it is about to show,
and a single worker thread services that queue and hands finished pixmaps back
through a Qt signal.

Design notes
------------
* One worker, not a pool.  MuPDF document handles are not thread-safe, so the
  document is opened inside the worker and never leaves it.
* The queue is a stack: the most recent request wins, because that is where the
  user just scrolled to.  Pages scrolled past are dropped rather than rendered
  into a view nobody is looking at.
* Results are cached, so scrolling back is instant and never re-renders.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QPixmap

# Sidebar thumbnails are small; 40 dpi is plenty and keeps rendering cheap.
THUMB_DPI = 40
THUMB_WIDTH = 130


class ThumbnailLoader(QObject):
    """Renders PDF page thumbnails off the GUI thread, newest request first."""

    ready = pyqtSignal(int, QPixmap)      # 1-based page number, thumbnail
    failed = pyqtSignal(int, str)

    def __init__(self, path: Path, password: str | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.path = Path(path)
        self.password = password
        self._cache: dict[int, QPixmap] = {}
        self._wanted: list[int] = []          # treated as a stack
        self._queued: set[int] = set()
        self._lock = threading.Lock()
        self._stopped = False
        self._running = False

    # --- public API -------------------------------------------------------
    def cached(self, page: int) -> QPixmap | None:
        return self._cache.get(page)

    def request(self, pages: list[int]) -> None:
        """Ask for *pages* (1-based).  Already cached pages are skipped."""
        if self._stopped:
            return
        with self._lock:
            for page in pages:
                if page in self._cache or page in self._queued:
                    continue
                self._wanted.append(page)
                self._queued.add(page)
            start = not self._running and bool(self._wanted)
            if start:
                self._running = True
        if start:
            pool = QThreadPool.globalInstance()
            if pool is not None:
                pool.start(_Worker(self))

    def stop(self) -> None:
        """Stop rendering; call when the tab closes or reloads."""
        self._stopped = True
        with self._lock:
            self._wanted.clear()
            self._queued.clear()

    def clear_cache(self) -> None:
        self._cache.clear()

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._wanted)

    # --- worker callbacks -------------------------------------------------
    def _next_page(self) -> int | None:
        with self._lock:
            while self._wanted:
                page = self._wanted.pop()        # newest request first
                self._queued.discard(page)
                if page not in self._cache:
                    return page
            self._running = False
            return None

    def _store(self, page: int, pixmap: QPixmap) -> None:
        self._cache[page] = pixmap


class _Worker(QRunnable):
    """Drains the loader's queue, holding one document open for the run."""

    def __init__(self, loader: ThumbnailLoader):
        super().__init__()
        self._loader = loader
        self.setAutoDelete(True)

    def run(self) -> None:      # noqa: D102 - QRunnable entry point
        loader = self._loader
        doc = None
        try:
            from ..backends import pdf as pb
            try:
                doc = pb.open_doc(loader.path, loader.password)
            except pb.PdfError as exc:
                loader.failed.emit(0, str(exc))
                return

            while not loader._stopped:
                page = loader._next_page()
                if page is None:
                    return
                if not 1 <= page <= doc.page_count:
                    continue
                try:
                    data = doc[page - 1].get_pixmap(dpi=THUMB_DPI).tobytes("png")
                except Exception as exc:        # one bad page must not stop the rest
                    loader.failed.emit(page, str(exc))
                    continue

                pixmap = QPixmap()
                pixmap.loadFromData(data, "PNG")
                if not pixmap.isNull():
                    pixmap = pixmap.scaledToWidth(
                        THUMB_WIDTH, Qt.TransformationMode.SmoothTransformation)
                    loader._store(page, pixmap)
                    loader.ready.emit(page, pixmap)
        finally:
            with loader._lock:
                loader._running = False
            if doc is not None:
                doc.close()
