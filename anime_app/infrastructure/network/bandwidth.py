"""Замер скорости интернета по кусочку настоящего видео (как у онлайн-кинотеатров).

Для HLS берём первые два сегмента из плейлиста, для mp4 — два куска файла, и качаем их параллельно
до ~3.5 секунды. Скорость считаем только после «разгона» соединения (первые 0.5 с не учитываем):
короткая закачка почти целиком уходит на установку соединения и показывала в 5–10 раз меньше
настоящей скорости.

Сам по себе замер ничего не кэширует и никогда не запускается повторно — когда мерить, решает NetworkService.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

PROBE_BYTES = 16_000_000
PROBE_MS = 3500
WARMUP_MS = 500
MIN_BYTES = 300_000


def speed_from_samples(samples: list[tuple[int, int]], total: int) -> float | None:
    """Мбит/с по точкам (мс, всего байт); окно после разгона, если всё скачалось мгновенно — по всей закачке."""
    if total < MIN_BYTES or len(samples) < 2:
        return None
    t0, end = samples[0][0], samples[-1]
    warm = next((x for x in samples if x[0] - t0 >= WARMUP_MS), None)
    ta, ba = warm if warm and end[0] - warm[0] >= 300 else (t0, 0)
    sec = (end[0] - ta) / 1000
    if sec <= 0:
        return None
    mbps = (end[1] - ba) * 8 / sec / 1e6
    return mbps if mbps > 0 else None


def playlist_segments(url: str, text: str) -> tuple[str | None, list[str]]:
    """Разбор HLS-плейлиста: (вариант мастер-плейлиста для следующего шага | None, первые два сегмента)."""
    uris = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not uris:
        return None, []
    base = QUrl(url)
    if "#EXTINF" not in text:   # мастер-плейлист → вариант
        return base.resolved(QUrl(uris[0])).toString(), []
    return None, [base.resolved(QUrl(u)).toString() for u in uris[:2]]


class BandwidthProbe(QObject):
    def __init__(self, nam: QNetworkAccessManager, parent=None):
        super().__init__(parent)
        self.nam = nam
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def measure(self, url: str, on_done: Callable[[float | None], None]) -> None:
        """on_done(Мбит/с | None). Один замер за раз."""
        if self._busy:
            QTimer.singleShot(0, lambda: on_done(None))
            return
        self._busy = True

        def done(mbps):
            self._busy = False
            on_done(mbps)
        if url.split("?")[0].endswith(".m3u8"):
            self._segments_from_playlist(url, lambda segs: self._download([(s, None) for s in segs], done)
                                         if segs else done(None))
        else:
            self._download([(url, "bytes=0-7999999"), (url, "bytes=8000000-15999999")], done)

    def _segments_from_playlist(self, url, cb, depth=0):
        reply = self.nam.get(QNetworkRequest(QUrl(url)))

        def finished():
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                cb(None)
                return
            variant, segments = playlist_segments(url, bytes(reply.readAll()).decode("utf-8", "replace"))
            if variant and depth < 2:
                self._segments_from_playlist(variant, cb, depth + 1)
            else:
                cb(segments or None)
        reply.finished.connect(finished)

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
            on_done(speed_from_samples(state["samples"], state["total"]))

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
