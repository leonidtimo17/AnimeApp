"""Асинхронный клиент бесплатного публичного API AniLibria (AniLiberty).

Ключи и оплата не нужны. Все запросы идут через QNetworkAccessManager,
поэтому интерфейс никогда не блокируется.
"""
import json

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MIRRORS = ["https://anilibria.top", "https://api.anilibria.app"]
USER_AGENT = "AnimeApp/1.0 (desktop)"


class Api(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self._mirror = 0
        self.cache = None   # Database: кэш ответов (ставится в AppContext)

    @property
    def site(self) -> str:
        return MIRRORS[self._mirror]

    def media_url(self, path):
        """Постеры и превью приходят относительными путями."""
        if not path:
            return None
        if path.startswith("http"):
            return path
        return self.site + path

    def poster_url(self, release: dict, size: str = "src"):
        poster = (release or {}).get("poster") or {}
        opt = poster.get("optimized") or {}
        return self.media_url(opt.get(size) or poster.get(size) or poster.get("src"))

    # ------------------------------------------------------------------ core
    def fetch(self, url, params=None, on_ok=None, on_err=None, headers=None, form=None, retry=None,
              json_body=None, timeout=20000, raw=False, cache_ttl=0):
        """Универсальный асинхронный запрос: GET, POST-форма (form) или POST JSON (json_body).
        raw=True — вернуть текст ответа, а не разобранный JSON.
        cache_ttl — сколько секунд ответ считается свежим (кэш в SQLite). Без интернета
        отдаётся последний сохранённый ответ любой давности."""
        qurl = QUrl(url)
        query = QUrlQuery()
        for key, value in (params or {}).items():
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    query.addQueryItem(f"{key}[]", str(item))
            else:
                query.addQueryItem(key, str(value))
        if not query.isEmpty():
            qurl.setQuery(query)

        cache_key = None
        if self.cache and json_body is None:
            cache_key = qurl.toString() + ("|" + json.dumps(form, sort_keys=True, ensure_ascii=False) if form else "")
            hit = self.cache.http_get(cache_key, cache_ttl) if cache_ttl else None
            if hit is not None:
                try:
                    data = hit if raw else json.loads(hit)
                except ValueError:
                    data = None
                if data is not None:
                    if on_ok:
                        QTimer.singleShot(0, lambda: on_ok(data))
                    return None

        req = QNetworkRequest(qurl)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        req.setRawHeader(b"Accept", b"application/json")
        for k, v in (headers or {}).items():
            req.setRawHeader(k.encode(), v.encode())
        req.setTransferTimeout(timeout)
        if json_body is not None:
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
            reply = self.nam.post(req, json.dumps(json_body, ensure_ascii=False).encode("utf-8"))
        elif form is not None:
            body = QUrlQuery()
            for k, v in form.items():
                body.addQueryItem(k, str(v).replace("+", "%2B").replace("&", "%26"))
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/x-www-form-urlencoded")
            reply = self.nam.post(req, body.query(QUrl.ComponentFormattingOption.FullyEncoded).encode())
        else:
            reply = self.nam.get(req)

        def finished():
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                http_status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if http_status is None and retry:
                    retry()
                    return
                # Нет сети — отдаём последний сохранённый ответ (офлайн-режим).
                stale = self.cache.http_get(cache_key, None) if (cache_key and http_status is None) else None
                if stale is not None:
                    try:
                        data = stale if raw else json.loads(stale)
                        if on_ok:
                            on_ok(data)
                        return
                    except ValueError:
                        pass
                if on_err:
                    on_err(reply.errorString())
                return
            try:
                text = bytes(reply.readAll()).decode("utf-8", "replace")
                data = text if raw else json.loads(text)
            except ValueError as exc:
                if on_err:
                    on_err(f"Некорректный ответ сервера: {exc}")
                return
            if cache_key and cache_ttl:
                self.cache.http_put(cache_key, text)
            if on_ok:
                on_ok(data)

        reply.finished.connect(finished)
        return reply

    def get(self, path, params=None, on_ok=None, on_err=None, _attempt=0, cache_ttl=0):
        def retry():
            # Сетевой сбой (не ответ сервера) — пробуем зеркало.
            self._mirror = (self._mirror + 1) % len(MIRRORS)
            self.get(path, params, on_ok, on_err, _attempt + 1, cache_ttl)
        return self.fetch(f"{self.site}/api/v1{path}", params, on_ok, on_err,
                          retry=retry if _attempt < len(MIRRORS) - 1 else None, cache_ttl=cache_ttl)

    # ------------------------------------------------------------- endpoints
    def latest(self, on_ok, on_err=None, limit=24):
        return self.get("/anime/releases/latest", {"limit": limit}, on_ok, on_err, cache_ttl=300)

    def release(self, id_or_alias, on_ok, on_err=None):
        return self.get(f"/anime/releases/{id_or_alias}", None, on_ok, on_err, cache_ttl=120)

    def catalog(self, on_ok, on_err=None, page=1, limit=30, search=None, genre=None,
                types=None, year_from=None, year_to=None, sorting=None, genres=None,
                ongoing=None, season=None):
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
        return self.get("/anime/catalog/releases", params, on_ok, on_err, cache_ttl=600)

    def genres(self, on_ok, on_err=None):
        return self.get("/anime/catalog/references/genres", None, on_ok, on_err, cache_ttl=86400)

    def years(self, on_ok, on_err=None):
        return self.get("/anime/catalog/references/years", None, on_ok, on_err, cache_ttl=86400)

    def schedule(self, on_ok, on_err=None):
        return self.get("/anime/schedule/week", None, on_ok, on_err, cache_ttl=900)

    def franchise(self, release_id, on_ok, on_err=None):
        return self.get(f"/anime/franchises/release/{release_id}", None, on_ok, on_err, cache_ttl=86400)


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
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def release_title(release: dict) -> str:
    name = (release or {}).get("name") or {}
    return name.get("main") or name.get("english") or "Без названия"


def release_subtitle(release: dict) -> str:
    parts = []
    if release.get("year"):
        parts.append(str(release["year"]))
    t = (release.get("type") or {}).get("description")
    if t:
        parts.append(t)
    total = release.get("episodes_total")
    if total:
        parts.append(f"{total} эп.")
    return " · ".join(parts)


def fmt_ordinal(value) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(f)) if f.is_integer() else str(f)


def episode_label(ep: dict) -> str:
    label = f"{fmt_ordinal(ep.get('ordinal'))} серия"
    if ep.get("name"):
        label += f" — {ep['name']}"
    return label
