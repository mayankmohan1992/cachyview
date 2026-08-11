"""Side-by-side PDF comparison (pixel diff) dialog."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QPushButton,
                             QVBoxLayout)

from ..backends import pdf as pb


class CompareDialog(QDialog):
    def __init__(self, parent=None, initial_a: str | None = None,
                 initial_b: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Compare PDFs")
        self.a: str | None = initial_a
        self.b: str | None = initial_b

        self.a_label = QLabel(self.a or "(not set)")
        self.b_label = QLabel(self.b or "(not set)")
        pick_a = QPushButton("Choose A…")
        pick_b = QPushButton("Choose B…")
        compare = QPushButton("Compare")
        self.status = QLabel("")

        self.list = QListWidget(self)
        self.preview = QLabel(self)
        self.preview.setMinimumSize(200, 260)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top = QHBoxLayout()
        top.addWidget(QLabel("A:"))
        top.addWidget(self.a_label, 1)
        top.addWidget(pick_a)
        top.addWidget(QLabel("B:"))
        top.addWidget(self.b_label, 1)
        top.addWidget(pick_b)

        mid = QHBoxLayout()
        mid.addWidget(self.list, 1)
        mid.addWidget(self.preview, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(compare)
        layout.addWidget(self.status)
        layout.addLayout(mid)

        pick_a.clicked.connect(self._pick_a)
        pick_b.clicked.connect(self._pick_b)
        compare.clicked.connect(self._compare)
        self.list.currentItemChanged.connect(self._show_preview)

    def _pick_a(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "File A", "", "PDF (*.pdf)")
        if p:
            self.a = p
            self.a_label.setText(Path(p).name)

    def _pick_b(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "File B", "", "PDF (*.pdf)")
        if p:
            self.b = p
            self.b_label.setText(Path(p).name)

    def _compare(self) -> None:
        if not self.a or not self.b:
            self.status.setText("Pick both files first.")
            return
        self.list.clear()
        self.preview.clear()
        try:
            res = pb.diff_pages(self.a, self.b)
        except Exception as exc:  # noqa: BLE001 - surface to the user
            self.status.setText(f"Compare failed: {exc}")
            return
        changed = 0
        for entry in res["report"]:
            mark = "CHANGED" if entry["changed"] else "same"
            item = QListWidgetItem(
                f"Page {entry['page']}: {mark} ({entry['diff_pct']}%)")
            item.setData(Qt.ItemDataRole.UserRole, entry.get("diff_image"))
            self.list.addItem(item)
            if entry["changed"]:
                changed += 1
        self.status.setText(
            f"{changed}/{res['pages']} pages differ{res.get('extra', '')}")

    def _show_preview(self, item) -> None:
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            self.preview.setPixmap(
                QPixmap(path).scaledToHeight(260, Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.clear()
