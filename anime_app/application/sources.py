"""Поиск озвучек тайтла во всех источниках и серии выбранной озвучки.

- AniLibria  — своя озвучка, прямые HLS-потоки → встроенный плеер;
- AnimeVost  — своя озвучка, прямые mp4 → встроенный плеер;
- AnimeLib   — десятки озвучек/субтитров через плеер Kodik;
- YummyAnime — ещё один каталог плееров Kodik: в нём есть тайтлы, скрытые в AnimeLib
               (лицензионные — «Тетрадь смерти», «Сага о Винланде», фильмы Гибли…);
- AniSkip    — время заставки и титров, размеченное сообществом.
"""
from __future__ import annotations

from typing import Callable

from ..core.cache import TTLCache
from ..core.config import ANILIBRIA_MEDIA, MemoryTTL
from ..core.errors import AppError
from ..core.logging import get_logger
from ..domain.dubs import ANILIBRIA, ANIMEVOST, choose_dub, sort_dubs
from ..domain.episodes import anilibria_episodes
from ..domain.titles import norm, same_dub
from ..infrastructure.api.sources import AniSkipApi, AnimeLibApi, AnimeVostApi, YaniApi, kodik_teams
from .library import Preferences

log = get_logger("sources")
DubsCallback = Callable[[list, bool], None]


