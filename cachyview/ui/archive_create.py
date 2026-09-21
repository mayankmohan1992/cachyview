"""Create-archive dialog (wraps backends.archive.create)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QLineEdit, QListWidget, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)


class CreateArchiveDialog(QDialog):
    def __init__(self, parent: QWidget | None = None,
                 initial: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Create archive")
        self.files = QListWidget(self)
        for p in initial or []:
            self.files.addItem(p)
        add = QPushButton("Add files…", self)
        add.clicked.connect(self._add)
        add_dir = QPushButton("Add folder…", self)
        add_dir.clicked.connect(self._add_dir)
        self.fmt = QComboBox(self)
        self.fmt.addItems(["zip", "7z", "tar", "tar.gz", "tar.xz", "tar.bz2",
                           "tar.zst"])
        self.level = QSpinBox(self)
        self.level.setRange(0, 9)
        self.level.setValue(5)
        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.output = QLineEdit(self)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._browse_out)
        form = QFormLayout()
        form.addRow("Format", self.fmt)
        form.addRow("Level", self.level)
        form.addRow("Password", self.password)
        form.addRow("Save as", self.output)
        form.addRow(browse)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.files)
        layout.addWidget(add)
        layout.addWidget(add_dir)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Files to compress")
        for p in paths:
            self.files.addItem(p)

    def _add_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder to compress")
        if d:
            self.files.addItem(d)

    def _browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Archive")
        if path:
            self.output.setText(path)

    def payload(self) -> tuple[Path, list[str], str, int, str | None]:
        sources = [self.files.item(i).text() for i in range(self.files.count())]
        out = Path(self.output.text().strip() or "archive.zip")
        pw = self.password.text() or None
        return out, sources, self.fmt.currentText(), self.level.value(), pw
