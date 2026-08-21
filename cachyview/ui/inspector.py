"""Shared file-info sidebar used by every document kind."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QLabel, QScrollArea, QWidget


class Inspector(QScrollArea):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(220)
        self.setMaximumWidth(340)
        self._body = QWidget(self)
        self._form = QFormLayout(self._body)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.setWidget(self._body)
        self.show_message("Open a file to inspect it.")

    def show_message(self, text: str) -> None:
        self._clear()
        self._form.addRow(QLabel(text, self._body))

    def show_pairs(self, pairs: list[tuple[str, str]]) -> None:
        self._clear()
        for key, value in pairs:
            val = QLabel(value or "—", self._body)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
            self._form.addRow(key, val)

    def inspect_path(self, path: Path, extra: list[tuple[str, str]] | None = None) -> None:
        try:
            st = path.stat()
            size = st.st_size
        except OSError:
            self.show_message("File is gone.")
            return
        human = _human(size)
        from ..core.mime import detect_kind, mime_type
        rows = [
            ("Name", path.name),
            ("Kind", detect_kind(path).value),
            ("MIME", mime_type(path)),
            ("Size", f"{human} ({size:,} bytes)"),
            ("Path", str(path)),
        ]
        if extra:
            rows.extend(extra)
        self.show_pairs(rows)

    def _clear(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
