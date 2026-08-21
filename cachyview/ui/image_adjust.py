"""Live Adjust Color panel — writes into the image tab's Op stack."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QLabel, QPushButton, QSlider,
                             QVBoxLayout, QWidget)


class _Slider(QWidget):
    changed = pyqtSignal(str, float)

    def __init__(self, key: str, label: str, lo: int, hi: int, zero: int,
                 parent=None):
        super().__init__(parent)
        self.key = key
        self.zero = zero
        self.lo, self.hi = lo, hi
        self.cap = QLabel(label, self)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(lo, hi)
        self.slider.blockSignals(True)
        self.slider.setValue(zero)
        self.slider.blockSignals(False)
        self.slider.valueChanged.connect(self._emit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.cap)
        layout.addWidget(self.slider)

    def _emit(self, value: int) -> None:
        self.changed.emit(self.key, float(value))

    def reset(self) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self.zero)
        self.slider.blockSignals(False)


class AdjustPanel(QWidget):
    """Brightness/contrast/etc. Values are mapped onto backend Op args."""

    adjusted = pyqtSignal(str, dict)   # op name, args
    toggled = pyqtSignal(str, bool)    # grayscale / invert
    reset_all = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.sliders: dict[str, _Slider] = {}
        specs = [
            ("brightness", "Brightness", 25, 250, 100),
            ("contrast", "Contrast", 25, 250, 100),
            ("saturation", "Saturation", 0, 250, 100),
            ("sharpness", "Sharpness", 0, 250, 100),
            ("gamma", "Gamma", 30, 250, 100),
            ("exposure", "Exposure (EV×10)", -30, 30, 0),
            ("temperature", "Temperature", -100, 100, 0),
            ("tint", "Tint", -100, 100, 0),
            ("hue", "Hue", -180, 180, 0),
            ("opacity", "Opacity", 0, 100, 100),
        ]
        for key, label, lo, hi, zero in specs:
            sl = _Slider(key, label, lo, hi, zero, self)
            sl.changed.connect(self._on_slider)
            self.sliders[key] = sl
            layout.addWidget(sl)
        self.gray = QCheckBox("Grayscale", self)
        self.invert = QCheckBox("Invert", self)
        self.gray.toggled.connect(lambda v: self.toggled.emit("grayscale", v))
        self.invert.toggled.connect(lambda v: self.toggled.emit("invert", v))
        layout.addWidget(self.gray)
        layout.addWidget(self.invert)
        reset = QPushButton("Reset adjustments", self)
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)
        layout.addStretch(1)

    def _on_slider(self, key: str, value: float) -> None:
        sl = self.sliders[key]
        if key in ("brightness", "contrast", "saturation", "sharpness", "gamma"):
            self.adjusted.emit(key, {"value": value / 100.0})
        elif key == "exposure":
            self.adjusted.emit(key, {"value": value / 10.0})
        elif key == "opacity":
            self.adjusted.emit(key, {"value": value / 100.0})
        else:
            self.adjusted.emit(key, {"value": value})
        _ = sl

    def _reset(self) -> None:
        for sl in self.sliders.values():
            sl.reset()
        self.gray.setChecked(False)
        self.invert.setChecked(False)
        self.reset_all.emit()
