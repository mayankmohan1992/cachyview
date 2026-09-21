"""SVG viewer/editor.

SVG is a vector format Pillow cannot rasterise, so it gets its own tab: a
QtSvg preview plus an editable source pane with a live preview.  A malformed
document sets an error state instead of raising during construction.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import (QPlainTextEdit, QScrollArea, QSplitter,
                             QVBoxLayout, QWidget)

from .highlight import CodeHighlighter, language_for


class SvgTab(QWidget):
    """Render an SVG and allow editing its source in place."""

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = Path(path)
        self.error = ""
        self._saved_text = ""

        try:
            self._saved_text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.error = str(exc)

        self.preview = QSvgWidget()
        self.preview.setMinimumSize(200, 200)
        scroll = QScrollArea(self)
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(True)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlainText(self._saved_text)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._highlighter = CodeHighlighter(self.editor.document(),
                                            language_for(str(self.path)))
        self.editor.textChanged.connect(self._live_preview)

        self.split = QSplitter(Qt.Orientation.Horizontal, self)
        self.split.addWidget(scroll)
        self.split.addWidget(self.editor)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.split, 1)

        self._render(self._saved_text)

    # --- rendering --------------------------------------------------------
    def _render(self, text: str) -> None:
        data = text.encode("utf-8")
        self.preview.load(data)
        if not self.preview.renderer().isValid() and text.strip():
            self.error = "Invalid SVG source."
        else:
            self.error = ""

    def _live_preview(self) -> None:
        self._render(self.editor.toPlainText())

    # --- document protocol (used by the main window) ----------------------
    def is_modified(self) -> bool:
        return self.editor.toPlainText() != self._saved_text

    def save(self) -> bool:
        if not self.is_modified():
            return True
        text = self.editor.toPlainText()
        try:
            self.path.write_text(text, encoding="utf-8")
        except OSError as exc:
            self.error = str(exc)
            return False
        self._saved_text = text
        return True
