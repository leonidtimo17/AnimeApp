"""Публичный API Shikimori: полный каталог, франшизы, «Похожее», темы и комментарии; запросы от имени
пользователя (с токеном) и получение токена OAuth. Разбор ответов в формат карточек приложения."""
from __future__ import annotations

import re
import urllib.parse

from ...core.config import SHIKI, TTL
from ...domain.ids import SHIKI_OFFSET
from ...domain.shikimori import HIDDEN_KINDS, KIND_RANK, KINDS, RATINGS, SCOPE
from ...domain.titles import strip_bbcode, title_key
from ..http.client import HttpClient

SEARCH_LIMIT = 50


def shiki_item(x: dict) -> dict:
    """Карточка и «релиз» из ответа Shikimori (для тайтлов, которых нет на AniLibria)."""
    img = ((x.get("image") or {}).get("original") or "")
    year = (x.get("aired_on") or "")[:4]
    parts = [p for p in (year, KINDS.get(x.get("kind"), ""),
                         f"{x['episodes']} эп." if x.get("episodes") else "") if p]
    rel = {"id": SHIKI_OFFSET + int(x["id"]),
           "name": {"main": x.get("russian") or x.get("name"), "english": x.get("name")},
           "poster": {"src": (SHIKI + img) if img and "missing" not in img else None},
           "year": int(year) if year.isdigit() else None,
           "type": {"description": KINDS.get(x.get("kind"), "")},
           "episodes_total": x.get("episodes") or None,
           "is_ongoing": x.get("status") == "ongoing",
           "shikimori": {"id": int(x["id"]), "rating": float(x["score"]) if x.get("score") else None},
           "episodes": []}
    return {"id": rel["id"], "title": rel["name"]["main"], "subtitle": " · ".join(parts),
            "poster": rel["poster"]["src"], "badge": "Анонс" if x.get("status") == "anons" else None,
            "status": None, "favorite": None, "progress": None, "release": rel}


def shiki_release(x: dict) -> dict:
    """Полная карточка тайтла из ответа /api/animes/{id}."""
    rel = shiki_item(x)["release"]
    rel["name"]["alternative"] = (x.get("english") or [None])[0]
    rel["description"] = strip_bbcode(x.get("description"))
    rel["genres"] = [{"name": g.get("russian") or g.get("name")} for g in x.get("genres") or []]
    rel["age_rating"] = {"label": RATINGS.get(x.get("rating"))}
    rel["average_duration_of_episode"] = x.get("duration")
    return rel


def sort_search_results(query: str, items: list[dict]) -> list[dict]:
    """Порядок: точное совпадение названия → сериалы, фильмы, потом спешлы → по дате выхода.
    (Сам Shikimori при поиске ставит первыми короткие спешлы, например у «Re:Zero».)"""
    key = title_key(query)
    items = [x for x in items or [] if x.get("kind") not in HIDDEN_KINDS]
    items.sort(key=lambda x: (key not in (title_key(x.get("russian")), title_key(x.get("name"))),
                              KIND_RANK.get(x.get("kind"), 6), x.get("aired_on") or "9999"))
    return items


class ShikimoriApi:
    def __init__(self, http: HttpClient):
        self.http = http

    # ------------------------------------------------------------ публичное
    def search(self, query, on_ok, on_err=None, page=1, scope=None):
        """on_ok(items, has_more) — has_more говорит, есть ли следующая страница."""
        def ok(items):
            has_more = len(items or []) >= SEARCH_LIMIT
            on_ok(sort_search_results(query, items), has_more)
        return self.http.request(f"{SHIKI}/api/animes", {"search": query, "limit": SEARCH_LIMIT, "page": page},
                                 ok, on_err, cache_ttl=TTL.SEARCH, scope=scope)

    def anime(self, sid, on_ok, on_err=None, scope=None):
        """Карточка тайтла — один запрос на всех: страница тайтла, предстоящие серии, тема обсуждения."""
        return self.http.request(f"{SHIKI}/api/animes/{sid}", None, on_ok, on_err, cache_ttl=TTL.SHIKI_ANIME,
                                 scope=scope)

    def similar(self, sid, on_ok, on_err=None, scope=None):
        return self.http.request(f"{SHIKI}/api/animes/{sid}/similar", None, on_ok, on_err, cache_ttl=TTL.FRANCHISE,
                                 scope=scope)

    def franchise(self, sid, on_ok, on_err=None):
        return self.http.request(f"{SHIKI}/api/animes/{sid}/franchise", None, on_ok, on_err, cache_ttl=TTL.FRANCHISE)

    def episode_topic(self, sid, episode: int, on_ok, on_err=None):
        return self.http.request(f"{SHIKI}/api/animes/{sid}/topics",
                                 {"kind": "episode", "episode": episode, "limit": 1}, on_ok, on_err,
                                 cache_ttl=TTL.SHIKI_ANIME)

    def comments(self, topic_id, page, on_ok, on_err=None, scope=None):
        return self.http.request(f"{SHIKI}/api/comments", {"commentable_id": topic_id, "commentable_type": "Topic",
                                                            "page": page, "limit": 30, "desc": 1},
                                 on_ok, on_err, scope=scope)

    def user(self, user_id, on_ok, on_err=None):
        return self.http.request(f"{SHIKI}/api/users/{user_id}", None, on_ok, on_err, cache_ttl=TTL.SHIKI_USER_STATS)

    # ------------------------------------------------------------ OAuth
    @staticmethod
    def authorize_url(client_id: str, redirect: str) -> str:
        return (f"{SHIKI}/oauth/authorize?client_id={urllib.parse.quote(client_id)}"
                f"&redirect_uri={urllib.parse.quote(redirect)}&response_type=code"
                f"&scope={urllib.parse.quote(SCOPE)}")

    def token(self, form: dict, app_name: str, on_ok, on_err):
        return self.http.request(f"{SHIKI}/oauth/token", None, on_ok, on_err, headers={"User-Agent": app_name},
                                 form=form, retries=0)

    def authorized(self, path, access_token: str, app_name: str, on_ok, on_err=None, params=None, json_body=None,
                   method=None):
        return self.http.request(f"{SHIKI}{path}", params, on_ok, on_err, json_body=json_body, method=method,
                                 headers={"Authorization": f"Bearer {access_token}", "User-Agent": app_name})


def poster_from_href(x: dict) -> str | None:
    """Постер с Shikimori по ссылке shikimori_href (обложки AnimeLib закрыты от встраивания)."""
    m = re.search(r"/animes/[a-z]*(\d+)", x.get("shikimori_href") or "")
    return f"{SHIKI}/system/animes/original/{m.group(1)}.jpg" if m else None
