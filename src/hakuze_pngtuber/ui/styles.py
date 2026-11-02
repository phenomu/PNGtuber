"""Cyberpunk dark QSS stylesheet for the settings window."""

# NOTE: this module has no imports; it only holds the stylesheet string.

STYLESHEET = """
* {
    font-family: 'Segoe UI', 'Inter', sans-serif;
    color: #d7f6ff;
}
QMainWindow, QDialog, QWidget#root {
    background-color: #0b0e17;
}
QLabel#title {
    font-size: 20px;
    font-weight: 700;
    color: #21e6ff;
    letter-spacing: 2px;
}
QLabel#subtitle {
    color: #7f8fa6;
    font-size: 11px;
}
QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 18px;
}
QLabel#sectionHeader {
    color: #b96bff;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.5px;
}
QLabel#stateLabel {
    font-size: 15px;
    font-weight: 700;
    color: #21e6ff;
}
QLabel#warningLabel {
    color: #ffb86c;
}
QTabWidget::pane {
    border: 1px solid #1e2740;
    border-radius: 10px;
    background: #0d1220;
    top: -1px;
}
QTabBar::tab {
    background: #0d1220;
    color: #7f8fa6;
    padding: 8px 18px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border: 1px solid #1e2740;
    border-bottom: none;
    font-size: 12px;
    font-weight: 600;
}
QTabBar::tab:selected {
    color: #21e6ff;
    background: #131a2e;
    border-color: #21e6ff;
}
QTabBar::tab:hover:!selected {
    color: #b96bff;
}
QFrame#line {
    background: #1e2740;
    max-height: 1px;
    border: none;
}
QFrame#panel {
    background: #0d1220;
    border: 1px solid #1e2740;
    border-radius: 12px;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #1e2740;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #21e6ff, stop:1 #b96bff);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #e8f9ff;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
    border: 2px solid #21e6ff;
}
QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0f1526;
    border: 1px solid #263252;
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 24px;
    color: #d7f6ff;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #0f1526;
    border: 1px solid #263252;
    selection-background-color: #1a2340;
    selection-color: #21e6ff;
    max-height: 330px;
}
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #0891b2, stop:1 #0d5c8f);
    color: #e8fbff;
    border: 1px solid #21e6ff;
    border-radius: 9px;
    padding: 10px 18px;
    font-weight: 600;
    font-size: 12px;
    min-height: 18px;
}
QPushButton:hover {
    background: #0aa3cc;
}
QPushButton:pressed {
    background: #067a9e;
}
QPushButton#danger {
    background: #2a1030;
    border-color: #ff5c8a;
    color: #ffd2e0;
}
QPushButton#danger:hover {
    background: #3d1535;
}
QPushButton#flat {
    background: transparent;
    border: 1px solid #263252;
    color: #8fa3c0;
}
QPushButton#flat:hover {
    border-color: #21e6ff;
    color: #21e6ff;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid #263252;
    background: #0f1526;
}
QCheckBox::indicator:checked {
    background: #21e6ff;
    border-color: #21e6ff;
    image: none;
}
QProgressBar {
    background: #0f1526;
    border: 1px solid #263252;
    border-radius: 7px;
    height: 10px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #21e6ff, stop:1 #b96bff);
    border-radius: 6px;
}
QStatusBar {
    background: transparent;
    color: #7f8fa6;
}
QStatusBar QLabel {
    color: #7f8fa6;
}
QToolTip {
    background: #131a2e;
    color: #d7f6ff;
    border: 1px solid #21e6ff;
    border-radius: 6px;
    padding: 4px;
}
"""
