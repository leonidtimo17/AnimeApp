"""Выбор качества видео по скорости интернета (без сети и без Qt — только правила)."""
from __future__ import annotations

from typing import Iterable

UNKNOWN_SPEED_MAX = 720   # скорость неизвестна — не выше 720p


def required_mbps(q) -> float:
    """Сколько Мбит/с нужно для качества (по высоте кадра): 1080p ≈ 4–6 Мбит/с потока + запас."""
    h = int(q)
    return 20.0 if h >= 2000 else 12.0 if h >= 1400 else 9.0 if h >= 1000 else 4.0 if h >= 700 else 0.0


def quality_name(height) -> str:
    h = int(height)
    return "4K" if h >= 2000 else "2K" if h >= 1400 else "Full HD" if h >= 1000 else "HD" if h >= 700 else "SD"


def sort_qualities(qualities: Iterable[str]) -> list[str]:
    """От лучшего к худшему."""
    return sorted(qualities, key=int, reverse=True)


def recommend(mbps: float | None, available: Iterable[str] = ("1080", "720", "480")) -> str | None:
    """Лучшее качество из доступных, на которое хватает скорости (скорость неизвестна → до 720p)."""
    avail = sort_qualities(available)
    if not avail:
        return None
    if mbps is None:
        return next((q for q in avail if int(q) <= UNKNOWN_SPEED_MAX), avail[-1])
    return next((q for q in avail if required_mbps(q) <= mbps), avail[-1])


def effective_quality(available: Iterable[str], preferred: str | None, bad: Iterable[str] = (),
                      cap: str | None = None) -> str | None:
    """Качество, которое реально включить: нужное, если есть; иначе ближайшее ниже; иначе самое низкое.
    bad — качества, которые не открылись; cap — потолок «Авто» после подгрузок."""
    bad = set(bad)
    avail = [q for q in sort_qualities(available) if q not in bad]
    if not avail:
        return None
    if cap and preferred and int(preferred) > int(cap):
        preferred = cap
    if preferred in avail:
        return preferred
    lower = [q for q in avail if preferred and int(q) < int(preferred)]
    return lower[0] if lower else avail[-1]


def lower_quality(available: Iterable[str], current: str | None, bad: Iterable[str] = ()) -> str | None:
    """Ближайшее качество ниже текущего (для понижения при подгрузках и ошибках)."""
    if not current:
        return None
    bad = set(bad)
    return next((q for q in sort_qualities(available) if int(q) < int(current) and q not in bad), None)


class StallTracker:
    """«Авто»: если за минуту видео подгружалось 3 раза — пора понизить качество."""

    WINDOW_SEC = 60
    LIMIT = 3

    def __init__(self):
        self._stalls: list[float] = []

    def stalled(self, now: float) -> bool:
        """Отметить подгрузку; True — подгрузок слишком много."""
        self._stalls = [t for t in self._stalls if now - t < self.WINDOW_SEC] + [now]
        return len(self._stalls) >= self.LIMIT

    def reset(self) -> None:
        self._stalls = []


class QualityPolicy:
    """Какое качество включить в плеере.

    mode: "auto" — по скорости интернета, иначе выбор пользователя ("1080"/"720"/"480").
    В «Авто» скорость берётся из единственного замера при запуске приложения (bandwidth()).
    Сам плеер скорость не меряет: если видео часто подгружается — качество понижается,
    а потолок снимается при смене сети или после ручной проверки скорости.
    """

    def __init__(self, mode: str = "auto", bandwidth=lambda: None):
        self.mode = mode
        self._bandwidth = bandwidth
        self.recommended: str | None = recommend(bandwidth())
        self.bad: set[str] = set()          # качества этой серии, которые не открылись
        self.cap: str | None = None         # потолок «Авто» после подгрузок
        self.real_height: dict[tuple, int] = {}   # (озвучка, качество) -> настоящая высота кадра
        self.stalls = StallTracker()

    @staticmethod
    def available(ep: dict | None) -> list[str]:
        """Качества, которые реально есть у серии, от лучшего к худшему."""
        return sort_qualities(q for q, url in ((ep or {}).get("streams") or {}).items() if url)

    def new_episode(self) -> None:
        self.bad = set()

    def choose(self, ep: dict | None) -> str | None:
        """Качество для серии (в «Авто» заодно обновляет рекомендацию)."""
        avail = self.available(ep)
        if self.mode == "auto":
            self.recommended = recommend(self._bandwidth(), avail)
        return self.effective(ep)

    def effective(self, ep: dict | None) -> str | None:
        pref = self.recommended if self.mode == "auto" else self.mode
        return effective_quality(self.available(ep), pref, self.bad, self.cap if self.mode == "auto" else None)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "auto":
            self.cap = None

    def height(self, dub: str, q: str) -> int:
        return self.real_height.get((dub, q)) or int(q)

    def label(self, dub: str, q: str, short: bool = False) -> str:
        h = self.height(dub, q)
        return f"{quality_name(h)} {h}p" if short else f"{h}p · {quality_name(h)}"

    def seen_height(self, dub: str, q: str, height: int) -> bool:
        """Узнали настоящее разрешение потока; True — подпись изменилась."""
        if q and height > 0 and self.real_height.get((dub, q)) != height:
            self.real_height[(dub, q)] = height
            return True
        return False

    def stalled(self, ep: dict | None, now: float) -> str | None:
        """«Авто»: видео подгружается — вернуть качество ниже (и запомнить потолок) или None."""
        if self.mode != "auto" or not self.stalls.stalled(now):
            return None
        lower = lower_quality(self.available(ep), self.effective(ep), self.bad)
        if lower:
            self.stalls.reset()
            self.cap = lower
            self.recommended = lower
        return lower

    def failed(self, ep: dict | None) -> tuple[str | None, str | None]:
        """Качество не открылось: (что не открылось, на что переключиться | None)."""
        q = self.effective(ep)
        lower = lower_quality(self.available(ep), q, self.bad)
        if lower:
            self.bad.add(q)
        return q, lower

    def network_changed(self) -> None:
        """Сменилась сеть: снимаем потолок (скорость не меряем — только по кнопке)."""
        self.cap = None
        self.stalls.reset()

    def bandwidth_updated(self) -> None:
        """Пользователь проверил скорость заново."""
        self.cap = None
        self.stalls.reset()
