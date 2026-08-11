"""PDF viewer tab: continuous page view, thumbnails, outline, search and tools."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QColorDialog, QComboBox, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMenu, QMessageBox, QPushButton, QScrollArea,
                             QSplitter, QToolBar, QToolButton, QVBoxLayout,
                             QWidget)

from ..backends import pdf as pb
from ..core.jobs import submit
from .annotation_layer import AnnotationLayer
from .thumbnails import THUMB_WIDTH, ThumbnailLoader

ZOOMS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


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
        side.addWidget(self.thumbs)
        side.addWidget(self.outline)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(side)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)

        # --- toolbars
        nav = QToolBar(self)
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
        nav.addAction("+", self.zoom_in)
        nav.addAction("Fit", self.fit_width)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search text…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.returnPressed.connect(self.search_next)
        nav.addSeparator()
        nav.addWidget(self.search_box)

        tools = QToolBar(self)
        self.tool_box = QComboBox(self)
        self.tool_box.addItems([
            "Tools…", "Organise pages…", "Rotate pages", "Delete pages",
            "Extract pages",
            "Split", "Merge with…", "Compress", "Flatten", "Protect", "Unlock",
            "Watermark", "Page numbers", "To images", "To text", "OCR",
            "Repair", "Metadata",
        ])
        self.tool_box.activated.connect(self._on_tool)
        tools.addWidget(self.tool_box)

        # --- annotation controls
        self.annot_btn = QToolButton(self)
        self.annot_btn.setText("Annotate")
        self.annot_btn.setCheckable(True)
        self.annot_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.annot_menu = QMenu(self)
        self.annot_action = QActionGroup(self)
        self.annot_action.setExclusive(True)
        for key, label in (("highlight", "Highlight"),
                            ("underline", "Underline"),
                            ("note", "Note")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(key)
            self.annot_action.addAction(act)
            self.annot_menu.addAction(act)
        self.annot_btn.setMenu(self.annot_menu)
        self.annot_action.triggered.connect(self._on_annotate_mode)
        self.annot_color = QColor(255, 217, 51)
        self.annot_color_btn = QPushButton("▮", self)
        self.annot_color_btn.setToolTip("Annotation colour")
        self.annot_color_btn.clicked.connect(self._pick_annot_color)
        self.show_marks_btn = QToolButton(self)
        self.show_marks_btn.setText("Marks")
        self.show_marks_btn.setCheckable(True)
        self.show_marks_btn.setChecked(True)
        self.show_marks_btn.toggled.connect(self._on_toggle_marks)
        tools.addWidget(self.annot_btn)
        tools.addWidget(self.annot_color_btn)
        tools.addWidget(self.show_marks_btn)
        tools.addSeparator()
        self.present_btn = QPushButton("▶ Present", self)
        self.present_btn.setToolTip(
            "Auto-advance pages on a timer (presentation / hands-free reading)")
        self.present_btn.setCheckable(True)
        self.present_btn.toggled.connect(self._toggle_present)
        tools.addWidget(self.present_btn)
        self._present_timer = None

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
        verb = {"highlight": "drag to highlight",
                "underline": "drag to underline",
                "note": "drag, then type a note"}[mode]
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

    def apply_annotation(self, kind: str, rect, color, text: str) -> None:
        """Write one annotation into the PDF (safe-swapped) on a worker."""
        from ..core.safe import replace_in_place
        from ..backends.pdf import Annotation

        ann = Annotation(page=self.page, kind=kind, rect=rect,
                         color=color, text=text)

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
    def _on_tool(self, index: int) -> None:
        name = self.tool_box.itemText(index)
        self.tool_box.setCurrentIndex(0)
        if index == 0:
            return
        from .pdf_tools import run_tool
        run_tool(self, name)

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
