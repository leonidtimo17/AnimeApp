"""Идентификаторы тайтлов.

Тайтлы AniLibria хранятся под своими id, а тайтлы, которых на AniLibria нет, — со смещением:
AnimeLib — от 100 000 000, каталог Shikimori — от 200 000 000. Так все источники живут в одной библиотеке.
"""
from __future__ import annotations

ANIMELIB_OFFSET = 100_000_000
SHIKI_OFFSET = 200_000_000


def is_shiki_id(release_id) -> bool:
    return int(release_id) >= SHIKI_OFFSET


def is_animelib_id(release_id) -> bool:
    return ANIMELIB_OFFSET <= int(release_id) < SHIKI_OFFSET


def is_external_id(release_id) -> bool:
    """Тайтл не с AniLibria (AnimeLib или Shikimori)."""
    return int(release_id) >= ANIMELIB_OFFSET


def shiki_id(release: dict | None) -> int | None:
    """id тайтла на Shikimori (он же id MyAnimeList)."""
    shiki = (release or {}).get("shikimori")
    return shiki.get("id") if isinstance(shiki, dict) else None
