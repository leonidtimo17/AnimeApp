"""Списки пользователя и правило «серия просмотрена»."""
from __future__ import annotations

from ..core.i18n import t

STATUSES = ("watching", "planned", "completed", "postponed", "dropped")


def status_name(key: str | None) -> str:
    """Название списка на языке интерфейса; пустая строка — нет статуса."""
    return t(f"status.{key}") if key in STATUSES else ""

# Статусы, при которых запуск серии переводит тайтл в «Смотрю»
AUTO_WATCHING_FROM = (None, "planned", "postponed")

# Серия считается просмотренной, если досмотрена до титров или осталось меньше 3 минут/10%.
WATCHED_TAIL_MS = 180_000


def is_watched(position_ms: int, duration_ms: int, ending_start_ms: int | None = None) -> bool:
    if duration_ms <= 0:
        return False
    if ending_start_ms and position_ms >= ending_start_ms:
        return True
    return duration_ms - position_ms <= min(WATCHED_TAIL_MS, duration_ms * 0.1)


def watched_count(progress: dict) -> int:
    """Наибольший номер просмотренной целой серии — счётчик для Shikimori."""
    n = 0
    for p in progress.values():
        o = p.get("ordinal")
        if p.get("watched") and o is not None and float(o) == int(float(o)):
            n = max(n, int(float(o)))
    return n


def card_item(anime_id, title, subtitle="", poster=None, *, badge=None, status=None, favorite=None,
              progress=None, release=None) -> dict:
    """Данные карточки тайтла для сеток и лент (одинаковые на всех экранах)."""
    return {"id": anime_id, "title": title or "", "subtitle": subtitle or "", "poster": poster, "badge": badge,
            "status": status, "favorite": favorite, "progress": progress, "release": release}
