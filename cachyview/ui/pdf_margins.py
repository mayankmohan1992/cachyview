"""Small parameter dialogs for page-level PDF tools.

Kept tiny: each returns its settings via a ``chosen`` property so the caller
does not have to know the widget layout.  (Named ``chosen`` rather than
``result`` to avoid clashing with ``QDialog.result``.)
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QSpinBox, QWidget,
)

from ..backends.pdf import PAGE_SIZES


class CropResizeDialog(QDialog):
    """Margins to trim (points) and/or a target page size."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Crop & Resize")
        margin = QSpinBox(self)
        margin.setRange(0, 200)
        margin.setSuffix(" pt")
        self._margin = margin

        size = QComboBox(self)
        size.addItems(["(keep size)"] + list(PAGE_SIZES))
        self._size = size

        form = QFormLayout(self)
        form.addRow("Trim margin (all sides):", margin)
        form.addRow("Resize page to:", size)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        form.addRow(box)
        self.chosen: tuple = (None, None)

    def _accept(self) -> None:
        m = self._margin.value()
        margins = (m, m, m, m) if m else None
        size = self._size.currentText()
        self.chosen = (margins, None if size == "(keep size)" else size)
        self.accept()


class HeaderFooterDialog(QDialog):
    """Header / footer text and optional page numbers."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Headers & Footers")
        self._header = QLineEdit(self)
        self._footer = QLineEdit(self)
        self._numbers = QCheckBox("Add page numbers", self)
        size = QSpinBox(self)
        size.setRange(6, 24)
        size.setValue(10)
        self._size = size

        form = QFormLayout(self)
        form.addRow("Header text:", self._header)
        form.addRow("Footer text:", self._footer)
        form.addRow(self._numbers)
        form.addRow("Font size:", size)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        form.addRow(box)
        self.chosen: tuple = ("", "", False, 10)

    def _accept(self) -> None:
        self.chosen = (self._header.text().strip(),
                       self._footer.text().strip(),
                       self._numbers.isChecked(),
                       self._size.value())
        self.accept()
