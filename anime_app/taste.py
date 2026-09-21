"""Анализ вкусов и рекомендации.

Алгоритм (работает без интернета-ИИ, на ваших данных):
1. Сигналы: каждому тайтлу из библиотеки/истории — вес
   избранное +3, просмотрено +2, смотрю +1.5, хочу посмотреть +0.6, отложено +0.3, брошено −2,
   личная оценка (оценка − 5) / 2.5, досмотренные серии — до +1.5.
2. Профиль: взвешенные суммы по жанрам, типам и годам → нормированные предпочтения.
3. Кандидаты: каталог AniLibria по любимым жанрам (по одному и парами) + популярное,
   без того, что уже есть в библиотеке.
4. Оценка кандидата: 0.60 · совпадение по жанрам (косинус) + 0.25 · рейтинг
   + 0.10 · любимый тип + 0.05 · близость по годам. Объяснение — общие жанры и самый похожий
   тайтл из того, что вам понравилось.

ИИ (необязательно): локальная Ollama, если запущена, иначе бесплатный Pollinations (без ключа).
ИИ получает только названия, жанры и годы — пишет разбор вкуса и выбирает из наших же кандидатов.
"""
import json
import math
import re
from collections import Counter, defaultdict

from PySide6.QtCore import QObject

from .api import release_title
from .sources import norm

STATUS_WEIGHT = {"completed": 2.0, "watching": 1.5, "planned": 0.6, "postponed": 0.3, "dropped": -2.0}
OLLAMA = "http://localhost:11434"
POLLINATIONS = "https://text.pollinations.ai/"


def _genres(release):
    return [g.get("name") for g in (release or {}).get("genres") or [] if g.get("name")]


def _type(release):
    return ((release or {}).get("type") or {}).get("description") or ""


def _rating(release):
    for key in ("shikimori", "mal"):
        r = (release.get(key) or {}).get("rating")
        if r:
            return float(r)
    return 0.0


def _extract_json(text):
    """JSON из ответа модели: голый, в ```-блоке или в обёртке OpenAI (choices → message → content)."""
    text = (text or "").strip()
    for candidate in (text, *re.findall(r"\{.*\}", text, re.S)):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("choices"):
            content = ((data["choices"][0] or {}).get("message") or {}).get("content") or ""
            return _extract_json(content)
        if isinstance(data, dict):
            return data
    return None


class TasteProfile:
    def __init__(self):
        self.titles = []                 # [(release, weight)]
        self.genres = {}                 # жанр -> 0..1
        self.genres_raw = Counter()
        self.types = {}
        self.year_mean = None
        self.year_spread = 8.0
        self.status_counts = Counter()
        self.episodes = 0
        self.hours = 0.0
        self.liked = []                  # тайтлы с большим весом (для объяснений)
        self.disliked_genres = set()

    @property
    def empty(self):
        return not any(w > 0 for _, w in self.titles)

    def summary(self):
        top = ", ".join(f"{g} ({v:.0%})" for g, v in list(self.genres.items())[:8])
        types = ", ".join(f"{t} ({v:.0%})" for t, v in list(self.types.items())[:4])
        years = f"около {int(self.year_mean)} года" if self.year_mean else "неизвестно"
        return f"Жанры: {top}. Типы: {types}. Годы: {years}."


