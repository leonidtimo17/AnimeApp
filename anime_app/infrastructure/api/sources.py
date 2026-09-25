"""Источники серий: AnimeLib (Kodik), AnimeVost, YummyAnime (Kodik), AniSkip. Все API публичные и бесплатные.

Каждый клиент ищет тайтл у себя и отдаёт серии в едином формате (см. domain/episodes.py).
Решение, какие озвучки показывать и как их объединять, — в application/sources.py.
"""
from __future__ import annotations

import re

from ...core.config import (ANIMELIB_API, ANIMELIB_HEADERS, ANIMEVOST_API, ANISKIP_API, TTL,
                            YANI_API)
from ...domain.episodes import make_episode, parse_ordinal
from ...domain.ids import ANIMELIB_OFFSET
from ...domain.titles import match_keys, search_queries, title_key
from ..http.client import HttpClient
from .shikimori import poster_from_href


# ================================================================ AnimeLib → Kodik
def animelib_release(x: dict, full: dict | None = None) -> dict:
    """Карточка тайтла AnimeLib (для тайтлов, которых нет на AniLibria)."""
    full = full or {}
    m = re.search(r"\d{4}", x.get("releaseDateString") or full.get("releaseDateString") or "")
    summary = full.get("summary")
    if isinstance(summary, dict):  # формат редактора: {"type":"doc","content":[...]}
        summary = "\n".join(
            "".join(t.get("text", "") for t in (p.get("content") or []))
            for p in summary.get("content") or []
        )
    rel = {
        "id": ANIMELIB_OFFSET + int(x["id"]),
        "animelib": x.get("slug_url"),
        "name": {"main": x.get("rus_name") or x.get("name"), "english": x.get("name"),
                 "alternative": x.get("eng_name")},
        "poster": {"src": poster_from_href(x) or poster_from_href(full)},
        "year": int(m.group()) if m else None,
        "type": {"description": ((x.get("type") or {}).get("label") or "").replace(" Сериал", "")},
        "age_rating": {"label": (x.get("ageRestriction") or {}).get("label")},
        "description": summary or "",
        "genres": [{"name": g.get("name")} for g in full.get("genres") or []],
        "episodes": [],
        "is_ongoing": (x.get("status") or {}).get("id") == 1,
    }
    rate = x.get("shiki_rate") or full.get("shiki_rate")
    m = re.search(r"/animes/[a-z]*(\d+)", x.get("shikimori_href") or full.get("shikimori_href") or "")
    rel["shikimori"] = {"rating": float(rate) if rate else None, "id": int(m.group(1)) if m else None}
    return rel


def animelib_episodes(items: list[dict]) -> list[dict]:
    return [make_episode(parse_ordinal(e.get("number") or e.get("item_number"), i + 1), name=e.get("name"),
                         animelib_id=e["id"]) for i, e in enumerate(items)]


def kodik_teams(players: list[dict]) -> dict[int, dict]:
    """Озвучки плеера Kodik из списка плееров серии AnimeLib: {id команды: озвучка}."""
    seen: dict[int, dict] = {}
    for p in players or []:
        if p.get("player") != "Kodik" or not p.get("team"):
            continue
        tid = p["team"]["id"]
        ttype = (p.get("translation_type") or {}).get("id")
        seen.setdefault(tid, {"id": f"kodik:{tid}", "name": p["team"].get("name") or "?",
                              "kind": "sub" if ttype == 1 else "voice", "native": False})
    return seen


class AnimeLibApi:
    def __init__(self, http: HttpClient):
        self.http = http

    def _get(self, path, on_ok, on_err=None, params=None, cache_ttl=0):
        return self.http.request(f"{ANIMELIB_API}{path}", params, on_ok, on_err, headers=ANIMELIB_HEADERS,
                                 cache_ttl=cache_ttl)

    def search(self, query, on_ok, on_err=None):
        return self._get("/anime", lambda d: on_ok(d.get("data") or []), on_err, {"q": query}, TTL.SEARCH)

    def anime(self, slug, on_ok, on_err=None):
        def ok(d):
            data = d.get("data") or {}
            on_ok(animelib_release(data, data))
        return self._get(f"/anime/{slug}", ok, on_err, {"fields": ["summary", "genres"]})

    def episodes(self, slug, on_ok, on_err=None):
        return self._get("/episodes", lambda d: on_ok(animelib_episodes(d.get("data") or [])), on_err,
                         {"anime_id": slug})

    def episode_players(self, episode_id, on_ok, on_err=None):
        return self._get(f"/episodes/{episode_id}", lambda d: on_ok((d.get("data") or {}).get("players") or []),
                         on_err)

    def find(self, release: dict, cb) -> None:
        """slug тайтла в AnimeLib по названиям или None."""
        if release.get("animelib"):
            cb(release["animelib"])
            return
        keys = match_keys(release)
        queries = search_queries(release)

        def attempt(i):
            if i >= len(queries):
                cb(None)
                return

            def ok(items):
                for x in items:
                    names = {title_key(x.get("name")), title_key(x.get("rus_name")), title_key(x.get("eng_name"))}
                    names |= {title_key(n) for n in x.get("otherNames") or []}
                    if keys & (names - {""}):
                        cb(x.get("slug_url"))
                        return
                attempt(i + 1)
            self.search(queries[i], ok, lambda _e: attempt(i + 1))
        attempt(0)


# ================================================================ AnimeVost
def vost_names(title) -> tuple[str, str]:
    """«Рус / Romaji [1-12 из 12]» → (рус, romaji)."""
    clean = re.sub(r"\[.*?\]", "", title or "").strip()
    parts = [p.strip() for p in clean.split(" / ")]
    return parts[0], parts[1] if len(parts) > 1 else ""


