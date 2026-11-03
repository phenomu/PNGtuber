"""Animated dialogue bubble above the avatar (child of AvatarOverlay).

One QTimer drives the typewriter reveal (no per-character timers). Text
is rendered with QPainter.drawPlainText-style layout — never rich text,
never HTML: LLM output is always treated as plain, safe text. Streaming
deltas append to the full text while the reveal catches up.

The bubble never touches the avatar pixmaps; it lives in the extra
margin the overlay reserves above the character. The overlay grows the
window upward while the bubble is visible (click-through, so the larger
transparent window is harmless to gameplay).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

_ELLIPSIS = "\u2026"


def _elided_lines(text: str, max_lines: int, font: QFont, max_width: int,
                  painter: QPainter) -> list[str]:
    """Wrap `text` to widget lines, clamp to max_lines with ellipsis.
    Layout is word-based and Unicode-safe; never interprets markup."""
    lines: list[str] = []
    for raw_line in text.split("\n"):
        raw_line = raw_line.rstrip()
        if not raw_line:
            lines.append("")
            continue
        current = ""
        for word in raw_line.split(" "):
            candidate = f"{current} {word}".strip()
            if painter.fontMetrics().horizontalAdvance(candidate) <= max_width \
                    or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    if len(lines) > max_lines:
        cut = lines[:max_lines]
        last = cut[-1]
        while last and painter.fontMetrics().horizontalAdvance(
                last + _ELLIPSIS) > max_width:
            last = last[:-1]
        cut[-1] = last + _ELLIPSIS if last else _ELLIPSIS
        return cut
    return lines


class DialogueBubble(QWidget):
    """Cyberpunk speech bubble with typewriter + streaming support."""

    hidden = Signal()          # fully hidden (after fade-out)
    fully_revealed = Signal()  # typewriter finished

    def __init__(self, parent: QWidget, width: int = 420,
                 max_lines: int = 6, font_size: int = 14,
                 typewriter_ms: int = 24, display_duration_s: float = 8.0,
                 opacity: float = 0.88, bg_opacity: float = 0.88):
        super().__init__(parent)
        self._full_text = ""
        self._revealed = 0
        self._visible_state = False
        self._fade = 0.0                 # 0..1 paint alpha multiplier
        self._persistent = display_duration_s <= 0
        self._display_s = float(display_duration_s)
        self._thinking = False
        self._think_dots = 0

        self.setBubbleStyle(width=width, max_lines=max_lines,
                            font_size=font_size, typewriter_ms=typewriter_ms,
                            opacity=opacity, bg_opacity=bg_opacity)

        self._typewriter = QTimer(self)
        self._typewriter.timeout.connect(self._tick_reveal)
        self._think_timer = QTimer(self)
        self._think_timer.timeout.connect(self._tick_think)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.begin_hide)
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._tick_fade)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    # ------------------------------------------------------------- config
    def setBubbleStyle(self, width: int = 420, max_lines: int = 6,
                       font_size: int = 14, typewriter_ms: int = 24,
                       display_duration_s: float | None = None,
                       opacity: float | None = None,
                       bg_opacity: float | None = None) -> None:
        self._width = max(200, min(900, int(width)))
        self._max_lines = max(1, min(30, int(max_lines)))
        self._font_size = max(9, min(32, int(font_size)))
        self._typewriter_ms = max(0, min(200, int(typewriter_ms)))
        if display_duration_s is not None:
            self._display_s = max(0.0, float(display_duration_s))
            self._persistent = self._display_s <= 0
        if opacity is not None:
            self._opacity = max(0.05, min(1.0, float(opacity)))
        if bg_opacity is not None:
            self._bg_opacity = max(0.05, min(1.0, float(bg_opacity)))
        self.setFont(QFont("Segoe UI", self._font_size))
        self._recalc_size()

    def _recalc_size(self) -> None:
        line_h = self.fontMetrics().height() + 2
        pad_v = 18
        height = pad_v * 2 + line_h * self._max_lines + 14  # + tail
        self._height = height
        self.resize(self._width, height)

    def sizeHint(self):
        return self.size()

    # ------------------------------------------------------------- show
    def show_text(self, text: str = "") -> None:
        """Start a new response: clear, show, optional initial text."""
        self._full_text = text or ""
        self._revealed = 0 if self._typewriter_ms > 0 else len(self._full_text)
        self._visible_state = True
        self._fade = 1.0
        self._layout()
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        if self._typewriter_ms > 0 and self._revealed < len(self._full_text):
            self._hide_timer.stop()
            self._typewriter.start(self._typewriter_ms)
            self._tick_reveal()
        else:
            self._start_hide_timer()

    def show_thinking(self) -> None:
        """Cloud-style 'sedang berpikir...' indicator while the LLM runs.

        Replaced by the real bubble on the first streamed delta."""
        self._full_text = ""
        self._revealed = 0
        self._thinking = True
        self._visible_state = True
        self._fade = 1.0
        self._layout()
        self.show()
        self.raise_()
        self._hide_timer.stop()
        self._typewriter.stop()
        self._think_timer.start(450)   # animate the dots

    def _tick_think(self) -> None:
        self._think_dots = (self._think_dots + 1) % 4
        self.update()

    def _paint_thinking(self, painter: QPainter, alpha: float) -> None:
        """Cloud bubble with animated 'sedang berpikir' + dots."""
        w, h = 230.0, 74.0
        x = (self._width - w) / 2.0
        y = 2.0
        cloud = QPainterPath()
        # main puffy body: 3 arcs unioned
        for cx, cy, r in ((x + 52, y + 38, 34),
                          (x + 108, y + 30, 40),
                          (x + 168, y + 40, 32)):
            cloud.addEllipse(QPointF(cx, cy), r, r)
        # flat-ish bottom edge
        bottom = QRectF(x + 20, y + 44, w - 40, 26)
        cloud.addRoundedRect(bottom, 22, 22)
        # small tail puff toward the character
        cloud.addEllipse(QPointF(x + w / 2 + 6, y + h + 2), 7, 7)
        cloud.addEllipse(QPointF(x + w / 2 - 8, y + h + 12), 5, 5)

        body = QColor(20, 26, 42, int(215 * self._bg_opacity * self._fade))
        border = QColor(33, 230, 255, int(235 * alpha))
        painter.setPen(QPen(border, 2))
        painter.setBrush(body)
        painter.drawPath(cloud.simplified())
        # text + animated dots
        text = "sedang berpikir" + "." * self._think_dots
        painter.setFont(self.font())
        painter.setPen(QColor(215, 246, 255, int(255 * alpha)))
        painter.drawText(QPointF(x + 34, y + 42), text)

    def _stop_thinking(self) -> None:
        self._think_timer.stop()
        self._thinking = False
        self._think_dots = 0

    def append_delta(self, delta: str) -> None:
        """Streaming: append text; reveal catches up."""
        if not delta:
            return
        if self._thinking:
            self._stop_thinking()   # first delta: replace the indicator
        if not self._visible_state:
            self.show_text()
            return
        self._full_text += delta
        if self._typewriter_ms <= 0:
            self._revealed = len(self._full_text)
            self._layout()
            self.update()
            return
        if not self._typewriter.isActive() and \
                self._revealed < len(self._full_text):
            self._typewriter.start(self._typewriter_ms)
        self._layout()
        self.update()

    def complete_text(self, text: str | None = None) -> None:
        """Response finished: keep the typewriter reveal going (it catches
        up), schedule hide AFTER the reveal completes."""
        if text is not None:
            self._full_text = text
        if self._thinking:
            self._stop_thinking()
        self._visible_state = True
        if not self.isVisible():
            self._fade = 1.0
            self.show()
        if self._typewriter_ms <= 0:
            self._revealed = len(self._full_text)
            self._layout()
            self._start_hide_timer()
        elif self._revealed >= len(self._full_text):
            # already fully revealed -> hide timer directly
            self._typewriter.stop()
            self._start_hide_timer()
        else:
            # still typing: _tick_reveal schedules the hide at the end
            if not self._typewriter.isActive():
                self._typewriter.start(self._typewriter_ms)
        self.update()
        if self._revealed >= len(self._full_text):
            self.fully_revealed.emit()

    def _start_hide_timer(self) -> None:
        self._typewriter.stop()
        if self._persistent:
            self._hide_timer.stop()
        else:
            self._hide_timer.start(int(self._display_s * 1000))

    def begin_hide(self) -> None:
        self._hide_timer.stop()
        self._typewriter.stop()
        self._stop_thinking()
        self._fade_timer.start(30)

    def hide_immediately(self) -> None:
        self._typewriter.stop()
        self._hide_timer.stop()
        self._fade_timer.stop()
        self._stop_thinking()
        self._visible_state = False
        self._fade = 0.0
        self.hide()
        self._full_text = ""
        self._revealed = 0
        self.hidden.emit()

    def cancel(self) -> None:
        self.hide_immediately()

    # ------------------------------------------------------------- timers
    def _tick_reveal(self) -> None:
        if self._revealed >= len(self._full_text):
            self._typewriter.stop()
            self.fully_revealed.emit()
            self._start_hide_timer()
            return
        # reveal 1..N chars per tick so long text still animates fast
        step = max(1, len(self._full_text) // 60)
        self._revealed = min(len(self._full_text), self._revealed + step)
        self._layout()
        self.update()

    def _tick_fade(self) -> None:
        self._fade -= 0.15
        if self._fade <= 0.0:
            self._fade = 0.0
            self._fade_timer.stop()
            self._visible_state = False
            self.hide()
            self._full_text = ""
            self._revealed = 0
            self.hidden.emit()
        self.update()

    # ------------------------------------------------------------- layout
    def _layout(self) -> None:
        """Position inside the parent: horizontally centered, top margin 2."""
        parent = self.parentWidget()
        if parent is not None:
            x = (parent.width() - self._width) // 2
            self.setGeometry(x, 2, self._width, self._height)

    def current_text(self) -> str:
        return self._full_text

    def is_showing(self) -> bool:
        return self._visible_state or self.isVisible()

    # ------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        if not self._visible_state and self._fade <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        alpha = self._opacity * self._fade

        if self._thinking:
            self._paint_thinking(painter, alpha)
            return

        # bubble body
        rect = QRectF(1.0, 1.0, float(self._width - 2), float(self._height - 16))
        path = QPainterPath()
        radius = 14.0
        path.addRoundedRect(rect, radius, radius)
        # tail pointing down toward the character
        tail = QPainterPath()
        cx = rect.center().x()
        tail.moveTo(cx - 9.0, rect.bottom() - 1.0)
        tail.lineTo(cx, rect.bottom() + 12.0)
        tail.lineTo(cx + 9.0, rect.bottom() - 1.0)
        tail.closeSubpath()

        body = QColor(13, 18, 32, int(224 * self._bg_opacity * self._fade))
        border = QColor(33, 230, 255, int(255 * alpha))
        painter.setPen(QPen(border, 2))
        painter.setBrush(body)
        painter.drawPath(path.united(tail))
        # purple accent underline
        accent = QColor(185, 107, 255, int(220 * alpha))
        painter.setPen(QPen(accent, 2))
        underline = QRectF(rect.left() + 14, rect.top() + 5,
                           46.0, 3.0)
        painter.drawRoundedRect(underline, 1.5, 1.5)

        # text (plain rendering — markup is never interpreted)
        shown = self._full_text[:self._revealed]
        painter.setFont(self.font())
        painter.setPen(QColor(215, 246, 255, int(255 * alpha)))
        lines = _elided_lines(shown, self._max_lines, self.font(),
                              int(rect.width()) - 24, painter)
        line_h = self.fontMetrics().height() + 2
        y = rect.top() + 14
        for line in lines:
            painter.drawText(QPointF(rect.left() + 12.0, y + line_h - 6),
                             line.replace("\u2028", " "))
            y += line_h
        # caret while typing
        if self._typewriter.isActive() and self._revealed < len(self._full_text):
            painter.setPen(QPen(QColor(33, 230, 255, int(200 * alpha)), 2))
            painter.drawText(QPointF(rect.left() + 12.0, y + line_h - 6), "|")
