"""Видео через QGraphicsVideoItem — поверх него можно рисовать свой интерфейс."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView


class VideoView(QGraphicsView):
    """Видео через QGraphicsVideoItem — поверх него можно рисовать свой интерфейс."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.item = QGraphicsVideoItem()
        self.item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.scene_.addItem(self.item)
        self.fill = False
        self.setBackgroundBrush(QColor("black"))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

    def set_fill(self, fill):
        """«Заполнить экран» — без чёрных полос, края кадра обрезаются; иначе виден весь кадр."""
        self.fill = fill
        self.item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatioByExpanding if fill
                                     else Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h = self.viewport().width(), self.viewport().height()
        self.scene_.setSceneRect(0, 0, w, h)
        self.item.setSize(QSizeF(w, h))
        self.item.setPos(0, 0)
        self.fitInView(QRectF(0, 0, w, h))
