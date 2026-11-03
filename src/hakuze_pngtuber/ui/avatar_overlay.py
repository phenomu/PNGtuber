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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dialogue_bubble import DialogueBubble


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

        self._bubble: "DialogueBubble | None" = None
        self._bubble_height = 0

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
        bubble_extra = self._bubble_height if self._bubble is not None else 0
        base_w = self._disp_w + 80
        # the bubble (child widget) is CLIPPED to the window: it must fit
        # horizontally or its text gets cut at both edges
        bubble_w = getattr(self._bubble, "_width", 0) + 40 \
            if self._bubble is not None else 0
        new_w = max(base_w, bubble_w)
        new_h = self._disp_h + 120 + bubble_extra
        pos_x = int(self._settings.get("avatar.pos_x", 120))
        pos_y = int(self._settings.get("avatar.pos_y", 120))
        if self.isVisible():
            # preserve the window CENTER (horizontal) and BOTTOM (vertical):
            # the avatar is painted centered + bottom-anchored, so keeping
            # center+bottom fixed means the character NEVER moves while the
            # window grows for the bubble or shrinks back afterwards.
            center_x = self.x() + self.width() / 2.0
            bottom = self.y() + self.height()
            if bubble_extra == 0:
                # returning to base size: land on the EXACT saved position
                # (center math can drift 1-2 px on odd widths)
                base_center = pos_x + base_w / 2.0
                self.setFixedSize(new_w, new_h)
                self.move(pos_x, bottom - new_h)
                if abs((self.x() + self.width() / 2.0) - base_center) <= 1 \
                        and self.width() == base_w:
                    pass  # exact
                else:
                    self.move(pos_x, bottom - new_h)
            else:
                self.setFixedSize(new_w, new_h)
                self.move(round(center_x - new_w / 2.0), bottom - new_h)
        else:
            self.setFixedSize(new_w, new_h)
            self.move(pos_x, pos_y)
        self._clamp_to_screen()

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
        # store the equivalent NO-BUBBLE window top: bubble growth is
        # upward-only and transient, so anchoring the saved position to
        # the base height keeps drag results stable across bubble show/hide
        base_h = self._disp_h + 120
        self._settings.set("avatar.pos_x", self.x())
        self._settings.set("avatar.pos_y",
                           self.y() + self.height() - base_h)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    # --- assistant dialogue bubble ----------------------------------------
    def ensure_bubble(self) -> "DialogueBubble":
        """Create/return the dialogue bubble child (lazily).

        Also re-applies the grown window geometry whenever the bubble is
        about to show again after a hide: the window shrinks back to the
        base size on hide, and a re-show MUST grow it again or the bubble
        is drawn over the avatar's face (user bug)."""
        from .dialogue_bubble import DialogueBubble
        if self._bubble is None:
            cfg = {
                "width": int(self._settings.get("ai.bubble_width", 420)),
                "max_lines": int(self._settings.get("ai.bubble_max_lines", 6)),
                "font_size": int(self._settings.get("ai.bubble_font_size", 14)),
                "typewriter_ms": int(self._settings.get("ai.bubble_typewriter_ms", 24)),
                "display_duration_s": float(self._settings.get("ai.bubble_duration_s", 8.0)),
                "opacity": float(self._settings.get("ai.bubble_opacity", 0.88)),
            }
            self._bubble = DialogueBubble(self, **cfg)
            self._bubble.hidden.connect(self._on_bubble_hidden)
        if self._bubble_height == 0:
            # re-grow the window for this (re)show — bubble goes above the
            # head, never over the face
            self._bubble_height = self._bubble.height() + 4
            self._relayout()
        return self._bubble

    def refresh_bubble_style(self) -> None:
        if self._bubble is not None:
            self._bubble.setBubbleStyle(
                width=int(self._settings.get("ai.bubble_width", 420)),
                max_lines=int(self._settings.get("ai.bubble_max_lines", 6)),
                font_size=int(self._settings.get("ai.bubble_font_size", 14)),
                typewriter_ms=int(self._settings.get("ai.bubble_typewriter_ms", 24)),
                display_duration_s=float(self._settings.get("ai.bubble_duration_s", 8.0)),
                opacity=float(self._settings.get("ai.bubble_opacity", 0.88)))
            self._bubble_height = self._bubble.height() + 4
            self._relayout()

    def hide_bubble(self) -> None:
        if self._bubble is not None:
            self._bubble.hide_immediately()

    def _on_bubble_hidden(self) -> None:
        self._bubble_height = 0
        # keep window stable-sized; avatar stays anchored via bottom margin
        self._relayout()

    def _clamp_to_screen(self, bubble_active: bool = False) -> None:
        """Intentionally a no-op.

        The user-set avatar position is sacred ('harus tepat seperti yang
        kusetting, tidak boleh berubah'): the window is mostly transparent
        padding, so edges hanging off-screen are harmless. Earlier versions
        clamped the whole window while the bubble was visible, which dragged
        bottom-placed characters upward. The bubble may be partially cut by
        a screen edge in extreme placements — the avatar never moves."""
        return


def scale_contain_pixmap(pm: QPixmap | None, max_w: int, max_h: int) -> QPixmap | None:
    if pm is None or pm.isNull():
        return pm
    if pm.width() <= max_w and pm.height() <= max_h:
        return pm
    return pm.scaled(max_w, max_h,
                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
