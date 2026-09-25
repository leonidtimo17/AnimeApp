"""Полоса перемотки: клик в любое место, превью времени, отметки опенинга/эндинга."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QSlider

from ...core.formatting import fmt_ms
from ..theme import ACCENT


class SeekBar(QSlider):
    """Полоса перемотки: клик в любое место, превью времени, отметки опенинга/эндинга."""

    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMouseTracking(True)
        self.setFixedHeight(26)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marks = []           # [(start_ms, stop_ms)]
        self.hover_x = None
        self.dragging = False
        self.buffer = 0.0
        self.tip = QLabel(parent)
        self.tip.setObjectName("SeekTip")
        self.tip.hide()

    def _value_at(self, x):
        w = max(1, self.width())
        return int(self.maximum() * min(max(x, 0), w) / w)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.setValue(self._value_at(e.position().x()))
            e.accept()

    def mouseMoveEvent(self, e):
        self.hover_x = e.position().x()
        if self.dragging:
            self.setValue(self._value_at(self.hover_x))
        self._show_tip()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.seek_requested.emit(self._value_at(e.position().x()))

    def leaveEvent(self, e):
        self.hover_x = None
        self.tip.hide()
        self.update()

    def _show_tip(self):
        if self.hover_x is None or self.maximum() <= 0:
            return
        ms = self._value_at(self.hover_x)
        text = fmt_ms(ms)
        for a, b in self.marks:
            if a <= ms <= b:
                text += "  · заставка" if a < self.maximum() / 2 else "  · титры"
        self.tip.setText(text)
        self.tip.adjustSize()
        p = self.mapTo(self.tip.parentWidget(), QPointF(self.hover_x, 0).toPoint())
        self.tip.move(int(p.x() - self.tip.width() / 2), p.y() - self.tip.height() - 6)
        self.tip.show()
        self.tip.raise_()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        hover = self.hover_x is not None or self.dragging
        bar_h = 6 if hover else 4
        y = (h - bar_h) / 2
        mx = max(1, self.maximum())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(QRectF(0, y, w, bar_h), 2, 2)
        if self.buffer > 0:
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawRoundedRect(QRectF(0, y, w * self.buffer, bar_h), 2, 2)
        for a, b in self.marks:
            p.setBrush(QColor(255, 210, 120, 120))
            p.drawRect(QRectF(w * a / mx, y, max(2, w * (b - a) / mx), bar_h))
        if self.hover_x is not None:
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawRoundedRect(QRectF(0, y, self.hover_x, bar_h), 2, 2)
        played = w * self.value() / mx
        p.setBrush(QColor(ACCENT))
        p.drawRoundedRect(QRectF(0, y, played, bar_h), 2, 2)
        if hover:
            p.setBrush(QColor("white"))
            p.drawEllipse(QPointF(played, h / 2), 7, 7)
        p.end()
