"""Озвучки: порядок, выбор по умолчанию, группы для меню.

Озвучка: {"id": "anilibria"|"animevost"|"kodik:<team_id>"|"yani:<озвучка>", "name": str,
          "kind": "voice"|"sub", "native": bool}   # native — встроенный плеер, иначе плеер Kodik
"""
from __future__ import annotations

from ..core.i18n import t
from .episodes import dub_group
from .titles import norm

ANILIBRIA = {"id": "anilibria", "name": "AniLibria", "kind": "voice", "native": True}
ANIMEVOST = {"id": "animevost", "name": "AnimeVost", "kind": "voice", "native": True}


def sort_dubs(dubs: list[dict]) -> list[dict]:
    """Встроенный плеер → озвучка → субтитры, по алфавиту."""
    return sorted(dubs, key=lambda d: (not d["native"], d["kind"] == "sub", d["name"].lower()))


def choose_dub(dubs: list[dict], saved_id: str | None, preferred_name: str | None) -> dict | None:
    """Сохранённая озвучка тайтла → любимая озвучка пользователя → первая (встроенный плеер)."""
    if not dubs:
        return None
    for d in dubs:
        if d["id"] == saved_id:
            return d
    pref = norm(preferred_name or "")
    if pref:
        for d in dubs:
            n = norm(d["name"])
            if n and (n.startswith(pref) or pref.startswith(n)):
                return d
    return dubs[0]


def menu_groups(dubs: list[dict]) -> list[tuple[str, list[dict]]]:
    """Группы меню озвучек (пустые не показываются)."""
    groups = [
        (t("dubs.builtin"), [d for d in dubs if d["native"]]),
        (t("dubs.kodik_voice"), [d for d in dubs if not d["native"] and d["kind"] == "voice"]),
        (t("dubs.kodik_subs"), [d for d in dubs if not d["native"] and d["kind"] == "sub"]),
    ]
    return [(title, items) for title, items in groups if items]


def representatives(dubs: list[dict]) -> list[dict]:
    """По одной озвучке на группу источника (все Kodik-озвучки делят один список серий)."""
    reps: dict[str, dict] = {}
    for d in dubs:
        reps.setdefault(dub_group(d), d)
    return list(reps.values())


def alternative_dub(dubs: list[dict], groups: set[str], choose_kodik) -> dict | None:
    """Озвучка, в которой есть серия: сначала встроенный плеер, потом Kodik (choose_kodik — любимая команда)."""
    for d in dubs:
        if d["native"] and d["id"] in groups:
            return d
    if "kodik" in groups:
        kodik = [d for d in dubs if not d["native"]]
        return choose_kodik(kodik) if kodik else None
    return None
