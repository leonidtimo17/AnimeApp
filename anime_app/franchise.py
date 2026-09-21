"""Сезоны, фильмы и OVA франшизы + предстоящие серии.

Граф франшизы берётся с Shikimori (самый полный: там есть и фильмы, которых нет на AniLibria),
релизы AniLibria подставляются по shikimori id, остальные ищутся в AnimeLib при клике.
"""
import datetime as dt
import re

from PySide6.QtCore import QObject

from .sources import SHIKI_OFFSET, is_external_id

SHIKI = "https://shikimori.io"
HIDDEN_KINDS = {"Клип", "Реклама", "Проморолик"}
TYPE_LABELS = {"MOVIE": "Фильм", "OVA": "OVA", "ONA": "ONA", "SPECIAL": "Спешл", "OAD": "OAD", "WEB": "WEB"}


def shiki_id(release):
    return (release or {}).get("shikimori", {}).get("id") if isinstance((release or {}).get("shikimori"), dict) else None


def is_movie(release):
    t = release.get("type") or {}
    return t.get("value") == "MOVIE" or t.get("description") in ("Фильм", "Movie")


def _label(kind, season_no):
    if kind in ("TV Сериал", "TV"):
        return f"{season_no} сезон"
    if kind in ("Фильм", "MOVIE"):
        return "Фильм"
    if "Спецвыпуск" in kind or kind == "SPECIAL":
        return "Спешл"
    return TYPE_LABELS.get(kind, kind)


class Franchise(QObject):
    def __init__(self, api, sources, parent=None):
        super().__init__(parent)
        self.api = api
        self.sources = sources
        self._cache = {}
        self._info = {}

    # ------------------------------------------------------------ информация о тайтле
    def info(self, release, on_ok):
        """Статус, число серий и дата следующей серии с Shikimori."""
        sid = shiki_id(release)
        if not sid:
            on_ok(None)
            return
        if sid in self._info:
            on_ok(self._info[sid])
            return

        def ok(d):
            self._info[sid] = d
            on_ok(d)
        self.api.fetch(f"{SHIKI}/api/animes/{sid}", None, ok, lambda _e: on_ok(None), cache_ttl=3600)

    # ------------------------------------------------------------ сезоны и фильмы
    def load(self, release, on_ok):
        """on_ok(entries): [{shiki_id, label, name, year, poster, release_id|None, current}]"""
        rid = release["id"]
        if rid in self._cache:
            on_ok(self._cache[rid])
            return
        sid = shiki_id(release)
        state = {"nodes": None, "anilibria": [], "left": (1 if sid else 0) + (0 if is_external_id(rid) else 1)}
        if state["left"] == 0:
            on_ok([])
            return

        def finish():
            state["left"] -= 1
            if state["left"] > 0:
                return
            entries = self._merge(release, state["nodes"], state["anilibria"])
            self._cache[rid] = entries
            on_ok(entries)

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
            self.api.fetch(f"{SHIKI}/api/animes/{sid}/franchise", None, shiki_ok, lambda _e: finish(),
                           cache_ttl=86400)
        if not is_external_id(rid):
            self.api.franchise(rid, al_ok, lambda _e: finish())

    def _merge(self, release, nodes, al_releases):
        by_shiki = {shiki_id(r): r for r in al_releases if shiki_id(r)}
        entries = []
        if nodes:
            nodes = [n for n in nodes if n.get("kind") not in HIDDEN_KINDS]
            nodes.sort(key=lambda n: (n.get("year") or 9999, n.get("date") or 0))
            season = 0
            for n in nodes:
                if n.get("kind") == "TV Сериал":
                    season += 1
                al = by_shiki.get(n["id"])
                poster = self.api.poster_url(al) if al else None
                if not poster and "missing" not in (n.get("image_url") or "missing"):
                    poster = f"{SHIKI}/system/animes/original/{n['id']}.jpg"
                entries.append({
                    "shiki_id": n["id"], "label": _label(n.get("kind") or "", season),
                    "name": ((al or {}).get("name") or {}).get("main") or n.get("name") or "",
                    "year": n.get("year"), "poster": poster,
                    "release_id": al["id"] if al else None, "release": al,
                    "current": n["id"] == shiki_id(release),
                })
        else:
            season = 0
            for r in sorted(al_releases, key=lambda r: r.get("year") or 0):
                t = (r.get("type") or {}).get("value") or ""
                if t == "TV":
                    season += 1
                entries.append({
                    "shiki_id": shiki_id(r), "label": _label(t, season), "name": (r.get("name") or {}).get("main"),
                    "year": r.get("year"), "poster": self.api.poster_url(r), "release_id": r["id"],
                    "release": r, "current": r["id"] == release["id"],
                })
        if len(entries) < 2:
            return []
        if not any(e["current"] for e in entries):
            for e in entries:
                if e["release_id"] == release["id"]:
                    e["current"] = True
        return entries

    def resolve(self, entry, on_ok):
        """Найти узел франшизы в наших источниках: on_ok(release_id | None)."""
        if entry.get("release_id"):
            on_ok(entry["release_id"])
            return
        sid = entry.get("shiki_id")

        def animelib(*_):
            on_ok(SHIKI_OFFSET + sid if sid else None)

        def al_ok(items):
            for r in items or []:
                if shiki_id(r) == sid:
                    on_ok(r["id"])
                    return
            animelib()
        self.api.get("/app/search/releases", {"query": entry["name"]}, al_ok, animelib)


