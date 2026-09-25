"""Названия: сопоставление между каталогами, поисковые запросы, подписи."""
from __future__ import annotations

import re

from ..core.formatting import fmt_ordinal
from ..core.i18n import t

_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8"}
_ORDINALS = {"первый": "1", "второй": "2", "третий": "3", "четвертый": "4", "пятый": "5", "шестой": "6",
             "первая": "1", "вторая": "2", "третья": "3", "четвертая": "4", "пятая": "5"}


def norm(text) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", (text or "").lower().replace("ё", "е"))


def title_key(text) -> str:
    """Ключ для сопоставления названий между сайтами:
    «Mushoku Tensei III» = «Mushoku Tensei 3», «(третий сезон)» = «3», «Часть 2» = «Part 2»."""
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"\b(ii|iii|iv|v|vi|vii|viii)\b", lambda m: " " + _ROMAN[m.group(1)] + " ", t)
    for word, digit in _ORDINALS.items():
        t = re.sub(rf"\b{word}\b", digit, t)
    t = re.sub(r"\b(сезон|season|часть|part|tv|тв)\b", lambda m: "p" if m.group(1) in ("часть", "part") else "", t)
    return norm(t)


def match_keys(release: dict) -> set[str]:
    """Все варианты названия тайтла в виде ключей title_key."""
    name = release.get("name") or {}
    return {title_key(name.get("english")), title_key(name.get("main")), title_key(name.get("alternative"))} - {""}


def search_queries(release: dict, full_first: bool = True) -> list[str]:
    """Варианты поискового запроса: полное название, часть до «:», первые слова.
    Поиск AnimeVost не находит ничего по длинным названиям — нужны короткие."""
    name = release.get("name") or {}
    out: list[str] = []
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


def same_dub(a, b) -> bool:
    """Одна команда в разных каталогах пишется по-разному: «Дублированный»/«Дублированная», «2x2»/«2×2»."""
    x, y = norm((a or "").replace("×", "x")), norm((b or "").replace("×", "x"))
    if x == y:
        return True
    return min(len(x), len(y)) >= 5 and (x.startswith(y) or y.startswith(x) or x[:8] == y[:8])


def strip_bbcode(text) -> str:
    text = re.sub(r"\[(\w+)=[^\]]*\](.*?)\[/\1\]", r"\2", text or "")
    return re.sub(r"\[/?[^\]]+\]", "", text).strip()


def release_title(release: dict | None) -> str:
    name = (release or {}).get("name") or {}
    return name.get("main") or name.get("english") or t("anime.untitled")


def release_subtitle(release: dict) -> str:
    parts = []
    if release.get("year"):
        parts.append(str(release["year"]))
    kind = (release.get("type") or {}).get("description")
    if kind:
        parts.append(kind)
    total = release.get("episodes_total")
    if total:
        parts.append(t("anime.episodes_short", n=total))
    return " · ".join(parts)


def episode_label(ep: dict) -> str:
    label = t("player.episode_n", n=fmt_ordinal(ep.get("ordinal")))
    if ep.get("name"):
        label += f" — {ep['name']}"
    return label
