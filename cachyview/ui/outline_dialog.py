"""Bookmark / outline editor dialog.

Lets the user view and edit the PDF table of contents: add, remove and reorder
entries, each with a title, target page and nesting level.  The result is written
back through ``backends.pdf.set_outline`` so it survives reopening elsewhere.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout,
                             QMessageBox)

from ..backends import pdf as pb


class OutlineDialog(QDialog):
    def __init__(self, path, password: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bookmarks")
        self.path = path
        self.password = password
        self.entries = pb.get_outline(path, password)

        self.list = QListWidget(self)
        for e in self.entries:
            self._add_row(e["title"], e["page"], e["level"])

        title = QLineEdit(self)
        title.setPlaceholderText("Title")
        page = QSpinBox(self)
        page.setMinimum(1)
        page.setMaximum(9999)
        level = QSpinBox(self)
        level.setMinimum(0)
        level.setMaximum(8)
        level.setPrefix("Lvl ")

        add_btn = QPushButton("Add")
        del_btn = QPushButton("Remove")
        upd_btn = QPushButton("Update")
        up_btn = QPushButton("↑")
        down_btn = QPushButton("↓")

        row = QHBoxLayout()
        row.addWidget(title)
        row.addWidget(page)
        row.addWidget(level)
        row.addWidget(add_btn)
        row.addWidget(upd_btn)
        row.addWidget(del_btn)
        row.addWidget(up_btn)
        row.addWidget(down_btn)

        save = QPushButton("Save bookmarks")
        cancel = QPushButton("Cancel")

        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(row)
        layout.addWidget(save)
        layout.addWidget(cancel)

        add_btn.clicked.connect(lambda: self._add_row(
            title.text() or "Untitled", page.value(), level.value()))
        upd_btn.clicked.connect(
            lambda: self._update(title.text() or "Untitled",
                                 page.value(), level.value()))
        del_btn.clicked.connect(self._remove)
        up_btn.clicked.connect(lambda: self._move(-1))
        down_btn.clicked.connect(lambda: self._move(1))
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        self.list.currentItemChanged.connect(self._load_selected)
        self._title, self._page, self._level = title, page, level

    def _load_selected(self, current, _previous) -> None:
        if current is None:
            return
        d = current.data(Qt.ItemDataRole.UserRole)
        self._title.setText(d["title"])
        self._page.setValue(int(d["page"]))
        self._level.setValue(int(d["level"]))

    def _update(self, title: str, page: int, level: int) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        item.setData(Qt.ItemDataRole.UserRole,
                     {"title": title, "page": page, "level": level})
        item.setText(f"L{level}  p{page}  {title}")

    def _add_row(self, title: str, page: int, level: int) -> None:
        item = QListWidgetItem(f"L{level}  p{page}  {title}")
        item.setData(Qt.ItemDataRole.UserRole,
                    {"title": title, "page": page, "level": level})
        self.list.addItem(item)

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        target = row + delta
        if 0 <= target < self.list.count():
            a = self.list.takeItem(row)
            self.list.insertItem(target, a)
            self.list.setCurrentRow(target)

    def _save(self) -> None:
        entries = []
        for i in range(self.list.count()):
            d = self.list.item(i).data(Qt.ItemDataRole.UserRole)
            entries.append(d)
        if not entries:
            QMessageBox.information(self, "Bookmarks",
                                   "No bookmarks to save.")
            return
        pb.set_outline(self.path, self.path, entries,
                       password=self.password)
        self.accept()
        if self.parent() is not None and hasattr(self.parent(), "reload"):
            self.parent().reload()
