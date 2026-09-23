"""Источники видео и выбор озвучки.

- AniLibria  — своя озвучка, прямые HLS-потоки → встроенный плеер;
- AnimeVost  — своя озвучка, прямые mp4 → встроенный плеер;
- AnimeLib   — каталог всех аниме и десятки озвучек/субтитров через плеер Kodik
               (открывается в окне веб-плеера, прогресс синхронизируется);
- YummyAnime — ещё один открытый каталог плееров Kodik: в нём есть тайтлы, скрытые в AnimeLib
               (лицензионные — «Тетрадь смерти», «Сага о Винланде», фильмы Гибли…);
- AniSkip    — время заставки и титров, размеченное сообществом.

Все API публичные и бесплатные, ключи не нужны.

Нормализованная серия (для всех источников):
    {"key": "12", "ordinal": 12.0, "name": str|None, "duration": сек|None,
     "opening": {...}|None, "ending": {...}|None,
     "streams": {"1080": url, "720": url, "480": url}|None,   # встроенный плеер
     "animelib_id": int|None,                                 # плеер Kodik (AnimeLib)
     "kodik": url|None,                                       # готовая ссылка Kodik (YummyAnime)
     "preview": url|None}                                     # кадр из серии
Озвучка:
    {"id": "anilibria"|"animevost"|"kodik:<team_id>"|"yani:<озвучка>", "name": str,
     "kind": "voice"|"sub", "native": bool}
"""
import re
import time

from PySide6.QtCore import QObject

from .api import fmt_ordinal

ANIMELIB_API = "https://api.cdnlibs.org/api"
ANIMELIB_HEADERS = {"Site-Id": "5"}
ANIMEVOST_API = "https://api.animetop.info/v1"
YANI_API = "https://api.yani.tv"
ANISKIP_API = "https://api.aniskip.com/v2/skip-times"
SHIKI_KIND_RANK = {"tv": 0, "movie": 1, "ona": 2, "ova": 3, "tv_special": 4, "special": 5}
ANIMELIB_OFFSET = 100_000_000  # id тайтлов из AnimeLib (нет на AniLibria)
SHIKI_OFFSET = 200_000_000     # id тайтлов из каталога Shikimori (нет на AniLibria)
SHIKI = "https://shikimori.io"
SHIKI_KINDS = {"tv": "ТВ", "movie": "Фильм", "ova": "OVA", "ona": "ONA", "special": "Спешл",
               "tv_special": "ТВ-спешл", "music": "Клип", "pv": "Промо", "cm": "Реклама"}
SHIKI_RATINGS = {"g": "0+", "pg": "6+", "pg_13": "13+", "r": "16+", "r_plus": "18+", "rx": "18+"}


def norm(text) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", (text or "").lower().replace("ё", "е"))


_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8"}
_ORDINALS = {"первый": "1", "второй": "2", "третий": "3", "четвертый": "4", "пятый": "5", "шестой": "6",
             "первая": "1", "вторая": "2", "третья": "3", "четвертая": "4", "пятая": "5"}


def title_key(text) -> str:
    """Ключ для сопоставления названий между сайтами:
    «Mushoku Tensei III» = «Mushoku Tensei 3», «(третий сезон)» = «3», «Часть 2» = «Part 2»."""
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"\b(ii|iii|iv|v|vi|vii|viii)\b", lambda m: " " + _ROMAN[m.group(1)] + " ", t)
    for word, digit in _ORDINALS.items():
        t = re.sub(rf"\b{word}\b", digit, t)
    t = re.sub(r"\b(сезон|season|часть|part|tv|тв)\b", lambda m: "p" if m.group(1) in ("часть", "part") else "", t)
    return norm(t)


def search_queries(release, full_first=True):
    """Варианты поискового запроса: полное название, часть до «:», первые слова.
    Поиск AnimeVost не находит ничего по длинным названиям — нужны короткие."""
    name = release.get("name") or {}
    out = []
    for title in (name.get("english"), name.get("main")):
        if not title:
            continue
        variants = [title] if full_first else []
        head = re.split(r"[:.!?(\[]", title)[0].strip()
        variants.append(head)
        words = re.sub(r"[^\w\s]", " ", head).split()
        if len(words) > 2:
            variants.append(" ".join(words[:2]))
        for v in variants:
            if v and len(v) >= 3 and v not in out:
                out.append(v)
    return out


