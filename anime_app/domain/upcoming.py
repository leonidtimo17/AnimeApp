"""Предстоящие серии: дата выхода в Японии (Shikimori) и примерная дата озвучки."""
from __future__ import annotations

import datetime as dt
import re


def upcoming_episodes(release, info, known_keys, dub_weekday=None, today=None):
    """Серии, которых ещё нет: [{ordinal, date|None, state}].

    state = "upcoming" — ещё не вышла в Японии (дата с Shikimori, дальше раз в неделю);
            "no_dub"   — уже вышла в Японии, озвучки пока нет;
            "dub"      — ждём озвучку (дата по дню выхода серий у AniLibria).
    dub_weekday — день недели (1 = пн), когда озвучка выходит, если релиз ещё озвучивается.
    """
    known = [float(k) for k in known_keys if re.fullmatch(r"\d+(\.\d+)?", str(k))]
    max_known = int(max(known)) if known else 0
    status = (info or {}).get("status")
    total = (info or {}).get("episodes") or release.get("episodes_total") or 0
    aired = (info or {}).get("episodes_aired") or 0
    if status == "released":
        aired = max(aired, total)

    dub_dates = None
    if dub_weekday:
        today = today or dt.date.today()
        first = today + dt.timedelta(days=(dub_weekday - today.isoweekday()) % 7 or 7)
        dub_dates = lambda i: dt.datetime.combine(first + dt.timedelta(days=7 * i), dt.time())  # noqa: E731

    out = []
    # Вышли в Японии, но ещё не озвучены
    for i, n in enumerate(range(max_known + 1, min(aired, max_known + 24) + 1)):
        if dub_dates:
            out.append({"ordinal": n, "date": dub_dates(i), "state": "dub"})
        else:
            out.append({"ordinal": n, "date": None, "state": "no_dub"})
    if status not in ("ongoing", "anons"):
        if not info and dub_dates and total > max_known and not out:
            for i, n in enumerate(range(max_known + 1, min(total, max_known + 24) + 1)):
                out.append({"ordinal": n, "date": dub_dates(i), "state": "dub"})
        return out

    # Ещё не вышли
    start = max(aired, max_known) + 1
    end = total if total >= start else start + 2  # число серий неизвестно — покажем ближайшие 3
    nxt = None
    try:
        if info.get("next_episode_at"):
            nxt = dt.datetime.fromisoformat(info["next_episode_at"].replace("Z", "+00:00")).astimezone()
        elif status == "anons" and info.get("aired_on"):
            nxt = dt.datetime.fromisoformat(info["aired_on"])
    except ValueError:
        nxt = None
    for i, n in enumerate(range(start, min(end, start + 24) + 1)):
        out.append({"ordinal": n, "date": nxt + dt.timedelta(days=7 * i) if nxt else None, "state": "upcoming"})
    return out
