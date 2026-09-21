"""Signature capture dialog.

Lets the user draw a signature with the mouse / trackpad on a transparent
canvas, then saves it as a PNG so it can be stamped onto a PDF page.  Up to a
few signatures are remembered for reuse, matching how macOS Preview keeps a
small library of saved signatures.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)


def _signature_dir() -> Path:
    base = Path.home() / ".config" / "cachyview" / "signatures"
    base.mkdir(parents=True, exist_ok=True)
    return base


class _Pad(QWidget):
    """A transparent drawing surface that records a freehand stroke."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(420, 160)
        self.image = QImage(self.size(), QImage.Format.Format_ARGB32)
        self.image.fill(Qt.GlobalColor.transparent)
        self._drawing = False
        self._last: QPoint | None = None
        self._stroke: list[QPoint] = []

    def clear(self) -> None:
        self.image.fill(Qt.GlobalColor.transparent)
        self._stroke = []
        self.update()

    def png(self, path: Path) -> None:
        self.image.save(str(path), "PNG")

    def mousePressEvent(self, a0) -> None:
        if a0 is not None:
            self._drawing = True
            self._last = a0.position().toPoint()
            self._stroke = [self._last]

    def mouseMoveEvent(self, a0) -> None:
        if a0 is None or not self._drawing or self._last is None:
            return
        pos = a0.position().toPoint()
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(20, 20, 20), 2.5,
                             Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                             Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(self._last, pos)
        painter.end()
        self._last = pos
        self._stroke.append(pos)
        self.update()

    def mouseReleaseEvent(self, a0) -> None:
        self._drawing = False

    def has_ink(self) -> bool:
        return len(self._stroke) >= 2

    def paintEvent(self, a0) -> None:
        painter = QPainter(self)
        painter.drawImage(0, 0, self.image)
        painter.setPen(QPen(QColor(200, 200, 200), 1,
                            Qt.PenStyle.DashLine))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


class SignatureDialog(QDialog):
    """Draw a signature and return its saved PNG path via ``result_path``."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sign")
        self.result_path: Path | None = None

        self.pad = _Pad(self)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.pad.clear)
        save_btn = QPushButton("Save & place")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._accept)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Sign with the mouse or trackpad:"))
        layout.addWidget(self.pad)
        row = QHBoxLayout()
        row.addWidget(clear_btn)
        row.addStretch(1)
        row.addWidget(save_btn)
        layout.addLayout(row)

    def _accept(self) -> None:
        if not self.pad.has_ink():
            return
        path = _signature_dir() / f"sig{len(list(_signature_dir().glob('*.png')))+1:02d}.png"
        self.pad.png(path)
        self.result_path = path
        self.accept()
