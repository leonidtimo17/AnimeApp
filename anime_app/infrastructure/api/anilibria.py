"""Бесплатный публичный API AniLibria (AniLiberty): каталог, релизы, расписание. Ключи не нужны."""
from __future__ import annotations

from ...core.config import ANILIBRIA_MIRRORS, TTL
from ...core.errors import NetworkError
from ..http.client import HttpClient, RequestHandle, RequestScope

TYPES = [
    ("TV", "ТВ"), ("ONA", "ONA"), ("WEB", "WEB"), ("OVA", "OVA"), ("OAD", "OAD"),
    ("MOVIE", "Фильм"), ("DORAMA", "Дорама"), ("SPECIAL", "Спешл"),
]
SORTINGS = [
    ("FRESH_AT_DESC", "Недавно обновлённые"),
    ("RATING_DESC", "По рейтингу"),
    ("YEAR_DESC", "Сначала новые"),
    ("YEAR_ASC", "Сначала старые"),
    ("FRESH_AT_ASC", "Давно обновлённые"),
]
SEASONS = [("winter", "Зима"), ("spring", "Весна"), ("summer", "Лето"), ("autumn", "Осень")]


class AniLibriaApi:
    def __init__(self, http: HttpClient):
        self.http = http
        self._mirror = 0

    @property
    def site(self) -> str:
        return ANILIBRIA_MIRRORS[self._mirror]

    def media_url(self, path):
        """Постеры и превью приходят относительными путями."""
        if not path:
            return None
        if path.startswith("http"):
            return path
        return self.site + path

    def poster_url(self, release: dict | None, size: str = "src"):
        poster = (release or {}).get("poster") or {}
        opt = poster.get("optimized") or {}
        return self.media_url(opt.get(size) or poster.get(size) or poster.get("src"))

    # ------------------------------------------------------------------ core
    def get(self, path, params=None, on_ok=None, on_err=None, cache_ttl=0, scope: RequestScope | None = None,
            _attempt=0) -> RequestHandle:
        """Сетевой сбой (не ответ сервера) — пробуем зеркало."""
        def fail(err):
            if isinstance(err, NetworkError) and _attempt < len(ANILIBRIA_MIRRORS) - 1:
                self._mirror = (self._mirror + 1) % len(ANILIBRIA_MIRRORS)
                self.get(path, params, on_ok, on_err, cache_ttl, scope, _attempt + 1)
            elif on_err:
                on_err(err)
        return self.http.request(f"{self.site}/api/v1{path}", params, on_ok, fail, cache_ttl=cache_ttl, scope=scope)

    # ------------------------------------------------------------- endpoints
    def latest(self, on_ok, on_err=None, limit=24):
        return self.get("/anime/releases/latest", {"limit": limit}, on_ok, on_err, cache_ttl=TTL.LATEST)

    def release(self, id_or_alias, on_ok, on_err=None, fresh=False, scope=None):
        # fresh=True — без кэша: ссылки на видео привязаны к сети (VPN/страна), старые перестают работать
        return self.get(f"/anime/releases/{id_or_alias}", None, on_ok, on_err,
                        cache_ttl=TTL.PLAYER_SOURCE if fresh else TTL.RELEASE, scope=scope)

    def catalog(self, on_ok, on_err=None, page=1, limit=30, search=None, genre=None,
                types=None, year_from=None, year_to=None, sorting=None, genres=None,
                ongoing=None, season=None, scope=None):
        """Каталог AniLibria. genres — список id (нужны все выбранные), ongoing — True/False/None."""
        genre_ids = list(genres or []) + ([genre] if genre else [])
        params = {
            "page": page,
            "limit": limit,
            "f[search]": search,
            "f[genres]": ",".join(str(g) for g in genre_ids) or None,
            "f[types]": types,
            "f[years][from_year]": year_from,
            "f[years][to_year]": year_to,
            "f[sorting]": sorting,
            "f[publish_statuses]": None if ongoing is None else ("IS_ONGOING" if ongoing else "IS_NOT_ONGOING"),
            "f[seasons]": season,
        }
        return self.get("/anime/catalog/releases", params, on_ok, on_err, cache_ttl=TTL.CATALOG, scope=scope)

    def genres(self, on_ok, on_err=None):
        return self.get("/anime/catalog/references/genres", None, on_ok, on_err, cache_ttl=TTL.REFERENCES)

    def years(self, on_ok, on_err=None):
        return self.get("/anime/catalog/references/years", None, on_ok, on_err, cache_ttl=TTL.REFERENCES)

    def schedule(self, on_ok, on_err=None):
        return self.get("/anime/schedule/week", None, on_ok, on_err, cache_ttl=TTL.SCHEDULE)

    def franchise(self, release_id, on_ok, on_err=None):
        return self.get(f"/anime/franchises/release/{release_id}", None, on_ok, on_err, cache_ttl=TTL.FRANCHISE)

    def search(self, query, on_ok, on_err=None):
        return self.get("/app/search/releases", {"query": query}, on_ok, on_err)


def sample_stream(releases: list[dict]) -> str | None:
    """Видео для замера скорости: самое высокое качество последней серии свежего релиза."""
    for r in releases or []:
        ep = r.get("latest_episode") or {}
        for q in ("1080", "720", "480"):
            if ep.get(f"hls_{q}"):
                return ep[f"hls_{q}"]
    return None
