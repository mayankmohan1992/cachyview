"""Page organiser: a thumbnail grid for rearranging a PDF.

Nothing is written until Apply, so the whole session is a plan the user can
undo.  Each grid item carries the source page it came from, which is what lets
duplicate work: two items can point at the same original page while holding
different rotations.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout,
)

from ..backends import pdf as pb
from .thumbnails import THUMB_WIDTH, ThumbnailLoader

# Role holding the 1-based source page of an item.
SOURCE_ROLE = Qt.ItemDataRole.UserRole
# Role holding the item's absolute rotation in degrees.
ROTATION_ROLE = Qt.ItemDataRole.UserRole + 1


class PageOrganiser(QDialog):
    """Reorder, rotate, duplicate and delete pages on a thumbnail grid."""

    def __init__(self, path: str | Path, password: str | None = None,
                 parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.password = password
        self.result_path: Path | None = None

        self.setWindowTitle(f"Organise Pages — {self.path.name}")
        self.resize(880, 620)

        self.grid = QListWidget(self)
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.45)))
        self.grid.setGridSize(QSize(THUMB_WIDTH + 34, int(THUMB_WIDTH * 1.45) + 44))
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Snap)
        self.grid.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.grid.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setSpacing(6)
        self.grid.setUniformItemSizes(True)
        model = self.grid.model()
        if model is not None:
            model.rowsMoved.connect(lambda *_: self._renumber())

        self.hint = QLabel(
            "Drag to reorder · select pages then use the buttons · "
            "nothing is saved until you press Apply", self)
        self.hint.setWordWrap(True)

        buttons = QHBoxLayout()
        for label, slot in (
            ("Rotate Left", lambda: self._rotate(-90)),
            ("Rotate Right", lambda: self._rotate(90)),
            ("Duplicate", self._duplicate),
            ("Delete", self._delete),
            ("Select All", self.grid.selectAll),
            ("Reset", self._reset),
        ):
            button = QPushButton(label, self)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel, self)
        save_as = self.box.button(QDialogButtonBox.StandardButton.Save)
        if save_as is not None:
            save_as.setText("Save As…")
        self.box.accepted.connect(self._apply)
        self.box.rejected.connect(self.reject)

        # Overwrite-original button lives on the left with a clear warning.
        self.overwrite_btn = QPushButton("Overwrite original", self)
        self.overwrite_btn.setToolTip(
            "Replace the file on disk. The previous version is kept as "
            f"{self.path.name}~ until you quit.")
        self.box.addButton(self.overwrite_btn,
                           QDialogButtonBox.ButtonRole.ActionRole)
        self.overwrite_btn.clicked.connect(self._overwrite)

        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addLayout(buttons)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.box)

        self._loader: ThumbnailLoader | None = None
        self._originals: dict[int, QPixmap] = {}
        self._load()

    # --- population -------------------------------------------------------
    def _load(self) -> None:
        try:
            info = pb.info(self.path, self.password)
        except pb.PdfError as exc:
            QMessageBox.warning(self, "Cannot open", str(exc))
            self.page_count = 0
            self._start_rotations = []
            return

        self.page_count = info.page_count
        self._start_rotations = [p.rotation for p in info.pages]
        placeholder = QPixmap(THUMB_WIDTH, int(THUMB_WIDTH * 1.4))
        placeholder.fill(self.palette().alternateBase().color())

        for n in range(1, self.page_count + 1):
            self._add_item(n, info.pages[n - 1].rotation, placeholder)

        self._loader = ThumbnailLoader(self.path, self.password, self)
        self._loader.ready.connect(self._on_thumb)
        self._loader.request(list(range(1, self.page_count + 1)))

    def _add_item(self, source: int, rotation: int, pixmap: QPixmap,
                  at: int | None = None) -> QListWidgetItem:
        item = QListWidgetItem(QIcon(pixmap), "")
        item.setData(SOURCE_ROLE, source)
        item.setData(ROTATION_ROLE, rotation % 360)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
        if at is None:
            self.grid.addItem(item)
        else:
            self.grid.insertItem(at, item)
        return item

    def _on_thumb(self, page: int, pixmap: QPixmap) -> None:
        self._originals[page] = pixmap
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item is not None and item.data(SOURCE_ROLE) == page:
                self._paint(item)
        self._renumber()

    def _paint(self, item: QListWidgetItem) -> None:
        """Show the item's thumbnail at its current rotation."""
        base = self._originals.get(item.data(SOURCE_ROLE))
        if base is None:
            return
        angle = item.data(ROTATION_ROLE) or 0
        pixmap = (base.transformed(QTransform().rotate(angle),
                                   Qt.TransformationMode.SmoothTransformation)
                  if angle else base)
        item.setIcon(QIcon(pixmap))

    def _renumber(self) -> None:
        """Label each slot with its new position and where it came from."""
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item is None:
                continue
            source = item.data(SOURCE_ROLE)
            angle = item.data(ROTATION_ROLE) or 0
            label = f"{row + 1}"
            if source != row + 1:
                label += f"  (was {source})"
            if angle:
                label += f"  {angle}°"
            item.setText(label)

    # --- editing ----------------------------------------------------------
    def _selected(self) -> list[QListWidgetItem]:
        return self.grid.selectedItems()

    def _rotate(self, delta: int) -> None:
        items = self._selected()
        if not items:
            QMessageBox.information(self, "Rotate", "Select one or more pages first.")
            return
        for item in items:
            item.setData(ROTATION_ROLE,
                         ((item.data(ROTATION_ROLE) or 0) + delta) % 360)
            self._paint(item)
        self._renumber()

    def _duplicate(self) -> None:
        items = self._selected()
        if not items:
            QMessageBox.information(self, "Duplicate", "Select a page first.")
            return
        for item in sorted(items, key=self.grid.row, reverse=True):
            row = self.grid.row(item)
            copy = self._add_item(item.data(SOURCE_ROLE),
                                  item.data(ROTATION_ROLE) or 0,
                                  QPixmap(), at=row + 1)
            self._paint(copy)
        self._renumber()

    def _delete(self) -> None:
        items = self._selected()
        if not items:
            QMessageBox.information(self, "Delete", "Select a page first.")
            return
        if self.grid.count() - len(items) < 1:
            QMessageBox.warning(self, "Delete",
                                "A document must keep at least one page.")
            return
        for item in sorted(items, key=self.grid.row, reverse=True):
            self.grid.takeItem(self.grid.row(item))
        self._renumber()

    def _reset(self) -> None:
        self.grid.clear()
        self._load()

    # --- result -----------------------------------------------------------
    def layout_plan(self) -> list[tuple[int, int]]:
        """The current grid as ``(source_page, rotation)`` pairs."""
        plan = []
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item is not None:
                plan.append((int(item.data(SOURCE_ROLE)),
                             int(item.data(ROTATION_ROLE) or 0)))
        return plan

    def is_unchanged(self) -> bool:
        """True when the grid still matches the document as opened."""
        return self.layout_plan() == [
            (n, self._start_rotations[n - 1] % 360)
            for n in range(1, self.page_count + 1)]

    def _apply(self) -> None:
        plan = self.layout_plan()
        if not plan:
            QMessageBox.warning(self, "Organise Pages",
                                "A document must keep at least one page.")
            return

        from .pdf_tools import output_path
        from PyQt6.QtWidgets import QFileDialog

        suggested = output_path(self.path, "organised")
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save organised PDF", str(suggested), "PDF files (*.pdf)")
        if not chosen:
            return
        self._write_to(Path(chosen), ask_overwrite=False)

    def _overwrite(self) -> None:
        """Replace the original file, keeping a ``name~`` recovery copy."""
        plan = self.layout_plan()
        if not plan:
            QMessageBox.warning(self, "Organise Pages",
                                "A document must keep at least one page.")
            return
        reply = QMessageBox.question(
            self, "Overwrite original",
            f"This will replace:\n  {self.path}\n\nThe current file is moved to "
            f"{self.path.name}~ first, so it can be recovered until you quit. "
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._write_to(self.path, ask_overwrite=False)

    def _write_to(self, dest: Path, *, ask_overwrite: bool) -> None:
        from ..core.safe import replace_in_place

        plan = self.layout_plan()
        if not plan:
            QMessageBox.warning(self, "Organise Pages",
                                "A document must keep at least one page.")
            return
        if ask_overwrite and dest.exists() and dest != self.path:
            reply = QMessageBox.question(
                self, "Overwrite?", f"{dest.name} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        def write(tmp: Path) -> None:
            pb.apply_layout(self.path, tmp, plan, self.password)

        try:
            self.result_path = replace_in_place(dest, write)
        except (pb.PdfError, OSError) as exc:
            QMessageBox.critical(self, "Organise Pages", str(exc))
            return
        self.accept()

    def cleanup(self) -> None:
        if self._loader is not None:
            self._loader.stop()

    def done(self, a0: int) -> None:
        self.cleanup()
        super().done(a0)
