"""PDF viewer tab: continuous page view, thumbnails, outline, search and tools."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMenu, QMessageBox, QFileDialog, QPushButton,
                             QScrollArea, QSlider, QSplitter, QToolBar, QToolButton,
                             QVBoxLayout, QWidget)

from ..backends import pdf as pb
from ..core.jobs import submit
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


def _shortcut(action, keys: str) -> None:
    if action is not None:
        action.setShortcut(keys)


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
        self._page_cache: dict[tuple[int, int], QPixmap] = {}

        # --- page view
        self.page_label = QLabel(self)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view = QScrollArea(self)
        self.view.setWidget(self.page_label)
        self.view.setWidgetResizable(True)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Annotation overlay lives on top of the rendered page label.
        self.annot_layer = AnnotationLayer(self)

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
        self.outline.itemActivated.connect(self._on_outline)

        side = QSplitter(Qt.Orientation.Vertical, self)
        self._side = side
        side.addWidget(self.thumbs)
        side.addWidget(self.outline)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(side)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)

        # --- toolbars
        nav = QToolBar(self)
        self.sidebar_btn = nav.addAction("▤", self._toggle_sidebar)
        self.sidebar_btn.setToolTip("Show / hide thumbnails & outline (S)")
        self.sidebar_btn.setCheckable(True)
        self.sidebar_btn.setChecked(True)
        _shortcut(nav.addAction("◀", self.prev_page), "PgUp")
        self.page_box = QLineEdit(self)
        self.page_box.setFixedWidth(60)
        self.page_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_box.returnPressed.connect(self._on_page_box)
        nav.addWidget(self.page_box)
        self.page_total = QLabel(" / ?", self)
        nav.addWidget(self.page_total)
        _shortcut(nav.addAction("▶", self.next_page), "PgDown")
        nav.addSeparator()
        nav.addAction("−", self.zoom_out)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.zoom_slider.setRange(25, 400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.setToolTip("Zoom")
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider)
        nav.addWidget(self.zoom_slider)
        nav.addAction("+", self.zoom_in)
        nav.addAction("Fit", self.fit_width)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search text…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.returnPressed.connect(self.search_next)
        nav.addSeparator()
        nav.addWidget(self.search_box)

        tools = QToolBar(self)
        # Preview-style inline controls: instant, in-place, no new tab.
        rot_l = tools.addAction("⟲", lambda: self.rotate_current(-90))
        rot_l.setToolTip("Rotate left (counter-clockwise)")
        rot_r = tools.addAction("⟳", lambda: self.rotate_current(90))
        rot_r.setToolTip("Rotate right (clockwise)")
        tools.addSeparator()
        del_btn = tools.addAction("🗑", lambda: self.delete_current())
        del_btn.setToolTip("Delete current page")
        ins_btn = tools.addAction("⎄", lambda: self.insert_after())
        ins_btn.setToolTip("Insert a page after this one")
        tools.addSeparator()

        # Annotation controls, collapsed into a single popup button.
        self.annot_btn = QToolButton(self)
        self.annot_btn.setText("Annotate")
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
        self.annot_color_btn.setText("▮")
        self.annot_color_btn.setToolTip("Annotation colour")
        self.annot_color_btn.clicked.connect(self._pick_annot_color)
        self.show_marks_btn = QToolButton(self)
        self.show_marks_btn.setText("Marks")
        self.show_marks_btn.setCheckable(True)
        self.show_marks_btn.setChecked(True)
        self.show_marks_btn.toggled.connect(self._on_toggle_marks)
        self.show_marks_btn.setToolTip("Show / hide annotations")
        tools.addWidget(self.annot_btn)
        tools.addWidget(self.annot_color_btn)
        tools.addWidget(self.show_marks_btn)
        tools.addSeparator()
        self.present_btn = QToolButton(self)
        self.present_btn.setText("▶ Present")
        self.present_btn.setToolTip(
            "Auto-advance pages on a timer (presentation / hands-free reading)")
        self.present_btn.setCheckable(True)
        self.present_btn.toggled.connect(self._toggle_present)
        tools.addWidget(self.present_btn)
        self._present_timer = None

        # Heavy / less-common operations live in an overflow menu so the
        # primary bar stays uncluttered.
        overflow = QToolButton(self)
        overflow.setText("Tools")
        overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        over_menu = QMenu(self)
        for name in ("Organise pages…", "Extract pages", "Split",
                     "Merge with…", "Compress", "Flatten", "Protect",
                     "Unlock", "Watermark", "Page numbers", "To images",
                     "To text", "OCR", "Repair", "Sign / Stamp",
                     "Bookmarks…", "Metadata"):
            over_menu.addAction(name, lambda n=name: run_tool(self, n))
        over_menu.addSeparator()
        over_menu.addAction("Sign…", self.sign)
        overflow.setMenu(over_menu)
        tools.addWidget(overflow)

        self.status = QLabel(self)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(nav, 1)
        top.addWidget(tools)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
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
        self.go_to(min(self.page, self.info.page_count))

    def reload_from(self, path: Path) -> None:
        """Re-read the document after an in-place edit replaced the file."""
        self.path = Path(path)
        self.page = 1
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
        self.outline.setVisible(bool(self.info.toc))

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
        if isinstance(page, int):
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

    def next_page(self) -> None:
        self.go_to(self.page + 1)

    def prev_page(self) -> None:
        self.go_to(self.page - 1)

    def _toggle_present(self, on: bool) -> None:
        """Start/stop a timer that advances pages automatically."""
        from PyQt6.QtCore import QTimer
        if on:
            self._present_timer = QTimer(self)
            self._present_timer.setInterval(3000)
            self._present_timer.timeout.connect(self._present_tick)
            self._present_timer.start()
            self.status.setText("Presenting — pages advance every 3s (Esc/again to stop)")
        else:
            if self._present_timer is not None:
                self._present_timer.stop()
                self._present_timer.deleteLater()
                self._present_timer = None
            self.status.setText("Presentation stopped.")

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
        self._render()

    def zoom_out(self) -> None:
        self.zoom = next((z for z in reversed(ZOOMS) if z < self.zoom - 1e-6), ZOOMS[0])
        self._render()

    def fit_width(self) -> None:
        if not self.info or not self.info.pages:
            return
        viewport = self.view.viewport()
        avail = (viewport.width() if viewport else self.width()) - 24
        page_width = self.info.pages[self.page - 1].width
        if page_width > 0:
            self.zoom = max(0.1, min(4.0, avail / page_width))
        self._render()

    def _on_zoom_slider(self, value: int) -> None:
        """Zoom to an arbitrary percentage via the slider."""
        self.zoom = max(0.1, min(4.0, value / 100))
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

    def _render(self) -> None:
        if not self.info:
            return
        dpi = int(72 * self.zoom)
        key = (self.page, dpi)
        cached = self._page_cache.get(key)
        if cached is None:
            try:
                data = pb.render_page(self.path, self.page, dpi=dpi,
                                      password=self.password)
            except pb.PdfError as exc:
                self.status.setText(str(exc))
                return
            cached = QPixmap()
            cached.loadFromData(data, "PNG")
            if len(self._page_cache) > 24:      # bound the cache
                self._page_cache.clear()
            self._page_cache[key] = cached
        self.page_label.setPixmap(cached)
        self.status.setText(
            f"Page {self.page} of {self.info.page_count} · {int(self.zoom * 100)}%")
        # keep the annotation overlay aligned with the page
        self.annot_layer.sync_geometry()
        self.annot_layer.refresh()
        self._sync_zoom_slider()

    # --- search ----------------------------------------------------------
    def search_next(self) -> None:
        needle = self.search_box.text().strip()
        if not needle or not self.info:
            return
        total = self.info.page_count
        for offset in range(1, total + 1):
            n = (self.page - 1 + offset) % total + 1
            try:
                text = pb.extract_text(self.path, [n], self.password)
            except pb.PdfError:
                break
            if needle.lower() in text.lower():
                self.go_to(n)
                self.status.setText(f"Found '{needle}' on page {n}")
                return
        self.status.setText(f"'{needle}' not found")

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

    def _pick_annot_color(self) -> None:
        col = QColorDialog.getColor(self.annot_color, self,
                                    "Annotation colour")
        if col.isValid():
            self.annot_color = col
            self.annot_color_btn.setStyleSheet(
                f"color: {col.name()}; font-size: 14px;")
            if self.annot_layer.mode != "off":
                self.annot_layer.color = (col.red() / 255, col.green() / 255,
                                          col.blue() / 255)
                self.annot_layer.update()

    def _on_toggle_marks(self, checked: bool) -> None:
        self.annot_layer.set_show_marks(checked)

    def apply_annotation(self, kind: str, rect, color, text: str,
                         points: list[tuple[float, float]] | None = None) -> None:
        """Write one annotation into the PDF (safe-swapped) on a worker."""
        from ..core.safe import replace_in_place
        from ..backends.pdf import Annotation

        ann = Annotation(page=self.page, kind=kind, rect=rect,
                         color=color, text=text, points=points or [])

        def write(tmp: Path) -> None:
            pb.add_annotations(self.path, tmp, [ann], self.password)

        self.status.setText(f"Adding {kind}…")
        try:
            replace_in_place(self.path, write)
        except (pb.PdfError, OSError) as exc:
            QMessageBox.critical(self, "Annotation failed", str(exc))
            return
        # Reload the document so info reflects the new annotation.
        self._page_cache.clear()
        self.annot_layer.refresh()
        self.status.setText(f"Added {kind} on page {self.page}.")

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
            pdf_backend.redact(self.path, tmp, [rect],
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
        self.view.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if getattr(self, "_placing_signature", None) is not None and \
                obj is self.view and event.type() == event.Type.MouseButtonPress:
            pos = self.page_label.mapFrom(self.view, event.position().toPoint())
            if 0 <= pos.x() <= self.page_label.width() \
                    and 0 <= pos.y() <= self.page_label.height():
                self._place_signature_at(pos)
                self.view.removeEventFilter(self)
                self._placing_signature = None
                return True
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

    def keyPressEvent(self, a0) -> None:  # noqa: N802

        if a0 is not None and a0.key() == Qt.Key.Key_Escape \
                and self.annot_layer.mode != "off":
            self.annot_layer.set_mode("off")
            self.annot_btn.setChecked(False)
            self.status.setText("Annotation mode off.")
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
        return _run_in_place(
            self, f"Deleting {spec}",
            lambda tmp, ctx: pb.delete_pages(
                self.path, tmp, spec, password=self.password))

    def extract_pages(self, pages: list[int]) -> None:
        """Pull the selected pages into a new file (keeps the original)."""
        if not pages:
            return
        spec = _ranges_label(pages)
        dest, _ = QFileDialog.getSaveFileName(
            self, "Extract pages",
            str(Path(self.path).with_suffix("")) + f"-pages.pdf",
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
        _run_in_place(
            self, "Inserting page",
            lambda tmp, ctx: pb.insert_pages(
                self.path, tmp, path, after=after, password=self.password))

    # --- lifecycle -------------------------------------------------------
    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True

    def cleanup(self) -> None:
        """Stop background rendering when the tab goes away."""
        if self._thumbs is not None:
            self._thumbs.stop()

    def closeEvent(self, a0) -> None:  # noqa: N802
        self.cleanup()
        super().closeEvent(a0)