def is_shiki_id(release_id) -> bool:
    return int(release_id) >= SHIKI_OFFSET


def shiki_poster(x):
    """Постер с Shikimori (обложки AnimeLib закрыты от встраивания в сторонние приложения)."""
    m = re.search(r"/animes/[a-z]*(\d+)", x.get("shikimori_href") or "")
    return f"https://shikimori.io/system/animes/original/{m.group(1)}.jpg" if m else None


def is_animelib_id(release_id) -> bool:
    return ANIMELIB_OFFSET <= int(release_id) < SHIKI_OFFSET


def is_external_id(release_id) -> bool:
    """Тайтл не с AniLibria (AnimeLib или Shikimori)."""
    return int(release_id) >= ANIMELIB_OFFSET


def strip_bbcode(text):
    text = re.sub(r"\[(\w+)=[^\]]*\](.*?)\[/\1\]", r"\2", text or "")
    return re.sub(r"\[/?[^\]]+\]", "", text).strip()


def has_streams(ep) -> bool:
    return bool(ep.get("streams") or ep.get("animelib_id") or ep.get("kodik"))


def same_dub(a, b) -> bool:
    """Одна команда в разных каталогах пишется по-разному: «Дублированный»/«Дублированная», «2x2»/«2×2»."""
    x, y = norm((a or "").replace("×", "x")), norm((b or "").replace("×", "x"))
    if x == y:
        return True
    return min(len(x), len(y)) >= 5 and (x.startswith(y) or y.startswith(x) or x[:8] == y[:8])


