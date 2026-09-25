"""Таймер сна: остановить видео через N минут или после текущей серии.

Один на всё приложение: общий для встроенного плеера и Kodik и не сбрасывается при смене серии или озвучки.
"""
from __future__ import annotations

import time
from typing import Callable

from ..core.i18n import t

CHOICES = (15, 30, 45, 60, 90)


class SleepTimer:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self.until = 0.0         # когда остановить (time.time()); 0 — не по времени
        self.minutes = 0
        self.after_episode = False
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------ состояние
    @property
    def active(self) -> bool:
        return self.after_episode or self.until > self._clock()

    def minutes_left(self) -> int:
        left = self.until - self._clock()
        return int(left // 60) + 1 if left > 0 else 0

    def set(self, minutes: int = 0, after_episode: bool = False) -> str:
        """Завести (или выключить: 0, False). Возвращает подсказку для экрана."""
        self.minutes = minutes
        self.after_episode = after_episode
        self.until = self._clock() + minutes * 60 if minutes else 0.0
        self._changed()
        if minutes:
            return t("sleep.set_minutes", n=minutes)
        return t("sleep.after_episode_set") if after_episode else t("sleep.off_set")

    def menu_items(self) -> list[tuple[str, int, bool, bool]]:
        """[(текст, минуты, после серии, выбрано)]."""
        timed = self.until > self._clock()
        items = [(t("sleep.off"), 0, False, not self.active), (t("sleep.after_episode"), 0, True, self.after_episode)]
        items += [(t("sleep.in_minutes", n=m), m, False, timed and self.minutes == m) for m in CHOICES]
        return items

    # ------------------------------------------------------------ срабатывание
    def due(self) -> bool:
        """Время вышло: сбрасывает таймер и возвращает True — видео пора остановить."""
        if self.until and self._clock() >= self.until:
            self.until, self.minutes = 0.0, 0
            self._changed()
            return True
        return False

    def episode_ended(self) -> bool:
        """Серия закончилась: True — если ждали её конца (следующую не включаем)."""
        if not self.after_episode:
            return False
        self.after_episode = False
        self._changed()
        return True

    # ------------------------------------------------------------ плеер Kodik (отдельный процесс, время в мс)
    def to_job(self) -> dict:
        return {"until": self.until * 1000 if self.until > self._clock() else 0,
                "min": self.minutes, "episode": self.after_episode}

    def from_job(self, until_ms, minutes, episode) -> None:
        self.until, self.minutes, self.after_episode = (until_ms or 0) / 1000, minutes or 0, bool(episode)
        self._changed()

    # ------------------------------------------------------------ подписка
    def subscribe(self, fn: Callable[[], None]) -> Callable[[], None]:
        """fn() при каждом изменении; возвращает функцию отписки."""
        self._listeners.append(fn)
        return lambda: self._listeners.remove(fn) if fn in self._listeners else None

    def _changed(self) -> None:
        for fn in list(self._listeners):
            fn()
