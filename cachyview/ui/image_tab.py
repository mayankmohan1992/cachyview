"""Image viewer and editor tab: zoom, pan, non-destructive edits, batch tools."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                             QMessageBox, QScrollArea, QToolBar, QVBoxLayout,
                             QWidget)

from ..backends import image as ib
from ..core.jobs import submit

ZOOM_STEPS = [0.05, 0.1, 0.25, 0.33, 0.5, 0.67, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0]


def _shortcut(action, keys: str) -> None:
    """QToolBar.addAction is typed as returning an optional action."""
    if action is not None:
        action.setShortcut(keys)


def pil_to_qpixmap(img) -> QPixmap:
    """Convert a Pillow image to a QPixmap without touching the filesystem."""
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888)
    # QImage does not copy the buffer, so copy() before `data` is collected.
    return QPixmap.fromImage(qimg.copy())


class ImageCanvas(QScrollArea):
    """Scrollable image display with zoom and drag-to-pan."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self._label)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pixmap: QPixmap | None = None
        self._zoom = 1.0
        self._fit = True
        self._drag_from: QPoint | None = None

        from .crop_overlay import CropOverlay
        self.crop = CropOverlay(self._label)
        self.crop.hide()

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_image(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._redraw()

    def _redraw(self) -> None:
        if self._pixmap is None:
            return
        if self._fit:
            viewport = self.viewport()
            area = viewport.size() if viewport is not None else self.size()
            if self._pixmap.width() and self._pixmap.height():
                self._zoom = min(
                    area.width() / self._pixmap.width(),
                    area.height() / self._pixmap.height(), 1.0)
        width = max(1, int(self._pixmap.width() * self._zoom))
        height = max(1, int(self._pixmap.height() * self._zoom))
        self._label.setPixmap(self._pixmap.scaled(
            width, height, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self._label.resize(width, height)

        # The crop overlay lives on the label, so it must track its geometry.
        keep = self.crop.image_rect() if self.crop.has_selection() else None
        self.crop.setGeometry(0, 0, width, height)
        self.crop.configure(self._zoom, self._pixmap.size())
        if keep is not None:
            self.crop.set_image_rect(keep)

    def set_zoom(self, value: float, *, fit: bool = False) -> None:
        self._fit = fit
        self._zoom = max(0.01, min(32.0, value))
        self._redraw()

    def zoom_in(self) -> None:
        nxt = next((z for z in ZOOM_STEPS if z > self._zoom + 1e-6), ZOOM_STEPS[-1])
        self.set_zoom(nxt)

    def zoom_out(self) -> None:
        prv = next((z for z in reversed(ZOOM_STEPS) if z < self._zoom - 1e-6),
                   ZOOM_STEPS[0])
        self.set_zoom(prv)

    def fit_to_window(self) -> None:
        self.set_zoom(self._zoom, fit=True)

    def set_crop_mode(self, on: bool) -> None:
        """Show the crop overlay; panning is disabled while it is active."""
        if on:
            if self._pixmap is not None:
                self.crop.configure(self._zoom, self._pixmap.size())
            self.crop.raise_()
            self.crop.show()
        else:
            self.crop.clear()
            self.crop.hide()

    @property
    def crop_active(self) -> bool:
        """True when crop mode is on.

        ``isHidden()`` rather than ``isVisible()``: a child widget of a window
        that has not been shown yet is *not* visible, but it is also not
        hidden, and crop mode must work before the tab is on screen.
        """
        return not self.crop.isHidden()

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def resizeEvent(self, a0) -> None:  # noqa: N802
        super().resizeEvent(a0)
        if self._fit:
            self._redraw()

    def wheelEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = a0.angleDelta().y()
            self.zoom_in() if delta > 0 else self.zoom_out()
            a0.accept()
        else:
            super().wheelEvent(a0)

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._drag_from = a0.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and self._drag_from is not None:
            delta = a0.position().toPoint() - self._drag_from
            self._drag_from = a0.position().toPoint()
            for bar, d in ((self.horizontalScrollBar(), delta.x()),
                           (self.verticalScrollBar(), delta.y())):
                if bar is not None:
                    bar.setValue(bar.value() - d)
        super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        self._drag_from = None
        self.unsetCursor()
        super().mouseReleaseEvent(a0)


class ImageTab(QWidget):
    """Full image tab: canvas, toolbar and a non-destructive edit stack."""

    modified_changed = pyqtSignal(bool)

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = Path(path)
        self.original = ib.load(self.path)
        self.info = ib.info(self.path)
        self.ops: list[ib.Op] = []
        self._redo: list[ib.Op] = []
        self._jobs: list = []
        self.current = self.original

        self.canvas = ImageCanvas(self)
        self.status = QLabel(self)

        bar = QToolBar(self)
        _shortcut(bar.addAction("Save", self.save), "Ctrl+S")
        bar.addAction("Save As…", self.save_as)
        bar.addSeparator()
        _shortcut(bar.addAction("Undo", self.undo), "Ctrl+Z")
        _shortcut(bar.addAction("Redo", self.redo), "Ctrl+Shift+Z")
        bar.addSeparator()
        bar.addAction("Rotate ⟲", lambda: self.add_op("rotate", angle=270))
        bar.addAction("Rotate ⟳", lambda: self.add_op("rotate", angle=90))
        bar.addAction("Flip ↔", lambda: self.add_op("flip", horizontal=True))
        bar.addAction("Flip ↕", lambda: self.add_op("flip", horizontal=False))
        bar.addSeparator()
        self.crop_action = bar.addAction("Crop", self.toggle_crop)
        if self.crop_action is not None:
            self.crop_action.setCheckable(True)
        bar.addAction("Resize…", self.resize_dialog)
        bar.addAction("Grayscale", lambda: self.add_op("grayscale"))
        bar.addAction("Invert", lambda: self.add_op("invert"))
        bar.addAction("Auto contrast", lambda: self.add_op("autocontrast"))
        bar.addSeparator()

        zoom = QToolBar(self)
        zoom.addAction("−", self.canvas.zoom_out)
        zoom.addAction("+", self.canvas.zoom_in)
        zoom.addAction("Fit", self.canvas.fit_to_window)
        zoom.addAction("1:1", self.canvas.actual_size)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(bar, 1)
        top.addWidget(zoom)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)

        self._refresh()

    # --- edit stack ------------------------------------------------------
    def add_op(self, name: str, **args) -> None:
        self.ops.append(ib.Op(name, args))
        self._redo.clear()
        self._reapply()

    def undo(self) -> None:
        if self.ops:
            self._redo.append(self.ops.pop())
            self._reapply()

    def redo(self) -> None:
        if self._redo:
            self.ops.append(self._redo.pop())
            self._reapply()

    def _reapply(self) -> None:
        """Rebuild the preview from the original plus the op stack.

        If the newest op is invalid it is dropped and the previous good state
        restored, so a bad edit can never leave the tab unusable.
        """
        try:
            self.current = ib.apply_ops(self.original, self.ops)
        except ib.ImageError as exc:
            QMessageBox.warning(self, "Edit failed", str(exc))
            if self.ops:
                self.ops.pop()
            self.current = ib.apply_ops(self.original, self.ops)
        self._refresh()
        self.modified_changed.emit(self.is_modified())

    def _refresh(self) -> None:
        self.canvas.set_image(pil_to_qpixmap(self.current))
        applied = f" · {len(self.ops)} edit(s)" if self.ops else ""
        self.status.setText(
            f"{self.current.width}×{self.current.height} · {self.info.format} "
            f"· {self.current.mode}{applied}")

    # --- dialogs ---------------------------------------------------------
    # --- cropping ---------------------------------------------------------
    def toggle_crop(self) -> None:
        """Enter crop mode, or apply the pending selection and leave it."""
        if not self.canvas.crop_active:
            self.canvas.set_crop_mode(True)
            self.status.setText(
                "Crop: drag to select, drag inside to move, corners to resize · "
                "press Crop again to apply, Esc to cancel")
            return

        rect = self.canvas.crop.image_rect()
        self.canvas.set_crop_mode(False)
        if self.crop_action is not None:
            self.crop_action.setChecked(False)

        if not rect.isValid() or rect.width() < 1 or rect.height() < 1:
            self.status.setText("Crop cancelled: nothing was selected.")
            return
        self.add_op("crop", box=(rect.left(), rect.top(),
                                 rect.right() + 1, rect.bottom() + 1))
        self.status.setText(f"Cropped to {rect.width()}x{rect.height()}")

    def cancel_crop(self) -> None:
        self.canvas.set_crop_mode(False)
        if self.crop_action is not None:
            self.crop_action.setChecked(False)
        self.status.setText("Crop cancelled.")

    def keyPressEvent(self, a0) -> None:  # noqa: N802
        if (a0 is not None and a0.key() == Qt.Key.Key_Escape
                and self.canvas.crop_active):
            self.cancel_crop()
            a0.accept()
            return
        super().keyPressEvent(a0)

    def resize_dialog(self) -> None:
        width, ok = QInputDialog.getInt(
            self, "Resize", "New width in pixels:", self.current.width, 1, 100000)
        if ok:
            self.add_op("resize", width=width)

    # --- saving ----------------------------------------------------------
    def is_modified(self) -> bool:
        return bool(self.ops)

    def save(self) -> bool:
        return self._write(self.path)

    def save_as(self) -> bool:
        target, _ = QFileDialog.getSaveFileName(
            self, "Save image as", str(self.path),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)")
        return self._write(Path(target)) if target else False

    def _write(self, target: Path) -> bool:
        try:
            ib.save(self.current, target, source=self.original)
        except ib.ImageError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self.path = target
        self.original = self.current
        self.ops.clear()
        self._redo.clear()
        self.modified_changed.emit(False)
        self.status.setText(f"Saved {target.name}")
        return True
