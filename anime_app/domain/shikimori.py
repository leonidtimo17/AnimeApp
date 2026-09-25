"""Правила связи с Shikimori: статусы и разметка комментариев."""
from __future__ import annotations

import html
import re

SCOPE = "user_rates comments"
TO_SHIKI = {"planned": "planned", "watching": "watching", "completed": "completed",
            "postponed": "on_hold", "dropped": "dropped"}
FROM_SHIKI = {"planned": "planned", "watching": "watching", "rewatching": "watching", "completed": "completed",
              "on_hold": "postponed", "dropped": "dropped"}
STATUS_NAMES = {"watching": "смотрю", "completed": "просмотрено", "planned": "запланировано",
                "on_hold": "отложено", "dropped": "брошено", "rewatching": "пересматриваю"}
KINDS = {"tv": "ТВ", "movie": "Фильм", "ova": "OVA", "ona": "ONA", "special": "Спешл",
         "tv_special": "ТВ-спешл", "music": "Клип", "pv": "Промо", "cm": "Реклама"}
HIDDEN_KINDS = ("music", "pv", "cm")
KIND_RANK = {"tv": 0, "movie": 1, "ona": 2, "ova": 3, "tv_special": 4, "special": 5}
RATINGS = {"g": "0+", "pg": "6+", "pg_13": "13+", "r": "16+", "r_plus": "18+", "rx": "18+"}


def rate_update(entry: dict, watched_eps: int, rate: dict | None) -> dict | None:
    """Тело записи user_rate для отправки на Shikimori или None, если отправлять нечего."""
    if not rate and not entry.get("status") and not watched_eps and not entry.get("score"):
        return None
    body = {"episodes": max((rate or {}).get("episodes") or 0, watched_eps),   # не уменьшаем
            "status": TO_SHIKI.get(entry.get("status")) or (rate or {}).get("status")
            or ("watching" if watched_eps else "planned")}
    if entry.get("score"):
        body["score"] = entry["score"]
    return body


def comment_body(text: str, *, episode_label: str | None, moment: str | None, spoiler: bool) -> str:
    """Комментарий: [b]серия, момент[/b] текст (под спойлером — если попросили)."""
    tag = [t for t in (episode_label, moment) if t]
    return (f"[b]{', '.join(tag)}[/b] " if tag else "") + (f"[spoiler]{text}[/spoiler]" if spoiler else text)


def render_body(body) -> str:
    """BBCode комментария → простой безопасный HTML (без чужой разметки). Время 12:34 — ссылка t:<сек>."""
    s = html.escape(body or "")
    s = re.sub(r"\[(b|i|u|s)\]([\s\S]*?)\[/\1\]", r"<\1>\2</\1>", s, flags=re.I)
    s = re.sub(r"\[spoiler(?:=[^\]]*)?\]([\s\S]*?)\[/spoiler\]",
               r'<span style="background:#3a3a44;color:#3a3a44">\1</span>', s, flags=re.I)
    s = re.sub(r"\[quote(?:=[^\]]*)?\]([\s\S]*?)\[/quote\]",
               r'<div style="color:#9a9aa6;margin:4px 0 4px 8px">«\1»</div>', s, flags=re.I)
    s = re.sub(r"\[comment=[^\]]*\]([\s\S]*?)\[/comment\]", r"@\1", s, flags=re.I)
    s = re.sub(r"\[(?:url|character|person|anime|manga|ranobe|user)=[^\]]*\]([\s\S]*?)"
               r"\[/(?:url|character|person|anime|manga|ranobe|user)\]", r"\1", s, flags=re.I)
    s = re.sub(r"\[(?:image|poster|img)[^\]]*\](?:[\s\S]*?\[/(?:img|poster)\])?", "🖼", s, flags=re.I)
    s = re.sub(r"\[replies=[^\]]*\]", "", s, flags=re.I)
    s = re.sub(r"\[/?[a-z_]+(?:=[^\]]*)?\]", "", s, flags=re.I)

    def ts(m):
        sec = 0
        for x in m.group(2).split(":"):
            sec = sec * 60 + int(x)
        return (f'{m.group(1)}<a href="t:{sec}" style="color:#ff6a1a;font-weight:700;'
                f'text-decoration:none">{m.group(2)}</a>')
    s = re.sub(r"(^|[^\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])", ts, s)
    return s.replace("\n", "<br>")
