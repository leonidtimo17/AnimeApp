"""Миниатюра серии: кадр из серии (или затемнённый постер с крупным номером), номер,
галочка «просмотрено», значок «сейчас», полоска прогресса снизу."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from ...infrastructure.images.processing import cover, rounded
from ..icons import icon
from ..theme import ACCENT, SURFACE_2


def episode_thumb(src, w, h, number, fallback, frac=0.0, watched=False, current=False, radius=0) -> QPixmap:
    ok = src is not None and not src.isNull()
    pix = cover(src, w, h) if ok else QPixmap(w, h)
    if not ok:
        pix.fill(QColor(SURFACE_2))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = p.font()
    f.setBold(True)
    if fallback:
        p.fillRect(pix.rect(), QColor(10, 10, 14, 165))
        f.setPixelSize(max(18, h // 3))
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, number)
    elif h >= 100:
        f.setPixelSize(13)
        p.setFont(f)
        rect = p.fontMetrics().boundingRect(number).adjusted(-8, -3, 8, 3)
        rect.moveTopLeft(QPoint(8, 8))
        p.setBrush(QColor(0, 0, 0, 180))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(QColor("white"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, number)
    s = 18 if h < 100 else 20
    if watched:
        p.drawPixmap(w - s - 6, 6, icon("circle-check", "#3fbf6a", s).pixmap(s, s))
    elif current:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawEllipse(w - s - 10, 6, s + 4, s + 4)
        p.drawPixmap(w - s - 6, 10, icon("play", "white", s - 4).pixmap(s - 4, s - 4))
    p.fillRect(0, h - 4, w, 4, QColor(255, 255, 255, 50))
    if frac:
        p.fillRect(0, h - 4, int(w * min(1.0, frac)), 4, QColor(ACCENT))
    p.end()
    return rounded(pix, radius) if radius else pix


class LazyThumbs(QObject):
    """Кадры серий в списке (QListWidget) рисуются и грузятся только для видимых строк.

    У длинных сериалов сотни серий: раньше на каждую рисовалась миниатюра и качался кадр,
    даже если до неё никто не долистает.
    """

    PARAMS = Qt.ItemDataRole.UserRole + 1     # (url, номер, без кадра, доля просмотра, просмотрено, текущая)
    DRAWN = Qt.ItemDataRole.UserRole + 2
    MARGIN_ROWS = 6

    def __init__(self, list_widget: QListWidget, images, w: int, h: int, radius: int):
        super().__init__(list_widget)
        self.list = list_widget
        self.images = images
        self.w, self.h, self.radius = w, h, radius
        blank = QPixmap(w, h)
        blank.fill(Qt.GlobalColor.transparent)
        self._blank = QIcon(blank)
        self._timer = QTimer(self, singleShot=True, interval=50)
        self._timer.timeout.connect(self._draw_visible)
        list_widget.verticalScrollBar().valueChanged.connect(lambda _v: self._timer.start())
        list_widget.viewport().installEventFilter(self)

    def set_row(self, item: QListWidgetItem, url, number, fallback, frac, watched, current=False) -> None:
        item.setData(self.PARAMS, (url, number, fallback, frac, watched, current))
        item.setData(self.DRAWN, False)
        item.setIcon(self._blank)
        self._timer.start()

    def redraw(self, item: QListWidgetItem, **changes) -> None:
        """Изменить отметки строки (текущая, просмотрено) и перерисовать её, если она на экране."""
        url, number, fallback, frac, watched, current = item.data(self.PARAMS)
        params = dict(url=url, number=number, fallback=fallback, frac=frac, watched=watched, current=current)
        params.update(changes)
        self.set_row(item, **params)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._timer.start()
        return False

    def _draw_visible(self) -> None:
        count = self.list.count()
        if not count:
            return
        vp = self.list.viewport()
        first = self.list.indexAt(QPoint(4, 4)).row()
        last = self.list.indexAt(QPoint(4, vp.height() - 4)).row()
        first = 0 if first < 0 else first
        if last < 0:   # низ окна — между строками или ниже последней: считаем по высоте строки
            step = max(1, self.list.visualItemRect(self.list.item(first)).height() + self.list.spacing())
            last = min(count - 1, first + vp.height() // step + 1)
        for row in range(max(0, first - self.MARGIN_ROWS), min(count, last + self.MARGIN_ROWS + 1)):
            item = self.list.item(row)
            if item is not None and not item.data(self.DRAWN):
                self._draw(item)

    def _draw(self, item: QListWidgetItem) -> None:
        item.setData(self.DRAWN, True)
        url, number, fallback, frac, watched, current = item.data(self.PARAMS)

        def paint(src):
            item.setIcon(QIcon(episode_thumb(src, self.w, self.h, number, fallback, frac, watched, current,
                                             radius=self.radius)))
        paint(None)
        if url:
            self.images.load(url, self.list, paint)
