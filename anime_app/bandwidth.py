"""Замер скорости интернета по кусочку настоящего видео (как у онлайн-кинотеатров).

Для HLS берём первый сегмент из плейлиста, для mp4 — начало файла.
Качаем до ~2.5 МБ или 4 секунды и считаем скорость с момента прихода первого байта
(чтобы не учитывать задержку соединения). Результат кэшируется на 10 минут.
"""
import time

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

PROBE_BYTES = 2_500_000
PROBE_MS = 4000
CACHE_SEC = 600

# Сколько Мбит/с нужно для качества (по высоте кадра): 1080p ≈ 4–6 Мбит/с потока + запас.
def required_mbps(q):
    h = int(q)
    return 20.0 if h >= 2000 else 12.0 if h >= 1400 else 9.0 if h >= 1000 else 4.0 if h >= 700 else 0.0


def recommend(mbps, available=("1080", "720", "480")):
    """Лучшее качество из доступных, на которое хватает скорости (скорость неизвестна → до 720p)."""
    avail = sorted(available, key=int, reverse=True)
    if not avail:
        return None
    if mbps is None:
        return next((q for q in avail if int(q) <= 720), avail[-1])
    return next((q for q in avail if required_mbps(q) <= mbps), avail[-1])


def quality_name(height):
    h = int(height)
    return "4K" if h >= 2000 else "2K" if h >= 1400 else "Full HD" if h >= 1000 else "HD" if h >= 700 else "SD"


class BandwidthProbe(QObject):
    _last = (0.0, None)   # (время замера, Мбит/с) — общий на всё приложение

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self._busy = False

    @classmethod
    def cached(cls):
        ts, mbps = cls._last
        return mbps if mbps is not None and time.time() - ts < CACHE_SEC else None

    def measure(self, url, on_done, force=False):
        """on_done(mbps | None). Сразу отдаёт кэш, если замер был недавно (force — замерить заново)."""
        hit = None if force else self.cached()
        if hit is not None:
            QTimer.singleShot(0, lambda: on_done(hit))
            return
        if url.split("?")[0].endswith(".m3u8"):
            self._segment_from_playlist(url, lambda seg: self._download(seg, on_done) if seg else on_done(None))
        else:
            self._download(url, on_done)

    def _segment_from_playlist(self, url, cb, depth=0):
        reply = self.nam.get(QNetworkRequest(QUrl(url)))

        def done():
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                cb(None)
                return
            lines = [ln.strip() for ln in bytes(reply.readAll()).decode("utf-8", "replace").splitlines()]
            uris = [ln for ln in lines if ln and not ln.startswith("#")]
            if not uris:
                cb(None)
                return
            nxt = QUrl(url).resolved(QUrl(uris[0])).toString()
            if nxt.split("?")[0].endswith(".m3u8") and depth < 2:   # мастер-плейлист → вариант
                self._segment_from_playlist(nxt, cb, depth + 1)
            else:
                cb(nxt)
        reply.finished.connect(done)

    def _download(self, url, on_done):
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"Range", f"bytes=0-{PROBE_BYTES - 1}".encode())
        req.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                         QNetworkRequest.CacheLoadControl.AlwaysNetwork)
        reply = self.nam.get(req)
        clock = QElapsedTimer()
        state = {"bytes": 0, "done": False}

        def finish():
            if state["done"]:
                return
            state["done"] = True
            elapsed = clock.elapsed() / 1000 if clock.isValid() else 0
            if reply.isRunning():
                reply.abort()
            reply.deleteLater()
            if state["bytes"] < 150_000 or elapsed <= 0.05:
                on_done(None)
                return
            mbps = state["bytes"] * 8 / elapsed / 1e6
            BandwidthProbe._last = (time.time(), mbps)
            on_done(mbps)

        def progress():
            if not clock.isValid():
                clock.start()
            state["bytes"] += len(reply.readAll())
            if state["bytes"] >= PROBE_BYTES:
                finish()

        reply.readyRead.connect(progress)
        reply.finished.connect(finish)
        QTimer.singleShot(PROBE_MS, finish)
