"""Main window: tabbed document shell with MIME-based routing."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox,
                             QTabWidget, QWidget)

from ..core.mime import Kind, detect_kind
from .text_tab import TextTab


class PlaceholderTab(QWidget):
    """Shown for kinds whose module is not implemented yet."""

    def __init__(self, path: Path, kind: Kind, parent: QWidget | None = None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(self)
        label = QLabel(
            f"<h3>{path.name}</h3>"
            f"<p>Detected as <b>{kind.value}</b>.</p>"
            f"<p>The {kind.value} module is not built yet — coming in a later milestone.</p>")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.path = path

    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True


class MainWindow(QMainWindow):
    def __init__(self, paths: list[str] | None = None):
        super().__init__()
        self.setWindowTitle("CachyView")
        self.resize(1200, 800)

        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._sync_title)
        self.setCentralWidget(self.tabs)
        self.setAcceptDrops(True)

        self._build_menu()
        self.statusBar().showMessage("Ready")

        for p in paths or []:
            self.open_path(p)

    # --- menu ----------------------------------------------------------
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_open = file_menu.addAction("&Open…", self.open_dialog)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_save = file_menu.addAction("&Save", self.save_current)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        file_menu.addSeparator()
        act_close = file_menu.addAction("&Close Tab", lambda: self.close_tab(self.tabs.currentIndex()))
        act_close.setShortcut(QKeySequence.StandardKey.Close)
        act_quit = file_menu.addAction("&Quit", self.close)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)

        tools_menu = self.menuBar().addMenu("&Tools")
        act_batch = tools_menu.addAction("&Batch processing…", self.show_batch)
        act_batch.setShortcut(QKeySequence("Ctrl+B"))

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("Dependency report", self.show_deps)
        help_menu.addAction("About CachyView", self.show_about)

    # --- opening --------------------------------------------------------
    def show_batch(self) -> None:
        """Open the batch-processing queue window."""
        from .batch_panel import BatchDialog
        dialog = BatchDialog(self)
        dialog.show()

    def open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open files")
        for p in paths:
            self.open_path(p)

    def open_path(self, path: str | Path) -> None:
        p = Path(path).expanduser()
        if not p.is_file():
            QMessageBox.warning(self, "Cannot open", f"Not a file: {p}")
            return

        for i in range(self.tabs.count()):
            if getattr(self.tabs.widget(i), "path", None) == p:
                self.tabs.setCurrentIndex(i)
                return

        kind = detect_kind(p)
        try:
            widget = self._make_tab(p, kind)
        except Exception as exc:      # a broken file must not kill the window
            QMessageBox.critical(self, "Cannot open", f"{p.name}: {exc}")
            return

        index = self.tabs.addTab(widget, p.name)
        self.tabs.setTabToolTip(index, str(p))
        self.tabs.setCurrentIndex(index)
        if hasattr(widget, "modified_changed"):
            widget.modified_changed.connect(lambda m, w=widget: self._mark_modified(w, m))
        if hasattr(widget, "open_request"):
            widget.open_request.connect(self.open_path)
        self.statusBar().showMessage(f"Opened {p.name} ({kind.value})", 4000)

    def _make_tab(self, path: Path, kind: Kind) -> QWidget:
        """Build the viewer widget appropriate to *kind*.

        Imports are local so a missing optional dependency only breaks the one
        file type that needs it, not the whole application.
        """
        if kind == Kind.TEXT:
            return TextTab(path, self)
        if kind == Kind.ARCHIVE:
            from .archive_tab import ArchiveTab
            return ArchiveTab(path, self)
        if kind == Kind.IMAGE:
            from .image_tab import ImageTab
            return ImageTab(path, self)
        if kind == Kind.PDF:
            from .pdf_tab import PdfTab
            return PdfTab(path, self)
        return PlaceholderTab(path, kind, self)

    def _mark_modified(self, widget: QWidget, modified: bool) -> None:
        index = self.tabs.indexOf(widget)
        if index < 0:
            return
        name = Path(getattr(widget, "path", "untitled")).name
        self.tabs.setTabText(index, f"{name} •" if modified else name)
        self._sync_title()

    def _sync_title(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is None:
            self.setWindowTitle("CachyView")
            self.statusBar().clearMessage()
            return
        self.setWindowTitle(f"{self.tabs.tabText(self.tabs.currentIndex())} — CachyView")
        # Clear any message left over from another tab; each tab shows its own
        # state in its internal status label.
        self.statusBar().clearMessage()

    # --- saving / closing ------------------------------------------------
    def save_current(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "save") and widget.save():
            self.statusBar().showMessage("Saved", 3000)

    def close_tab(self, index: int) -> None:
        if index < 0:
            return
        widget = self.tabs.widget(index)
        if getattr(widget, "is_modified", lambda: False)():
            name = self.tabs.tabText(index).rstrip(" •")
            choice = QMessageBox.question(
                self, "Unsaved changes", f"Save changes to {name}?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Save and not widget.save():
                return
        self.tabs.removeTab(index)
        if hasattr(widget, "cleanup"):
            widget.cleanup()          # archive tabs purge their scratch dir
        widget.deleteLater()

    def closeEvent(self, event) -> None:  # noqa: N802
        while self.tabs.count():
            before = self.tabs.count()
            self.close_tab(self.tabs.currentIndex())
            if self.tabs.count() == before:
                event.ignore()
                return
        event.accept()

    # --- drag and drop ----------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())
        event.acceptProposedAction()

    # --- help --------------------------------------------------------------
    def show_deps(self) -> None:
        from ..core import deps
        box = QMessageBox(self)
        box.setWindowTitle("Dependency report")
        box.setText("Optional components detected on this system:")
        box.setDetailedText(deps.report())
        box.exec()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About CachyView",
            "<h3>CachyView</h3>"
            "<p>A fast native archive, PDF, image and text toolkit for CachyOS.</p>"
            "<p>Built on Qt 6, MuPDF, qpdf, libarchive and Pillow. No network access.</p>")
