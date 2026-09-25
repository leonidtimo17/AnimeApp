"""Репозитории: всё чтение и запись таблиц. Не знают ни об интерфейсе, ни о сети."""
from __future__ import annotations

import json
import time

from ...core.cache import TTLCache
from ...domain.library import STATUSES, is_watched
from .connection import Database


class AnimeRepository:
    """Карточки тайтлов, которые пользователь видел: чтобы библиотека и история работали офлайн."""

    def __init__(self, db: Database):
        self.db = db
        self._releases: TTLCache[int, dict | None] = TTLCache(max_size=300)   # разобранный JSON релизов

    def save(self, release: dict, poster_url: str | None, subtitle: str, full: bool = False) -> None:
        name = release.get("name") or {}
        rid = release["id"]
        data = json.dumps(release, ensure_ascii=False) if full else None
        # Неполную карточку (из списка) пишем, не затирая уже сохранённые полные данные.
        self.db.execute(
            """INSERT INTO anime (id, alias, title, title_en, poster, subtitle, episodes_total,
                                  is_ongoing, data, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET alias=excluded.alias, title=excluded.title,
                   title_en=excluded.title_en, poster=excluded.poster, subtitle=excluded.subtitle,
                   episodes_total=excluded.episodes_total, is_ongoing=excluded.is_ongoing,
                   data=COALESCE(excluded.data, anime.data), updated_at=excluded.updated_at""",
            (rid, release.get("alias"), name.get("main") or name.get("english"), name.get("english"),
             poster_url, subtitle, release.get("episodes_total"), int(bool(release.get("is_ongoing"))), data,
             time.time()),
        )
        if full:
            self._releases.set(rid, json.loads(data))
        else:
            self._releases.pop(rid)

    def release(self, anime_id) -> dict | None:
        """Сохранённый релиз (копия — её можно менять)."""
        anime_id = int(anime_id)
        hit = self._releases.get(anime_id, False)
        if hit is False:
            row = self.db.one("SELECT data FROM anime WHERE id=?", (anime_id,))
            hit = json.loads(row["data"]) if row and row["data"] else None
            self._releases.set(anime_id, hit)
        return json.loads(json.dumps(hit)) if hit else None

    def releases(self, ids) -> dict[int, dict]:
        """Несколько релизов одним запросом."""
        ids = [int(i) for i in ids]
        out: dict[int, dict] = {}
        for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
            marks = ",".join("?" * len(chunk))
            for r in self.db.query(f"SELECT id, data FROM anime WHERE id IN ({marks}) AND data IS NOT NULL",
                                   tuple(chunk)):
                out[r["id"]] = json.loads(r["data"])
        return out

    def shiki_ids(self) -> dict[int, int]:
        """{наш id: id Shikimori} для всех сохранённых тайтлов (без разбора всего JSON в Python)."""
        rows = self.db.query("SELECT id, json_extract(data, '$.shikimori.id') sid FROM anime "
                             "WHERE data IS NOT NULL AND json_extract(data, '$.shikimori.id') IS NOT NULL")
        return {r["id"]: int(r["sid"]) for r in rows}

    def forget_cache(self) -> None:
        self._releases.clear()

    def export_rows(self) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT id, alias, title, title_en, poster, subtitle, episodes_total, is_ongoing FROM anime")]


