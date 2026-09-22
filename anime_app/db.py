"""Локальная база SQLite: списки, избранное, прогресс серий, история, настройки."""
import json
import sqlite3
import time

STATUSES = {
    "watching": "Смотрю",
    "planned": "Хочу посмотреть",
    "completed": "Просмотрено",
    "postponed": "Отложено",
    "dropped": "Брошено",
}

# Серия считается просмотренной, если досмотрена до титров или осталось меньше 3 минут/10%.
WATCHED_TAIL_MS = 180_000


class Database:
    def __init__(self, path):
        # Подписчики на изменения списка и прогресса (связь с Shikimori): fn(kind, anime_id),
        # kind — "status" | "score" | "episode"
        self.listeners = []
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS anime (
                id INTEGER PRIMARY KEY,
                alias TEXT,
                title TEXT,
                title_en TEXT,
                poster TEXT,
                subtitle TEXT,
                episodes_total INTEGER,
                is_ongoing INTEGER,
                data TEXT,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS library (
                anime_id INTEGER PRIMARY KEY,
                status TEXT,
                favorite INTEGER NOT NULL DEFAULT 0,
                score INTEGER,
                added_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS progress (
                anime_id INTEGER NOT NULL,
                episode_id TEXT NOT NULL,
                ordinal REAL,
                position INTEGER NOT NULL DEFAULT 0,
                duration INTEGER NOT NULL DEFAULT 0,
                watched INTEGER NOT NULL DEFAULT 0,
                updated_at REAL,
                PRIMARY KEY (anime_id, episode_id)
            );
            CREATE INDEX IF NOT EXISTS idx_progress_updated ON progress(updated_at DESC);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS http_cache (url TEXT PRIMARY KEY, ts REAL, body TEXT);
            """
        )
        # v2: прогресс хранится по номеру серии — он общий для всех озвучек.
        self.conn.execute(
            """UPDATE OR IGNORE progress SET episode_id =
                   CASE WHEN ordinal = CAST(ordinal AS INTEGER) THEN CAST(CAST(ordinal AS INTEGER) AS TEXT)
                        ELSE CAST(ordinal AS TEXT) END
               WHERE episode_id LIKE '%-%-%'"""
        )
        self.conn.execute("DELETE FROM progress WHERE episode_id LIKE '%-%-%'")
        self.conn.commit()

    # ---------------------------------------------------------------- anime
    def cache_anime(self, release: dict, poster_url: str, subtitle: str, full: bool = False):
        """Сохраняет релиз, чтобы библиотека и история работали офлайн."""
        name = release.get("name") or {}
        existing = self.conn.execute("SELECT data FROM anime WHERE id=?", (release["id"],)).fetchone()
        data = json.dumps(release, ensure_ascii=False) if full else (existing["data"] if existing else None)
        self.conn.execute(
            """INSERT INTO anime (id, alias, title, title_en, poster, subtitle, episodes_total,
                                  is_ongoing, data, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET alias=excluded.alias, title=excluded.title,
                   title_en=excluded.title_en, poster=excluded.poster, subtitle=excluded.subtitle,
                   episodes_total=excluded.episodes_total, is_ongoing=excluded.is_ongoing,
                   data=excluded.data, updated_at=excluded.updated_at""",
            (
                release["id"], release.get("alias"), name.get("main") or name.get("english"),
                name.get("english"), poster_url, subtitle, release.get("episodes_total"),
                int(bool(release.get("is_ongoing"))), data, time.time(),
            ),
        )
        self.conn.commit()

    def cached_release(self, anime_id):
        row = self.conn.execute("SELECT data FROM anime WHERE id=?", (anime_id,)).fetchone()
        return json.loads(row["data"]) if row and row["data"] else None

    # -------------------------------------------------------------- library
    def library_entry(self, anime_id):
        row = self.conn.execute("SELECT * FROM library WHERE anime_id=?", (anime_id,)).fetchone()
        return dict(row) if row else {"anime_id": anime_id, "status": None, "favorite": 0, "score": None}

    def _upsert_library(self, anime_id, **fields):
        now = time.time()
        entry = self.library_entry(anime_id)
        entry.update(fields)
        self.conn.execute(
            """INSERT INTO library (anime_id, status, favorite, score, added_at, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(anime_id) DO UPDATE SET status=excluded.status, favorite=excluded.favorite,
                   score=excluded.score, updated_at=excluded.updated_at""",
            (anime_id, entry["status"], entry["favorite"], entry.get("score"), now, now),
        )
        self.conn.execute(
            "DELETE FROM library WHERE status IS NULL AND favorite=0 AND score IS NULL"
        )
        self.conn.commit()

    def _notify(self, kind, anime_id):
        for fn in list(self.listeners):
            try:
                fn(kind, anime_id)
            except Exception:  # noqa: BLE001 — сбой подписчика не должен мешать сохранению
                pass

    def set_status(self, anime_id, status):
        self._upsert_library(anime_id, status=status)
        self._notify("status", anime_id)

    def set_favorite(self, anime_id, favorite: bool):
        self._upsert_library(anime_id, favorite=int(favorite))

    def set_score(self, anime_id, score):
        self._upsert_library(anime_id, score=score)
        self._notify("score", anime_id)

    def set_entry_quiet(self, anime_id, status, score):
        """Без отправки на Shikimori — для загрузки списка оттуда."""
        self._upsert_library(anime_id, status=status, score=score)

    def library(self, status=None, favorites=False):
        sql = """SELECT a.*, l.status, l.favorite, l.score, l.updated_at AS lib_updated
                 FROM library l JOIN anime a ON a.id = l.anime_id"""
        if favorites:
            rows = self.conn.execute(sql + " WHERE l.favorite=1 ORDER BY l.updated_at DESC")
        else:
            rows = self.conn.execute(sql + " WHERE l.status=? ORDER BY l.updated_at DESC", (status,))
        return [dict(r) for r in rows]

    def library_counts(self):
        counts = {s: 0 for s in STATUSES}
        for r in self.conn.execute("SELECT status, COUNT(*) c FROM library WHERE status IS NOT NULL GROUP BY status"):
            counts[r["status"]] = r["c"]
        counts["favorite"] = self.conn.execute("SELECT COUNT(*) FROM library WHERE favorite=1").fetchone()[0]
        return counts

    # ------------------------------------------------------------- progress
    def save_progress(self, anime_id, episode_id, ordinal, position, duration, ending_start_ms=None):
        if duration <= 0:
            return False
        tail = duration - position
        watched = (
            (ending_start_ms and position >= ending_start_ms)
            or tail <= min(WATCHED_TAIL_MS, duration * 0.1)
        )
        prev = self.conn.execute(
            "SELECT watched FROM progress WHERE anime_id=? AND episode_id=?", (anime_id, episode_id)
        ).fetchone()
        was = bool(prev and prev["watched"])
        watched = int(bool(watched) or was)
        self.conn.execute(
            """INSERT INTO progress (anime_id, episode_id, ordinal, position, duration, watched, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(anime_id, episode_id) DO UPDATE SET position=excluded.position,
                   duration=excluded.duration, watched=excluded.watched, updated_at=excluded.updated_at""",
            (anime_id, episode_id, ordinal, int(position), int(duration), watched, time.time()),
        )
        self.conn.commit()
        if watched and not was:
            self._notify("episode", anime_id)
        return bool(watched)

    def set_watched(self, anime_id, episode_id, ordinal, watched: bool, duration=0):
        self.conn.execute(
            """INSERT INTO progress (anime_id, episode_id, ordinal, position, duration, watched, updated_at)
               VALUES (?,?,?,0,?,?,?)
               ON CONFLICT(anime_id, episode_id) DO UPDATE SET watched=excluded.watched,
                   position=CASE WHEN excluded.watched=0 THEN 0 ELSE progress.position END""",
            (anime_id, episode_id, ordinal, int(duration or 0), int(watched), time.time()),
        )
        self.conn.commit()
        self._notify("episode", anime_id)

    def tracked_ids(self):
        """Все тайтлы из списков и истории просмотра."""
        rows = self.conn.execute("SELECT anime_id FROM library UNION SELECT DISTINCT anime_id FROM progress")
        return [r[0] for r in rows]

    def progress_for(self, anime_id):
        rows = self.conn.execute("SELECT * FROM progress WHERE anime_id=?", (anime_id,))
        return {r["episode_id"]: dict(r) for r in rows}

    def last_progress(self, anime_id):
        row = self.conn.execute(
            "SELECT * FROM progress WHERE anime_id=? AND updated_at IS NOT NULL ORDER BY updated_at DESC, ordinal DESC LIMIT 1",
            (anime_id,),
        ).fetchone()
        return dict(row) if row else None

    def continue_watching(self, limit=20):
        rows = self.conn.execute(
            """SELECT a.*, p.episode_id, p.ordinal, p.position, p.duration, p.watched, p.updated_at AS watched_at
               FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY anime_id ORDER BY updated_at DESC, ordinal DESC) rn
                     FROM progress WHERE updated_at IS NOT NULL) p
               JOIN anime a ON a.id = p.anime_id
               WHERE p.rn = 1
                 AND COALESCE((SELECT status FROM library WHERE anime_id=a.id), '') NOT IN ('completed','dropped')
               ORDER BY p.updated_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]

    def history(self, limit=300):
        rows = self.conn.execute(
            """SELECT a.id, a.title, a.poster, a.subtitle, p.episode_id, p.ordinal, p.position,
                      p.duration, p.watched, p.updated_at
               FROM progress p JOIN anime a ON a.id = p.anime_id
               WHERE p.updated_at IS NOT NULL AND p.position > 0
               ORDER BY p.updated_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]

    def clear_history(self):
        # Отметки «просмотрено» сохраняем, стираем только позиции.
        self.conn.execute("DELETE FROM progress WHERE watched=0")
        self.conn.execute("UPDATE progress SET position=0")
        self.conn.commit()

    def stats(self):
        r = self.conn.execute(
            "SELECT COUNT(*) eps, COALESCE(SUM(duration),0) ms FROM progress WHERE watched=1"
        ).fetchone()
        return {"episodes": r["eps"], "hours": r["ms"] / 3_600_000}

    # ------------------------------------------------------------- settings
    def setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    # ------------------------------------------------------------ http cache
    def http_get(self, url, ttl):
        """Тело ответа из кэша: свежее ttl секунд (ttl=None — любой давности)."""
        row = self.conn.execute("SELECT ts, body FROM http_cache WHERE url=?", (url,)).fetchone()
        if not row or (ttl is not None and time.time() - row["ts"] > ttl):
            return None
        return row["body"]

    def http_put(self, url, body):
        self.conn.execute("INSERT OR REPLACE INTO http_cache (url, ts, body) VALUES (?,?,?)", (url, time.time(), body))
        self.conn.commit()

    def http_prune(self, max_age_days=14):
        self.conn.execute("DELETE FROM http_cache WHERE ts < ?", (time.time() - max_age_days * 86400,))
        self.conn.commit()

    def http_clear(self):
        self.conn.execute("DELETE FROM http_cache")
        self.conn.commit()
        self.conn.execute("VACUUM")

    def http_stats(self):
        r = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(body)),0) FROM http_cache").fetchone()
        return r[0], r[1]

    # --------------------------------------------------------------- backup
    def export_json(self, path):
        dump = {
            "version": 1,
            "anime": [dict(r) for r in self.conn.execute("SELECT id, alias, title, title_en, poster, subtitle, episodes_total, is_ongoing FROM anime")],
            "library": [dict(r) for r in self.conn.execute("SELECT * FROM library")],
            "progress": [dict(r) for r in self.conn.execute("SELECT * FROM progress")],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False, indent=1)

    def import_json(self, path):
        with open(path, encoding="utf-8") as f:
            dump = json.load(f)
        for table in ("anime", "library", "progress"):
            for row in dump.get(table, []):
                cols = ",".join(row)
                marks = ",".join("?" * len(row))
                self.conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
        self.conn.commit()
