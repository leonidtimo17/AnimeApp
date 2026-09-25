"""Загрузка постеров и кадров.

- дисковый кэш (до 500 МБ): скачанное повторно не качается;
- кэш в памяти с ограничением по объёму (не по числу картинок) + кэш уже обрезанных/скруглённых копий;
- декодирование JPEG/WebP — в фоновых потоках, интерфейс не подтормаживает на сетке из десятков постеров;
- одна картинка не качается дважды, даже если её ждут несколько карточек;
- не больше N запросов к одному серверу, первыми — картинки открытого экрана; картинки закрытых экранов не качаются;
- битые адреса запоминаются на 10 минут и не запрашиваются снова.
"""
from __future__ import annotations

from collections import deque
from typing import Callable

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkRequest

from ...core.cache import TTLCache
from ...core.config import USER_AGENT
from .processing import cover, pixmap_bytes, rounded

# Не больше N одновременных запросов к одному серверу (у Shikimori лимит ~5 запросов/с).
MAX_PER_HOST = 6
HOST_LIMITS = {"shikimori.io": 4}
MAX_SIDE = 420            # крупнее постеры нигде не показываются — в памяти держим уменьшенную копию
DISK_CACHE_BYTES = 500 * 1024 * 1024
MEMORY_BYTES = 64 * 1024 * 1024
PROCESSED_BYTES = 48 * 1024 * 1024
FAILED_TTL = 600


class _Relay(QObject):
    decoded = Signal(str, QImage)


class _DecodeJob(QRunnable):
    def __init__(self, url: str, data: bytes, relay: _Relay):
        super().__init__()
        self.url, self.data, self.relay = url, data, relay

    def run(self):
        img = QImage()
        img.loadFromData(self.data)
        if not img.isNull() and img.height() > MAX_SIDE:
            img = img.scaledToHeight(MAX_SIDE, Qt.TransformationMode.SmoothTransformation)
        self.relay.decoded.emit(self.url, img)


def _alive(receiver) -> bool:
    return receiver is None or shiboken6.isValid(receiver)


class ImageLoader(QObject):
    def __init__(self, cache_dir: str, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self.disk = QNetworkDiskCache(self)
        self.disk.setCacheDirectory(cache_dir)
        self.disk.setMaximumCacheSize(DISK_CACHE_BYTES)
        self.nam.setCache(self.disk)
        self._memory: TTLCache[str, QPixmap] = TTLCache(max_size=2000, max_weight=MEMORY_BYTES, weigher=pixmap_bytes)
        self._processed: TTLCache[tuple, QPixmap] = TTLCache(max_size=2000, max_weight=PROCESSED_BYTES,
                                                             weigher=pixmap_bytes)
        self._failed: TTLCache[str, bool] = TTLCache(max_size=500, default_ttl=FAILED_TTL)
        self._pending: dict[str, list[tuple[object, Callable]]] = {}
        self._queues: dict[str, deque] = {}    # host -> deque[(url, attempt)]
        self._active: dict[str, int] = {}      # host -> число запросов в работе
        self._idle_waiters: list[Callable[[], None]] = []
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._relay = _Relay(self)
        self._relay.decoded.connect(self._decoded)

    # ------------------------------------------------------------------ публичное
    def load(self, url: str | None, receiver, callback: Callable[[QPixmap], None]) -> None:
        """callback(QPixmap) вызывается, только если receiver ещё жив."""
        if not url or url in self._failed:
            return
        hit = self._memory.get(url)
        if hit is not None:
            callback(hit)
            return
        waiters = self._pending.setdefault(url, [])
        waiters.append((receiver, callback))
        if len(waiters) > 1:
            return
        # Уже скачано раньше — берём с диска, без очереди к серверу
        data = self._from_disk(url)
        if data is not None:
            self._pool.start(_DecodeJob(url, data, self._relay))
        else:
            self._enqueue(url, 0)

    def load_cover(self, url: str | None, w: int, h: int, radius: int, receiver,
                   callback: Callable[[QPixmap], None]) -> None:
        """Картинка, уже обрезанная под размер w×h и скруглённая (готовые копии кэшируются)."""
        if not url:
            return
        key = (url, w, h, radius)
        hit = self._processed.get(key)
        if hit is not None:
            callback(hit)
            return

        def got(pix):
            out = cover(pix, w, h)
            if radius:
                out = rounded(out, radius)
            self._processed.set(key, out)
            callback(out)
        self.load(url, receiver, got)

    def call_when_idle(self, fn: Callable[[], None], timeout_ms: int = 6000) -> None:
        """fn() — когда картинки открытого экрана догрузятся (но не позже timeout_ms)."""
        state = {"done": False}

        def fire():
            if not state["done"]:
                state["done"] = True
                fn()
        if self.idle:
            QTimer.singleShot(0, fire)
            return
        self._idle_waiters.append(fire)
        QTimer.singleShot(timeout_ms, fire)

    @property
    def idle(self) -> bool:
        return not self._pending

    def clear(self) -> None:
        """Очистить кэш картинок (диск и память)."""
        self.disk.clear()
        self._memory.clear()
        self._processed.clear()
        self._failed.clear()

    # ------------------------------------------------------------------ загрузка
    def _from_disk(self, url) -> bytes | None:
        dev = self.disk.data(QUrl(url))
        if dev is None:
            return None
        data = bytes(dev.readAll())
        dev.close()
        return data or None

    def _enqueue(self, url, attempt):
        host = QUrl(url).host()
        self._queues.setdefault(host, deque()).append((url, attempt))
        self._pump(host)

    def _pump(self, host):
        """Сначала — самые свежие запросы: это картинки экрана, который сейчас открыт.
        Картинки закрытых экранов (их виджетов уже нет) не качаем вовсе."""
        queue = self._queues.get(host)
        limit = HOST_LIMITS.get(host, MAX_PER_HOST)
        while queue and self._active.get(host, 0) < limit:
            url, attempt = queue.pop()
            alive = [(r, cb) for r, cb in self._pending.get(url, []) if _alive(r)]
            if not alive:
                self._pending.pop(url, None)
                continue
            self._pending[url] = alive
            self._active[host] = self._active.get(host, 0) + 1
            self._fetch(host, url, attempt)
        self._check_idle()

    def _fetch(self, host, url, attempt):
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                         QNetworkRequest.CacheLoadControl.PreferCache)
        req.setTransferTimeout(30000)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
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
            data = bytes(reply.readAll())
            self._pump(host)
            if not data:
                self._fail(url)
                return
            self._pool.start(_DecodeJob(url, data, self._relay))

        reply.finished.connect(finished)

    def _decoded(self, url: str, image: QImage):
        if image.isNull():
            self._fail(url)
            return
        pix = QPixmap.fromImage(image)
        self._memory.set(url, pix)
        for recv, cb in self._pending.pop(url, []):
            if _alive(recv):
                try:
                    cb(pix)
                except RuntimeError:   # «C++ object already deleted»: строку списка уже перестроили
                    pass
        self._check_idle()

    def _fail(self, url):
        self._failed.set(url, True)
        self._pending.pop(url, None)
        self._check_idle()

    def _check_idle(self):
        if self._pending or not self._idle_waiters:
            return
        waiters, self._idle_waiters = self._idle_waiters, []
        for fn in waiters:
            fn()
