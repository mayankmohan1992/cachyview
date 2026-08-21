"""Images → PDF with a visual drag-and-drop ordering grid.

Reuses the icon-grid + InternalMove drag pattern from PageOrganiser, but the
items are image files the user picks (not PDF pages).  The grid order is the
page order in the output PDF, so arranging is the whole point.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QListView,
)

from ..backends import image as ib
from .pdf_tools import output_path

# Role holding the source image path of an item.
PATH_ROLE = Qt.ItemDataRole.UserRole
THUMB = 120


class ImageToPdfDialog(QDialog):
    """Arrange images by dragging, then combine them into a PDF."""

    def __init__(self, parent=None, initial: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Images to PDF")
        self.resize(820, 600)

        self.grid = QListWidget(self)
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 26, THUMB + 40))
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Snap)
        self.grid.setDragDropMode(QListView.DragDropMode.InternalMove)
        self.grid.setSelectionMode(
            QListView.SelectionMode.ExtendedSelection)
        self.grid.setSpacing(6)
        model = self.grid.model()
        if model is not None:
            model.rowsMoved.connect(lambda *_: self._renumber())

        self.hint = QPushButton(
            "Drag thumbnails to reorder · Add / Remove / Rotate as needed", self)
        self.hint.setFlat(True)
        self.hint.setEnabled(False)

        buttons = QHBoxLayout()
        for label, slot in (
            ("Add images…", self._add),
            ("Remove", self._remove),
            ("Rotate", lambda: self._rotate(90)),
            ("Move up", lambda: self._shift(-1)),
            ("Move down", lambda: self._shift(1)),
            ("Clear", self.grid.clear),
        ):
            btn = QPushButton(label, self)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch(1)

        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        self.box.button(QDialogButtonBox.StandardButton.Ok).setText("Create PDF")
        self.box.accepted.connect(self._create)
        self.box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addLayout(buttons)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.box)

        if initial:
            self._add_files([Path(p) for p in initial])

    # --- population -------------------------------------------------------
    def _add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select images",
            "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif)")
        if files:
            self._add_files([Path(f) for f in files])

    def _add_files(self, paths: list[Path]) -> None:
        for p in paths:
            if not p.is_file():
                continue
            item = QListWidgetItem("", self.grid)
            item.setData(PATH_ROLE, str(p))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._paint(item)
        self._renumber()

    def _paint(self, item: QListWidgetItem) -> None:
        p = Path(item.data(PATH_ROLE))
        pm = QPixmap(str(p))
        if pm.isNull():
            pm = QPixmap(THUMB, THUMB)
            pm.fill(self.palette().alternateBase().color())
        else:
            pm = pm.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        item.setIcon(QIcon(pm))

    def _renumber(self) -> None:
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item is not None:
                item.setText(str(row + 1))

    # --- editing ---------------------------------------------------------
    def _selected(self) -> list[QListWidgetItem]:
        return self.grid.selectedItems()

    def _remove(self) -> None:
        for item in sorted(self._selected(), key=self.grid.row, reverse=True):
            self.grid.takeItem(self.grid.row(item))
        self._renumber()

    def _rotate(self, angle: int) -> None:
        for item in self._selected() or [self.grid.item(self.grid.count() - 1)]:
            p = Path(item.data(PATH_ROLE))
            rotated = ib.lossless_rotate(p, p, angle=angle)
            item.setData(PATH_ROLE, str(rotated))
            self._paint(item)

    def _shift(self, step: int) -> None:
        items = self._selected()
        if not items:
            return
        row = self.grid.row(items[0]) + step
        row = max(0, min(self.grid.count() - 1, row))
        self.grid.takeItem(self.grid.row(items[0]))
        self.grid.insertItem(row, items[0])
        self._renumber()

    # --- result -----------------------------------------------------------
    def ordered_paths(self) -> list[Path]:
        return [Path(self.grid.item(r).data(PATH_ROLE))
                for r in range(self.grid.count())]

    def _create(self) -> None:
        paths = self.ordered_paths()
        if len(paths) < 1:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", str(output_path(Path("images"), "combined")),
            "PDF files (*.pdf)")
        if not dest:
            return
        try:
            ib.images_to_pdf(paths, dest)
        except ib.ImageError as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Images to PDF", str(exc))
            return
        self.accept()
