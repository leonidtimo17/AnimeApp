"""Плеер Kodik: ссылка на серию и выбор плеера команды озвучки. Те же правила — в мобильной версии (services/kodik.js).

Kodik отдаёт видео только через свой встраиваемый плеер (публичный iframe-API), поэтому источник — ссылка на плеер.
"""
from __future__ import annotations

import urllib.parse

MIN_START = 5   # меньше — начинаем сначала (как и прогресс: первые 5 с не записываются)


def kodik_url(src: str, start_from: float = 0) -> str:
    """https, без своего выбора озвучки и серий (они — в нашем интерфейсе), с позицией продолжения."""
    parts = urllib.parse.urlsplit(("https:" + src) if src.startswith("//") else src)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k not in ("translations", "only_episode", "start_from")]
    query.append(("translations", "false"))
    if parts.path.startswith(("/season/", "/serial/")):
        query.append(("only_episode", "true"))
    if start_from and start_from > MIN_START:
        query.append(("start_from", str(int(start_from))))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), ""))


def pick_kodik_player(players: list[dict] | None, team_id) -> dict | None:
    """Плеер нужной команды из списка плееров серии AnimeLib; нет её — первый доступный (fallback)."""
    kodik = [p for p in players or [] if p.get("player") == "Kodik" and p.get("src")]
    exact = [p for p in kodik if (p.get("team") or {}).get("id") == int(team_id)]
    chosen = (exact or kodik or [None])[0]
    if not chosen:
        return None
    return {"src": chosen["src"], "team": (chosen.get("team") or {}).get("name"), "fallback": not exact}