class LibraryRepository:
    """Списки: статус, избранное, оценка."""

    EMPTY = {"status": None, "favorite": 0, "score": None}

    def __init__(self, db: Database):
        self.db = db

    def entry(self, anime_id) -> dict:
        row = self.db.one("SELECT * FROM library WHERE anime_id=?", (anime_id,))
        return dict(row) if row else {"anime_id": anime_id, **self.EMPTY}

    def update(self, anime_id, **fields) -> dict:
        """Изменить поля записи; пустая запись (нет статуса, избранного и оценки) удаляется."""
        entry = self.entry(anime_id)
        entry.update(fields)
        now = time.time()
        with self.db.transaction():
            if entry["status"] is None and not entry["favorite"] and entry.get("score") is None:
                self.db.execute("DELETE FROM library WHERE anime_id=?", (anime_id,))
            else:
                self.db.execute(
                    """INSERT INTO library (anime_id, status, favorite, score, added_at, updated_at)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(anime_id) DO UPDATE SET status=excluded.status, favorite=excluded.favorite,
                           score=excluded.score, updated_at=excluded.updated_at""",
                    (anime_id, entry["status"], entry["favorite"], entry.get("score"), now, now),
                )
        return entry

    def list(self, status: str | None = None, favorites: bool = False, limit: int | None = None) -> list[dict]:
        sql = """SELECT a.*, l.status, l.favorite, l.score, l.updated_at AS lib_updated
                 FROM library l JOIN anime a ON a.id = l.anime_id"""
        if favorites:
            sql += " WHERE l.favorite=1 ORDER BY l.updated_at DESC"
            params: tuple = ()
        else:
            sql += " WHERE l.status=? ORDER BY l.updated_at DESC"
            params = (status,)
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.db.query(sql, params)]

    def counts(self) -> dict[str, int]:
        counts = {s: 0 for s in STATUSES}
        for r in self.db.query("SELECT status, COUNT(*) c FROM library WHERE status IS NOT NULL GROUP BY status"):
            counts[r["status"]] = r["c"]
        counts["favorite"] = self.db.one("SELECT COUNT(*) FROM library WHERE favorite=1")[0]
        return counts

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM library")]

    def tracked_ids(self) -> list[int]:
        """Все тайтлы из списков и истории просмотра."""
        return [r[0] for r in self.db.query("SELECT anime_id FROM library UNION SELECT DISTINCT anime_id FROM progress")]

    def signature(self) -> tuple:
        """Меняется при любом изменении списков или просмотренных серий (для пересчёта рекомендаций)."""
        a = self.db.one("SELECT COUNT(*), COALESCE(SUM(favorite),0), COALESCE(MAX(updated_at),0) FROM library")
        b = self.db.one("SELECT COALESCE(SUM(watched),0) FROM progress")
        return tuple(a) + tuple(b)

    def export_rows(self) -> list[dict]:
        return self.all()


