"""Preferences: session restore and optional default-app takeover per type."""
from __future__ import annotations

import shutil

from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel,
                             QMessageBox, QVBoxLayout, QWidget)

from ..core import settings
from ..core.process import run as run_tool
from ..integration.desktop import ARCHIVE_MIMES, IMAGE_MIMES, PDF_MIMES, TEXT_MIMES

_GROUPS = (
    ("default_pdf", "PDF", PDF_MIMES),
    ("default_image", "images", IMAGE_MIMES),
    ("default_archive", "archives", ARCHIVE_MIMES),
    ("default_text", "text", TEXT_MIMES),
)


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("CachyView settings")
        state = settings.load()
        self.restore = QCheckBox("Reopen last session on launch", self)
        self.restore.setChecked(bool(state.get("restore_session", True)))
        note = QLabel(
            "Set as default uses xdg-mime. The installer never changes this.",
            self)
        note.setWordWrap(True)
        self._boxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(self.restore)
        layout.addWidget(QLabel("Set CachyView as the default app for:", self))
        for key, label, _mimes in _GROUPS:
            box = QCheckBox(label, self)
            box.setChecked(bool(state.get(key, False)))
            self._boxes[key] = box
            layout.addWidget(box)
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        data = {"restore_session": self.restore.isChecked()}
        for key, _label, mimes in _GROUPS:
            on = self._boxes[key].isChecked()
            data[key] = on
            if on:
                self._apply_default(mimes)
        settings.save(data)
        self.accept()

    def _apply_default(self, mimes: list[str]) -> None:
        tool = shutil.which("xdg-mime")
        if not tool:
            QMessageBox.information(
                self, "xdg-mime missing",
                "Install xdg-utils to register a default application.")
            return
        for mime in mimes:
            run_tool([tool, "default", "cachyview.desktop", mime], timeout=10)
