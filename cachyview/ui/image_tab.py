"""Image viewer and editor tab: zoom, pan, non-destructive edits, batch tools."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout,
                             QInputDialog, QLabel, QListWidget, QListWidgetItem,
                             QMenu, QMessageBox, QScrollArea, QSplitter, QToolBar,
                             QToolButton, QVBoxLayout, QWidget)

from ..backends import image as ib

ZOOM_STEPS = [0.05, 0.1, 0.25, 0.33, 0.5, 0.67, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0]


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
        from .inspect_overlay import InspectOverlay
        from .image_markup import MarkupOverlay
        self.crop = CropOverlay(self._label)
        self.crop.hide()
        self.inspect = InspectOverlay(self._label)
        self.inspect.hide()
        self.markup = MarkupOverlay(self._label)
        self.markup.hide()
        self._label.setStyleSheet(
            "background-color: #c8c8c8; background-image: none;")

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
        # The inspect overlay tracks zoom/geometry the same way.
        self.inspect.setGeometry(0, 0, width, height)
        self.inspect.configure(self._zoom, self._pixmap.size())
        self.markup.setGeometry(0, 0, width, height)
        self.markup.configure(self._zoom)

    def set_zoom(self, value: float, *, fit: bool = False, anchor=None) -> None:
        old = self._zoom
        self._fit = fit
        self._zoom = max(0.01, min(32.0, value))
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        mx = my = None
        if anchor is not None:
            mx, my = anchor
        self._redraw()
        if mx is not None and old > 1e-6 and hbar is not None and vbar is not None:
            ratio = self._zoom / old
            hbar.setValue(int(mx * ratio - (mx - hbar.value())))
            vbar.setValue(int(my * ratio - (my - vbar.value())))

    def zoom_in(self, *, anchor=None) -> None:
        nxt = next((z for z in ZOOM_STEPS if z > self._zoom + 1e-6), ZOOM_STEPS[-1])
        self.set_zoom(nxt, anchor=anchor)

    def zoom_out(self, *, anchor=None) -> None:
        prv = next((z for z in reversed(ZOOM_STEPS) if z < self._zoom - 1e-6),
                   ZOOM_STEPS[0])
        self.set_zoom(prv, anchor=anchor)

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

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        if self._fit:
            self._redraw()

    def wheelEvent(self, a0) -> None:
        if a0 is not None and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = a0.angleDelta().y()
            pos = a0.position()
            anchor = (self.horizontalScrollBar().value() + int(pos.x()),
                      self.verticalScrollBar().value() + int(pos.y()))
            self.zoom_in(anchor=anchor) if delta > 0 else self.zoom_out(anchor=anchor)
            a0.accept()
        else:
            super().wheelEvent(a0)

    def mousePressEvent(self, a0) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._drag_from = a0.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0) -> None:
        if a0 is not None and self._drag_from is not None:
            delta = a0.position().toPoint() - self._drag_from
            self._drag_from = a0.position().toPoint()
            for bar, d in ((self.horizontalScrollBar(), delta.x()),
                           (self.verticalScrollBar(), delta.y())):
                if bar is not None:
                    bar.setValue(bar.value() - d)
        super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0) -> None:
        self._drag_from = None
        self.unsetCursor()
        super().mouseReleaseEvent(a0)


class ImageTab(QWidget):
    """Full image tab: canvas, toolbar and a non-destructive edit stack."""

    modified_changed = pyqtSignal(bool)
    inspect_readout = pyqtSignal(str)

    def __init__(self, path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = Path(path)
        self.original = ib.load(self.path)
        self.info = ib.info(self.path)
        self.ops: list[ib.Op] = []
        self._redo: list[ib.Op] = []
        self._jobs: list = []
        self.current = self.original

        # Replay any persisted edit stack so reopening resumes where left off.
        from ..core import image_history as ih
        self._history = ih
        self._source_path = Path(path)  # original file the edits derive from
        try:
            self.ops = self._history.load(self._source_path)
        except Exception:
            self.ops = []

        self.canvas = ImageCanvas(self)
        self.canvas.inspect.readout.connect(self.inspect_readout)
        self.status = QLabel(self)

        from .icons import add_action, icon_button, style_bar

        bar = QToolBar(self)
        style_bar(bar)
        add_action(bar, "document-save", "Save", self.save,
                   tooltip="Save (Ctrl+S)")
        add_action(bar, "document-save-as", "Save As…", self.save_as)
        bar.addSeparator()
        add_action(bar, "edit-undo", "Undo", self.undo,
                   tooltip="Undo (Ctrl+Z)")
        add_action(bar, "edit-redo", "Redo", self.redo, shortcut="Ctrl+Shift+Z")
        bar.addSeparator()
        add_action(bar, "object-rotate-left", "Rotate left",
                   lambda: self.add_op("rotate", angle=270))
        add_action(bar, "object-rotate-right", "Rotate right",
                   lambda: self.add_op("rotate", angle=90))
        add_action(bar, "object-flip-horizontal", "Flip horizontal",
                   lambda: self.add_op("flip", horizontal=True))
        add_action(bar, "object-flip-vertical", "Flip vertical",
                   lambda: self.add_op("flip", horizontal=False))
        bar.addSeparator()
        add_action(bar, "object-rotate-left", "Lossless rotate left",
                   lambda: self.lossless_rotate(270),
                   tooltip="Lossless JPEG rotate left")
        add_action(bar, "object-rotate-right", "Lossless rotate right",
                   lambda: self.lossless_rotate(90),
                   tooltip="Lossless JPEG rotate right")
        bar.addSeparator()
        # Inspection tools (non-destructive): picker, ruler, magnifier.
        self._inspect_actions: dict[str, object] = {}
        for label, mode, names in (
            ("Picker", "picker", ("color-picker", "tool-color-picker")),
            ("Ruler", "ruler", ("measure", "tool-measure")),
            ("Magnifier", "magnifier", ("zoom", "page-zoom")),
        ):
            act = add_action(bar, names, label,
                             lambda m=mode: self.set_inspect_mode(m),
                             checkable=True)
            if act is not None:
                self._inspect_actions[mode] = act
        bar.addSeparator()
        self.crop_action = add_action(
            bar, ("transform-crop", "edit-cut"), "Crop", self.toggle_crop,
            checkable=True)
        add_action(bar, "transform-scale", "Resize…", self.resize_dialog)
        add_action(bar, "transform-crop-resize", "Canvas…", self.canvas_dialog)
        add_action(bar, "object-rotate-right", "Straighten…",
                   self.straighten_dialog)
        filt = icon_button(self, ("draw-brush", "image-filter"), "Filters")
        filt.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        fmenu = QMenu(self)
        fmenu.addAction("Grayscale", lambda: self.add_op("grayscale"))
        fmenu.addAction("Invert", lambda: self.add_op("invert"))
        fmenu.addAction("Auto contrast", lambda: self.add_op("autocontrast"))
        fmenu.addSeparator()
        for name, op, args in (
            ("Gaussian blur", "blur", {"radius": 2.0}),
            ("Unsharp mask", "unsharp", {}),
            ("Median denoise", "median", {"size": 3}),
            ("Smooth", "smooth", {}),
            ("Detail", "detail", {}),
            ("Edge enhance", "edge_enhance", {}),
            ("Emboss", "emboss", {}),
            ("Find edges", "find_edges", {}),
            ("Contour", "contour", {}),
            ("Sepia", "sepia", {}),
            ("Vignette", "vignette", {}),
            ("Posterize", "posterize", {"bits": 4}),
            ("Solarize", "solarize", {}),
            ("Equalize", "equalize", {}),
            ("Add noise", "noise", {"amount": 12}),
        ):
            fmenu.addAction(name, lambda o=op, a=args: self.add_op(o, **a))
        fmenu.addSeparator()
        fmenu.addAction("Watermark…", self.watermark_dialog)
        filt.setMenu(fmenu)
        bar.addWidget(filt)
        self.hist_action = add_action(
            bar, ("view-statistics", "office-chart-bar"), "Histogram",
            self.toggle_histogram, checkable=True,
            tooltip="Show RGB/luma histogram")
        mark = icon_button(self, ("draw-freehand", "draw-rectangle"), "Markup")
        mark.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        mmenu = QMenu(self)
        for kind in ("rectangle", "oval", "line", "arrow", "freehand", "highlight", "text"):
            mmenu.addAction(kind.title(), lambda k=kind: self.set_markup_mode(k))
        mmenu.addAction("Off", lambda: self.set_markup_mode("off"))
        mark.setMenu(mmenu)
        bar.addWidget(mark)
        add_action(bar, "document-export", "Export…", self.export_file)
        add_action(bar, "media-playback-start", "Slideshow", self.slideshow)
        add_action(bar, "go-previous", "Previous image", self.prev_image)
        add_action(bar, "go-next", "Next image", self.next_image)
        bar.addSeparator()

        zoom = QToolBar(self)
        style_bar(zoom)
        add_action(zoom, "zoom-out", "Zoom out", self.canvas.zoom_out)
        add_action(zoom, "zoom-in", "Zoom in", self.canvas.zoom_in)
        add_action(zoom, "zoom-fit-best", "Fit", self.canvas.fit_to_window)
        add_action(zoom, "zoom-original", "1:1", self.canvas.actual_size)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(bar, 1)
        top.addWidget(zoom)

        from .image_adjust import AdjustPanel
        self.adjust = AdjustPanel(self)
        self.adjust.adjusted.connect(self._on_adjust)
        self.adjust.toggled.connect(self._on_adjust_toggle)
        self.adjust.reset_all.connect(self._reset_adjust)
        self._adjust_keys = set()
        from .histogram import HistogramPanel
        self.histogram = HistogramPanel(self)
        self.histogram.setVisible(False)
        self.film = QListWidget(self)
        self.film.setMaximumHeight(88)
        self.film.setFlow(QListWidget.Flow.LeftToRight)
        self.film.setViewMode(QListWidget.ViewMode.IconMode)
        self.film.itemActivated.connect(self._film_open)
        self._slideshow = None
        self._anim = None
        self._frames: list = []
        self._durations: list[int] = []

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self.canvas)
        split.addWidget(self.adjust)
        split.addWidget(self.histogram)
        split.setStretchFactor(0, 5)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        layout.addWidget(self.film)
        layout.addWidget(self.status)

        self.canvas.markup.committed.connect(self._markup_done)
        self._fill_film()
        self._maybe_animate()
        self._refresh()

        # If a persisted edit stack was replayed, rebuild the preview now that
        # the canvas exists.
        if self.ops:
            self._reapply()

    # --- edit stack ------------------------------------------------------
    def _persist(self) -> None:
        """Write the current edit stack to disk (best-effort)."""
        try:
            self._history.remember(self._source_path, self.ops)
        except Exception:
            pass

    def add_op(self, name: str, **args) -> None:
        self.ops.append(ib.Op(name, args))
        self._redo.clear()
        self._persist()
        self._reapply()

    def undo(self) -> None:
        if self.ops:
            self._redo.append(self.ops.pop())
            self._persist()
            self._reapply()

    def redo(self) -> None:
        if self._redo:
            self.ops.append(self._redo.pop())
            self._persist()
            self._reapply()

    def lossless_rotate(self, angle: int) -> None:
        """Rotate the file on disk losslessly (JPEG right-angles) via the backend."""
        from ..backends import image as ib
        from ..core.safe import replace_in_place
        src = self.path

        def write(tmp: Path) -> None:
            ib.lossless_rotate(src, tmp, angle=angle)

        try:
            out = replace_in_place(src, write)
        except ib.ImageError as exc:
            QMessageBox.warning(self, "Lossless rotate failed", str(exc))
            return
        # Reload the freshly rotated file so the view and EXIF match disk.
        self.reload_from(out)

    def reload_from(self, path: Path) -> None:
        """Replace the loaded image in place after an external on-disk change."""
        from ..backends import image as ib
        self.path = path
        self.original = ib.load(path)
        self.info = ib.info(path)
        self.ops.clear()
        self._redo.clear()
        try:
            self._history.clear(self._source_path)
        except Exception:
            pass
        self._source_path = Path(path)
        self.current = self.original.copy()
        self._maybe_animate()
        self._refresh()
        self.modified_changed.emit(False)

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
        if self.histogram.isVisible():
            self.histogram.set_image(self.current)
        applied = f" · {len(self.ops)} edit(s)" if self.ops else ""
        self.status.setText(
            f"{self.current.width}×{self.current.height} · {self.info.format} "
            f"· {self.current.mode}{applied}")

    def toggle_histogram(self) -> None:
        show = self.hist_action is not None and self.hist_action.isChecked()
        self.histogram.setVisible(show)
        if show:
            self.histogram.set_image(self.current)

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

    def set_inspect_mode(self, mode: str) -> None:
        """Toggle one of the inspection tools (picker / ruler / magnifier).

        Selecting one disables the others and leaves crop mode, since the
        overlays would otherwise fight over mouse events.
        """
        if self.canvas.crop_active:
            self.canvas.set_crop_mode(False)
            if self.crop_action is not None:
                self.crop_action.setChecked(False)

        if self._inspect_actions.get(mode) is not None and \
                self._inspect_actions[mode].isChecked():  # type: ignore[union-attr]
            # already on -> turn off
            self.canvas.inspect.set_mode("off")
            self._inspect_actions[mode].setChecked(False)  # type: ignore[union-attr]
            self.status.setText("Inspection off.")
            return

        self.canvas.inspect.set_mode(mode)
        for m, act in self._inspect_actions.items():
            if act is not None:
                act.setChecked(m == mode)  # type: ignore[union-attr]
        hints = {
            "picker": "Picker: hover to read colour, click to copy the hex.",
            "ruler": "Ruler: drag from A to B to measure the distance.",
            "magnifier": "Magnifier: a zoomed lens follows the cursor.",
        }
        self.status.setText(hints.get(mode, ""))
        self.inspect_readout.connect(self.status.setText)

    def keyPressEvent(self, a0) -> None:
        if (a0 is not None and a0.key() == Qt.Key.Key_Escape
                and self.canvas.crop_active):
            self.cancel_crop()
            a0.accept()
            return
        super().keyPressEvent(a0)

    def resize_dialog(self) -> None:
        from .image_resize import ResizeDialog
        dialog = ResizeDialog(self.current.width, self.current.height, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            w, h = dialog.result_size()
            self.add_op("resize", width=w, height=h,
                        keep_aspect=dialog.keep_aspect(),
                        resample=dialog.resample_name())

    def canvas_dialog(self) -> None:
        from .image_resize import CanvasDialog
        dialog = CanvasDialog(self.current.width, self.current.height, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.add_op("canvas", **dialog.values())

    def straighten_dialog(self) -> None:
        angle, ok = QInputDialog.getDouble(
            self, "Straighten", "Angle (degrees):", 0, -45, 45, 1)
        if ok and abs(angle) > 0.01:
            self.add_op("straighten", angle=angle)

    def watermark_dialog(self) -> None:
        from .image_resize import WatermarkDialog
        dialog = WatermarkDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values.get("text") and not values.get("image"):
            QMessageBox.information(self, "Watermark",
                                    "Enter text or choose an image first.")
            return
        self.add_op("watermark", **values)

    def export_file(self) -> None:
        from .image_resize import ExportDialog
        dialog = ExportDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "Export image", str(self.path),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)")
        if not target:
            return
        img = self.current
        edge = dialog.max_edge.value()
        if edge:
            img = ib.apply_ops(img, [ib.Op("thumbnail", {"size": edge})])
        try:
            ib.save(img, target, quality=dialog.quality.value(),
                    keep_exif=not dialog.strip.isChecked(), source=self.original)
        except ib.ImageError as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return
        self.status.setText(f"Exported {Path(target).name}")

    def set_markup_mode(self, kind: str) -> None:
        self.canvas.markup.set_mode(kind)
        self.status.setText("Markup off." if kind == "off" else f"Markup: {kind}")

    def _markup_done(self, kind, points, color, text) -> None:
        self.add_op("draw", kind=kind, points=points, color=color, text=text)
        self.canvas.markup.set_mode("off")

    def _on_adjust(self, name: str, args: dict) -> None:
        self.ops = [op for op in self.ops if op.name != name]
        self.add_op(name, **args)
        self._adjust_keys.add(name)

    def _on_adjust_toggle(self, name: str, on: bool) -> None:
        self.ops = [op for op in self.ops if op.name != name]
        if on:
            self.add_op(name)
        else:
            self._persist()
            self._reapply()

    def _reset_adjust(self) -> None:
        names = {"brightness", "contrast", "saturation", "sharpness", "gamma",
                 "exposure", "temperature", "tint", "hue", "opacity",
                 "levels", "curves", "grayscale", "invert"}
        self.ops = [op for op in self.ops if op.name not in names]
        self._persist()
        self._reapply()

    def _siblings(self) -> list[Path]:
        from ..core.mime import IMAGE_EXTS
        parent = self.path.parent
        return sorted(p for p in parent.iterdir()
                      if p.is_file() and p.suffix.lower() in IMAGE_EXTS)

    def next_image(self) -> None:
        sibs = self._siblings()
        if self.path in sibs:
            i = (sibs.index(self.path) + 1) % len(sibs)
            self._open_sibling(sibs[i])

    def prev_image(self) -> None:
        sibs = self._siblings()
        if self.path in sibs:
            i = (sibs.index(self.path) - 1) % len(sibs)
            self._open_sibling(sibs[i])

    def _open_sibling(self, path: Path) -> None:
        if self.is_modified():
            choice = QMessageBox.question(
                self, "Unsaved edits",
                "Save edits before switching image?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Save and not self.save():
                return
        self.reload_from(path)
        self._fill_film()

    def _fill_film(self) -> None:
        self.film.clear()
        for p in self._siblings()[:80]:
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            self.film.addItem(item)

    def _film_open(self, item) -> None:
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if path != self.path:
            self._open_sibling(path)

    def slideshow(self) -> None:
        from PyQt6.QtCore import QTimer
        if self._slideshow is not None:
            self._slideshow.stop()
            self._slideshow = None
            self.status.setText("Slideshow stopped.")
            return
        self._slideshow = QTimer(self)
        self._slideshow.setInterval(3000)
        self._slideshow.timeout.connect(self.next_image)
        self._slideshow.start()
        self.status.setText("Slideshow — next image every 3s.")

    def _maybe_animate(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if not self.info.is_animated:
            return
        try:
            self._frames = [pil_to_qpixmap(f) for f in ib.load_frames(self.path)]
            self._durations = ib.frame_durations(self.path)
        except Exception:
            self._frames = []
            self._durations = []
            return
        if len(self._frames) < 2:
            return
        self._anim_i = 0
        self._anim = QTimer(self)
        self._anim.setSingleShot(True)
        self._anim.timeout.connect(self._anim_tick)
        self._schedule_frame()

    def _schedule_frame(self) -> None:
        if self._anim is None:
            return
        idx = self._anim_i % len(self._durations) if self._durations else 0
        ms = self._durations[idx] if self._durations else 100
        self._anim.start(max(20, ms))

    def _anim_tick(self) -> None:
        if not self._frames:
            return
        self._anim_i = (self._anim_i + 1) % len(self._frames)
        self.canvas.set_image(self._frames[self._anim_i])
        self._schedule_frame()

    def print_file(self) -> None:
        from PyQt6.QtGui import QPainter
        from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter()
        if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
            return
        painter = QPainter(printer)
        pix = pil_to_qpixmap(self.current)
        painter.drawPixmap(0, 0, pix.scaled(painter.viewport().size(),
                                            Qt.AspectRatioMode.KeepAspectRatio))
        painter.end()

    # --- saving ----------------------------------------------------------
    def is_modified(self) -> bool:
        return bool(self.ops)

    def save(self) -> bool:
        if self.ops and self.path.exists() and self.isVisible():
            choice = QMessageBox.question(
                self, "Overwrite file",
                f"Overwrite {self.path.name} with the edited image?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                return False
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
        # The edits are now baked into the file; drop the persisted stack and
        # track any future edits against the newly saved file.
        try:
            self._history.clear(self._source_path)
        except Exception:
            pass
        self._source_path = Path(target)
        self.modified_changed.emit(False)
        self.status.setText(f"Saved {target.name}")
        return True