def _ordinal(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        m = re.search(r"\d+(?:[.,]\d+)?", str(value or ""))
        return float(m.group().replace(",", ".")) if m else float(fallback)


def anilibria_episodes(release):
    eps = []
    for e in release.get("episodes") or []:
        streams = {q: e.get(f"hls_{q}") for q in ("1080", "720", "480") if e.get(f"hls_{q}")}
        if not streams:
            continue
        o = _ordinal(e.get("ordinal"), len(eps) + 1)
        eps.append({
            "key": fmt_ordinal(o), "ordinal": o, "name": e.get("name") or e.get("name_english"),
            "duration": e.get("duration"), "opening": e.get("opening"), "ending": e.get("ending"),
            "streams": streams, "animelib_id": None, "preview": _al_preview(e.get("preview")),
        })
    return eps


def _al_preview(pv):
    """Кадр серии AniLibria: относительный путь → полный адрес."""
    pv = pv or {}
    path = (pv.get("optimized") or {}).get("preview") or pv.get("preview") or pv.get("src")
    if not path:
        return None
    return path if path.startswith("http") else "https://anilibria.top" + path


class Sources(QObject):
    def __init__(self, api, db, parent=None):
        super().__init__(parent)
        self.api = api
        self.db = db
        self._dubs = {}       # release_id -> (time, dubs, matches)
        self._episodes = {}   # (release_id, dub_id) -> episodes
        self._pending = {}    # release_id -> [callbacks]
        self._slugs = {}      # наш id -> slug_url AnimeLib

    # ================================================================ AnimeLib
    def _al(self, path, on_ok, on_err=None, params=None):
        return self.api.fetch(f"{ANIMELIB_API}{path}", params, on_ok, on_err, headers=ANIMELIB_HEADERS)

    def animelib_search(self, query, on_ok, on_err=None):
        self.api.fetch(f"{ANIMELIB_API}/anime", {"q": query}, lambda d: on_ok(d.get("data") or []), on_err,
                       headers=ANIMELIB_HEADERS, cache_ttl=3600)

    def animelib_item(self, x) -> dict:
        """Карточка из результата поиска AnimeLib (для тайтлов, которых нет на AniLibria)."""
        self._slugs[ANIMELIB_OFFSET + int(x["id"])] = x.get("slug_url")
        year = None
        m = re.search(r"\d{4}", x.get("releaseDateString") or "")
        if m:
            year = int(m.group())
        parts = [str(year)] if year else []
        if (x.get("type") or {}).get("label"):
            parts.append(x["type"]["label"].replace(" Сериал", ""))
        return {
            "id": ANIMELIB_OFFSET + int(x["id"]),
            "title": x.get("rus_name") or x.get("name") or "",
            "subtitle": " · ".join(parts),
            "poster": shiki_poster(x),
            "badge": "AnimeLib",
            "release": self._animelib_release(x),
        }

    def _animelib_release(self, x, full=None) -> dict:
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
            "poster": {"src": shiki_poster(x) or shiki_poster(full)},
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

    def animelib_release(self, release_id, on_ok, on_err=None):
        """Полная карточка тайтла из AnimeLib по нашему id."""
        cached = self.db.cached_release(release_id)
        slug = self._slugs.get(int(release_id)) or (cached or {}).get("animelib")
        if not slug:
            if on_err:
                on_err("Тайтл не найден в кэше — откройте его заново через поиск")
            return

        def ok(d):
            data = d.get("data") or {}
            on_ok(self._animelib_release(data, data))

        self._al(f"/anime/{slug}", ok, on_err, {"fields": ["summary", "genres"]})

    # ================================================================ Shikimori (полный каталог)
    SHIKI_SEARCH_LIMIT = 50

    def shiki_search(self, query, on_ok, on_err=None, page=1):
        """Порядок: точное совпадение названия → сериалы, фильмы, потом спешлы → по дате выхода.
        (Сам Shikimori при поиске ставит первыми короткие спешлы, например у «Re:Zero».)
        on_ok(items, has_more) — has_more говорит, есть ли следующая страница."""
        key = title_key(query)

        def ok(items):
            has_more = len(items or []) >= self.SHIKI_SEARCH_LIMIT
            items = [x for x in items or [] if x.get("kind") not in ("music", "pv", "cm")]
            items.sort(key=lambda x: (key not in (title_key(x.get("russian")), title_key(x.get("name"))),
                                      SHIKI_KIND_RANK.get(x.get("kind"), 6), x.get("aired_on") or "9999"))
            on_ok(items, has_more)
        self.api.fetch(f"{SHIKI}/api/animes", {"search": query, "limit": self.SHIKI_SEARCH_LIMIT, "page": page},
                       ok, on_err, cache_ttl=3600)

    @staticmethod
    def shiki_item(x) -> dict:
        img = ((x.get("image") or {}).get("original") or "")
        year = (x.get("aired_on") or "")[:4]
        parts = [p for p in (year, SHIKI_KINDS.get(x.get("kind"), ""),
                             f"{x['episodes']} эп." if x.get("episodes") else "") if p]
        rel = {"id": SHIKI_OFFSET + int(x["id"]),
               "name": {"main": x.get("russian") or x.get("name"), "english": x.get("name")},
               "poster": {"src": (SHIKI + img) if img and "missing" not in img else None},
               "year": int(year) if year.isdigit() else None,
               "type": {"description": SHIKI_KINDS.get(x.get("kind"), "")},
               "episodes_total": x.get("episodes") or None,
               "is_ongoing": x.get("status") == "ongoing",
               "shikimori": {"id": int(x["id"]), "rating": float(x["score"]) if x.get("score") else None},
               "episodes": []}
        return {"id": rel["id"], "title": rel["name"]["main"], "subtitle": " · ".join(parts),
                "poster": rel["poster"]["src"], "badge": "Анонс" if x.get("status") == "anons" else None,
                "release": rel}

    def shiki_release(self, release_id, on_ok, on_err=None):
        """Полная карточка тайтла из Shikimori (для аниме, которых нет на AniLibria)."""
        sid = int(release_id) - SHIKI_OFFSET

        def ok(x):
            rel = self.shiki_item(x)["release"]
            rel["name"]["alternative"] = (x.get("english") or [None])[0]
            rel["description"] = strip_bbcode(x.get("description"))
            rel["genres"] = [{"name": g.get("russian") or g.get("name")} for g in x.get("genres") or []]
            rel["age_rating"] = {"label": SHIKI_RATINGS.get(x.get("rating"))}
            rel["average_duration_of_episode"] = x.get("duration")
            on_ok(rel)
        self.api.fetch(f"{SHIKI}/api/animes/{sid}", None, ok, on_err, cache_ttl=3600)

    # ================================================================ AnimeVost
    def _vost_search(self, query, on_ok, on_err=None):
        def ok(d):
            on_ok(d.get("data") if isinstance(d, dict) and not d.get("error") else [])
        # AnimeVost отвечает 404 на знаки препинания и когда ничего не найдено.
        clean = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", query)).strip()
        self.api.fetch(f"{ANIMEVOST_API}/search", None, ok, lambda _e: on_ok([]), form={"name": clean},
                       cache_ttl=3600)

    @staticmethod
    def _vost_names(title):
        """«Рус / Romaji [1-12 из 12]» → (рус, romaji)."""
        clean = re.sub(r"\[.*?\]", "", title or "").strip()
        parts = [p.strip() for p in clean.split(" / ")]
        return parts[0], parts[1] if len(parts) > 1 else ""

    def _vost_episodes(self, vost_id, on_ok, on_err=None):
        def ok(items):
            eps = []
            for i, it in enumerate(items or []):
                streams = {}
                if it.get("hd"):
                    streams["720"] = it["hd"]
                if it.get("std"):
                    streams["480"] = it["std"]
                if not streams:
                    continue
                o = _ordinal(it.get("name"), i + 1)
                eps.append({"key": fmt_ordinal(o), "ordinal": o, "name": None, "duration": None,
                            "opening": None, "ending": None, "streams": streams, "animelib_id": None,
                            "preview": it.get("preview")})
            eps.sort(key=lambda e: e["ordinal"])
            on_ok(eps)
        self.api.fetch(f"{ANIMEVOST_API}/playlist", None, ok, on_err, form={"id": vost_id}, cache_ttl=900)

    # ================================================================ YummyAnime
    def _find_yani(self, release, cb):
        """id тайтла в YummyAnime: сверяем по id Shikimori, без него — по названию и году."""
        sid = (release.get("shikimori") or {}).get("id")
        keys = self._match_key(release)
        queries = []
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
            self.api.fetch(f"{YANI_API}/search", {"q": queries[i], "limit": 20}, ok, lambda _e: attempt(i + 1),
                           cache_ttl=3600)
        attempt(0)

    def _yani_dubs(self, anime_id, cb):
        """Серии по озвучкам: {"yani:<озвучка>": {"name", "kind", "eps"}}. Только плеер Kodik — у него есть API."""
        def ok(d):
            out = {}
            for v in (d or {}).get("response") or []:
                data = v.get("data") or {}
                if "kodik" not in (data.get("player") or "").lower() or not v.get("iframe_url"):
                    continue
                name = re.sub(r"^Озвучка\s+", "", data.get("dubbing") or "", flags=re.I).strip() or "Kodik"
                g = out.setdefault(f"yani:{name}", {"name": name, "eps": [],
                                                    "kind": "sub" if "субтитр" in name.lower() else "voice"})
                o = _ordinal(v.get("number"), len(g["eps"]) + 1)
                if any(e["ordinal"] == o for e in g["eps"]):
                    continue
                url = v["iframe_url"]
                op = (v.get("skips") or {}).get("opening") or {}
                g["eps"].append({
                    "key": fmt_ordinal(o), "ordinal": o, "name": None, "duration": v.get("duration"),
                    "opening": {"start": op["time"], "stop": op["time"] + op["length"]} if op.get("length") else None,
                    "ending": None, "streams": None, "animelib_id": None, "preview": None,
                    "kodik": ("https:" + url) if url.startswith("//") else url,
                })
            for g in out.values():
                g["eps"].sort(key=lambda e: e["ordinal"])
            cb(out)
        self.api.fetch(f"{YANI_API}/anime/{anime_id}/videos", None, ok, lambda _e: cb({}), cache_ttl=1800)

    # ================================================================ AniSkip
    def skip_times(self, sid, ordinal, duration_s, cb):
        """cb({"opening": {start, stop}, "ending": {...}}) или cb(None). Ключ AniSkip — id MyAnimeList = id Shikimori;
        длительность передаём, чтобы получить разметку под эту версию видео."""
        if not sid or not duration_s or duration_s < 60 or float(ordinal) != int(float(ordinal)):
            cb(None)
            return

        def ok(d):
            res = {}
            for r in (d or {}).get("results") or [] if (d or {}).get("found") else []:
                k = "opening" if r.get("skipType") == "op" else "ending"
                iv = r.get("interval") or {}
                res.setdefault(k, {"start": iv.get("startTime"), "stop": iv.get("endTime")})
            cb(res or None)
        self.api.fetch(f"{ANISKIP_API}/{sid}/{int(float(ordinal))}",
                       {"types": ["op", "ed"], "episodeLength": round(duration_s)}, ok, lambda _e: cb(None),
                       cache_ttl=7 * 86400)

    # ================================================================ matching
    def _match_key(self, release):
        name = release.get("name") or {}
        return {title_key(name.get("english")), title_key(name.get("main")), title_key(name.get("alternative"))} - {""}

    def _find_animelib(self, release, cb):
        if release.get("animelib"):
            cb(release["animelib"])
            return
        keys = self._match_key(release)
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
            self.animelib_search(queries[i], ok, lambda _e: attempt(i + 1))
        attempt(0)

    def _find_animevost(self, release, cb):
        keys = self._match_key(release)
        queries = search_queries(release, full_first=False)

        def attempt(i):
            if i >= len(queries):
                cb(None)
                return

            def ok(items):
                for x in items:
                    ru, romaji = self._vost_names(x.get("title"))
                    if keys & ({title_key(ru), title_key(romaji)} - {""}):
                        cb(x.get("id"))
                        return
                attempt(i + 1)
            self._vost_search(queries[i], ok)
        attempt(0)

    # ================================================================ dubs
    def find_dubs(self, release, callback):
        """callback(dubs, finished) может вызываться несколько раз по мере ответа источников."""
        rid = release["id"]
        cached = self._dubs.get(rid)
        if cached and time.time() - cached[0] < 1800:
            callback(cached[1], True)
            return
        if rid in self._pending:
            self._pending[rid].append(callback)
            return
        self._pending[rid] = [callback]

        state = {"dubs": [], "matches": {}, "left": 3}
        if anilibria_episodes(release):
            state["dubs"].append({"id": "anilibria", "name": "AniLibria", "kind": "voice", "native": True})
            self._episodes[(rid, "anilibria")] = anilibria_episodes(release)

        def publish(finished=False):
            dubs = self._sorted(state["dubs"])
            if finished:
                self._dubs[rid] = (time.time(), dubs, state["matches"])
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
                state["dubs"].append({"id": "animevost", "name": "AnimeVost", "kind": "voice", "native": True})
            done()

        def animelib(slug):
            if not slug:
                done()
                return
            state["matches"]["animelib"] = slug

            def eps_ok(d):
                items = d.get("data") or []
                eps = []
                for i, e in enumerate(items):
                    o = _ordinal(e.get("number") or e.get("item_number"), i + 1)
                    eps.append({"key": fmt_ordinal(o), "ordinal": o, "name": e.get("name"), "duration": None,
                                "opening": None, "ending": None, "streams": None, "animelib_id": e["id"]})
                state["matches"]["animelib_eps"] = eps
                if not eps:
                    done()
                    return
                probe = {eps[0]["animelib_id"], eps[-1]["animelib_id"]}
                seen = {}
                left = {"n": len(probe)}

                def players_ok(pd):
                    for p in (pd.get("data") or {}).get("players") or []:
                        if p.get("player") != "Kodik" or not p.get("team"):
                            continue
                        tid = p["team"]["id"]
                        ttype = (p.get("translation_type") or {}).get("id")
                        seen.setdefault(tid, {
                            "id": f"kodik:{tid}", "name": p["team"].get("name") or "?",
                            "kind": "sub" if ttype == 1 else "voice", "native": False,
                        })
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
                    self._al(f"/episodes/{eid}", players_ok, fin)

            self._al("/episodes", eps_ok, lambda _e: done(), {"anime_id": slug})

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

        self._find_animevost(release, vost)
        self._find_animelib(release, animelib)
        self._find_yani(release, lambda aid: self._yani_dubs(aid, yani) if aid else yani({}))
        publish(False)

    @staticmethod
    def _sorted(dubs):
        return sorted(dubs, key=lambda d: (not d["native"], d["kind"] == "sub", d["name"].lower()))

    def invalidate(self, release_id):
        """Забыть найденные озвучки и серии тайтла (после смены сети ссылки могли устареть)."""
        self._dubs.pop(release_id, None)
        for k in [k for k in self._episodes if k[0] == release_id]:
            self._episodes.pop(k, None)

    def episodes(self, release, dub, on_ok, on_err=None):
        rid = release["id"]
        key = (rid, dub["id"])
        if dub["id"] == "anilibria":
            # Серии AniLibria — всегда из переданного (свежего) релиза: в них ссылки на поток
            on_ok(anilibria_episodes(release))
            return
        if key in self._episodes:
            on_ok(self._episodes[key])
            return
        matches = (self._dubs.get(rid) or (0, [], {}))[2]

        def store(eps):
            self._episodes[key] = eps
            on_ok(eps)

        if dub["id"] == "anilibria":
            store(anilibria_episodes(release))
        elif dub["id"] == "animevost" and matches.get("animevost"):
            self._vost_episodes(matches["animevost"], store, on_err)
        elif dub["id"].startswith("kodik:"):
            store([dict(e) for e in matches.get("animelib_eps") or []])
        elif dub["id"].startswith("yani:"):
            store([dict(e) for e in ((matches.get("yani") or {}).get(dub["id"]) or {}).get("eps", [])])
        elif on_err:
            on_err("Источник недоступен")

    def previews(self, release, dubs, cb):
        """Кадры серий со всех «родных» источников: {ключ серии: url} (у Kodik картинок нет)."""
        native = [d for d in dubs if d["native"]]
        out, left = {}, {"n": len(native)}
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

    # ================================================================ choice
    def choose(self, release, dubs):
        """Сохранённая озвучка тайтла → любимая озвучка пользователя → встроенный плеер."""
        if not dubs:
            return None
        saved = self.db.setting(f"dub:{release['id']}")
        for d in dubs:
            if d["id"] == saved:
                return d
        pref = norm(self.db.setting("preferred_dub", ""))
        if pref:
            for d in dubs:
                n = norm(d["name"])
                if n and (n.startswith(pref) or pref.startswith(n)):
                    return d
        return dubs[0]

    def remember_choice(self, release, dub):
        self.db.set_setting(f"dub:{release['id']}", dub["id"])
        self.db.set_setting("preferred_dub", dub["name"])


def resume_target(release_id, episodes, db):
    """С какой серии и позиции продолжать: (index, position_ms)."""
    if not episodes:
        return 0, 0
    progress = db.progress_for(release_id)
    last = db.last_progress(release_id)
    idx = next((i for i, e in enumerate(episodes) if last and e["key"] == last["episode_id"]), None)
    if idx is None:
        # Нет истории для этих серий — первая непросмотренная.
        for i, e in enumerate(episodes):
            if not (progress.get(e["key"]) or {}).get("watched"):
                return i, (progress.get(e["key"]) or {}).get("position", 0)
        return 0, 0
    if last["watched"]:
        for i in range(idx + 1, len(episodes)):
            p = progress.get(episodes[i]["key"]) or {}
            if not p.get("watched"):
                return i, p.get("position", 0)
        return idx, 0
    return idx, last["position"]
