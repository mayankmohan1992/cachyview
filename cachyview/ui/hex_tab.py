"""Hex viewer for binary files and oversized text."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QToolBar, QVBoxLayout,
                             QWidget)

from ..backends import text as text_backend

CHUNK = 256 * 1024


class HexTab(QWidget):
    modified_changed = pyqtSignal(bool)

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = Path(path)
        self._offset = 0
        self._size = self.path.stat().st_size

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.view.setFont(font)

        from .icons import add_action, style_bar

        bar = QToolBar(self)
        style_bar(bar)
        add_action(bar, "edit-copy", "Copy", self._copy)
        self.jump = QLineEdit(self)
        self.jump.setPlaceholderText("Offset (hex or decimal)")
        self.jump.returnPressed.connect(self._jump)
        bar.addWidget(self.jump)
        more = QPushButton("Load more", self)
        more.clicked.connect(self._more)
        bar.addWidget(more)
        self.status = QLabel(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(bar)
        layout.addWidget(self.view)
        layout.addWidget(self.status)
        self._load_chunk(0)

    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True

    def _load_chunk(self, offset: int, append: bool = False) -> None:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(offset)
                data = fh.read(CHUNK)
        except OSError as exc:
            QMessageBox.warning(self, "Cannot read", str(exc))
            return
        dump = text_backend.hex_dump(data, offset=offset)
        if append:
            self.view.appendPlainText(dump)
        else:
            self.view.setPlainText(dump)
        self._offset = offset + len(data)
        self.status.setText(
            f"{self.path.name} · {self._size:,} bytes · showing 0–{self._offset:,}")

    def _more(self) -> None:
        if self._offset >= self._size:
            self.status.setText("End of file.")
            return
        self._load_chunk(self._offset, append=True)

    def _jump(self) -> None:
        raw = self.jump.text().strip().lower()
        try:
            off = int(raw, 16) if raw.startswith("0x") or all(
                c in "0123456789abcdef" for c in raw) and not raw.isdigit() else int(raw)
        except ValueError:
            return
        self._load_chunk(max(0, off))

    def _copy(self) -> None:
        self.view.copy()