class Taste(QObject):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx

    # ================================================================ профиль
    def build_profile(self):
        db = self.ctx.db
        p = TasteProfile()
        weights = defaultdict(float)
        lib = {r["anime_id"]: dict(r) for r in db.conn.execute("SELECT * FROM library")}
        for aid, entry in lib.items():
            if entry.get("status"):
                p.status_counts[entry["status"]] += 1
            w = STATUS_WEIGHT.get(entry.get("status"), 0.0)
            if entry.get("favorite"):
                w += 3.0
            if entry.get("score"):
                w += (entry["score"] - 5) / 2.5
            weights[aid] += w
        for r in db.conn.execute(
                "SELECT anime_id, SUM(watched) eps, SUM(CASE WHEN watched=1 THEN duration ELSE 0 END) ms "
                "FROM progress GROUP BY anime_id"):
            weights[r["anime_id"]] += min(r["eps"] or 0, 12) / 8.0
            p.episodes += r["eps"] or 0
            p.hours += (r["ms"] or 0) / 3_600_000

        genre_w, type_w = Counter(), Counter()
        year_sum = year_w = 0.0
        for aid, w in weights.items():
            rel = db.cached_release(aid)
            if not rel:
                continue
            p.titles.append((rel, w))
            gs = _genres(rel)
            for g in gs:
                genre_w[g] += w / math.sqrt(len(gs))
                p.genres_raw[g] += 1
            if _type(rel):
                type_w[_type(rel)] += w
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

    def missing_details(self):
        """Тайтлы из библиотеки без жанров в кэше — их надо догрузить."""
        ids = [r[0] for r in self.ctx.db.conn.execute(
            "SELECT anime_id FROM library UNION SELECT DISTINCT anime_id FROM progress")]
        return [aid for aid in ids if not _genres(self.ctx.db.cached_release(aid))]

    def fetch_missing(self, done):
        ids = self.missing_details()[:30]
        if not ids:
            done()
            return
        left = {"n": len(ids)}

        def one(*_):
            left["n"] -= 1
            if left["n"] == 0:
                done()

        for aid in ids:
            def ok(rel):
                self.ctx.remember(rel, full=True)
                one()
            self.ctx.load_release(aid, ok, one)

    # ================================================================ кандидаты
    def candidates(self, profile, on_ok):
        """Собирает кандидатов из каталога AniLibria по любимым жанрам."""
        api = self.ctx.api
        known = {r[0] for r in self.ctx.db.conn.execute(
            "SELECT anime_id FROM library UNION SELECT DISTINCT anime_id FROM progress")}
        pool = {}
        queries = []

        def genre_ids(ok):
            api.genres(lambda data: ok({g["name"]: g["id"] for g in data}), lambda _e: ok({}))

        def run(name_to_id):
            top = [g for g in profile.genres if g in name_to_id][:4]
            for g in top:
                queries.append({"genres": [name_to_id[g]], "sorting": "RATING_DESC", "limit": 40})
            if len(top) >= 2:
                queries.append({"genres": [name_to_id[top[0]], name_to_id[top[1]]], "sorting": "RATING_DESC",
                                "limit": 30})
            queries.append({"sorting": "RATING_DESC", "limit": 40})
            queries.append({"sorting": "FRESH_AT_DESC", "limit": 30})
            left = {"n": len(queries)}

            def fin():
                left["n"] -= 1
                if left["n"] == 0:
                    on_ok([r for r in pool.values() if r["id"] not in known])

            for q in queries:
                def ok(data):
                    for r in data.get("data", []):
                        pool.setdefault(r["id"], r)
                    fin()
                api.catalog(ok, lambda _e: fin(), **q)

        genre_ids(run)

    def score(self, profile, releases):
        """[(score, release, reason)] по убыванию."""
        liked_sets = [(r, set(_genres(r))) for r in profile.liked]
        out = []
        for rel in releases:
            gs = _genres(rel)
            if not gs:
                continue
            if profile.disliked_genres & set(gs) and len(profile.disliked_genres & set(gs)) >= len(gs) / 2:
                continue
            g_score = sum(profile.genres.get(g, 0.0) for g in gs) / math.sqrt(len(gs)) if profile.genres else 0
            g_score = min(1.0, g_score / 1.6)
            rating = _rating(rel) / 10.0
            t_score = profile.types.get(_type(rel), 0.0)
            y_score = 0.5
            if profile.year_mean and rel.get("year"):
                y_score = math.exp(-abs(rel["year"] - profile.year_mean) / (2 * profile.year_spread))
            total = 0.60 * g_score + 0.25 * rating + 0.10 * t_score + 0.05 * y_score
            common = [g for g in gs if g in profile.genres][:3]
            similar = max(liked_sets, key=lambda x: len(x[1] & set(gs)), default=(None, set()))
            reason = ""
            if common:
                reason = "жанры: " + ", ".join(common)
            if similar[0] and len(similar[1] & set(gs)) >= 2:
                reason += f" · похоже на «{release_title(similar[0])}»"
            out.append((total, rel, reason or "популярное"))
        out.sort(key=lambda x: -x[0])
        return out

    def because_of(self, profile, scored, limit=12):
        """Подборки «Потому что вам понравилось X»."""
        rows = []
        used = set()
        for liked in profile.liked[:3]:
            lg = set(_genres(liked))
            if len(lg) < 2:
                continue
            picks = []
            for s, rel, _ in scored:
                overlap = len(lg & set(_genres(rel)))
                if overlap >= min(3, len(lg)) - 1 and rel["id"] not in used and rel["id"] != liked["id"]:
                    picks.append(rel)
                if len(picks) >= limit:
                    break
            if len(picks) >= 4:
                used.update(r["id"] for r in picks)
                rows.append((liked, picks))
        return rows

    # ================================================================ ИИ
    def ai_analyze(self, profile, scored, on_ok, on_err):
        """Разбор вкуса и подборка от ИИ. Выбирает только из наших кандидатов."""
        liked = [f"{release_title(r)} ({r.get('year') or '?'}; {', '.join(_genres(r)[:4])})"
                 for r in profile.liked[:15]]
        pool = [rel for _, rel, _ in scored[:45]]
        cand = [f"{i + 1}. {release_title(r)} ({r.get('year') or '?'}; {', '.join(_genres(r)[:4])})"
                for i, r in enumerate(pool)]
        prompt = (
            "Ты эксперт по аниме. По данным пользователя сделай короткий разбор его вкуса (4–6 предложений, "
            "по-русски, дружелюбно, без воды) и выбери из СПИСКА КАНДИДАТОВ 8 аниме, которые ему понравятся, "
            "с короткой причиной для каждого (до 12 слов).\n\n"
            f"Профиль: {profile.summary()}\n"
            f"Понравилось: {'; '.join(liked) or 'пока мало данных'}\n\n"
            "СПИСОК КАНДИДАТОВ:\n" + "\n".join(cand) + "\n\n"
            'Ответь ТОЛЬКО JSON без пояснений: {"analysis": "...", "picks": [{"n": номер, "reason": "..."}]}'
        )

        def parse(text):
            """Разбирает ответ; возвращает текст ошибки или None при успехе."""
            data = _extract_json(text)
            if data is None:
                return f"ИИ ответил не по формату.\n({(text or '').strip()[:160]})"
            analysis = data.get("analysis") or data.get("разбор") or data.get("анализ") or ""
            if not isinstance(analysis, str):
                analysis = json.dumps(analysis, ensure_ascii=False)
            raw_picks = data.get("picks") or data.get("recommendations") or next(
                (v for v in data.values() if isinstance(v, list)), [])
            picks = []
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
                    n = next((i for i, r in enumerate(pool) if title and norm(release_title(r)) == title), -1)
                if 0 <= n < len(pool) and pool[n] not in [x for x, _ in picks]:
                    picks.append((pool[n], p.get("reason") or p.get("причина") or ""))
            # Иногда модель вместо ответа выдаёт свои рассуждения (по-английски) — считаем это браком.
            cyr = sum(1 for ch in analysis if "а" <= ch.lower() <= "я")
            if not picks or cyr < len(analysis) * 0.3:
                return f"ИИ ответил непонятно.\n({(text or '').strip()[:160]})"
            on_ok({"analysis": analysis.strip(), "picks": picks, "provider": state["provider"]})
            return None

        state = {"provider": "", "attempt": 0}
        api = self.ctx.api
        system = ("Ты помощник в приложении для просмотра аниме. Отвечай только валидным JSON на русском языке, "
                  "без рассуждений, пояснений и markdown.")

        def handle(text):
            error = parse(text)
            if error is None:
                return
            if state["attempt"] < 2:
                pollinations()  # у бесплатной модели бывают неудачные ответы — пробуем ещё раз
            else:
                on_err(error + "\nПопробуйте ещё раз через минуту.")

        def pollinations():
            state["attempt"] += 1
            state["provider"] = "Pollinations (облако, бесплатно)"
            body = {"model": "openai", "jsonMode": True, "private": True, "seed": state["attempt"] * 17,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
            api.fetch(POLLINATIONS, None, handle, lambda e: on_err(f"ИИ недоступен: {e}"),
                      json_body=body, timeout=90000, raw=True)

        def ollama(tags):
            models = [m["name"] for m in (tags or {}).get("models") or []]
            if not models:
                pollinations()
                return
            state["provider"] = f"Ollama · {models[0]} (локально)"
            body = {"model": models[0], "system": system, "prompt": prompt, "stream": False, "format": "json"}

            def got(d):
                if parse(d.get("response", "")) is not None:
                    pollinations()
            api.fetch(f"{OLLAMA}/api/generate", None, got, lambda _e: pollinations(),
                      json_body=body, timeout=180000)

        # Локальная Ollama приватнее и работает офлайн — пробуем её первой.
        api.fetch(f"{OLLAMA}/api/tags", None, ollama, lambda _e: pollinations(), timeout=1500)
