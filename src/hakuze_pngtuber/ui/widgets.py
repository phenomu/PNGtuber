"""Reusable widgets: labeled slider rows, level meter, section panels."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class LabeledSlider(QWidget):
    """Slider + live value label; emits value_changed(float)."""

    value_changed = Signal(float)

    def __init__(self, label: str, lo: float, hi: float, value: float,
                 decimals: int = 2, suffix: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._lo, self._hi, self._decimals, self._suffix = lo, hi, decimals, suffix
        self._scale = 10 ** decimals

        self._label = QLabel(label)
        self._value_label = QLabel()
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(int(lo * self._scale), int(hi * self._scale))
        self._slider.setValue(int(value * self._scale))
        self._slider.valueChanged.connect(self._on_slider)
        self._on_slider(self._slider.value())

        row = QHBoxLayout()
        row.addWidget(self._label, 1)
        row.addWidget(self._value_label)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addLayout(row)
        col.addWidget(self._slider)

    def _fmt(self, v: float) -> str:
        return f"{v:.{self._decimals}f}{self._suffix}"

    def _on_slider(self, raw: int) -> None:
        v = raw / self._scale
        self._value_label.setText(self._fmt(v))
        self.value_changed.emit(v)

    def value(self) -> float:
        return self._slider.value() / self._scale

    def set_value(self, v: float) -> None:
        self._slider.setValue(int(v * self._scale))


class LevelMeter(QProgressBar):
    """Peak-style microphone level meter (0..100)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setFormat("")
        self.setTextVisible(False)
        self.setFixedHeight(10)

    def set_level(self, level: float) -> None:
        self.setValue(int(min(1.0, max(0.0, level)) * 100))


class ToggleRow(QWidget):
    """Checkbox row: label left, checkbox right."""

    toggled = Signal(bool)

    def __init__(self, label: str, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._check = QCheckBox(label)
        self._check.setChecked(checked)
        self._check.toggled.connect(self.toggled.emit)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._check)
        row.addStretch(1)

    def set_checked(self, checked: bool) -> None:
        self._check.setChecked(checked)

    def is_checked(self) -> bool:
        return self._check.isChecked()


class NumberBox(QDoubleSpinBox):
    """Small numeric input with bounds."""

    def __init__(self, lo: float, hi: float, value: float, decimals: int = 0,
                 suffix: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setRange(lo, hi)
        self.setDecimals(decimals)
        self.setValue(value)
        if suffix:
            self.setSuffix(f" {suffix}")
        self.setFixedWidth(90)


def section(title: str) -> tuple[QWidget, QVBoxLayout]:
    """Build a rounded panel with a purple section header.

    Returns (panel, content_layout) - add rows to content_layout.
    """
    panel = QWidget()
    panel.setObjectName("panel")
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(14, 10, 14, 12)
    outer.setSpacing(8)
    header = QLabel(title.upper())
    header.setObjectName("sectionHeader")
    outer.addWidget(header)
    return panel, outer
