"""PDF viewer tab: continuous page view, thumbnails, outline, search and tools."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMenu, QMessageBox, QFileDialog,
                             QSlider, QSplitter, QTabWidget, QToolBar, QToolButton,
                             QVBoxLayout, QWidget)

from ..backends import pdf as pb
from ..core.safe import replace_in_place
from .annotation_layer import AnnotationLayer
from .pdf_tools import run_tool, _run_in_place
from .thumbnails import THUMB_WIDTH, ThumbnailLoader

ZOOMS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


def _ranges_label(pages: list[int]) -> str:
    """Compact 1-based range spec like ``1,3-5`` for a set of pages."""
    nums = sorted(set(pages))
    if not nums:
        return ""
    out: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(f"{start}-{prev}" if prev != start else str(start))
        start = prev = n
    out.append(f"{start}-{prev}" if prev != start else str(start))
    return ",".join(out)


class PdfTab(QWidget):
    """Read a PDF and run the toolbox against it."""

    modified_changed = pyqtSignal(bool)
    open_request = pyqtSignal(str)

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = Path(path)
        self.password: str | None = None
        self.info: pb.PdfInfo | None = None
        self.error = ""
        self.page = 1
        self.zoom = 1.0
        self._jobs: list = []
        self._page_cache: OrderedDict[tuple[int, int], QPixmap] = OrderedDict()
        self._page_cache_max = 24
        self._pending: list[pb.Annotation] = []
        self._undo: list[pb.Annotation] = []
        self._search_hits: list[tuple[int, tuple]] = []
        self._layout_mode = "continuous"

        # Hidden pixmap target for tests.
        self.page_label = QLabel(self)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.hide()

        # --- sidebar
        self.thumbs = QListWidget(self)
        self.thumbs.setFixedWidth(180)
        self.thumbs.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.5)))
        self.thumbs.setUniformItemSizes(True)
        self.thumbs.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        self.thumbs.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumbs_context)
        self.thumbs.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel)
        self.thumbs.currentRowChanged.connect(
            lambda row: self.go_to(row + 1) if row >= 0 else None)
        bar = self.thumbs.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(lambda _v: self._request_visible_thumbs())
        self._thumbs: ThumbnailLoader | None = None

        self.outline = QListWidget(self)
        self.outline.itemClicked.connect(self._on_outline)
        self.outline.itemActivated.connect(self._on_outline)

        self.side_tabs = QTabWidget(self)
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.addTab(self.thumbs, "Pages")
        self.side_tabs.addTab(self.outline, "Contents")
        self._side = self.side_tabs

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self.side_tabs)
        from .pdf_pages import ContinuousPdfView
        self.strip = ContinuousPdfView(self)
        self.strip.need_render.connect(self._on_need_render)
        self.strip.page_changed.connect(self._on_strip_page)
        self.strip.zoom_requested.connect(self._on_view_zoom)
        split.addWidget(self.strip)
        split.setStretchFactor(1, 1)
        self.view = self.strip
        self.annot_layer = AnnotationLayer(self)
        gone = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        gone.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        gone.activated.connect(self.delete_selected_annotation)

        # --- toolbar (one Preview-style icon bar)
        from .icons import add_action, icon_button, style_bar

        bar = QToolBar(self)
        style_bar(bar)
        self.sidebar_btn = add_action(
            bar, ("view-sidetree", "view-list-details", "sidebar-show"),
            "Sidebar", self._toggle_sidebar,
            shortcut="S", checkable=True,
            tooltip="Show / hide thumbnails and outline")
        if self.sidebar_btn is not None:
            self.sidebar_btn.setChecked(True)
        add_action(bar, "go-previous", "Previous page", self.prev_page,
                   shortcut="PgUp")
        self.page_box = QLineEdit(self)
        self.page_box.setFixedWidth(52)
        self.page_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_box.returnPressed.connect(self._on_page_box)
        self.page_box.setToolTip("Page number")
        bar.addWidget(self.page_box)
        self.page_total = QLabel(" / ?", self)
        bar.addWidget(self.page_total)
        add_action(bar, "go-next", "Next page", self.next_page, shortcut="PgDown")
        bar.addSeparator()
        add_action(bar, "zoom-out", "Zoom out", self.zoom_out)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.zoom_slider.setRange(25, 400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(100)
        self.zoom_slider.setToolTip("Zoom")
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider)
        bar.addWidget(self.zoom_slider)
        add_action(bar, "zoom-in", "Zoom in", self.zoom_in)
        add_action(bar, ("zoom-fit-width", "zoom-fit-best"), "Fit width",
                   self.fit_width)
        self.layout_box = QComboBox(self)
        self.layout_box.addItem("Continuous", "continuous")
        self.layout_box.addItem("Single", "single")
        self.layout_box.addItem("Facing", "facing")
        self.layout_box.setToolTip("Page layout")
        self.layout_box.currentIndexChanged.connect(self._on_layout_mode)
        bar.addWidget(self.layout_box)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMaximumWidth(220)
        self.search_box.returnPressed.connect(self.search_next)
        bar.addSeparator()
        bar.addWidget(self.search_box)
        add_action(bar, "go-previous", "Previous match", self.search_prev,
                   tooltip="Previous search match")

        bar.addSeparator()
        add_action(bar, "object-rotate-left", "Rotate left",
                   lambda: self.rotate_current(-90),
                   tooltip="Rotate current page left")
        add_action(bar, "object-rotate-right", "Rotate right",
                   lambda: self.rotate_current(90),
                   tooltip="Rotate current page right")
        self.dark_btn = add_action(
            bar, ("view-contrast", "color-invert", "object-invert-image"),
            "Invert view", self._toggle_dark, checkable=True,
            tooltip="Invert colours for dark-mode reading (view only)")
        bar.addSeparator()

        self.annot_btn = icon_button(
            self, ("draw-highlight", "document-edit", "edit-entry"), "Annotate")
        self.annot_btn.setCheckable(True)
        self.annot_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.annot_menu = QMenu(self)
        self.annot_action = QActionGroup(self)
        self.annot_action.setExclusive(True)
        annot_items = (
            ("highlight", "Highlight"),
            ("underline", "Underline"),
            ("strike", "Strikethrough"),
            ("rectangle", "Rectangle"),
            ("oval", "Oval"),
            ("line", "Line"),
            ("arrow", "Arrow"),
            ("sketch", "Sketch"),
            ("note", "Note"),
            ("redact", "Redact (permanent)"),
        )
        for key, label in annot_items:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(key)
            self.annot_action.addAction(act)
            self.annot_menu.addAction(act)
        self.annot_menu.addSeparator()
        off_act = QAction("None (off)", self)
        off_act.setCheckable(True)
        off_act.setData("off")
        self.annot_action.addAction(off_act)
        self.annot_menu.addAction(off_act)
        self.annot_btn.setMenu(self.annot_menu)
        self.annot_action.triggered.connect(self._on_annotate_mode)
        self.annot_color = QColor(255, 217, 51)
        self.annot_color_btn = QToolButton(self)
        self.annot_color_btn.setToolTip("Annotation colour")
        self.annot_color_btn.setFixedSize(28, 28)
        self.annot_color_btn.clicked.connect(self._pick_annot_color)
        self._style_color_btn()
        self.show_marks_btn = icon_button(
            self, ("view-visible", "layer-visible-on"), "Show annotations")
        self.show_marks_btn.setCheckable(True)
        self.show_marks_btn.setChecked(True)
        self.show_marks_btn.toggled.connect(self._on_toggle_marks)
        cluster = QWidget(self)
        cluster_row = QHBoxLayout(cluster)
        cluster_row.setContentsMargins(6, 0, 6, 0)
        cluster_row.setSpacing(8)
        cluster_row.addWidget(self.annot_btn)
        cluster_row.addWidget(self.annot_color_btn)
        cluster_row.addWidget(self.show_marks_btn)
        bar.addWidget(cluster)
        bar.addSeparator()
        self.present_btn = icon_button(
            self, ("media-playback-start", "media-playback-pause"), "Present")
        self.present_btn.setCheckable(True)
        self.present_btn.setToolTip("Auto-advance pages (presentation)")
        self.present_btn.toggled.connect(self._toggle_present)
        self.present_btn.hide()
        self._present_timer = None

        overflow = icon_button(self, "application-menu", "Tools")
        overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        over_menu = QMenu(self)
        over_menu.addAction("Delete page", self.delete_current)
        over_menu.addAction("Insert page…", self.insert_after)
        over_menu.addSeparator()
        for name in ("Organise pages…", "Extract pages", "Split",
                     "Merge with…", "Compress", "Flatten", "Protect",
                     "Unlock", "Watermark", "Page numbers",
                     "Crop & Resize", "Invert colours", "Headers & Footers",
                     "N-up…", "Booklet…", "Linearize",
                     "To images", "To text", "To HTML", "To Word (.docx)",
                     "To PDF/A", "OCR", "Repair",
                     "Sign / Stamp", "Bookmarks…", "Metadata", "Fill form…",
                     "Text / Markdown to PDF…", "Fingerprint"):
            over_menu.addAction(name, lambda n=name: run_tool(self, n))
        over_menu.addSeparator()
        over_menu.addAction("Present", lambda: self.present_btn.toggle())
        over_menu.addAction("Sign…", self.sign)
        over_menu.addAction("Print…", self.print_file)
        over_menu.addAction("Copy page text", self.copy_page_text)
        overflow.setMenu(over_menu)
        bar.addWidget(overflow)

        self.status = QLabel(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(split, 1)
        layout.addWidget(self.status)

        # prompt=False: a constructor must never block on a modal dialog.
        self.reload(prompt=False)

    # --- loading ---------------------------------------------------------
    def reload(self, *, prompt: bool = True) -> None:
        """Load the document.

        Errors are reported through ``self.error`` and the status bar rather
        than a modal dialog, so constructing a tab never blocks.  Only an
        explicit user action (``prompt=True`` from the retry button) may open
        the password dialog.
        """
        self.error = ""
        try:
            self.info = pb.info(self.path, self.password)
        except pb.PdfPasswordRequired as exc:
            self.error = str(exc)
            self.status.setText("Password required — use Unlock to enter it.")
            if prompt and self._ask_password():
                return self.reload(prompt=False)
            return
        except pb.PdfError as exc:
            self.error = str(exc)
            self.status.setText(str(exc))
            return

        self._page_cache.clear()
        self.page_total.setText(f" / {self.info.page_count}")
        self._fill_outline()
        self._fill_thumbs()
        self.strip.load(self.info, self.zoom)
        self.go_to(min(self.page, self.info.page_count))

    def reload_from(self, path: Path) -> None:
        """Re-read the document after an in-place edit replaced the file."""
        self.path = Path(path)
        self.reload(prompt=False)

    def _ask_password(self) -> bool:
        pw, ok = QInputDialog.getText(
            self, "Password required", f"Password for {self.path.name}:",
            QLineEdit.EchoMode.Password)
        if ok and pw:
            self.password = pw
            return True
        return False

    def _fill_outline(self) -> None:
        self.outline.clear()
        if not self.info:
            return
        for level, title, page in self.info.toc:
            item = QListWidgetItem("   " * max(0, level - 1) + title)
            item.setData(Qt.ItemDataRole.UserRole, page)
            self.outline.addItem(item)
        if not self.info.toc:
            empty = QListWidgetItem("No contents in this file")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.outline.addItem(empty)

    def _fill_thumbs(self) -> None:
        """Create placeholder rows and start rendering the visible ones."""
        if self._thumbs is not None:
            self._thumbs.stop()
        self.thumbs.clear()
        if not self.info:
            return

        placeholder = QPixmap(THUMB_WIDTH, int(THUMB_WIDTH * 1.4))
        placeholder.fill(self.palette().alternateBase().color())
        for n in range(1, self.info.page_count + 1):
            item = QListWidgetItem(QIcon(placeholder), f"Page {n}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumbs.addItem(item)

        self._thumbs = ThumbnailLoader(self.path, self.password, self)
        self._thumbs.ready.connect(self._on_thumb_ready)
        self._request_visible_thumbs()

    def _on_thumb_ready(self, page: int, pixmap: QPixmap) -> None:
        item = self.thumbs.item(page - 1)
        if item is not None:
            item.setIcon(QIcon(pixmap))

    def _request_visible_thumbs(self) -> None:
        """Render the rows on screen plus a small look-ahead margin."""
        if self._thumbs is None or not self.info:
            return
        total = self.info.page_count
        first, last = 1, min(total, 12)

        viewport = self.thumbs.viewport()
        if viewport is not None and self.thumbs.count():
            top = self.thumbs.indexAt(viewport.rect().topLeft())
            bottom = self.thumbs.indexAt(viewport.rect().bottomLeft())
            if top.isValid():
                first = top.row() + 1
                last = (bottom.row() + 1) if bottom.isValid() else total
        margin = 4
        wanted = range(max(1, first - margin), min(total, last + margin) + 1)
        self._thumbs.request([n for n in wanted
                              if self._thumbs.cached(n) is None])

    def _on_outline(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.ItemDataRole.UserRole)
        try:
            page = int(page)
        except (TypeError, ValueError):
            return
        if page >= 1:
            self.go_to(page)

    # --- navigation ------------------------------------------------------
    def go_to(self, page: int) -> None:
        if not self.info:
            return
        self.page = max(1, min(page, self.info.page_count))
        self.page_box.setText(str(self.page))
        if self.thumbs.currentRow() != self.page - 1:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(self.page - 1)
            self.thumbs.blockSignals(False)
        self._render()
        self._request_visible_thumbs()
        self.strip.scroll_to(self.page)

    def next_page(self) -> None:
        self.go_to(self.page + 1)

    def prev_page(self) -> None:
        self.go_to(self.page - 1)

    def _toggle_present(self, on: bool) -> None:
        """Start/stop a timer that advances pages automatically."""
        from PyQt6.QtCore import QTimer
        if on:
            window = self.window()
            self._present_restore = window.isMaximized()
            window.showFullScreen()
            self._present_timer = QTimer(self)
            self._present_timer.setInterval(3000)
            self._present_timer.timeout.connect(self._present_tick)
            self._present_timer.start()
            self.status.setText("Presenting — ←/→ change page, Esc stops")
        else:
            if self._present_timer is not None:
                self._present_timer.stop()
                self._present_timer.deleteLater()
                self._present_timer = None
            window = self.window()
            if window.isFullScreen():
                if getattr(self, "_present_restore", False):
                    window.showMaximized()
                else:
                    window.showNormal()
            self.status.setText("Presentation stopped.")

    def _toggle_dark(self) -> None:
        on = bool(self.dark_btn and self.dark_btn.isChecked())
        self.strip.set_invert(on)
        self.status.setText("Dark view on." if on else "Dark view off.")

    def _present_tick(self) -> None:
        if self.page >= self.info.page_count:
            # loop back to the start so a deck plays continuously
            self.go_to(1)
        else:
            self.next_page()

    def _on_page_box(self) -> None:
        try:
            self.go_to(int(self.page_box.text()))
        except ValueError:
            self.page_box.setText(str(self.page))

    def zoom_in(self) -> None:
        self.zoom = next((z for z in ZOOMS if z > self.zoom + 1e-6), ZOOMS[-1])
        self.strip.set_zoom(self.zoom)
        self._render()

    def zoom_out(self) -> None:
        self.zoom = next((z for z in reversed(ZOOMS) if z < self.zoom - 1e-6), ZOOMS[0])
        self.strip.set_zoom(self.zoom)
        self._render()

    def fit_width(self) -> None:
        if not self.info or not self.info.pages:
            return
        viewport = self.view.viewport()
        avail = (viewport.width() if viewport else self.width()) - 24
        page_width = self.info.pages[self.page - 1].width
        if page_width > 0:
            self.zoom = max(0.1, min(4.0, avail / page_width))
        self.strip.set_zoom(self.zoom)
        self._render()

    def _on_zoom_slider(self, value: int) -> None:
        """Zoom to an arbitrary percentage via the slider."""
        self.zoom = max(0.1, min(4.0, value / 100))
        self.strip.set_zoom(self.zoom)
        self._render()

    def _sync_zoom_slider(self) -> None:
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(self.zoom * 100))
        self.zoom_slider.blockSignals(False)

    def _toggle_sidebar(self) -> None:
        """Show / hide the thumbnails & outline pane (Preview's sidebar)."""
        visible = not self._side.isVisible()
        self._side.setVisible(visible)
        self.sidebar_btn.setChecked(visible)

    def _selected_pages(self) -> list[int]:
        """1-based page numbers of the currently selected thumbnails."""
        return sorted({idx.row() + 1 for idx in self.thumbs.selectedIndexes()})

    def _thumbs_context(self, pos) -> None:
        """Right-click on a thumbnail: act on the selection (or that row)."""
        item = self.thumbs.itemAt(pos) if hasattr(self.thumbs, "itemAt") else None
        if item is None:
            return
        row = self.thumbs.row(item)
        if row not in (idx.row() for idx in self.thumbs.selectedIndexes()):
            self.thumbs.setCurrentRow(row)
        pages = self._selected_pages() or [row + 1]
        menu = QMenu(self)
        menu.addAction(f"Delete page(s) {_ranges_label(pages)}",
                       lambda: self.delete_pages(pages))
        menu.addAction(f"Rotate left {_ranges_label(pages)}",
                       lambda: self.rotate_pages(pages, -90))
        menu.addAction(f"Rotate right {_ranges_label(pages)}",
                       lambda: self.rotate_pages(pages, 90))
        menu.addAction("Extract selected pages…",
                       lambda: self.extract_pages(pages))
        menu.exec(self.thumbs.viewport().mapToGlobal(pos))

    def _on_layout_mode(self, _index: int = 0) -> None:
        mode = self.layout_box.currentData()
        if isinstance(mode, str):
            self.strip.set_layout_mode(mode)
            self.annot_layer.sync_geometry()

    def _on_view_zoom(self, zoom: float) -> None:
        self.zoom = zoom
        self._sync_zoom_slider()
        self.annot_layer.sync_geometry()
        self.status.setText(
            f"Page {self.page} of {self.info.page_count if self.info else '?'} · {int(self.zoom * 100)}%")

    def _cache_get(self, key: tuple[int, int]) -> "QPixmap | None":
        pix = self._page_cache.get(key)
        if pix is not None:
            self._page_cache.move_to_end(key)
        return pix

    def _cache_put(self, key: tuple[int, int], pixmap: QPixmap) -> None:
        self._page_cache[key] = pixmap
        self._page_cache.move_to_end(key)
        while len(self._page_cache) > self._page_cache_max:
            self._page_cache.popitem(last=False)

    def _render(self) -> None:
        if not self.info:
            return
        dpi = self.strip.current_dpi()
        key = (self.page, dpi)
        cached = self._cache_get(key)
        if cached is None:
            cached = self._raster(self.page, dpi)
            if cached is None:
                return
            self._cache_put(key, cached)
        self.page_label.setPixmap(cached)
        self.strip.show_pixmap(self.page, cached, dpi)
        self.status.setText(
            f"Page {self.page} of {self.info.page_count} · {int(self.zoom * 100)}%")
        self.annot_layer.sync_geometry()
        self.annot_layer.refresh()
        self._sync_zoom_slider()

    def _raster(self, page: int, dpi: int) -> QPixmap | None:
        try:
            data = pb.render_page(self.path, page, dpi=dpi,
                                  password=self.password)
        except pb.PdfError as exc:
            self.status.setText(str(exc))
            return None
        cached = QPixmap()
        cached.loadFromData(data, "PNG")
        return cached if not cached.isNull() else None

    def _on_need_render(self, page: int, dpi: int) -> None:
        if not self.info:
            return
        key = (page, dpi)
        cached = self._cache_get(key)
        if cached is None:
            cached = self._raster(page, dpi)
            if cached is None:
                return
            self._cache_put(key, cached)
        self.strip.show_pixmap(page, cached, dpi)
        if page == self.page:
            self.page_label.setPixmap(cached)
        self.annot_layer.sync_geometry()

    def _on_strip_page(self, page: int) -> None:
        if page == self.page or not self.info:
            return
        self.page = page
        self.page_box.setText(str(self.page))
        if self.thumbs.currentRow() != self.page - 1:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(self.page - 1)
            self.thumbs.blockSignals(False)
        self.status.setText(
            f"Page {self.page} of {self.info.page_count} · {int(self.zoom * 100)}%")

    # --- search ----------------------------------------------------------
    def search_next(self) -> None:
        self._search(1)

    def search_prev(self) -> None:
        self._search(-1)

    def _search(self, direction: int) -> None:
        needle = self.search_box.text().strip()
        if not needle or not self.info:
            return
        if needle != getattr(self, "_search_needle", None) or not self._search_hits:
            try:
                self._search_hits = pb.search_text(
                    self.path, needle, password=self.password)
            except pb.PdfError:
                self._search_hits = []
            self._search_needle = needle
        hits = self._search_hits
        self.strip.set_search_hits(hits)
        if not hits:
            self.status.setText(f"'{needle}' not found")
            return
        if direction > 0:
            after = [h for h in hits if h[0] > self.page] or hits
            page, _rect = after[0]
        else:
            before = [h for h in hits if h[0] < self.page] or hits
            page, _rect = before[-1]
        self.go_to(page)
        n = sum(1 for h in hits if h[0] == page)
        self.status.setText(
            f"Found '{needle}' on page {page} ({len(hits)} hit(s), "
            f"{n} on this page)")

    # --- annotations -----------------------------------------------------
    def _on_annotate_mode(self, action) -> None:
        mode = action.data()
        self.annot_layer.color = (self.annot_color.red() / 255,
                                  self.annot_color.green() / 255,
                                  self.annot_color.blue() / 255)
        self.annot_layer.set_mode(mode)
        self.annot_btn.setChecked(mode != "off")
        verbs = {
            "highlight": "drag to highlight text",
            "underline": "drag to underline text",
            "strike": "drag to strike through text",
            "note": "drag, then type a note",
            "rectangle": "drag to draw a rectangle",
            "oval": "drag to draw an ellipse",
            "line": "drag to draw a line",
            "arrow": "drag to draw an arrow",
            "sketch": "draw freehand",
            "redact": "drag to mark what to remove permanently",
        }
        verb = verbs.get(mode, "drag on the page to annotate")
        self.status.setText(f"Annotation mode: {verb}. Esc or toggle off to stop.")

    def _style_color_btn(self) -> None:
        c = self.annot_color.name()
        self.annot_color_btn.setStyleSheet(
            f"QToolButton {{"
            f" background: {c};"
            f" border: 1px solid palette(mid);"
            f" border-radius: 6px;"
            f" min-width: 28px; min-height: 28px;"
            f" max-width: 28px; max-height: 28px;"
            f"}}")

    def _pick_annot_color(self) -> None:
        col = QColorDialog.getColor(self.annot_color, self,
                                    "Annotation colour")
        if not col.isValid():
            return
        self.annot_color = col
        self._style_color_btn()
        rgb = (col.red() / 255, col.green() / 255, col.blue() / 255)
        self.annot_layer.color = rgb
        selected = self.annot_layer.selected()
        if selected is not None:
            self._recolor_annotation(selected, rgb)
        self.annot_layer.update()

    def _recolor_annotation(self, ann: pb.Annotation, rgb) -> None:
        if not getattr(ann, "saved", False):
            ann.color = rgb
            self.annot_layer.refresh()
            self.modified_changed.emit(True)
            self.status.setText("Colour updated — Save to write it into the file.")
            return

        def write(tmp: Path) -> None:
            pb.recolor_annotation(self.path, tmp, ann.page, ann.rect, rgb,
                                  self.password)

        try:
            replace_in_place(self.path, write)
        except (pb.PdfError, OSError) as exc:
            QMessageBox.critical(self, "Colour change failed", str(exc))
            return
        self.annot_layer.refresh()
        self.status.setText("Annotation colour saved.")

    def _on_toggle_marks(self, checked: bool) -> None:
        self.annot_layer.set_show_marks(checked)

    def apply_annotation(self, kind: str, rect, color, text: str,
                         points: list[tuple[float, float]] | None = None,
                         page: int | None = None) -> None:
        """Queue one annotation; Ctrl+S writes it into the file."""
        from ..backends.pdf import Annotation

        target = page or self.page
        ann = Annotation(page=target, kind=kind, rect=rect,
                         color=color, text=text, points=points or [],
                         saved=False)
        self._pending.append(ann)
        self._undo.append(ann)
        self.annot_layer.refresh()
        self.modified_changed.emit(True)
        self.status.setText(
            f"Queued {kind} on page {target} — Save to write it into the file.")

    def undo(self) -> bool:
        """Remove the last unsaved annotation (Ctrl+Z)."""
        if not self._undo:
            self.status.setText("Nothing to undo.")
            return True
        ann = self._undo.pop()
        if ann in self._pending:
            self._pending.remove(ann)
        if self.annot_layer.selected() is ann:
            self.annot_layer._selected = None
        self.annot_layer.refresh()
        self.modified_changed.emit(bool(self._pending))
        self.status.setText("Undid last annotation.")
        return True

    def delete_selected_annotation(self) -> None:
        ann = self.annot_layer.selected()
        if ann is None:
            return
        if not getattr(ann, "saved", False):
            if ann in self._pending:
                self._pending.remove(ann)
            if ann in self._undo:
                self._undo.remove(ann)
            self.annot_layer._selected = None
            self.annot_layer.refresh()
            self.modified_changed.emit(bool(self._pending))
            self.status.setText("Removed unsaved annotation.")
            return

        def write(tmp: Path) -> None:
            pb.remove_annotation(self.path, tmp, ann.page, ann.rect,
                                 self.password)

        try:
            replace_in_place(self.path, write)
        except (pb.PdfError, OSError) as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self.annot_layer._selected = None
        self.annot_layer.refresh()
        self.status.setText("Deleted annotation from the file.")

    def apply_redaction(self, rect) -> None:
        """Permanently remove content under *rect* on the current page.

        Redaction is destructive and unrecoverable, so the user must confirm
        explicitly before anything is written.
        """
        from ..backends import pdf as pdf_backend
        from ..core.safe import replace_in_place

        reply = QMessageBox.question(
            self, "Permanent redaction",
            "Redacting permanently deletes everything inside the selection — "
            "text, images and vector art cannot be recovered. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        def write(tmp: Path) -> None:
            pdf_backend.redact(self.path, tmp, [rect], page=self.page,
                              password=self.password)

        self.status.setText("Redacting…")
        try:
            replace_in_place(self.path, write)
        except (pdf_backend.PdfError, OSError) as exc:
            QMessageBox.critical(self, "Redaction failed", str(exc))
            return
        self._page_cache.clear()
        self.annot_layer.refresh()
        self.status.setText("Redacted — content permanently removed.")

    def sign(self) -> None:
        """Capture a signature, then click on the page to drop it."""
        from .signature_dialog import SignatureDialog
        dialog = SignatureDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or not dialog.result_path:
            return
        self._placing_signature = dialog.result_path
        self.status.setText("Click anywhere on the page to place the signature "
                            "(Esc to cancel).")

    def eventFilter(self, obj, event) -> bool:
        return super().eventFilter(obj, event)

    def _place_signature_at(self, pos) -> None:
        sig = getattr(self, "_placing_signature", None)
        if sig is None:
            return
        zoom = self.zoom
        page = self.info.pages[self.page - 1]
        # click point -> PDF, bottom-left origin
        px = pos.x() / zoom
        py = page.height - (pos.y() / zoom)
        from PyQt6.QtGui import QImage
        img = QImage(str(sig))
        w = (img.width() / 3.0)  # ~1/3 of drawn width in points
        h = (img.height() / 3.0)
        rect = (px, py - h, px + w, py)  # anchor bottom-left at click

        def write(tmp: Path) -> None:
            pb.stamp(self.path, tmp, image=sig, page=self.page,
                     rect=rect, password=self.password)

        self.status.setText("Placing signature…")
        try:
            replace_in_place(self.path, write)
        except (pb.PdfError, OSError) as exc:
            QMessageBox.critical(self, "Sign failed", str(exc))
            return
        self._page_cache.clear()
        self.annot_layer.refresh()
        self.status.setText("Signature placed.")

    def keyPressEvent(self, a0) -> None:
        if a0 is not None and self.present_btn.isChecked():
            if a0.key() == Qt.Key.Key_Escape:
                self.present_btn.setChecked(False)
                a0.accept()
                return
            if a0.key() in (Qt.Key.Key_Next, Qt.Key.Key_Space,
                            Qt.Key.Key_Right, Qt.Key.Key_Down):
                self.next_page()
                a0.accept()
                return
            if a0.key() in (Qt.Key.Key_Prior, Qt.Key.Key_Left, Qt.Key.Key_Up):
                self.prev_page()
                a0.accept()
                return
        if a0 is not None and a0.key() == Qt.Key.Key_Escape \
                and self.annot_layer.mode != "off":
            self.annot_layer.set_mode("off")
            self.annot_btn.setChecked(False)
            self.status.setText("Annotation mode off.")
            a0.accept()
            return
        if a0 is not None and a0.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.annot_layer.selected() is not None:
                self.delete_selected_annotation()
                a0.accept()
                return
        super().keyPressEvent(a0)

    # --- tools -----------------------------------------------------------
    # --- Preview-style inline page edits (in place, no new tab) ----------
    def rotate_current(self, angle: int) -> None:
        """Rotate the current page (and only it) in place."""
        return self.rotate_pages([self.page], angle)

    def delete_current(self) -> None:
        """Delete the page currently shown."""
        return self.delete_pages([self.page])

    def rotate_pages(self, pages: list[int], angle: int) -> None:
        """Rotate the given pages in place (no new tab)."""
        if not pages:
            return
        spec = _ranges_label(pages)
        return _run_in_place(
            self, f"Rotating {spec}",
            lambda tmp, ctx: pb.rotate_pages(
                self.path, tmp, angle=angle, ranges=spec,
                password=self.password))

    def delete_pages(self, pages: list[int]) -> None:
        """Delete the given pages in place (no new tab)."""
        if not pages:
            return
        total = self.info.page_count if self.info else 0
        remaining = total - len(set(pages))
        if remaining <= 0:
            QMessageBox.warning(self, "Cannot delete",
                                "A PDF must keep at least one page.")
            return
        spec = _ranges_label(pages)
        self._drop_pending_on_pages(pages)
        return _run_in_place(
            self, f"Deleting {spec}",
            lambda tmp, ctx: pb.delete_pages(
                self.path, tmp, spec, password=self.password))

    def _drop_pending_on_pages(self, pages: list[int]) -> None:
        gone = set(pages)
        kept: list[pb.Annotation] = []
        for ann in self._pending:
            if ann.page in gone:
                continue
            ann.page -= sum(1 for p in gone if p < ann.page)
            kept.append(ann)
        self._pending = kept
        self._undo = [a for a in self._undo if a in kept]
        self.modified_changed.emit(bool(self._pending))

    def extract_pages(self, pages: list[int]) -> None:
        """Pull the selected pages into a new file (keeps the original)."""
        if not pages:
            return
        spec = _ranges_label(pages)
        dest, _ = QFileDialog.getSaveFileName(
            self, "Extract pages",
            str(Path(self.path).with_suffix("")) + "-pages.pdf",
            "PDF (*.pdf)")
        if not dest:
            return
        try:
            pb.extract_pages(self.path, Path(dest), spec,
                             password=self.password)
        except pb.PdfError as exc:
            QMessageBox.critical(self, "Extract failed", str(exc))
            return
        self.open_request.emit(str(Path(dest).resolve()))

    def insert_after(self) -> None:
        """Insert a page (image or PDF) immediately after the current one."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Insert page", str(Path(self.path).parent),
            "PDF or image (*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tiff)")
        if not path:
            return
        after = self.page
        for ann in self._pending:
            if ann.page > after:
                ann.page += 1
        _run_in_place(
            self, "Inserting page",
            lambda tmp, ctx: pb.insert_pages(
                self.path, tmp, path, after=after, password=self.password))

    # --- lifecycle -------------------------------------------------------
    def is_modified(self) -> bool:
        return bool(self._pending)

    def save(self) -> bool:
        if not self._pending:
            return True
        pending = list(self._pending)

        def write(tmp: Path) -> None:
            pb.add_annotations(self.path, tmp, pending, self.password)

        try:
            replace_in_place(self.path, write)
        except (pb.PdfError, OSError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._pending.clear()
        self._undo.clear()
        self._page_cache.clear()
        self.annot_layer.refresh()
        self.modified_changed.emit(False)
        self.status.setText("Saved annotations into the file.")
        return True

    def copy_page_text(self) -> None:
        from PyQt6.QtWidgets import QApplication
        try:
            text = pb.extract_text(self.path, [self.page], self.password)
        except pb.PdfError as exc:
            QMessageBox.warning(self, "Copy", str(exc))
            return
        QApplication.clipboard().setText(text)
        self.status.setText("Copied this page's text.")

    def print_file(self) -> None:
        """Send the PDF file to CUPS instead of rasterising every page."""
        import shutil
        from ..core.process import run as run_tool
        from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        lp = shutil.which("lp")
        if lp is None:
            QMessageBox.warning(self, "Print", "The lp command is not available.")
            return
        cmd = [lp]
        name = printer.printerName()
        if name:
            cmd.extend(["-d", name])
        copies = printer.copyCount()
        if copies > 1:
            cmd.extend(["-n", str(copies)])
        frm, to = printer.fromPage(), printer.toPage()
        if frm and to:
            cmd.extend(["-P", f"{frm}-{to}"])
        cmd.append(str(self.path))
        try:
            run_tool(cmd, timeout=30)
        except OSError as exc:
            QMessageBox.warning(self, "Print", str(exc))
            return
        self.status.setText(f"Sent {self.path.name} to the printer.")

    def cleanup(self) -> None:
        """Stop background rendering when the tab goes away."""
        if self._thumbs is not None:
            self._thumbs.stop()

    def closeEvent(self, a0) -> None:
        self.cleanup()
        super().closeEvent(a0)
