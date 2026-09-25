"""Сезоны, фильмы и OVA франшизы, информация о выходе серий (Shikimori). Общий кэш для страницы тайтла и плееров."""
from __future__ import annotations

from ..core.cache import TTLCache
from ..core.config import SHIKI, MemoryTTL
from ..domain.franchise import merge_franchise
from ..domain.ids import SHIKI_OFFSET, is_external_id, shiki_id
from ..infrastructure.api.anilibria import AniLibriaApi
from ..infrastructure.api.shikimori import ShikimoriApi


class FranchiseService:
    def __init__(self, anilibria: AniLibriaApi, shikimori: ShikimoriApi):
        self.anilibria = anilibria
        self.shikimori = shikimori
        self._cache: TTLCache[int, list] = TTLCache(max_size=64, default_ttl=MemoryTTL.FRANCHISE)
        self._pending: dict[int, list] = {}

    def info(self, release: dict, on_ok) -> None:
        """Статус, число серий и дата следующей серии с Shikimori (или None)."""
        sid = shiki_id(release)
        if not sid:
            on_ok(None)
            return
        self.shikimori.anime(sid, on_ok, lambda _e: on_ok(None))

    def load(self, release: dict, on_ok) -> None:
        """on_ok(entries): [{shiki_id, label, name, year, poster, release_id|None, current}]"""
        rid = release["id"]
        hit = self._cache.get(rid)
        if hit is not None:
            on_ok(hit)
            return
        if rid in self._pending:       # страница тайтла и плеер спрашивают одновременно — один запрос
            self._pending[rid].append(on_ok)
            return
        sid = shiki_id(release)
        state = {"nodes": None, "anilibria": [], "left": (1 if sid else 0) + (0 if is_external_id(rid) else 1)}
        if state["left"] == 0:
            on_ok([])
            return
        self._pending[rid] = [on_ok]

        def finish():
            state["left"] -= 1
            if state["left"] > 0:
                return
            entries = merge_franchise(release, state["nodes"], state["anilibria"], self.anilibria.poster_url, SHIKI)
            self._cache.set(rid, entries)
            for cb in self._pending.pop(rid, []):
                cb(entries)

        def shiki_ok(data):
            state["nodes"] = data.get("nodes") or []
            finish()

        def al_ok(data):
            for fr in data or []:
                for x in fr.get("franchise_releases") or []:
                    if x.get("release"):
                        state["anilibria"].append(x["release"])
            finish()

        if sid:
            self.shikimori.franchise(sid, shiki_ok, lambda _e: finish())
        if not is_external_id(rid):
            self.anilibria.franchise(rid, al_ok, lambda _e: finish())

    def resolve(self, entry: dict, on_ok) -> None:
        """Найти сезон франшизы в наших источниках: on_ok(release_id | None)."""
        if entry.get("release_id"):
            on_ok(entry["release_id"])
            return
        sid = entry.get("shiki_id")

        def from_shikimori(*_):
            on_ok(SHIKI_OFFSET + sid if sid else None)

        def al_ok(items):
            for r in items or []:
                if shiki_id(r) == sid:
                    on_ok(r["id"])
                    return
            from_shikimori()
        self.anilibria.search(entry["name"], al_ok, from_shikimori)
