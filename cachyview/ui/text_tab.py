"""Text/code viewer-editor tab with line numbers, find, and pretty-print."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QTextCursor,
                         QTextFormat)
from PyQt6.QtWidgets import (QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                             QTextEdit, QToolBar, QVBoxLayout, QWidget)

from ..backends import text as text_backend


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with a gutter and current-line highlight."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(max(10, font.pointSize()))
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self._gutter = _LineNumberArea(self)
        self.blockCountChanged.connect(lambda _: self._update_margins())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_margins()
        self._highlight_current_line()

    def line_number_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(),
                                       self.line_number_width(), cr.height()))

    def _highlight_current_line(self) -> None:
        sel = QTextEdit.ExtraSelection()
        colour = self.palette().alternateBase().color()
        sel.format.setBackground(colour)
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), self.palette().window().color())
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        dim = self.palette().text().color()
        dim.setAlpha(110)
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(self.palette().text().color()
                               if number == current else QColor(dim))
                painter.drawText(0, top, self._gutter.width() - 6,
                                 self.fontMetrics().height(),
                                 int(Qt.AlignmentFlag.AlignRight), str(number + 1))
            block = block.next()
            number += 1
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())


class TextTab(QWidget):
    """A full text-document tab: toolbar + find bar + editor."""

    modified_changed = pyqtSignal(bool)

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.doc = text_backend.load(path)
        self.path = Path(path)

        self.editor = CodeEditor(self)
        self.editor.setPlainText(self.doc.text)
        self.editor.document().setModified(False)
        self.editor.document().modificationChanged.connect(self.modified_changed)

        self.find_input = QLineEdit(self)
        self.find_input.setPlaceholderText("Find… (Enter for next)")
        self.find_input.setClearButtonEnabled(True)
        self.find_input.returnPressed.connect(self.find_next)
        self.find_input.hide()

        bar = QToolBar(self)
        bar.addAction("Save", self.save).setShortcut("Ctrl+S")
        bar.addAction("Find", self.toggle_find).setShortcut("Ctrl+F")
        bar.addAction("Wrap", self.toggle_wrap)
        bar.addAction("Format JSON", lambda: self.reformat("json"))
        bar.addAction("Format XML", lambda: self.reformat("xml"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.find_input)
        layout.addWidget(self.editor)

        if self.doc.truncated:
            self.editor.setReadOnly(True)
            bar.addWidget(QPushButton("Large file: showing first 8 MB (read-only)"))

    # --- actions -------------------------------------------------------
    def toggle_find(self) -> None:
        if self.find_input.isVisible():
            self.find_input.hide()
            self.editor.setFocus()
        else:
            self.find_input.show()
            self.find_input.setFocus()
            self.find_input.selectAll()

    def find_next(self) -> None:
        needle = self.find_input.text()
        if not needle:
            return
        if not self.editor.find(needle):
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            self.editor.find(needle)

    def toggle_wrap(self) -> None:
        mode = self.editor.lineWrapMode()
        self.editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
            if mode == QPlainTextEdit.LineWrapMode.WidgetWidth
            else QPlainTextEdit.LineWrapMode.WidgetWidth)

    def reformat(self, fmt: str) -> None:
        try:
            pretty = text_backend.pretty_print(self.editor.toPlainText(), fmt)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot format", str(exc))
            return
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(pretty)
        cursor.endEditBlock()

    def is_modified(self) -> bool:
        return self.editor.document().isModified()

    def save(self) -> bool:
        if self.doc.truncated:
            QMessageBox.warning(self, "Read-only",
                                "This file was truncated for display and cannot be saved.")
            return False
        try:
            text_backend.save(self.doc, self.editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self.editor.document().setModified(False)
        return True
