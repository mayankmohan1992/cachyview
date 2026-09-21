"""Main window: tabbed document shell with MIME-based routing."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PyQt6.QtWidgets import (QFileDialog, QLabel,
                             QMainWindow, QMessageBox, QMenu, QSplitter,
                             QStackedWidget, QTabWidget, QVBoxLayout,
                             QWidget)

from ..core.mime import Kind, detect_kind
from ..core import recents
from .text_tab import TextTab


class PlaceholderTab(QWidget):
    """Shown for kinds whose module is not implemented yet."""

    def __init__(self, path: Path, kind: Kind, parent: QWidget | None = None):
        super().__init__(parent)
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


class EmptyState(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._window = window
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("<h2>CachyView</h2><p>Drop files here, or open a recent one.</p>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)
        self.recents = QLabel(self)
        self.recents.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recents.setOpenExternalLinks(False)
        self.recents.linkActivated.connect(window.open_path)
        layout.addWidget(self.recents)
        self.refresh()

    def refresh(self) -> None:
        state = recents.existing(recents.load())
        bits = []
        for p in (state.get("pins") or [])[:8] + (state.get("recents") or [])[:12]:
            bits.append(f'<a href="{p}">{Path(p).name}</a>')
        self.recents.setText("<br>".join(bits) or "No recent files yet.")


class MainWindow(QMainWindow):
    def __init__(self, paths: list[str] | None = None, *, peek: bool = False):
        super().__init__()
        self.peek = peek
        self.setWindowTitle("CachyView")
        self.resize(720, 560) if peek else self.resize(1200, 800)
        if peek:
            self.setWindowFlags(self.windowFlags()
                                | Qt.WindowType.Tool
                                | Qt.WindowType.WindowStaysOnTopHint)

        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(not peek)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        from .inspector import Inspector
        self.inspector = Inspector(self)
        self.inspector.hide()
        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self.tabs)
        split.addWidget(self.inspector)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)

        self.empty = EmptyState(self)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(split)
        self.setCentralWidget(self.stack)
        self.setAcceptDrops(True)

        self._build_menu()
        self._wire_shortcuts()
        self.statusBar().showMessage("Ready")

        for p in paths or []:
            self.open_path(p)
        self._show_empty_if_needed()

    def _icon(self, name: str) -> QIcon:
        return QIcon.fromTheme(name)

    # --- menu ----------------------------------------------------------
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_open = file_menu.addAction(self._icon("document-open"), "&Open…", self.open_dialog)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_save = file_menu.addAction(self._icon("document-save"), "&Save", self.save_current)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        file_menu.addAction(self._icon("document-save-as"), "Save &As…", self.save_as_current)
        file_menu.addAction("Export…", self.export_current)
        act_print = file_menu.addAction(self._icon("document-print"), "&Print…", self.print_current)
        act_print.setShortcut(QKeySequence.StandardKey.Print)
        file_menu.addSeparator()
        file_menu.addAction("Open Containing Folder", self.open_containing)
        file_menu.addAction("Open With…", self.open_with)
        file_menu.addAction("Share / Email…", self.share_current)
        file_menu.addSeparator()
        act_close = file_menu.addAction("&Close Tab",
                                       lambda: self.close_tab(self.tabs.currentIndex()))
        act_close.setShortcut(QKeySequence.StandardKey.Close)
        act_quit = file_menu.addAction("&Quit", self.close)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)

        self.recent_menu = file_menu.addMenu("&Recent")
        self._fill_recent_menu()

        edit_menu = self.menuBar().addMenu("&Edit")
        act_find = edit_menu.addAction(self._icon("edit-find"), "&Find…",
                                      self.find_current)
        act_find.setShortcut(QKeySequence.StandardKey.Find)
        act_undo = edit_menu.addAction(self._icon("edit-undo"), "&Undo",
                                       self.undo_current)
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)

        view_menu = self.menuBar().addMenu("&View")
        self.act_inspector = view_menu.addAction("Inspector", self.toggle_inspector)
        self.act_inspector.setCheckable(True)
        self.act_inspector.setShortcut(QKeySequence("Ctrl+Shift+I"))
        view_menu.addAction("Command palette…", self.show_palette).setShortcut(
            QKeySequence("Ctrl+K"))

        tools_menu = self.menuBar().addMenu("&Tools")
        act_batch = tools_menu.addAction("&Batch processing…", self.show_batch)
        act_batch.setShortcut(QKeySequence("Ctrl+B"))
        tools_menu.addAction("&Compare PDFs…", self.show_compare)
        tools_menu.addAction("Compare text files…", self.show_text_diff)
        tools_menu.addAction("Create archive…", self.show_create_archive)
        tools_menu.addAction("Images to PDF…", self.show_images_to_pdf)
        tools_menu.addAction("Comic mode", self.show_comic)
        tools_menu.addSeparator()
        tools_menu.addAction("Settings…", self.show_settings)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("Dependency report", self.show_deps)
        help_menu.addAction("&Shortcuts", self.show_shortcuts)
        help_menu.addAction("About CachyView", self.show_about)

    def _wire_shortcuts(self) -> None:
        from . import theming
        theming.bind_shortcuts(self, {
            "Open files": self.open_dialog,
            "Close tab": lambda: self.close_tab(self.tabs.currentIndex()),
            "Quit": self.close,
            "Batch processing": self.show_batch,
            "Show shortcuts": self.show_shortcuts,
            "Command palette": self.show_palette,
            "Inspector": self.toggle_inspector,
            "Next page": self._next_in_tab,
            "Previous page": self._prev_in_tab,
            "Zoom in": self._zoom_in_tab,
            "Zoom out": self._zoom_out_tab,
            "Fit to window": self._fit_tab,
        })

    def _current_tab(self) -> QWidget | None:
        return self.tabs.currentWidget()

    def _call_tab(self, *names: str) -> None:
        widget = self._current_tab()
        if widget is None:
            return
        for name in names:
            fn = getattr(widget, name, None)
            if callable(fn):
                fn()
                return

    def _next_in_tab(self) -> None:
        self._call_tab("next_page", "next_image")

    def _prev_in_tab(self) -> None:
        self._call_tab("prev_page", "prev_image")

    def _zoom_in_tab(self) -> None:
        widget = self._current_tab()
        if widget is None:
            return
        if hasattr(widget, "zoom_in"):
            widget.zoom_in()
        elif hasattr(widget, "canvas"):
            widget.canvas.zoom_in()

    def _zoom_out_tab(self) -> None:
        widget = self._current_tab()
        if widget is None:
            return
        if hasattr(widget, "zoom_out"):
            widget.zoom_out()
        elif hasattr(widget, "canvas"):
            widget.canvas.zoom_out()

    def _fit_tab(self) -> None:
        widget = self._current_tab()
        if widget is None:
            return
        if hasattr(widget, "fit_width"):
            widget.fit_width()
        elif hasattr(widget, "canvas"):
            widget.canvas.fit_to_window()

    def show_batch(self) -> None:
        from .batch_panel import BatchDialog
        dialog = BatchDialog(self)
        dialog.show()

    def show_compare(self) -> None:
        from .compare_dialog import CompareDialog
        dialog = CompareDialog(self)
        dialog.exec()

    def show_text_diff(self) -> None:
        from .text_diff import TextDiffDialog
        TextDiffDialog(self).exec()

    def show_create_archive(self) -> None:
        from .archive_create import CreateArchiveDialog
        from ..backends import archive as ar
        dialog = CreateArchiveDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        out, sources, fmt, level, pw = dialog.payload()
        if not sources:
            return
        try:
            ar.create(out, sources, fmt=fmt, password=pw, level=level)
        except ar.ArchiveError as exc:
            QMessageBox.warning(self, "Create archive", str(exc))
            return
        self.open_path(out)

    def show_images_to_pdf(self) -> None:
        from .image_to_pdf import ImageToPdfDialog
        ImageToPdfDialog(self).exec()

    def show_comic(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "comic_mode"):
            widget.comic_mode()

    def show_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        SettingsDialog(self).exec()

    def show_palette(self) -> None:
        from .palette import CommandPalette
        actions: list[QAction] = []
        for menu in self.menuBar().findChildren(QMenu):
            actions.extend(menu.actions())
        CommandPalette(actions, self).exec()

    def toggle_inspector(self) -> None:
        visible = self.inspector.isHidden()
        self.inspector.setVisible(visible)
        self.act_inspector.setChecked(visible)
        self._refresh_inspector()

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
            existing = self.tabs.widget(i)
            if getattr(existing, "path", None) == p:
                self.tabs.setCurrentIndex(i)
                self._show_empty_if_needed()
                return

        kind = detect_kind(p)
        if kind == Kind.IMAGE:
            from .image_tab import ImageTab
            for i in range(self.tabs.count()):
                existing = self.tabs.widget(i)
                if isinstance(existing, ImageTab) and existing.path.parent == p.parent:
                    existing._open_sibling(p)
                    self.tabs.setCurrentIndex(i)
                    self.tabs.setTabText(i, p.name)
                    recents.remember(p)
                    self._fill_recent_menu()
                    self._show_empty_if_needed()
                    return
        try:
            widget = self._make_tab(p, kind)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open", f"{p.name}: {exc}")
            return

        index = self.tabs.addTab(widget, p.name)
        self.tabs.setTabToolTip(index, str(p))
        self.tabs.setCurrentIndex(index)
        if hasattr(widget, "modified_changed"):
            widget.modified_changed.connect(lambda m, w=widget: self._mark_modified(w, m))
        if hasattr(widget, "open_request"):
            widget.open_request.connect(self.open_path)
        recents.remember(p)
        self._fill_recent_menu()
        self.empty.refresh()
        self._show_empty_if_needed()
        self.statusBar().showMessage(f"Opened {p.name} ({kind.value})", 4000)

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        state = recents.existing(recents.load())
        if not state["pins"] and not state["recents"]:
            self.recent_menu.addAction("(no recent files)").setEnabled(False)
            return
        if state["pins"]:
            pin_header = self.recent_menu.addAction("Pinned")
            pin_header.setEnabled(False)
            for path in state["pins"]:
                act = self.recent_menu.addAction("📌 " + Path(path).name)
                act.setToolTip(path)
                act.triggered.connect(lambda _=False, p=path: self.open_path(p))
            self.recent_menu.addSeparator()
        for path in state["recents"]:
            act = self.recent_menu.addAction(Path(path).name)
            act.setToolTip(path)
            act.triggered.connect(lambda _=False, p=path: self.open_path(p))

    def _make_tab(self, path: Path, kind: Kind) -> QWidget:
        if kind == Kind.TEXT:
            return TextTab(path, self)
        if kind == Kind.ARCHIVE:
            from .archive_tab import ArchiveTab
            return ArchiveTab(path, self)
        if kind == Kind.IMAGE:
            from .image_tab import ImageTab
            return ImageTab(path, self)
        if kind == Kind.SVG:
            from .svg_tab import SvgTab
            return SvgTab(path, self)
        if kind == Kind.PDF:
            from .pdf_tab import PdfTab
            return PdfTab(path, self)
        if kind == Kind.BINARY:
            from .hex_tab import HexTab
            return HexTab(path, self)
        return PlaceholderTab(path, kind, self)

    def _mark_modified(self, widget: QWidget, modified: bool) -> None:
        index = self.tabs.indexOf(widget)
        if index < 0:
            return
        name = Path(getattr(widget, "path", "untitled")).name
        self.tabs.setTabText(index, f"{name} •" if modified else name)
        self._sync_title()

    def _on_tab_changed(self, _index: int) -> None:
        self._sync_title()
        self._refresh_inspector()

    def _sync_title(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is None:
            self.setWindowTitle("CachyView")
            return
        self.setWindowTitle(f"{self.tabs.tabText(self.tabs.currentIndex())} — CachyView")

    def _refresh_inspector(self) -> None:
        if self.inspector.isHidden():
            return
        widget = self.tabs.currentWidget()
        path = getattr(widget, "path", None) if widget else None
        if not isinstance(path, (str, Path)):
            self.inspector.show_message("Open a file to inspect it.")
            return
        extra: list[tuple[str, str]] = []
        info = getattr(widget, "info", None)
        if info is not None:
            for attr, label in (("format", "Format"), ("page_count", "Pages"),
                                ("width", "Width"), ("height", "Height"),
                                ("mode", "Mode"), ("file_count", "Files")):
                if hasattr(info, attr):
                    extra.append((label, str(getattr(info, attr))))
            exif = getattr(info, "exif", None)
            if isinstance(exif, dict):
                extra.extend((str(k), str(v)) for k, v in list(exif.items())[:24])
            meta = getattr(info, "metadata", None)
            if isinstance(meta, dict):
                extra.extend((str(k), str(v)) for k, v in list(meta.items())[:24])
        self.inspector.inspect_path(Path(path), extra)

    def _show_empty_if_needed(self) -> None:
        self.stack.setCurrentIndex(1 if self.tabs.count() else 0)

    def find_current(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is None:
            return
        if hasattr(widget, "toggle_find"):
            widget.toggle_find()
        elif hasattr(widget, "search_box"):
            widget.search_box.setFocus()
            widget.search_box.selectAll()

    def undo_current(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "undo"):
            widget.undo()

    def save_current(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "save") and widget.save():
            self.statusBar().showMessage("Saved", 3000)

    def save_as_current(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "save_as"):
            widget.save_as()
        else:
            self.export_current()

    def export_current(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "export_file"):
            widget.export_file()
            return
        path = getattr(widget, "path", None) if widget else None
        if not path:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Export copy", str(path))
        if dest:
            import shutil
            shutil.copy2(path, dest)

    def print_current(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is not None and hasattr(widget, "print_file"):
            widget.print_file()
            return
        QMessageBox.information(self, "Print", "Nothing printable in this tab.")

    def open_containing(self) -> None:
        widget = self.tabs.currentWidget()
        path = getattr(widget, "path", None) if widget else None
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def open_with(self) -> None:
        widget = self.tabs.currentWidget()
        path = getattr(widget, "path", None) if widget else None
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def share_current(self) -> None:
        widget = self.tabs.currentWidget()
        path = getattr(widget, "path", None) if widget else None
        if not path:
            return
        QDesktopServices.openUrl(QUrl(f"mailto:?subject={Path(path).name}&attach={path}"))

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
            widget.cleanup()
        widget.deleteLater()
        self._show_empty_if_needed()

    def save_session(self) -> None:
        if self.peek:
            return
        paths = []
        for i in range(self.tabs.count()):
            p = getattr(self.tabs.widget(i), "path", None)
            if isinstance(p, (str, Path)):
                paths.append(str(p))
        state = {"recents": recents.load()["recents"], "pins": recents.load()["pins"],
                 "session": paths}
        recents.save(state)

    def restore_session(self) -> None:
        session = recents.load().get("session", [])
        for p in session:
            if Path(p).is_file():
                self.open_path(p)

    def contextMenuEvent(self, event) -> None:
        tab = self.tabs.tabBar().tabAt(event.pos())
        if tab < 0:
            return
        widget = self.tabs.widget(tab)
        path = getattr(widget, "path", None)
        if not isinstance(path, (str, Path)):
            return
        menu = QMenu(self)
        pinned = str(path) in recents.load()["pins"]
        if pinned:
            menu.addAction("Unpin from recents", lambda: self._toggle_pin(path, False))
        else:
            menu.addAction("Pin to recents", lambda: self._toggle_pin(path, True))
        menu.addSeparator()
        menu.addAction("Close", lambda: self.close_tab(tab))
        menu.exec(event.globalPosition().toPoint())

    def _toggle_pin(self, path: str | Path, on: bool) -> None:
        if on:
            recents.pin(path)
        else:
            recents.unpin(path)
        self._fill_recent_menu()
        self.empty.refresh()

    def closeEvent(self, event) -> None:
        self.save_session()
        while self.tabs.count():
            before = self.tabs.count()
            self.close_tab(self.tabs.currentIndex())
            if self.tabs.count() == before:
                event.ignore()
                return
        event.accept()

    def keyPressEvent(self, event) -> None:
        if self.peek and event is not None and event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())
        event.acceptProposedAction()

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
            "<p>A fast native archive, PDF, image and text toolkit for Linux.</p>"
            "<p>Built on Qt 6, MuPDF, qpdf and Pillow. No network access. No AI filters.</p>")

    def show_shortcuts(self) -> None:
        from . import theming
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard shortcuts")
        box.setText(theming.format_shortcuts())
        box.exec()
