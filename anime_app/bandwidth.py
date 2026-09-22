"""Замер скорости интернета по кусочку настоящего видео (как у онлайн-кинотеатров).

Для HLS берём первые два сегмента из плейлиста, для mp4 — два куска файла, и качаем их параллельно
до ~3.5 секунды. Скорость считаем только после «разгона» соединения (первые 0.5 с не учитываем):
короткая закачка почти целиком уходит на установку соединения и показывала в 5–10 раз меньше
настоящей скорости. Результат кэшируется на 10 минут.
"""
import time

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

PROBE_BYTES = 16_000_000
PROBE_MS = 3500
WARMUP_MS = 500
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
            self._segments_from_playlist(url, lambda segs: self._download([(s, None) for s in segs], on_done)
                                         if segs else on_done(None))
        else:
            self._download([(url, "bytes=0-7999999"), (url, "bytes=8000000-15999999")], on_done)

    def _segments_from_playlist(self, url, cb, depth=0):
        reply = self.nam.get(QNetworkRequest(QUrl(url)))

        def done():
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                cb(None)
                return
            text = bytes(reply.readAll()).decode("utf-8", "replace")
            uris = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if not uris:
                cb(None)
                return
            if "#EXTINF" not in text and depth < 2:   # мастер-плейлист → вариант
                self._segments_from_playlist(QUrl(url).resolved(QUrl(uris[0])).toString(), cb, depth + 1)
            else:
                cb([QUrl(url).resolved(QUrl(u)).toString() for u in uris[:2]])
        reply.finished.connect(done)

    def _download(self, targets, on_done):
        """Параллельная закачка; скорость — по окну после разгона соединения."""
        clock = QElapsedTimer()
        state = {"total": 0, "done": False, "left": len(targets), "samples": []}   # samples: (мс, всего байт)
        replies = []

        def finish():
            if state["done"]:
                return
            state["done"] = True
            for r in replies:
                if r.isRunning():
                    r.abort()
                r.deleteLater()
            s = state["samples"]
            if state["total"] < 300_000 or len(s) < 2:
                on_done(None)
                return
            t0, end = s[0][0], s[-1]
            warm = next((x for x in s if x[0] - t0 >= WARMUP_MS), None)
            ta, ba = warm if warm and end[0] - warm[0] >= 300 else (t0, 0)
            sec = (end[0] - ta) / 1000
            if sec <= 0:
                on_done(None)
                return
            mbps = (end[1] - ba) * 8 / sec / 1e6
            BandwidthProbe._last = (time.time(), mbps)
            on_done(mbps)

        def make(url, rng):
            req = QNetworkRequest(QUrl(url))
            if rng:
                req.setRawHeader(b"Range", rng.encode())
            req.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                             QNetworkRequest.CacheLoadControl.AlwaysNetwork)
            reply = self.nam.get(req)
            replies.append(reply)

            def progress():
                if state["done"]:
                    return
                if not clock.isValid():
                    clock.start()
                state["total"] += len(reply.readAll())
                state["samples"].append((clock.elapsed(), state["total"]))
                if state["total"] >= PROBE_BYTES:
                    finish()

            def ended():
                state["left"] -= 1
                if state["left"] == 0:
                    finish()
            reply.readyRead.connect(progress)
            reply.finished.connect(ended)

        for url, rng in targets:
            make(url, rng)
        QTimer.singleShot(PROBE_MS, finish)
