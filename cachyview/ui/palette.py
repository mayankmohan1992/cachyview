"""Ctrl+K command palette — fuzzy-run the current window's actions."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QDialog, QLineEdit, QListWidget, QListWidgetItem,
                             QVBoxLayout, QWidget)


class CommandPalette(QDialog):
    def __init__(self, actions: list[QAction], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Command palette")
        self.resize(480, 360)
        self._actions = [a for a in actions
                         if a is not None and a.text() and a.isEnabled()]
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Run a command…")
        self.list = QListWidget(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_current)
        self.list.itemActivated.connect(lambda _i: self._run_current())
        self._filter("")

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        self.list.clear()
        for act in self._actions:
            label = act.text().replace("&", "")
            if needle and needle not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, act)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        act = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if act is not None:
            act.trigger()
