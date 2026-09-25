"""Сторож воспроизведения: замечает, что видео «встало» (обрыв сети, смена Wi-Fi/VPN), и просит переподключиться.

Это не проверка интернета: сторож не делает ни одного запроса, он смотрит только на позицию видео.
И работает лишь пока видео играет — на паузе, в меню и с закрытым плеером таймер остановлен.
"""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

CHECK_MS = 2000
FROZEN_SEC = 12          # позиция не меняется столько секунд — переподключаемся
HURRY_SEC = 8            # после смены сети — проверить быстрее


class PlaybackWatchdog(QObject):
    frozen = Signal()        # видео стоит — пора переподключиться

    def __init__(self, position: Callable[[], int], parent=None, clock: Callable[[], float] = time.time):
        super().__init__(parent)
        self._position = position
        self._clock = clock
        self._timer = QTimer(self, interval=CHECK_MS)
        self._timer.timeout.connect(self._check)
        self._last_pos = -1
        self._frozen_since: float | None = None
        self.tries = 0           # попыток переподключения подряд (сбрасывается, когда видео пошло)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def playing(self, on: bool) -> None:
        """Видео пошло / встало на паузу (не из-за сети)."""
        if on and not self._timer.isActive():
            self._last_pos = self._position()
            self._frozen_since = None
            self._timer.start()
        elif not on:
            self._timer.stop()
            self._frozen_since = None

    def hurry(self) -> None:
        """Сменилась сеть: проверить поток побыстрее, чем через обычные 12 секунд."""
        if self._timer.isActive() and self._frozen_since is None:
            self._frozen_since = self._clock() - HURRY_SEC

    def reset(self) -> None:
        self._frozen_since = None

    def _check(self) -> None:
        pos = self._position()
        if pos != self._last_pos:
            if pos > self._last_pos >= 0:
                self.tries = 0
            self._last_pos = pos
            self._frozen_since = None
            return
        if self._frozen_since is None:
            self._frozen_since = self._clock()
        elif self._clock() - self._frozen_since >= FROZEN_SEC:
            self._frozen_since = None
            self.frozen.emit()
