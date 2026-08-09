"""Archive browser tab: tree view, password prompt, preview and extraction."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QFileDialog, QHeaderView,
                             QInputDialog, QLabel, QLineEdit, QMessageBox,
                             QToolBar, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from ..backends import archive as ar
from ..core.jobs import submit
from ..core.sandbox import Sandbox, UnsafePath


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


class ArchiveTab(QWidget):
    """Browse an archive, preview members and extract them."""

    open_request = pyqtSignal(str)      # a member was extracted for viewing

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = Path(path)
        self.password: str | None = None
        self.info: ar.ArchiveInfo | None = None
        self.error = ""
        self._sandbox = Sandbox(prefix="arc-")
        self._jobs: list = []

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Name", "Size", "Packed", "Modified"])
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        header = self.tree.header()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Filter files…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)

        self.status = QLabel("Loading…", self)

        bar = QToolBar(self)
        bar.addAction("Extract All…", self.extract_all)
        bar.addAction("Extract Selected…", self.extract_selected)
        bar.addSeparator()
        bar.addAction("Test Integrity", self.test_integrity)
        bar.addAction("Unlock…", self.unlock)
        bar.addAction("Reload", lambda: self.reload(prompt=False))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.filter)
        layout.addWidget(self.tree)
        layout.addWidget(self.status)

        # prompt=False: a constructor must never block on a modal dialog.
        self.reload(prompt=False)

    # --- loading ---------------------------------------------------------
    def reload(self, *, prompt: bool = True) -> None:
        """Read the archive listing.

        Failures set ``self.error`` and update the status bar instead of
        opening a modal dialog, so constructing the tab never blocks waiting
        for input.  The password dialog appears only on an explicit retry.
        """
        self.error = ""
        self.status.setText("Reading archive…")
        try:
            self.info = ar.list_archive(self.path, self.password)
        except ar.PasswordRequired as exc:
            self.error = str(exc)
            self.status.setText("Password required — click Unlock to enter it.")
            if prompt and self._ask_password():
                return self.reload(prompt=False)
            return
        except ar.ArchiveError as exc:
            self.error = str(exc)
            self.status.setText(str(exc))
            return
        self._populate()

    def unlock(self) -> None:
        """Ask for a password and retry (an explicit user action)."""
        if self._ask_password():
            self.reload(prompt=False)

    def _ask_password(self) -> bool:
        pw, ok = QInputDialog.getText(
            self, "Password required",
            f"Enter the password for {self.path.name}:",
            QLineEdit.EchoMode.Password)
        if ok and pw:
            self.password = pw
            return True
        return False

    def _populate(self) -> None:
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        if self.info is None:
            return

        nodes: dict[str, QTreeWidgetItem] = {}

        def folder(path: str) -> QTreeWidgetItem | None:
            if not path:
                return None
            if path in nodes:
                return nodes[path]
            parent_path, _, name = path.rpartition("/")
            parent = folder(parent_path)
            item = QTreeWidgetItem([name, "", "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, None)
            (parent.addChild(item) if parent
             else self.tree.addTopLevelItem(item))
            nodes[path] = item
            return item

        for entry in sorted(self.info.entries, key=lambda e: e.name):
            parent_path, _, name = entry.name.rstrip("/").rpartition("/")
            if entry.is_dir:
                folder(entry.name.rstrip("/"))
                continue
            item = QTreeWidgetItem([
                name,
                human_size(entry.size),
                human_size(entry.packed),
                entry.modified.strftime("%Y-%m-%d %H:%M") if entry.modified else "",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.name)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
            if entry.encrypted:
                item.setText(0, f"{name}  🔒")
            parent = folder(parent_path)
            (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))

        self.tree.setSortingEnabled(True)
        self.tree.expandToDepth(0)
        if self.info.encrypted and not self.password:
            lock = " · 🔒 encrypted — a password is needed to extract"
        elif self.info.encrypted:
            lock = " · 🔒 unlocked"
        else:
            lock = ""
        self.status.setText(
            f"{self.info.file_count} files · {human_size(self.info.total_size)} "
            f"· {self.info.format}{lock}")

    def _apply_filter(self, text: str) -> None:
        needle = text.lower().strip()

        def visit(item: QTreeWidgetItem | None) -> bool:
            if item is None:
                return False
            match = needle in item.text(0).lower()
            child_match = False
            for i in range(item.childCount()):
                child_match |= visit(item.child(i))
            visible = match or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    # --- actions ---------------------------------------------------------
    def selected_members(self) -> list[str]:
        out: list[str] = []
        for item in self.tree.selectedItems():
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name:
                out.append(name)
        return out

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if not name:
            item.setExpanded(not item.isExpanded())
            return
        try:
            target = ar.extract_one(self.path, name, self._sandbox.path,
                                    self.password)
        except ar.PasswordRequired:
            if self._ask_password():
                self._on_double_click(item, _column)
            return
        except (ar.ArchiveError, UnsafePath) as exc:
            QMessageBox.warning(self, "Cannot open file", str(exc))
            return
        self.open_request.emit(str(target))

    def extract_all(self) -> None:
        self._extract(None)

    def extract_selected(self) -> None:
        members = self.selected_members()
        if not members:
            QMessageBox.information(self, "Nothing selected",
                                    "Select one or more files first.")
            return
        self._extract(members)

    def _extract(self, members: list[str] | None) -> None:
        dest = QFileDialog.getExistingDirectory(
            self, "Extract to", str(self.path.parent))
        if not dest:
            return
        self.status.setText("Extracting…")

        def work(ctx):
            return ar.extract(self.path, dest, members, self.password, ctx=ctx)

        job = submit(work, name="extract")
        self._jobs.append(job)
        job.signals.progress.connect(lambda _p, m: self.status.setText(m))
        job.signals.finished.connect(
            lambda files: self.status.setText(f"Extracted {len(files)} file(s) to {dest}"))
        job.signals.failed.connect(self._on_job_failed)

    def _on_job_failed(self, message: str, _trace: str) -> None:
        self.status.setText(message)
        QMessageBox.warning(self, "Extraction failed", message)

    def test_integrity(self) -> None:
        try:
            ok = ar.test_archive(self.path, self.password)
        except ar.PasswordRequired:
            if self._ask_password():
                self.test_integrity()
            return
        except ar.ArchiveError as exc:
            QMessageBox.warning(self, "Test failed", str(exc))
            return
        QMessageBox.information(
            self, "Integrity test",
            "The archive is intact." if ok else "The archive is damaged.")

    # --- lifecycle -------------------------------------------------------
    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True

    def cleanup(self) -> None:
        self._sandbox.cleanup()

    def closeEvent(self, a0) -> None:  # noqa: N802
        self.cleanup()
        super().closeEvent(a0)
