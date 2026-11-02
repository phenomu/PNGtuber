"""Transparent frameless avatar overlay window.

Renders the avatar on a fully transparent canvas. OBS Window Capture
(method: Windows 10 (1903+) / BitBlt) picks it up with alpha preserved.
Mouse is click-through via WS_EX_TRANSPARENT unless edit mode is on.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ..core.animation_engine import AnimationEngine
from ..core.asset_manager import AssetManager
from ..utils.image_utils import desaturate
from ..utils.platform_utils import set_click_through


def pil_to_qpixmap(pil_img) -> QPixmap:
    """Convert a PIL RGBA image to QPixmap without extra copies."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, pil_img.width * 4,
                  QImage.Format_RGBA8888)
    # QImage does not own the buffer; copy into QPixmap to detach
    return QPixmap.fromImage(qimg.copy())


class AvatarOverlay(QWidget):
    """Transparent always-on-top overlay showing the avatar."""

    state_changed = Signal(bool)  # emitted on every talk/idle flip

    def __init__(self, assets: AssetManager, animation: AnimationEngine,
                 settings, parent: QWidget | None = None):
        super().__init__(None,
                         Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Hakuze PNGtuber Overlay")

        self._assets = assets
        self._anim = animation
        self._settings = settings
        self._idle_pm: QPixmap | None = None
        self._talk_pm: QPixmap | None = None
        self._idle_gray_pm: QPixmap | None = None
        self._talking = False
        self._edit_mode = False
        self._drag_offset = None
        self._frame_count = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setTimerType(Qt.PreciseTimer)

        self.reload_assets()
        self._apply_window_flags()

    # ------------------------------------------------------------------
    def reload_assets(self) -> None:
        idle, talk = self._assets.get_images()
        self._idle_pil = idle
        self._talk_pil = talk
        self._idle_pm = pil_to_qpixmap(idle)
        self._talk_pm = pil_to_qpixmap(talk)
        self._refresh_gray()
        self._relayout()

    def _refresh_gray(self) -> None:
        gray = desaturate(self._idle_pil,
                          float(self._settings.get("avatar.grayscale_intensity", 0.85)))
        self._idle_gray_pm = pil_to_qpixmap(gray)

    def _relayout(self) -> None:
        screen_h = 1080
        screen = self.screen() or None
        if screen is not None:
            screen_h = screen.availableGeometry().height()
        base_h = int(screen_h * 0.45)
        base_w = base_h
        self._base_size = (base_w, base_h)
        scale = float(self._settings.get("avatar.scale", 0.55))
        self._disp_w = max(40, int(base_w * scale))
        self._disp_h = max(40, int(base_h * scale))
        self._idle_scaled = scale_contain_pixmap(self._idle_gray_pm, self._disp_w, self._disp_h)
        self._talk_scaled = scale_contain_pixmap(self._talk_pm, self._disp_w, self._disp_h)
        self.setFixedSize(self._disp_w + 80, self._disp_h + 120)
        pos_x = int(self._settings.get("avatar.pos_x", 120))
        pos_y = int(self._settings.get("avatar.pos_y", 120))
        self.move(pos_x, pos_y)

    def _apply_window_flags(self) -> None:
        on_top = bool(self._settings.get("overlay.always_on_top", True))
        flags = (Qt.FramelessWindowHint | Qt.Tool)
        if on_top or self._edit_mode:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._update_click_through()

    def _update_click_through(self) -> None:
        click_through = bool(self._settings.get("overlay.click_through", True))
        enable = click_through and not self._edit_mode
        hwnd = int(self.winId()) if self.isVisible() else 0
        if hwnd:
            set_click_through(hwnd, enable)

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_click_through()
        self._timer.start(16)  # ~60 FPS target

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = bool(enabled)
        self._apply_window_flags()
        self.show()
        self._update_click_through()

    def set_state(self, talking: bool) -> None:
        if talking != self._talking:
            self._talking = talking
            self.state_changed.emit(talking)

    def update_display_size(self) -> None:
        self._relayout()
        self.update()

    def refresh_look(self) -> None:
        """Re-render pixmaps after grayscale/scale/image changes."""
        if getattr(self, "_idle_pil", None) is None:
            self.reload_assets()
            return
        self._refresh_gray()
        self._relayout()
        self.update()

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._frame_count += 1
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        offset_y = 0.0
        if self._anim is not None:
            import time
            t_ms = time.monotonic() * 1000.0
            frame = self._anim.frame(self._talking, t_ms)
            offset_y = frame.offset_y
        pm = self._talk_scaled if self._talking else self._idle_scaled
        if pm is None or pm.isNull():
            return
        # anchor: horizontal center, bottom of canvas - avatar sits on a floor line
        x = (self.width() - pm.width()) / 2.0
        y = self.height() - pm.height() - 60.0 - offset_y
        painter.drawPixmap(QPointF(x, y), pm)

    # --- drag support for edit mode -------------------------------------
    def mousePressEvent(self, event) -> None:
        if self._edit_mode and event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._edit_mode and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._edit_mode and self._drag_offset is not None:
            self._drag_offset = None
            self.save_position()
            self.position_saved.emit()
        else:
            super().mouseReleaseEvent(event)

    position_saved = Signal()

    def save_position(self) -> None:
        self._settings.set("avatar.pos_x", self.x())
        self._settings.set("avatar.pos_y", self.y())

    def stop(self) -> None:
        self._timer.stop()
        self.hide()


def scale_contain_pixmap(pm: QPixmap | None, max_w: int, max_h: int) -> QPixmap | None:
    if pm is None or pm.isNull():
        return pm
    if pm.width() <= max_w and pm.height() <= max_h:
        return pm
    return pm.scaled(max_w, max_h,
                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
