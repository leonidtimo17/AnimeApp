"""Форматирование чисел, времени и дат для интерфейса (без Qt)."""
from __future__ import annotations

import datetime

MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def fmt_ordinal(value) -> str:
    """Номер серии: 12.0 → «12», 12.5 → «12.5»."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(f)) if f.is_integer() else str(f)


def fmt_seconds(sec) -> str:
    """75 → «1:15», 3725 → «1:02:05»."""
    s = int(max(0, sec or 0))
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_ms(ms) -> str:
    return fmt_seconds((ms or 0) // 1000)


def fmt_duration(sec) -> str:
    if not sec:
        return ""
    m = round(sec / 60)
    return f"{m} мин" if m < 60 else f"{m // 60} ч {m % 60} мин"


def fmt_when(ts, today: datetime.date | None = None) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    today = today or datetime.date.today()
    if dt.date() == today:
        return f"сегодня в {dt:%H:%M}"
    if dt.date() == today - datetime.timedelta(days=1):
        return f"вчера в {dt:%H:%M}"
    return f"{dt:%d.%m.%Y %H:%M}"


def next_air_date(weekday: int, today: datetime.date | None = None) -> datetime.date:
    """Ближайшая дата для дня недели (1 = понедельник), включая сегодня."""
    today = today or datetime.date.today()
    return today + datetime.timedelta(days=(weekday - today.isoweekday()) % 7)


def short_date(d) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def fmt_air_date(d) -> str:
    if not d:
        return "дата пока неизвестна"
    text = f"{d.day} {MONTHS[d.month - 1]}, {WEEKDAYS_SHORT[d.weekday()]}"
    if getattr(d, "hour", 0) or getattr(d, "minute", 0):
        text += f" · {d:%H:%M}"
    return text


def ago(iso: str | None, now: datetime.datetime | None = None) -> str:
    """«5 мин назад», «3 ч назад», «2 дн назад» или дата."""
    try:
        t = datetime.datetime.fromisoformat(iso)
        s = ((now or datetime.datetime.now(t.tzinfo)) - t).total_seconds()
    except (TypeError, ValueError):
        return ""
    if s < 3600:
        return f"{max(1, round(s / 60))} мин назад"
    if s < 86400:
        return f"{round(s / 3600)} ч назад"
    if s < 86400 * 30:
        return f"{round(s / 86400)} дн назад"
    return t.strftime("%d.%m.%Y")
