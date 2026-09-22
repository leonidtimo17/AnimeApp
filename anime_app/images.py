"""Загрузка постеров с дисковым кэшем (повторно не качаются) и кэшем в памяти."""
from collections import OrderedDict, deque

import shiboken6
from PySide6.QtCore import QObject, QTimer, QUrl, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkRequest


# Не больше N одновременных запросов к одному серверу (у Shikimori лимит ~5 запросов/с).
MAX_PER_HOST = 3


class ImageLoader(QObject):
    def __init__(self, cache_dir, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        disk = QNetworkDiskCache(self)
        disk.setCacheDirectory(cache_dir)
        disk.setMaximumCacheSize(500 * 1024 * 1024)
        self.nam.setCache(disk)
        self._memory = OrderedDict()
        self._pending = {}
        self._queues = {}    # host -> deque[(url, attempt)]
        self._active = {}    # host -> число запросов в работе

    def load(self, url, receiver, callback):
        """callback(QPixmap) вызывается, только если receiver ещё жив."""
        if not url:
            return
        if url in self._memory:
            self._memory.move_to_end(url)
            callback(self._memory[url])
            return
        waiters = self._pending.setdefault(url, [])
        waiters.append((receiver, callback))
        if len(waiters) > 1:
            return
        self._enqueue(url, 0)

    def _enqueue(self, url, attempt):
        host = QUrl(url).host()
        self._queues.setdefault(host, deque()).append((url, attempt))
        self._pump(host)

    def _pump(self, host):
        queue = self._queues.get(host)
        while queue and self._active.get(host, 0) < MAX_PER_HOST:
            url, attempt = queue.popleft()
            self._active[host] = self._active.get(host, 0) + 1
            self._fetch(host, url, attempt)

    def _fetch(self, host, url, attempt):
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                         QNetworkRequest.CacheLoadControl.PreferCache)
        req.setTransferTimeout(30000)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "AnimeApp/1.0 (desktop)")
        reply = self.nam.get(req)

        def finished():
            reply.deleteLater()
            self._active[host] -= 1
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status == 429 and attempt < 4:
                # Слишком часто — повторим чуть позже.
                QTimer.singleShot(800 * (attempt + 1), lambda: self._enqueue(url, attempt + 1))
                self._pump(host)
                return
            pix = QPixmap()
            pix.loadFromData(bytes(reply.readAll()))
            callbacks = self._pending.pop(url, [])
            self._pump(host)
            if pix.isNull():
                return
            # В памяти держим уменьшенную копию: крупнее 420 px постеры нигде не показываются.
            if pix.height() > 420:
                pix = pix.scaledToHeight(420, Qt.TransformationMode.SmoothTransformation)
            self._memory[url] = pix
            while len(self._memory) > 250:
                self._memory.popitem(last=False)
            for recv, cb in callbacks:
                if recv is None or shiboken6.isValid(recv):
                    cb(pix)

        reply.finished.connect(finished)


def cover(pix: QPixmap, w: int, h: int) -> QPixmap:
    """Масштабирует с обрезкой, как CSS object-fit: cover."""
    scaled = pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - w) // 2
    y = (scaled.height() - h) // 2
    return scaled.copy(x, y, w, h)


def episode_thumb(src, w, h, number, fallback, frac=0.0, watched=False, current=False, radius=0):
    """Миниатюра серии: кадр из серии (или затемнённый постер с крупным номером), номер,
    галочка «просмотрено», значок «сейчас», полоска прогресса снизу."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QPainter
    from .icons import icon
    from .theme import ACCENT
    ok = src is not None and not src.isNull()
    pix = cover(src, w, h) if ok else QPixmap(w, h)
    if not ok:
        pix.fill(QColor("#24242c"))
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


def rounded(pix: QPixmap, radius: int) -> QPixmap:
    from PySide6.QtGui import QPainter, QPainterPath
    out = QPixmap(pix.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pix.width(), pix.height(), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pix)
    p.end()
    return out
