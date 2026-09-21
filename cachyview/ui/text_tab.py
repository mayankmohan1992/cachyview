"""Text/code viewer-editor tab with line numbers, find, and pretty-print."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFontDatabase, QPainter, QTextCursor,
                         QTextFormat)
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                             QPushButton, QSplitter, QStackedWidget, QTableWidget,
                             QTableWidgetItem, QTextBrowser, QTextEdit, QToolBar,
                             QVBoxLayout, QWidget)

from ..backends import text as text_backend


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
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

    def resizeEvent(self, event) -> None:
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
        from .highlight import CodeHighlighter, language_for
        self._highlighter = CodeHighlighter(
            self.editor.document(), language_for(str(path)))

        self.find_input = QLineEdit(self)
        self.find_input.setPlaceholderText("Find…")
        self.find_input.setClearButtonEnabled(True)
        self.find_input.returnPressed.connect(self.find_next)
        self.replace_input = QLineEdit(self)
        self.replace_input.setPlaceholderText("Replace…")
        self.case = QCheckBox("Aa", self)
        self.regex = QCheckBox(".*", self)
        find_row = QHBoxLayout()
        find_row.addWidget(self.find_input)
        find_row.addWidget(self.replace_input)
        find_row.addWidget(self.case)
        find_row.addWidget(self.regex)
        find_go = QPushButton("Next", self)
        find_go.clicked.connect(self.find_next)
        rep = QPushButton("Replace", self)
        rep.clicked.connect(self.replace_one)
        rep_all = QPushButton("All", self)
        rep_all.clicked.connect(self.replace_all)
        find_row.addWidget(find_go)
        find_row.addWidget(rep)
        find_row.addWidget(rep_all)
        self.find_bar = QWidget(self)
        self.find_bar.setLayout(find_row)
        self.find_bar.hide()

        self.preview = QTextBrowser(self)
        self.preview.hide()
        self.table = QTableWidget(self)
        split = QSplitter(self)
        split.addWidget(self.editor)
        split.addWidget(self.preview)
        self._md_split = split
        self.stack = QStackedWidget(self)
        self.stack.addWidget(split)
        self.stack.addWidget(self.table)

        from .icons import add_action, style_bar

        bar = QToolBar(self)
        style_bar(bar)
        add_action(bar, "document-save", "Save", self.save,
                   tooltip="Save (Ctrl+S)")
        add_action(bar, "edit-find", "Find", self.toggle_find,
                   tooltip="Find (Ctrl+F)")
        add_action(bar, "go-jump", "Go to line", self.goto_line)
        add_action(bar, "format-justify-left", "Wrap", self.toggle_wrap)
        add_action(bar, "format-indent-more", "Format JSON",
                   lambda: self.reformat("json"))
        add_action(bar, "edit-compress", "Minify JSON",
                   lambda: self.reformat("json", minify=True))
        add_action(bar, "text-xml", "Format XML", lambda: self.reformat("xml"))
        add_action(bar, "format-text-strikethrough", "Format YAML",
                   lambda: self.reformat("yaml"))
        add_action(bar, "tools-check-spelling", "Validate", self.validate_doc)
        add_action(bar, "view-preview", "Markdown preview", self.toggle_markdown)
        add_action(bar, "view-form-table", "CSV table", self.toggle_csv)
        self.enc = QComboBox(self)
        self.enc.addItems(["utf-8", "utf-8-sig", "utf-16", "latin-1", "cp1252"])
        self.enc.setCurrentText(self.doc.encoding.split()[0])
        self.nl = QComboBox(self)
        self.nl.addItems(["LF", "CRLF", "CR"])
        self.nl.setCurrentText({"\n": "LF", "\r\n": "CRLF", "\r": "CR"}.get(
            self.doc.newline, "LF"))
        bar.addWidget(QLabel(" Enc "))
        bar.addWidget(self.enc)
        bar.addWidget(self.nl)
        self.status = QLabel(self)
        self.editor.cursorPositionChanged.connect(self._status)
        self.editor.textChanged.connect(self._on_text)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status)

        if self.doc.truncated:
            self.editor.setReadOnly(True)
            bar.addWidget(QPushButton("Large file: showing first 8 MB (read-only)"))
        self._status()
        if self.path.suffix.lower() in {".md", ".markdown"}:
            self.toggle_markdown()

    def _on_text(self) -> None:
        if self.preview.isVisible():
            self.preview.setMarkdown(self.editor.toPlainText())

    def _status(self) -> None:
        cur = self.editor.textCursor()
        self.status.setText(
            f"Ln {cur.blockNumber() + 1}, Col {cur.columnNumber() + 1} · "
            f"{self.doc.encoding} · {self.nl.currentText()}")

    def toggle_find(self) -> None:
        if self.find_bar.isVisible():
            self.find_bar.hide()
            self.editor.setFocus()
        else:
            self.find_bar.show()
            self.find_input.setFocus()
            self.find_input.selectAll()

    def _flags(self):
        from PyQt6.QtGui import QTextDocument
        flags = QTextDocument.FindFlag(0)
        if self.case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def find_next(self) -> None:
        needle = self.find_input.text()
        if not needle:
            return
        if not self.editor.find(needle, self._flags()):
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            self.editor.find(needle, self._flags())

    def replace_one(self) -> None:
        if self.editor.textCursor().hasSelection():
            self.editor.textCursor().insertText(self.replace_input.text())
        self.find_next()

    def replace_all(self) -> None:
        needle, repl = self.find_input.text(), self.replace_input.text()
        if not needle:
            return
        text = self.editor.toPlainText()
        if self.regex.isChecked():
            import re
            flags = 0 if self.case.isChecked() else re.IGNORECASE
            text = re.sub(needle, repl, text, flags=flags)
        else:
            if not self.case.isChecked():
                # simple case-insensitive replace
                import re
                text = re.sub(re.escape(needle), repl, text, flags=re.IGNORECASE)
            else:
                text = text.replace(needle, repl)
        self.editor.setPlainText(text)

    def goto_line(self) -> None:
        n, ok = QInputDialog.getInt(self, "Go to line", "Line:", 1, 1,
                                    max(1, self.editor.blockCount()))
        if ok:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down,
                                QTextCursor.MoveMode.MoveAnchor, n - 1)
            self.editor.setTextCursor(cursor)

    def toggle_wrap(self) -> None:
        mode = self.editor.lineWrapMode()
        self.editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
            if mode == QPlainTextEdit.LineWrapMode.WidgetWidth
            else QPlainTextEdit.LineWrapMode.WidgetWidth)

    def toggle_markdown(self) -> None:
        if self.preview.isVisible():
            self.preview.hide()
            return
        self.preview.setMarkdown(self.editor.toPlainText())
        self.preview.show()
        self.stack.setCurrentWidget(self._md_split)

    def toggle_csv(self) -> None:
        if self.stack.currentWidget() is self.table:
            self.stack.setCurrentWidget(self.editor)
            return
        header, rows = text_backend.csv_rows(self.editor.toPlainText())
        self.table.clear()
        self.table.setColumnCount(len(header) or 1)
        self.table.setHorizontalHeaderLabels(header or ["col"])
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                self.table.setItem(i, j, QTableWidgetItem(cell))
        self.stack.setCurrentWidget(self.table)

    def reformat(self, fmt: str, minify: bool = False) -> None:
        try:
            pretty = (text_backend.minify(self.editor.toPlainText(), fmt)
                      if minify else text_backend.pretty_print(
                          self.editor.toPlainText(), fmt))
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot format", str(exc))
            return
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(pretty)
        cursor.endEditBlock()

    def validate_doc(self) -> None:
        """Check JSON/XML/TOML/YAML well-formedness for the current text."""
        fmt = {".json": "json", ".xml": "xml", ".toml": "toml",
               ".yaml": "yaml", ".yml": "yaml"}.get(self.path.suffix.lower())
        if not fmt:
            QMessageBox.information(
                self, "Validate", "No validator for this file type.")
            return
        try:
            text_backend.validate(self.editor.toPlainText(), fmt)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid", f"{fmt.upper()}: {exc}")
            return
        QMessageBox.information(self, "Valid", f"{fmt.upper()} is well-formed.")

    def is_modified(self) -> bool:
        return self.editor.document().isModified()

    def save(self) -> bool:
        if self.doc.truncated:
            QMessageBox.warning(self, "Read-only",
                                "This file was truncated for display and cannot be saved.")
            return False
        nl = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}[self.nl.currentText()]
        try:
            text_backend.save(self.doc, self.editor.toPlainText(),
                              encoding=self.enc.currentText(), newline=nl)
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self.editor.document().setModified(False)
        return True

    def print_file(self) -> None:
        from PyQt6.QtGui import QTextDocument
        from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter()
        if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
            return
        doc = QTextDocument()
        doc.setPlainText(self.editor.toPlainText())
        doc.print(printer)
