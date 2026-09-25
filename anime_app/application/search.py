"""Поиск по названию сразу в двух каталогах, постранично: сначала страницы AniLibria,
потом — полный каталог Shikimori (там есть все аниме, серии для них ищутся в других источниках)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..core.errors import describe
from ..core.i18n import t
from ..domain.titles import norm
from ..infrastructure.api.anilibria import AniLibriaApi
from ..infrastructure.api.shikimori import ShikimoriApi
from ..infrastructure.http.client import RequestScope
from .releases import ReleaseService


@dataclass
class SearchPage:
    items: list[dict]
    source: str                   # "anilibria" | "shikimori"
    number: int                   # номер страницы в своём каталоге
    total: int = 0                # найдено на AniLibria
    extra: int = 0                # добавлено из полного каталога
    has_more: bool = False
    finished: bool = False        # оба каталога пролистаны до конца

    @property
    def nothing_found(self) -> bool:
        return self.number == 1 and not self.items and (self.source == "anilibria" or self.total == 0)


@dataclass
class _State:
    page: int = 0
    total_pages: int = 1
    total: int = 0
    shiki_page: int = 0
    shiki_done: bool = False
    extra: int = 0
    seen_names: set = field(default_factory=set)
    seen_shiki: set = field(default_factory=set)


class SearchSession:
    """Один поиск: filters — параметры каталога AniLibria (жанр, тип, годы, сортировка)."""

    def __init__(self, anilibria: AniLibriaApi, shikimori: ShikimoriApi, releases: ReleaseService,
                 query: str, filters: dict | None = None):
        self.anilibria = anilibria
        self.shikimori = shikimori
        self.releases = releases
        self.query = query.strip()
        self.filters = filters or {}
        self.loading = False
        self._s = _State()
        self._scope = RequestScope()

    @property
    def exhausted(self) -> bool:
        s = self._s
        return s.page >= s.total_pages and (not self.query or s.shiki_done)

    def cancel(self) -> None:
        """Пользователь начал новый поиск — ответы старого не нужны."""
        self._scope.cancel()
        self.loading = False

    def next_page(self, on_page: Callable[[SearchPage], None], on_err: Callable[[str], None]) -> None:
        if self.loading or self.exhausted:
            return
        self.loading = True
        if self._s.page < self._s.total_pages:
            self._anilibria_page(on_page, on_err)
        else:
            self._shiki_page(on_page, on_err)

    def _anilibria_page(self, on_page, on_err):
        s = self._s

        def ok(data):
            self.loading = False
            pag = data.get("meta", {}).get("pagination", {})
            s.total_pages = pag.get("total_pages", 1)
            s.page = pag.get("current_page", s.page + 1)
            s.total = pag.get("total", 0)
            releases = data.get("data", [])
            for r in releases:
                name = r.get("name") or {}
                s.seen_names |= {norm(name.get("main")), norm(name.get("english"))} - {""}
                if (r.get("shikimori") or {}).get("id"):
                    s.seen_shiki.add(int(r["shikimori"]["id"]))
            on_page(SearchPage(self.releases.items(releases), "anilibria", s.page, s.total, s.extra,
                               not self.exhausted, self.exhausted))
            # Страницы AniLibria кончились — сразу подгружаем полный каталог Shikimori
            if s.page >= s.total_pages and self.query and not s.shiki_done:
                self.next_page(on_page, on_err)

        def fail(err):
            self.loading = False
            on_err(describe(err, t("search.failed")))

        f = self.filters
        self.anilibria.catalog(ok, fail, page=s.page + 1, limit=30, search=self.query or None,
                               genre=f.get("genre"), types=f.get("types"), year_from=f.get("year_from"),
                               year_to=f.get("year_to"), sorting=f.get("sorting"), scope=self._scope)

    def _shiki_page(self, on_page, on_err):
        s = self._s
        s.shiki_page += 1
        page = s.shiki_page

        def ok(results, has_more):
            self.loading = False
            s.shiki_done = not has_more
            items = []
            for x in results:
                names = {norm(x.get("name")), norm(x.get("russian"))} - {""}
                if names & s.seen_names or int(x["id"]) in s.seen_shiki:
                    continue
                items.append(self.releases.shiki_card(x))
            for x in results or []:
                s.seen_shiki.add(int(x["id"]))
            s.extra += len(items)
            on_page(SearchPage(items, "shikimori", page, s.total, s.extra, not self.exhausted, self.exhausted))

        def fail(_err):
            self.loading = False
            s.shiki_done = True
            on_page(SearchPage([], "shikimori", page, s.total, s.extra, False, True))
        self.shikimori.search(self.query, ok, fail, page=page, scope=self._scope)
