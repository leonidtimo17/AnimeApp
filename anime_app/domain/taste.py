"""Анализ вкусов и рекомендации — только вычисления, без сети и базы.

Алгоритм (работает без ИИ, на ваших данных):
1. Сигналы: каждому тайтлу из библиотеки/истории — вес
   избранное +3, просмотрено +2, смотрю +1.5, хочу посмотреть +0.6, отложено +0.3, брошено −2,
   личная оценка (оценка − 5) / 2.5, досмотренные серии — до +1.5.
2. Профиль: взвешенные суммы по жанрам, типам и годам → нормированные предпочтения.
3. Оценка кандидата: 0.60 · совпадение по жанрам (косинус) + 0.25 · рейтинг
   + 0.10 · любимый тип + 0.05 · близость по годам. Объяснение — общие жанры и самый похожий
   тайтл из того, что вам понравилось.

ИИ получает только названия, жанры и годы — пишет разбор вкуса и выбирает из наших же кандидатов.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from typing import Callable

from ..core.i18n import service, t
from ..core.logging import get_logger
from .titles import norm, release_title

log = get_logger("taste")

STATUS_WEIGHT = {"completed": 2.0, "watching": 1.5, "planned": 0.6, "postponed": 0.3, "dropped": -2.0}
# Язык ответа ИИ — язык интерфейса. Саха модели пока не знают — разбор по-русски.
AI_LANGS = {"ru": "на русском языке", "sah": "на русском языке", "en": "на английском языке (in English)"}


def ai_lang(lang: str | None = None) -> str:
    return lang if (lang or "") in AI_LANGS else ("en" if service().locale == "en" else "ru")


def ai_system(lang: str | None = None) -> str:
    return (f"Ты помощник в приложении для просмотра аниме. Отвечай только валидным JSON {AI_LANGS[ai_lang(lang)]}, "
            "без рассуждений, пояснений и markdown.")


AI_SYSTEM = ai_system("ru")


def genres_of(release) -> list[str]:
    return [g.get("name") for g in (release or {}).get("genres") or [] if g.get("name")]


def type_of(release) -> str:
    return ((release or {}).get("type") or {}).get("description") or ""


def rating_of(release) -> float:
    for key in ("shikimori", "mal"):
        r = (release.get(key) or {}).get("rating")
        if r:
            return float(r)
    return 0.0


class TasteProfile:
    def __init__(self):
        self.titles: list[tuple[dict, float]] = []   # [(release, weight)]
        self.genres: dict[str, float] = {}           # жанр -> 0..1
        self.genres_raw: Counter = Counter()
        self.types: dict[str, float] = {}
        self.year_mean: float | None = None
        self.year_spread = 8.0
        self.status_counts: Counter = Counter()
        self.episodes = 0
        self.hours = 0.0
        self.liked: list[dict] = []                  # тайтлы с большим весом (для объяснений)
        self.disliked_genres: set[str] = set()

    @property
    def empty(self) -> bool:
        return not any(w > 0 for _, w in self.titles)

    def summary(self) -> str:
        top = ", ".join(f"{g} ({v:.0%})" for g, v in list(self.genres.items())[:8])
        types = ", ".join(f"{t} ({v:.0%})" for t, v in list(self.types.items())[:4])
        years = f"около {int(self.year_mean)} года" if self.year_mean else "неизвестно"
        return f"Жанры: {top}. Типы: {types}. Годы: {years}."

    def describe(self) -> str:
        """Разбор вкуса простыми словами."""
        if self.empty:
            return ""
        g = list(self.genres)
        parts = []
        if len(g) >= 2:
            parts.append(t("recs.taste_top3", a=g[0].lower(), b=g[1].lower(), c=g[2].lower()) if len(g) > 2
                         else t("recs.taste_top2", a=g[0].lower(), b=g[1].lower()))
        if self.year_mean:
            decade = int(self.year_mean) // 10 * 10
            parts.append(t("recs.taste_decade", decade=decade) if self.year_spread < 8
                         else t("recs.taste_years", year=int(self.year_mean)))
        if self.types:
            kind, v = next(iter(self.types.items()))
            parts.append(t("recs.taste_format", kind=kind.lower(), share=f"{v:.0%}"))
        if self.status_counts.get("dropped"):
            parts.append(t("recs.taste_dropped", n=self.status_counts["dropped"]))
        return " ".join(parts)


def build_profile(library: list[dict], watched: list[dict], releases: dict[int, dict]) -> TasteProfile:
    """library — строки списков (anime_id, status, favorite, score);
    watched — по тайтлам: (anime_id, eps, ms) — сколько серий досмотрено; releases — кэш карточек тайтлов."""
    p = TasteProfile()
    weights: defaultdict[int, float] = defaultdict(float)
    for entry in library:
        if entry.get("status"):
            p.status_counts[entry["status"]] += 1
        w = STATUS_WEIGHT.get(entry.get("status"), 0.0)
        if entry.get("favorite"):
            w += 3.0
        if entry.get("score"):
            w += (entry["score"] - 5) / 2.5
        weights[entry["anime_id"]] += w
    for r in watched:
        weights[r["anime_id"]] += min(r.get("eps") or 0, 12) / 8.0
        p.episodes += r.get("eps") or 0
        p.hours += (r.get("ms") or 0) / 3_600_000

    genre_w: Counter = Counter()
    type_w: Counter = Counter()
    year_sum = year_w = 0.0
    for aid, w in weights.items():
        rel = releases.get(aid)
        if not rel:
            continue
        p.titles.append((rel, w))
        gs = genres_of(rel)
        for g in gs:
            genre_w[g] += w / math.sqrt(len(gs))
            p.genres_raw[g] += 1
        if type_of(rel):
            type_w[type_of(rel)] += w
        if rel.get("year") and w > 0:
            year_sum += rel["year"] * w
            year_w += w
    pos = {g: v for g, v in genre_w.items() if v > 0}
    top = max(pos.values(), default=1.0)
    p.genres = dict(sorted(((g, v / top) for g, v in pos.items()), key=lambda x: -x[1]))
    p.disliked_genres = {g for g, v in genre_w.items() if v < -1}
    tpos = {t: v for t, v in type_w.items() if v > 0}
    ttot = sum(tpos.values()) or 1.0
    p.types = dict(sorted(((t, v / ttot) for t, v in tpos.items()), key=lambda x: -x[1]))
    if year_w:
        p.year_mean = year_sum / year_w
        dev = [abs((r.get("year") or p.year_mean) - p.year_mean) for r, w in p.titles if w > 0]
        p.year_spread = max(4.0, sum(dev) / len(dev)) if dev else 8.0
    p.liked = [r for r, w in sorted(p.titles, key=lambda x: -x[1]) if w >= 1.5][:12]
    return p


def candidate_queries(profile: TasteProfile, genre_ids: dict[str, int]) -> list[dict]:
    """Запросы каталога: любимые жанры по одному и парой + популярное и свежее."""
    top = [g for g in profile.genres if g in genre_ids][:4]
    queries = [{"genres": [genre_ids[g]], "sorting": "RATING_DESC", "limit": 40} for g in top]
    if len(top) >= 2:
        queries.append({"genres": [genre_ids[top[0]], genre_ids[top[1]]], "sorting": "RATING_DESC", "limit": 30})
    queries.append({"sorting": "RATING_DESC", "limit": 40})
    queries.append({"sorting": "FRESH_AT_DESC", "limit": 30})
    return queries


def score(profile: TasteProfile, releases: list[dict]) -> list[tuple[float, dict, str]]:
    """[(оценка, релиз, причина)] по убыванию."""
    liked_sets = [(r, set(genres_of(r))) for r in profile.liked]
    out = []
    for rel in releases:
        gs = genres_of(rel)
        if not gs:
            continue
        if profile.disliked_genres & set(gs) and len(profile.disliked_genres & set(gs)) >= len(gs) / 2:
            continue
        g_score = sum(profile.genres.get(g, 0.0) for g in gs) / math.sqrt(len(gs)) if profile.genres else 0
        g_score = min(1.0, g_score / 1.6)
        rating = rating_of(rel) / 10.0
        t_score = profile.types.get(type_of(rel), 0.0)
        y_score = 0.5
        if profile.year_mean and rel.get("year"):
            y_score = math.exp(-abs(rel["year"] - profile.year_mean) / (2 * profile.year_spread))
        total = 0.60 * g_score + 0.25 * rating + 0.10 * t_score + 0.05 * y_score
        common = [g for g in gs if g in profile.genres][:3]
        similar = max(liked_sets, key=lambda x: len(x[1] & set(gs)), default=(None, set()))
        reason = ""
        if common:
            reason = t("recs.reason_genres", genres=", ".join(common))
        if similar[0] and len(similar[1] & set(gs)) >= 2:
            reason += " · " + t("recs.reason_similar", title=release_title(similar[0]))
        out.append((total, rel, reason or t("recs.reason_popular")))
    out.sort(key=lambda x: -x[0])
    return out


def because_of(profile: TasteProfile, scored, limit: int = 12) -> list[tuple[dict, list[dict]]]:
    """Подборки «Потому что вам понравилось X»."""
    rows = []
    used: set = set()
    for liked in profile.liked[:3]:
        lg = set(genres_of(liked))
        if len(lg) < 2:
            continue
        picks = []
        for _s, rel, _ in scored:
            overlap = len(lg & set(genres_of(rel)))
            if overlap >= min(3, len(lg)) - 1 and rel["id"] not in used and rel["id"] != liked["id"]:
                picks.append(rel)
            if len(picks) >= limit:
                break
        if len(picks) >= 4:
            used.update(r["id"] for r in picks)
            rows.append((liked, picks))
    return rows


# ================================================================ ИИ
def extract_json(text):
    """JSON из ответа модели: голый, в ```-блоке или в обёртке OpenAI (choices → message → content)."""
    text = (text or "").strip()
    for candidate in (text, *re.findall(r"\{.*\}", text, re.S)):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("choices"):
            content = ((data["choices"][0] or {}).get("message") or {}).get("content") or ""
            return extract_json(content)
        if isinstance(data, dict):
            return data
    return None


def ai_prompt(profile: TasteProfile, pool: list[dict], lang: str | None = None) -> str:
    liked = [f"{release_title(r)} ({r.get('year') or '?'}; {', '.join(genres_of(r)[:4])})"
             for r in profile.liked[:15]]
    cand = [f"{i + 1}. {release_title(r)} ({r.get('year') or '?'}; {', '.join(genres_of(r)[:4])})"
            for i, r in enumerate(pool)]
    return (
        "Ты эксперт по аниме. По данным пользователя сделай короткий разбор его вкуса (4–6 предложений, "
        f"{AI_LANGS[ai_lang(lang)]}, дружелюбно, без воды) и выбери из СПИСКА КАНДИДАТОВ 8 аниме, которые ему понравятся, "
        f"с короткой причиной для каждого (до 12 слов, {AI_LANGS[ai_lang(lang)]}).\n\n"
        f"Профиль: {profile.summary()}\n"
        f"Понравилось: {'; '.join(liked) or 'пока мало данных'}\n\n"
        "СПИСОК КАНДИДАТОВ:\n" + "\n".join(cand) + "\n\n"
        'Ответь ТОЛЬКО JSON без пояснений: {"analysis": "...", "picks": [{"n": номер, "reason": "..."}]}'
    )


def parse_ai_answer(text: str, pool: list[dict], title_of: Callable[[dict], str] = release_title,
                    lang: str | None = None):
    """(analysis, [(релиз, причина)]) или строка-ошибка, если ответ не годится (сам ответ — в журнал)."""
    data = extract_json(text)
    if data is None:
        log.info("ИИ: ответ не JSON: %s", (text or "").strip()[:300])
        return t("recs.ai_errors.format")
    analysis = data.get("analysis") or data.get("разбор") or data.get("анализ") or ""
    if not isinstance(analysis, str):
        analysis = json.dumps(analysis, ensure_ascii=False)
    raw_picks = data.get("picks") or data.get("recommendations") or next(
        (v for v in data.values() if isinstance(v, list)), [])
    picks: list[tuple[dict, str]] = []
    for p in raw_picks:
        if not isinstance(p, dict):
            continue
        n = -1
        for k in ("n", "номер", "id", "index"):
            try:
                n = int(p.get(k)) - 1
                break
            except (TypeError, ValueError):
                continue
        if not 0 <= n < len(pool):
            title = norm(p.get("title") or p.get("name") or p.get("название"))
            n = next((i for i, r in enumerate(pool) if title and norm(title_of(r)) == title), -1)
        if 0 <= n < len(pool) and pool[n] not in [x for x, _ in picks]:
            picks.append((pool[n], p.get("reason") or p.get("причина") or ""))
    # Иногда модель вместо ответа выдаёт свои рассуждения (по-английски) — для русского разбора это брак.
    cyr = sum(1 for ch in analysis if "а" <= ch.lower() <= "я")
    if not picks or (ai_lang(lang) != "en" and cyr < len(analysis) * 0.3):
        log.info("ИИ: непонятный ответ: %s", (text or "").strip()[:300])
        return t("recs.ai_errors.unclear")
    return analysis.strip(), picks
