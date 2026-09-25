"""Сезоны, фильмы и OVA франшизы: сведение графа Shikimori с релизами AniLibria.

Граф франшизы берётся с Shikimori (самый полный: там есть и фильмы, которых нет на AniLibria),
релизы AniLibria подставляются по shikimori id.
"""
from __future__ import annotations

from typing import Callable

from .ids import shiki_id

HIDDEN_KINDS = {"Клип", "Реклама", "Проморолик"}
TYPE_LABELS = {"MOVIE": "Фильм", "OVA": "OVA", "ONA": "ONA", "SPECIAL": "Спешл", "OAD": "OAD", "WEB": "WEB"}


def is_movie(release: dict) -> bool:
    t = release.get("type") or {}
    return t.get("value") == "MOVIE" or t.get("description") in ("Фильм", "Movie")


def entry_label(kind: str, season_no: int) -> str:
    if kind in ("TV Сериал", "TV"):
        return f"{season_no} сезон"
    if kind in ("Фильм", "MOVIE"):
        return "Фильм"
    if "Спецвыпуск" in kind or kind == "SPECIAL":
        return "Спешл"
    return TYPE_LABELS.get(kind, kind)


def merge_franchise(release: dict, nodes: list[dict] | None, al_releases: list[dict],
                    poster_url: Callable[[dict], str | None], shiki_base: str) -> list[dict]:
    """[{shiki_id, label, name, year, poster, release_id|None, release|None, current}] или [], если сезон один."""
    by_shiki = {shiki_id(r): r for r in al_releases if shiki_id(r)}
    entries: list[dict] = []
    if nodes:
        nodes = sorted((n for n in nodes if n.get("kind") not in HIDDEN_KINDS),
                       key=lambda n: (n.get("year") or 9999, n.get("date") or 0))
        season = 0
        for n in nodes:
            if n.get("kind") == "TV Сериал":
                season += 1
            al = by_shiki.get(n["id"])
            poster = poster_url(al) if al else None
            if not poster and "missing" not in (n.get("image_url") or "missing"):
                poster = f"{shiki_base}/system/animes/original/{n['id']}.jpg"
            entries.append({
                "shiki_id": n["id"], "label": entry_label(n.get("kind") or "", season),
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
                "shiki_id": shiki_id(r), "label": entry_label(t, season), "name": (r.get("name") or {}).get("main"),
                "year": r.get("year"), "poster": poster_url(r), "release_id": r["id"],
                "release": r, "current": r["id"] == release["id"],
            })
    if len(entries) < 2:
        return []
    if not any(e["current"] for e in entries):
        for e in entries:
            if e["release_id"] == release["id"]:
                e["current"] = True
    return entries