def upcoming_episodes(release, info, known_keys, dub_weekday=None):
    """Серии, которых ещё нет: [{ordinal, date|None, state}].

    state = "upcoming" — ещё не вышла в Японии (дата с Shikimori, дальше раз в неделю);
            "no_dub"   — уже вышла в Японии, озвучки пока нет;
            "dub"      — ждём озвучку (дата по дню выхода серий у AniLibria).
    dub_weekday — день недели (1 = пн), когда озвучка выходит, если релиз ещё озвучивается.
    """
    known = [float(k) for k in known_keys if re.fullmatch(r"\d+(\.\d+)?", str(k))]
    max_known = int(max(known)) if known else 0
    status = (info or {}).get("status")
    total = (info or {}).get("episodes") or release.get("episodes_total") or 0
    aired = (info or {}).get("episodes_aired") or 0
    if status == "released":
        aired = max(aired, total)

    dub_dates = None
    if dub_weekday:
        today = dt.date.today()
        first = today + dt.timedelta(days=(dub_weekday - today.isoweekday()) % 7 or 7)
        dub_dates = lambda i: dt.datetime.combine(first + dt.timedelta(days=7 * i), dt.time())  # noqa: E731

    out = []
    # Вышли в Японии, но ещё не озвучены
    for i, n in enumerate(range(max_known + 1, min(aired, max_known + 24) + 1)):
        if dub_dates:
            out.append({"ordinal": n, "date": dub_dates(i), "state": "dub"})
        else:
            out.append({"ordinal": n, "date": None, "state": "no_dub"})
    if status not in ("ongoing", "anons"):
        if not info and dub_dates and total > max_known and not out:
            for i, n in enumerate(range(max_known + 1, min(total, max_known + 24) + 1)):
                out.append({"ordinal": n, "date": dub_dates(i), "state": "dub"})
        return out

    # Ещё не вышли
    start = max(aired, max_known) + 1
    end = total if total >= start else start + 2  # число серий неизвестно — покажем ближайшие 3
    nxt = None
    try:
        if info.get("next_episode_at"):
            nxt = dt.datetime.fromisoformat(info["next_episode_at"].replace("Z", "+00:00")).astimezone()
        elif status == "anons" and info.get("aired_on"):
            nxt = dt.datetime.fromisoformat(info["aired_on"])
    except ValueError:
        nxt = None
    for i, n in enumerate(range(start, min(end, start + 24) + 1)):
        out.append({"ordinal": n, "date": nxt + dt.timedelta(days=7 * i) if nxt else None, "state": "upcoming"})
    return out