class ProgressRepository:
    """Прогресс серий (ключ серии — её номер, общий для всех озвучек) и история."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, anime_id, episode_id, ordinal, position, duration, ending_start_ms=None) -> tuple[bool, bool]:
        """(просмотрена ли серия, стала ли просмотренной только что)."""
        if duration <= 0:
            return False, False
        prev = self.db.one("SELECT watched FROM progress WHERE anime_id=? AND episode_id=?", (anime_id, episode_id))
        was = bool(prev and prev["watched"])
        watched = int(is_watched(position, duration, ending_start_ms) or was)
        self.db.execute(
            """INSERT INTO progress (anime_id, episode_id, ordinal, position, duration, watched, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(anime_id, episode_id) DO UPDATE SET position=excluded.position,
                   duration=excluded.duration, watched=excluded.watched, updated_at=excluded.updated_at""",
            (anime_id, episode_id, ordinal, int(position), int(duration), watched, time.time()),
        )
        return bool(watched), bool(watched) and not was

    def set_watched(self, anime_id, episode_id, ordinal, watched: bool, duration=0) -> None:
        self.db.execute(
            """INSERT INTO progress (anime_id, episode_id, ordinal, position, duration, watched, updated_at)
               VALUES (?,?,?,0,?,?,?)
               ON CONFLICT(anime_id, episode_id) DO UPDATE SET watched=excluded.watched,
                   position=CASE WHEN excluded.watched=0 THEN 0 ELSE progress.position END""",
            (anime_id, episode_id, ordinal, int(duration or 0), int(watched), time.time()),
        )

    def set_watched_many(self, anime_id, episodes: list[tuple[str, float, int]], watched: bool) -> None:
        """[(ключ, номер, длительность мс)] одной транзакцией."""
        with self.db.transaction():
            for key, ordinal, duration in episodes:
                self.set_watched(anime_id, key, ordinal, watched, duration)

    def mark_watched_quiet(self, anime_id, episode_id, ordinal) -> None:
        """Отметка «просмотрено» без позиции (данные с Shikimori)."""
        self.db.execute(
            """INSERT INTO progress (anime_id, episode_id, ordinal, position, duration, watched, updated_at)
               VALUES (?,?,?,0,0,1,?)
               ON CONFLICT(anime_id, episode_id) DO UPDATE SET watched=1""",
            (anime_id, episode_id, ordinal, time.time()),
        )

    def for_anime(self, anime_id) -> dict[str, dict]:
        return {r["episode_id"]: dict(r) for r in self.db.query("SELECT * FROM progress WHERE anime_id=?", (anime_id,))}

    def last(self, anime_id) -> dict | None:
        row = self.db.one(
            "SELECT * FROM progress WHERE anime_id=? AND updated_at IS NOT NULL "
            "ORDER BY updated_at DESC, ordinal DESC LIMIT 1", (anime_id,))
        return dict(row) if row else None

    def continue_watching(self, limit=20) -> list[dict]:
        rows = self.db.query(
            """SELECT a.*, p.episode_id, p.ordinal, p.position, p.duration, p.watched, p.updated_at AS watched_at
               FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY anime_id ORDER BY updated_at DESC, ordinal DESC) rn
                     FROM progress WHERE updated_at IS NOT NULL) p
               JOIN anime a ON a.id = p.anime_id
               LEFT JOIN library l ON l.anime_id = a.id
               WHERE p.rn = 1 AND COALESCE(l.status, '') NOT IN ('completed','dropped')
               ORDER BY p.updated_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]

    def history(self, limit=300) -> list[dict]:
        rows = self.db.query(
            """SELECT a.id, a.title, a.poster, a.subtitle, p.episode_id, p.ordinal, p.position,
                      p.duration, p.watched, p.updated_at
               FROM progress p JOIN anime a ON a.id = p.anime_id
               WHERE p.updated_at IS NOT NULL AND p.position > 0
               ORDER BY p.updated_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]

    def clear_history(self) -> None:
        # Отметки «просмотрено» сохраняем, стираем только позиции.
        with self.db.transaction():
            self.db.execute("DELETE FROM progress WHERE watched=0")
            self.db.execute("UPDATE progress SET position=0")

    def stats(self) -> dict:
        r = self.db.one("SELECT COUNT(*) eps, COALESCE(SUM(duration),0) ms FROM progress WHERE watched=1")
        return {"episodes": r["eps"], "hours": r["ms"] / 3_600_000}

    def watched_by_anime(self) -> list[dict]:
        """По тайтлам: сколько серий досмотрено и сколько это времени."""
        return [dict(r) for r in self.db.query(
            "SELECT anime_id, SUM(watched) eps, SUM(CASE WHEN watched=1 THEN duration ELSE 0 END) ms "
            "FROM progress GROUP BY anime_id")]

    def export_rows(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM progress")]


class SettingsRepository:
    """Настройки (ключ → JSON). Читаются часто, поэтому держим их в памяти."""

    def __init__(self, db: Database):
        self.db = db
        self._cache: dict[str, object] = {}

    def get(self, key: str, default=None):
        if key not in self._cache:
            row = self.db.one("SELECT value FROM settings WHERE key=?", (key,))
            self._cache[key] = json.loads(row["value"]) if row else _ABSENT
        value = self._cache[key]
        return default if value is _ABSENT else json.loads(json.dumps(value))

    def set(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self._cache[key] = json.loads(json.dumps(value))


_ABSENT = object()


class HttpCacheRepository:
    """Ответы серверов (со временем получения): для кэша и работы без интернета."""

    MAX_AGE_DAYS = 14

    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, ttl: float | None) -> str | None:
        """Тело ответа: свежее ttl секунд (ttl=None — любой давности)."""
        row = self.db.one("SELECT ts, body FROM http_cache WHERE url=?", (key,))
        if not row or (ttl is not None and time.time() - row["ts"] > ttl):
            return None
        return row["body"]

    def put(self, key: str, body: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO http_cache (url, ts, body) VALUES (?,?,?)", (key, time.time(), body))

    def prune(self, max_age_days: int = MAX_AGE_DAYS) -> None:
        self.db.execute("DELETE FROM http_cache WHERE ts < ?", (time.time() - max_age_days * 86400,))

    def clear(self) -> None:
        self.db.execute("DELETE FROM http_cache")
        self.db.vacuum()

    def stats(self) -> tuple[int, int]:
        r = self.db.one("SELECT COUNT(*), COALESCE(SUM(LENGTH(body)),0) FROM http_cache")
        return r[0], r[1]
