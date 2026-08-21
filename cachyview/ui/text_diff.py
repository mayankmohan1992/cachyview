"""Side-by-side text diff dialog."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)

from ..backends import text as text_backend


class TextDiffDialog(QDialog):
    def __init__(self, parent: QWidget | None = None,
                 left: Path | None = None, right: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Compare text files")
        self.resize(900, 600)
        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        pick_a = QPushButton("Left…", self)
        pick_b = QPushButton("Right…", self)
        pick_a.clicked.connect(lambda: self._pick(True))
        pick_b.clicked.connect(lambda: self._pick(False))
        row = QHBoxLayout()
        row.addWidget(pick_a)
        row.addWidget(pick_b)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.view)
        self._a = left
        self._b = right
        if left and right:
            self._run()

    def _pick(self, left: bool) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose file")
        if not path:
            return
        if left:
            self._a = Path(path)
        else:
            self._b = Path(path)
        if self._a and self._b:
            self._run()

    def _run(self) -> None:
        if not (self._a and self._b):
            return
        a = text_backend.load(self._a).text
        b = text_backend.load(self._b).text
        self.view.setPlainText(text_backend.unified_diff(
            a, b, self._a.name, self._b.name) or "(files are identical)")
