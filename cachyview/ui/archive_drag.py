"""Drag archive members out of the tree onto the desktop or Dolphin.

When the user starts dragging a file (or several) out of the archive browser,
we extract those members to the sandbox up front and offer the resulting real
files through a ``QDrag`` carrying ``text/uri-list``.  Anything that accepts
file drops — Dolphin, the desktop, a mail composer — then receives the actual
files.  Extraction reuses the sandbox, so a malicious archive cannot escape.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMimeData, QUrl, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QTreeWidget

from ..backends import archive as ar
from ..core.sandbox import Sandbox, UnsafePath


class DraggableArchiveTree(QTreeWidget):
    """A tree that extracts selected members on drag and offers real files.

    The host tab provides ``path``, ``password`` and ``_sandbox``; if a drag
    cannot proceed (locked archive, unsafe path) it calls the host's
    ``_drag_failed`` so the tab can surface a message.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)

    # Satisfied by the hosting ArchiveTab:
    path: Path
    password: str | None
    _sandbox: Sandbox

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        members = self._selected_file_members()
        if not members:
            return

        # Extract up front so the drag carries real, readable files.
        try:
            targets = ar.extract(self.path, str(self._sandbox.path),
                                 members, self.password)
        except ar.PasswordRequired:
            host = self.parent()
            if host is not None and hasattr(host, "_ask_password"):
                if host._ask_password():
                    try:
                        targets = ar.extract(self.path, str(self._sandbox.path),
                                             members, self.password)
                    except (ar.ArchiveError, UnsafePath) as exc:
                        self._report_failure(str(exc))
                        return
                else:
                    return
            else:
                return
        except (ar.ArchiveError, UnsafePath) as exc:
            self._report_failure(str(exc))
            return

        if not targets:
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(t)) for t in targets])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions)

    def _report_failure(self, message: str) -> None:
        host = self.parent()
        if host is not None and hasattr(host, "_drag_failed"):
            host._drag_failed(message)

    def _selected_file_members(self) -> list[str]:
        out: list[str] = []
        for item in self.selectedItems():
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name:                      # folders carry None
                out.append(name)
        return out
