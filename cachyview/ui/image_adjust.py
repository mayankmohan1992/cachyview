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


class _Multi(QWidget):
    """A titled group of sliders that emits one combined value dict."""

    changed = pyqtSignal(dict)

    def __init__(self, title: str, specs, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(title, self))
        self.sliders: dict[str, _Slider] = {}
        for key, label, lo, hi, zero in specs:
            sl = _Slider(key, label, lo, hi, zero, self)
            sl.changed.connect(self._emit)
            self.sliders[key] = sl
            layout.addWidget(sl)

    def _emit(self, *_args) -> None:
        self.changed.emit({k: int(sl.slider.value())
                           for k, sl in self.sliders.items()})

    def values(self) -> dict[str, int]:
        return {k: int(sl.slider.value()) for k, sl in self.sliders.items()}

    def reset(self) -> None:
        for sl in self.sliders.values():
            sl.reset()


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
        self.levels = _Multi("Levels", [
            ("black", "Black point", 0, 200, 0),
            ("white", "White point", 55, 255, 255),
            ("gamma", "Gamma", 30, 250, 100)], self)
        self.levels.changed.connect(self._on_levels)
        layout.addWidget(self.levels)
        self.curves = _Multi("Curves", [
            ("shadows", "Shadows", -100, 100, 0),
            ("midtones", "Midtones", -100, 100, 0),
            ("highlights", "Highlights", -100, 100, 0)], self)
        self.curves.changed.connect(self._on_curves)
        layout.addWidget(self.curves)
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

    def _on_levels(self, values: dict) -> None:
        self.adjusted.emit("levels", {"black": values["black"],
                                      "white": values["white"],
                                      "gamma": values["gamma"] / 100.0})

    def _on_curves(self, values: dict) -> None:
        def out(base: int) -> int:
            shift = int(values_shift(values, base) * 1.27)
            return max(0, min(255, base + shift))
        points = [(0, 0), (64, out(64)), (128, out(128)), (192, out(192)),
                  (255, 255)]
        self.adjusted.emit("curves", {"points": points})

    def _reset(self) -> None:
        for sl in self.sliders.values():
            sl.reset()
        self.levels.reset()
        self.curves.reset()
        self.gray.setChecked(False)
        self.invert.setChecked(False)
        self.reset_all.emit()


def values_shift(values: dict, base: int) -> int:
    """Map the shadow/midtone/highlight slider for *base* to a −100..100 shift."""
    if base <= 85:
        return int(values.get("shadows", 0))
    if base >= 170:
        return int(values.get("highlights", 0))
    return int(values.get("midtones", 0))
