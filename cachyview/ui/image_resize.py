"""Resize / canvas / export dialogs for the image tab."""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                             QWidget)


class ResizeDialog(QDialog):
    def __init__(self, width: int, height: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Resize image")
        self._ow, self._oh = width, height
        self._lock = True

        self.w = QSpinBox(self)
        self.w.setRange(1, 100000)
        self.w.setValue(width)
        self.h = QSpinBox(self)
        self.h.setRange(1, 100000)
        self.h.setValue(height)
        self.pct = QSpinBox(self)
        self.pct.setRange(1, 1000)
        self.pct.setValue(100)
        self.pct.setSuffix("%")
        self.lock = QCheckBox("Keep aspect ratio", self)
        self.lock.setChecked(True)
        self.resample = QComboBox(self)
        self.resample.addItems(["Lanczos (best)", "Bicubic", "Nearest (pixel art)"])
        self.preview = QLabel(self)

        self.w.valueChanged.connect(self._from_width)
        self.h.valueChanged.connect(self._from_height)
        self.pct.valueChanged.connect(self._from_pct)
        self.lock.toggled.connect(lambda v: setattr(self, "_lock", v))

        form = QFormLayout()
        form.addRow("Width", self.w)
        form.addRow("Height", self.h)
        form.addRow("Scale", self.pct)
        form.addRow(self.lock)
        form.addRow("Resample", self.resample)
        form.addRow(self.preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._update_label()

    def _from_width(self, value: int) -> None:
        if self._lock:
            self.h.blockSignals(True)
            self.h.setValue(max(1, round(self._oh * value / self._ow)))
            self.h.blockSignals(False)
        self._sync_pct()
        self._update_label()

    def _from_height(self, value: int) -> None:
        if self._lock:
            self.w.blockSignals(True)
            self.w.setValue(max(1, round(self._ow * value / self._oh)))
            self.w.blockSignals(False)
        self._sync_pct()
        self._update_label()

    def _from_pct(self, value: int) -> None:
        self.w.blockSignals(True)
        self.h.blockSignals(True)
        self.w.setValue(max(1, round(self._ow * value / 100)))
        self.h.setValue(max(1, round(self._oh * value / 100)))
        self.w.blockSignals(False)
        self.h.blockSignals(False)
        self._update_label()

    def _sync_pct(self) -> None:
        self.pct.blockSignals(True)
        self.pct.setValue(max(1, round(self.w.value() / self._ow * 100)))
        self.pct.blockSignals(False)

    def _update_label(self) -> None:
        self.preview.setText(
            f"{self._ow}×{self._oh} → {self.w.value()}×{self.h.value()}")

    def result_size(self) -> tuple[int, int]:
        return self.w.value(), self.h.value()

    def keep_aspect(self) -> bool:
        return self.lock.isChecked()

    def resample_name(self) -> str:
        return ("lanczos", "bicubic", "nearest")[self.resample.currentIndex()]


class CanvasDialog(QDialog):
    def __init__(self, width: int, height: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Canvas size")
        self.w = QSpinBox(self)
        self.w.setRange(1, 100000)
        self.w.setValue(width)
        self.h = QSpinBox(self)
        self.h.setRange(1, 100000)
        self.h.setValue(height)
        self.anchor = QComboBox(self)
        self.anchor.addItems([
            "center", "top-left", "top", "top-right", "left", "right",
            "bottom-left", "bottom", "bottom-right"])
        self.fill = QComboBox(self)
        self.fill.addItems(["#ffffff", "#000000", "#00000000"])
        form = QFormLayout()
        form.addRow("Width", self.w)
        form.addRow("Height", self.h)
        form.addRow("Anchor", self.anchor)
        form.addRow("Fill", self.fill)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {"width": self.w.value(), "height": self.h.value(),
                "anchor": self.anchor.currentText(),
                "fill": self.fill.currentText()}


class ExportDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Export image")
        self.quality = QSpinBox(self)
        self.quality.setRange(1, 100)
        self.quality.setValue(92)
        self.strip = QCheckBox("Strip EXIF", self)
        self.max_edge = QSpinBox(self)
        self.max_edge.setRange(0, 100000)
        self.max_edge.setValue(0)
        self.max_edge.setSpecialValueText("no limit")
        form = QFormLayout()
        form.addRow("JPEG/WebP quality", self.quality)
        form.addRow("Longest edge (px)", self.max_edge)
        form.addRow(self.strip)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)


class WatermarkDialog(QDialog):
    """Choose an image and/or text watermark and where it goes."""

    POSITIONS = ["bottom-right", "bottom-left", "bottom", "top-right",
                 "top-left", "top", "center"]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Watermark")
        self.text = QLineEdit(self)
        self.text.setPlaceholderText("optional text")
        self.image = QLineEdit(self)
        self.image.setPlaceholderText("optional image/logo")
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._pick)
        row = QHBoxLayout()
        row.addWidget(self.image, 1)
        row.addWidget(browse)
        self.position = QComboBox(self)
        self.position.addItems(self.POSITIONS)
        self.opacity = QSpinBox(self)
        self.opacity.setRange(1, 100)
        self.opacity.setValue(50)
        self.opacity.setSuffix("%")
        self.scale = QSpinBox(self)
        self.scale.setRange(1, 100)
        self.scale.setValue(20)
        self.scale.setSuffix("% of width")
        self.size = QSpinBox(self)
        self.size.setRange(8, 400)
        self.size.setValue(32)
        form = QFormLayout()
        form.addRow("Text", self.text)
        form.addRow("Image", row)
        form.addRow("Position", self.position)
        form.addRow("Opacity", self.opacity)
        form.addRow("Image scale", self.scale)
        form.addRow("Text size", self.size)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Watermark image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff)")
        if path:
            self.image.setText(path)

    def values(self) -> dict:
        return {
            "text": self.text.text().strip() or None,
            "image": self.image.text().strip() or None,
            "position": self.position.currentText(),
            "opacity": self.opacity.value() / 100,
            "scale": self.scale.value() / 100,
            "size": self.size.value(),
        }