class SourceResolver:
    def __init__(self, animelib: AnimeLibApi, animevost: AnimeVostApi, yani: YaniApi, aniskip: AniSkipApi,
                 prefs: Preferences):
        self.animelib = animelib
        self.animevost = animevost
        self.yani = yani
        self.aniskip = aniskip
        self.prefs = prefs
        # Найденные озвучки и серии — в памяти, с ограничением (раньше словари росли весь сеанс)
        self._dubs: TTLCache[int, tuple[list, dict]] = TTLCache(max_size=64, default_ttl=MemoryTTL.DUBS)
        self._episodes: TTLCache[tuple, list] = TTLCache(max_size=128, default_ttl=MemoryTTL.EPISODES)
        self._pending: dict[int, list[DubsCallback]] = {}

    # ================================================================ озвучки
    def find_dubs(self, release: dict, callback: DubsCallback) -> None:
        """callback(dubs, finished) может вызываться несколько раз по мере ответа источников.
        Если поиск по этому тайтлу уже идёт — новый не запускается, ответ получат все."""
        rid = release["id"]
        cached = self._dubs.get(rid)
        if cached:
            callback(cached[0], True)
            return
        if rid in self._pending:
            self._pending[rid].append(callback)
            return
        self._pending[rid] = [callback]

        state = {"dubs": [], "matches": {}, "left": 3}
        al_eps = anilibria_episodes(release, ANILIBRIA_MEDIA)
        if al_eps:
            state["dubs"].append(dict(ANILIBRIA))
            self._episodes.set((rid, "anilibria"), al_eps)

        def publish(finished=False):
            if finished:
                # Команда Kodik с тем же именем, что «родная» озвучка, — дубль (AnimeVost мог ответить последним)
                native = {norm(d["name"]) for d in state["dubs"] if d["native"]}
                state["dubs"] = [d for d in state["dubs"] if d["native"] or not d["id"].startswith("kodik:")
                                 or not any(norm(d["name"]).startswith(n) for n in native)]
            dubs = sort_dubs(state["dubs"])
            if finished:
                self._dubs.set(rid, (dubs, state["matches"]))
            for cb in list(self._pending.get(rid, [])):
                cb(dubs, finished)
            if finished:
                self._pending.pop(rid, None)

        def done():
            state["left"] -= 1
            # YummyAnime добавляем последним, когда AnimeVost и AnimeLib уже ответили, — чтобы не задвоить команды
            if state["left"] == 1 and "yani_add" in state:
                state.pop("yani_add")()
                return
            publish(state["left"] == 0)

        def vost(vost_id):
            if vost_id:
                state["matches"]["animevost"] = vost_id
                state["dubs"].append(dict(ANIMEVOST))
            done()

        def animelib(slug):
            if not slug:
                done()
                return
            state["matches"]["animelib"] = slug

            def eps_ok(eps):
                state["matches"]["animelib_eps"] = eps
                if not eps:
                    done()
                    return
                # Составы озвучек — по первой и последней серии
                probe = {eps[0]["animelib_id"], eps[-1]["animelib_id"]}
                seen: dict = {}
                left = {"n": len(probe)}

                def players_ok(players):
                    for tid, dub in kodik_teams(players).items():
                        seen.setdefault(tid, dub)
                    fin()

                def fin(*_):
                    left["n"] -= 1
                    if left["n"] == 0:
                        native = {norm(d["name"]) for d in state["dubs"]}
                        for d in seen.values():
                            if not any(norm(d["name"]).startswith(n) for n in native):
                                state["dubs"].append(d)
                        done()

                for eid in probe:
                    self.animelib.episode_players(eid, players_ok, fin)

            self.animelib.episodes(slug, eps_ok, lambda err: (log.info("AnimeLib: %s", err), done()))

        def yani(groups):
            state["matches"]["yani"] = groups or {}

            def add():
                for gid, g in (groups or {}).items():
                    if g["eps"] and not any(same_dub(d["name"], g["name"]) for d in state["dubs"]):
                        state["dubs"].append({"id": gid, "name": g["name"], "kind": g["kind"], "native": False})
                done()
            if state["left"] > 1:
                state["yani_add"] = add  # ждём остальные источники
            else:
                add()

        self.animevost.find(release, vost)
        self.animelib.find(release, animelib)
        self.yani.find(release, lambda aid: self.yani.dubs(aid, yani) if aid else yani({}))
        publish(False)

    def invalidate(self, release_id) -> None:
        """Забыть найденные озвучки и серии тайтла (после смены сети ссылки могли устареть)."""
        self._dubs.pop(release_id)
        self._episodes.discard_where(lambda k: k[0] == release_id)

    # ================================================================ серии
    def episodes(self, release: dict, dub: dict, on_ok, on_err=None) -> None:
        rid = release["id"]
        if dub["id"] == "anilibria":
            # Серии AniLibria — всегда из переданного (свежего) релиза: в них ссылки на поток
            on_ok(anilibria_episodes(release, ANILIBRIA_MEDIA))
            return
        key = (rid, dub["id"])
        hit = self._episodes.get(key)
        if hit is not None:
            on_ok(hit)
            return
        matches = (self._dubs.get(rid) or ([], {}))[1]

        def store(eps):
            self._episodes.set(key, eps)
            on_ok(eps)

        if dub["id"] == "animevost" and matches.get("animevost"):
            self.animevost.episodes(matches["animevost"], store, on_err)
        elif dub["id"].startswith("kodik:"):
            store([dict(e) for e in matches.get("animelib_eps") or []])
        elif dub["id"].startswith("yani:"):
            store([dict(e) for e in ((matches.get("yani") or {}).get(dub["id"]) or {}).get("eps", [])])
        elif on_err:
            on_err(AppError("Источник недоступен"))

    def previews(self, release: dict, dubs: list[dict], cb) -> None:
        """Кадры серий со всех «родных» источников: {ключ серии: url} (у Kodik картинок нет)."""
        native = [d for d in dubs if d["native"]]
        out: dict[str, str] = {}
        left = {"n": len(native)}
        if not native:
            cb(out)
            return

        def got(eps):
            for e in eps:
                if e.get("preview"):
                    out.setdefault(e["key"], e["preview"])
            left["n"] -= 1
            if left["n"] == 0:
                cb(out)
        for d in native:
            self.episodes(release, d, got, lambda _e: got([]))

    def skip_times(self, sid, ordinal, duration_s, cb) -> None:
        self.aniskip.skip_times(sid, ordinal, duration_s, cb)

    # ================================================================ выбор
    def choose(self, release: dict, dubs: list[dict]) -> dict | None:
        """Сохранённая озвучка тайтла → любимая озвучка пользователя → встроенный плеер."""
        return choose_dub(dubs, self.prefs.get(f"dub:{release['id']}"), self.prefs.get("preferred_dub", ""))

    def remember_choice(self, release: dict, dub: dict) -> None:
        self.prefs.set(f"dub:{release['id']}", dub["id"])
        self.prefs.set("preferred_dub", dub["name"])
