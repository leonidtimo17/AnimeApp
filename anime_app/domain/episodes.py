"""Серии: единый формат для всех источников, продолжение просмотра, объединение серий разных озвучек.

Нормализованная серия (для всех источников):
    {"key": "12", "ordinal": 12.0, "name": str|None, "duration": сек|None,
     "opening": {"start", "stop"}|None, "ending": {...}|None,
     "streams": {"1080": url, "720": url, "480": url}|None,   # встроенный плеер
     "animelib_id": int|None,                                 # плеер Kodik (AnimeLib)
     "kodik": url|None,                                       # готовая ссылка Kodik (YummyAnime)
     "preview": url|None}                                     # кадр из серии
Ключ серии — её номер: прогресс общий для всех озвучек.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..core.formatting import fmt_ordinal

EPISODES_PAGE = 100   # серий на одной вкладке-диапазоне


def parse_ordinal(value, fallback) -> float:
    """Номер серии из числа или строки («12», «12.5», «Серия 12»); иначе — fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        m = re.search(r"\d+(?:[.,]\d+)?", str(value or ""))
        return float(m.group().replace(",", ".")) if m else float(fallback)


def make_episode(ordinal: float, **fields) -> dict:
    ep = {"key": fmt_ordinal(ordinal), "ordinal": ordinal, "name": None, "duration": None, "opening": None,
          "ending": None, "streams": None, "animelib_id": None, "preview": None}
    ep.update(fields)
    return ep


def has_streams(ep: dict) -> bool:
    return bool(ep.get("streams") or ep.get("animelib_id") or ep.get("kodik"))


def media_url(path, base: str) -> str | None:
    """Относительный путь картинки → полный адрес."""
    if not path:
        return None
    return path if path.startswith("http") else base + path


def anilibria_episodes(release: dict, media_base: str) -> list[dict]:
    """Серии AniLibria с прямыми HLS-потоками. Ссылки привязаны к сети — берутся из свежего релиза."""
    eps: list[dict] = []
    for e in release.get("episodes") or []:
        streams = {q: e.get(f"hls_{q}") for q in ("1080", "720", "480") if e.get(f"hls_{q}")}
        if not streams:
            continue
        pv = e.get("preview") or {}
        preview = (pv.get("optimized") or {}).get("preview") or pv.get("preview") or pv.get("src")
        eps.append(make_episode(
            parse_ordinal(e.get("ordinal"), len(eps) + 1), name=e.get("name") or e.get("name_english"),
            duration=e.get("duration"), opening=e.get("opening"), ending=e.get("ending"), streams=streams,
            preview=media_url(preview, media_base)))
    return eps


def resume_target(episodes: list[dict], progress: dict, last: dict | None) -> tuple[int, int]:
    """С какой серии и позиции продолжать: (index, position_ms).

    progress — {ключ серии: {"watched", "position", ...}}, last — последняя запись прогресса тайтла.
    """
    if not episodes:
        return 0, 0
    idx = next((i for i, e in enumerate(episodes) if last and e["key"] == last["episode_id"]), None)
    if idx is None:
        # Нет истории для этих серий — первая непросмотренная.
        for i, e in enumerate(episodes):
            p = progress.get(e["key"]) or {}
            if not p.get("watched"):
                return i, p.get("position", 0)
        return 0, 0
    if last["watched"]:
        for i in range(idx + 1, len(episodes)):
            p = progress.get(episodes[i]["key"]) or {}
            if not p.get("watched"):
                return i, p.get("position", 0)
        return idx, 0
    return idx, last["position"]


def start_position(prog: dict | None) -> int:
    """С какого места открыть конкретную серию: досмотренную — с начала."""
    return 0 if not prog or prog.get("watched") else prog.get("position", 0)


def progress_fraction(prog: dict | None) -> float:
    prog = prog or {}
    if prog.get("watched"):
        return 1.0
    return prog["position"] / prog["duration"] if prog.get("duration") else 0.0


def dub_group(dub: dict) -> str:
    """Группа источника серии: у встроенного плеера — сама озвучка, у всех Kodik — общая."""
    return dub["id"] if dub["native"] else "kodik"


class EpisodeUnion:
    """Серии из всех источников — чтобы показать все, даже если в выбранной озвучке их нет."""

    def __init__(self):
        self._slots: dict[str, dict] = {}

    def add(self, group: str, episodes: Iterable[dict]) -> None:
        for e in episodes:
            slot = self._slots.setdefault(e["key"], {"ep": e, "groups": set(), "preview": None})
            slot["groups"].add(group)
            slot["preview"] = slot["preview"] or e.get("preview")

    def keys(self) -> list[str]:
        return list(self._slots)

    def groups(self, key: str) -> set[str]:
        return (self._slots.get(key) or {}).get("groups", set())

    def preview(self, key: str) -> str | None:
        return (self._slots.get(key) or {}).get("preview")

    def has(self, key: str) -> bool:
        return key in self._slots

    def __bool__(self) -> bool:
        return bool(self._slots)

    def shown(self, own: list[dict]) -> list[dict]:
        """Серии выбранной озвучки + те, что есть только в других, по порядку."""
        own_keys = {e["key"] for e in own}
        out = list(own) + [s["ep"] for k, s in self._slots.items() if k not in own_keys]
        out.sort(key=lambda e: e["ordinal"])
        return out


def episode_ranges(shown: list[dict], page: int = EPISODES_PAGE) -> list[tuple[str, str]]:
    """Подписи вкладок-диапазонов («1–100», «101–200»), если серий больше одной страницы."""
    if len(shown) <= page:
        return []
    pages = (len(shown) + page - 1) // page
    return [(fmt_ordinal(shown[i * page]["ordinal"]),
             fmt_ordinal(shown[min(len(shown), (i + 1) * page) - 1]["ordinal"])) for i in range(pages)]
