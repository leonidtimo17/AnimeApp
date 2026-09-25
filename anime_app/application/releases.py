"""Карточки тайтлов: откуда загрузить (AniLibria, AnimeLib или Shikimori), что сохранить для офлайна,
как показать в сетке."""
from __future__ import annotations

from ..core.errors import AppError
from ..core.i18n import t
from ..domain.ids import SHIKI_OFFSET, is_animelib_id, is_shiki_id
from ..domain.library import card_item
from ..domain.titles import release_subtitle, release_title
from ..infrastructure.api.anilibria import AniLibriaApi
from ..infrastructure.api.shikimori import ShikimoriApi, shiki_item, shiki_release
from ..infrastructure.api.sources import AnimeLibApi
from ..infrastructure.database.repositories import AnimeRepository, LibraryRepository


class ReleaseService:
    def __init__(self, anilibria: AniLibriaApi, shikimori: ShikimoriApi, animelib: AnimeLibApi,
                 anime_repo: AnimeRepository, library_repo: LibraryRepository):
        self.anilibria = anilibria
        self.shikimori = shikimori
        self.animelib = animelib
        self.anime = anime_repo
        self.library = library_repo

    def poster_url(self, release: dict | None) -> str | None:
        return self.anilibria.poster_url(release)

    # ------------------------------------------------------------ загрузка
    def load(self, release_id, on_ok, on_err=None, fresh=False, scope=None):
        """Карточка тайтла: AniLibria или AnimeLib/Shikimori (для тайтлов, которых нет на AniLibria).
        fresh — ссылки на видео без кэша (для плеера)."""
        release_id = int(release_id)
        if is_shiki_id(release_id):
            return self.shikimori.anime(release_id - SHIKI_OFFSET, lambda x: on_ok(shiki_release(x)), on_err,
                                        scope=scope)
        if is_animelib_id(release_id):
            slug = (self.anime.release(release_id) or {}).get("animelib")
            if not slug:
                if on_err:
                    on_err(AppError(t("anime.not_cached")))
                return None
            return self.animelib.anime(slug, on_ok, on_err)
        return self.anilibria.release(release_id, on_ok, on_err, fresh=fresh, scope=scope)

    def load_or_cached(self, release_id, on_ok, on_err, fresh=False):
        """Свежая карточка, а без сети — сохранённая."""
        def fail(err):
            cached = self.anime.release(release_id)
            if cached:
                on_ok(cached)
            else:
                on_err(err)
        self.load(release_id, lambda rel: (self.remember(rel, full=True), on_ok(rel)), fail, fresh=fresh)

    def cached(self, release_id) -> dict | None:
        return self.anime.release(release_id)

    def remember(self, release: dict, full: bool = False) -> None:
        """Сохранить тайтл, чтобы библиотека и история работали офлайн."""
        self.anime.save(release, self.poster_url(release), release_subtitle(release), full=full)

    # ------------------------------------------------------------ карточки
    def item(self, release: dict) -> dict:
        entry = self.library.entry(release["id"])
        return card_item(release["id"], release_title(release), release_subtitle(release), self.poster_url(release),
                         badge=t("anime.ongoing") if release.get("is_ongoing") else None, status=entry.get("status"),
                         favorite=entry.get("favorite"), release=release)

    def items(self, releases: list[dict]) -> list[dict]:
        return [self.item(r) for r in releases]

    def shiki_card(self, x: dict) -> dict:
        """Карточка тайтла из каталога Shikimori (со статусом из библиотеки)."""
        item = shiki_item(x)
        entry = self.library.entry(item["id"])
        item["status"], item["favorite"] = entry.get("status"), entry.get("favorite")
        return item

    @staticmethod
    def item_from_row(row: dict) -> dict:
        progress = None
        if row.get("duration"):
            progress = min(1.0, (row.get("position") or 0) / row["duration"])
        return card_item(row["id"], row.get("title"), row.get("subtitle"), row.get("poster"),
                         status=row.get("status"), favorite=row.get("favorite"), progress=progress)