def vost_episodes(items: list[dict]) -> list[dict]:
    eps = []
    for i, it in enumerate(items or []):
        streams = {}
        if it.get("hd"):
            streams["720"] = it["hd"]
        if it.get("std"):
            streams["480"] = it["std"]
        if not streams:
            continue
        eps.append(make_episode(parse_ordinal(it.get("name"), i + 1), streams=streams, preview=it.get("preview")))
    eps.sort(key=lambda e: e["ordinal"])
    return eps


class AnimeVostApi:
    def __init__(self, http: HttpClient):
        self.http = http

    def search(self, query, on_ok):
        def ok(d):
            on_ok(d.get("data") if isinstance(d, dict) and not d.get("error") else [])
        # AnimeVost отвечает 404 на знаки препинания и когда ничего не найдено.
        clean = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", query)).strip()
        self.http.request(f"{ANIMEVOST_API}/search", None, ok, lambda _e: on_ok([]), form={"name": clean},
                          cache_ttl=TTL.SEARCH)

    def episodes(self, vost_id, on_ok, on_err=None):
        self.http.request(f"{ANIMEVOST_API}/playlist", None, lambda items: on_ok(vost_episodes(items)), on_err,
                          form={"id": vost_id}, cache_ttl=TTL.VOST_PLAYLIST)

    def find(self, release: dict, cb) -> None:
        keys = match_keys(release)
        queries = search_queries(release, full_first=False)

        def attempt(i):
            if i >= len(queries):
                cb(None)
                return

            def ok(items):
                for x in items:
                    ru, romaji = vost_names(x.get("title"))
                    if keys & ({title_key(ru), title_key(romaji)} - {""}):
                        cb(x.get("id"))
                        return
                attempt(i + 1)
            self.search(queries[i], ok)
        attempt(0)


# ================================================================ YummyAnime → Kodik
def yani_dub_groups(videos: list[dict]) -> dict[str, dict]:
    """Серии по озвучкам: {"yani:<озвучка>": {"name", "kind", "eps"}}. Только плеер Kodik — у него есть API."""
    out: dict[str, dict] = {}
    for v in videos or []:
        data = v.get("data") or {}
        if "kodik" not in (data.get("player") or "").lower() or not v.get("iframe_url"):
            continue
        name = re.sub(r"^Озвучка\s+", "", data.get("dubbing") or "", flags=re.I).strip() or "Kodik"
        g = out.setdefault(f"yani:{name}", {"name": name, "eps": [],
                                            "kind": "sub" if "субтитр" in name.lower() else "voice"})
        o = parse_ordinal(v.get("number"), len(g["eps"]) + 1)
        if any(e["ordinal"] == o for e in g["eps"]):
            continue
        url = v["iframe_url"]
        op = (v.get("skips") or {}).get("opening") or {}
        g["eps"].append(make_episode(
            o, duration=v.get("duration"), kodik=("https:" + url) if url.startswith("//") else url,
            opening={"start": op["time"], "stop": op["time"] + op["length"]} if op.get("length") else None))
    for g in out.values():
        g["eps"].sort(key=lambda e: e["ordinal"])
    return out


class YaniApi:
    def __init__(self, http: HttpClient):
        self.http = http

    def find(self, release: dict, cb) -> None:
        """id тайтла в YummyAnime: сверяем по id Shikimori, без него — по названию и году."""
        sid = (release.get("shikimori") or {}).get("id")
        keys = match_keys(release)
        queries: list[str] = []
        for q in [(release.get("name") or {}).get("main")] + search_queries(release):
            if q and q not in queries:
                queries.append(q)
        queries = queries[:4]

        def attempt(i):
            if i >= len(queries):
                cb(None)
                return

            def ok(d):
                for x in (d or {}).get("response") or []:
                    if sid:
                        hit = (x.get("remote_ids") or {}).get("shikimori_id") == sid
                    else:
                        year = release.get("year")
                        hit = title_key(x.get("title")) in keys and (not year or abs((x.get("year") or 0) - year) <= 1)
                    if hit:
                        cb(x.get("anime_id"))
                        return
                attempt(i + 1)
            self.http.request(f"{YANI_API}/search", {"q": queries[i], "limit": 20}, ok, lambda _e: attempt(i + 1),
                              cache_ttl=TTL.SEARCH)
        attempt(0)

    def dubs(self, anime_id, cb) -> None:
        self.http.request(f"{YANI_API}/anime/{anime_id}/videos", None,
                          lambda d: cb(yani_dub_groups((d or {}).get("response"))), lambda _e: cb({}),
                          cache_ttl=TTL.YANI_VIDEOS)


# ================================================================ AniSkip
def parse_skip_times(d: dict | None) -> dict | None:
    res: dict = {}
    for r in (d or {}).get("results") or [] if (d or {}).get("found") else []:
        k = "opening" if r.get("skipType") == "op" else "ending"
        iv = r.get("interval") or {}
        res.setdefault(k, {"start": iv.get("startTime"), "stop": iv.get("endTime")})
    return res or None


class AniSkipApi:
    """Время заставки и титров, размеченное сообществом. Ключ — id MyAnimeList = id Shikimori;
    длительность передаём, чтобы получить разметку под эту версию видео."""

    def __init__(self, http: HttpClient):
        self.http = http

    def skip_times(self, sid, ordinal, duration_s, cb) -> None:
        if not sid or not duration_s or duration_s < 60 or float(ordinal) != int(float(ordinal)):
            cb(None)
            return
        self.http.request(f"{ANISKIP_API}/{sid}/{int(float(ordinal))}",
                          {"types": ["op", "ed"], "episodeLength": round(duration_s)},
                          lambda d: cb(parse_skip_times(d)), lambda _e: cb(None), cache_ttl=TTL.ANISKIP)
