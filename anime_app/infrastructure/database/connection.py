"""SQLite: соединение, схема и миграции. Файл library.db совместим со всеми прошлыми версиями."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from ...core.errors import DatabaseError
from ...core.logging import get_logger

log = get_logger("db")

SCHEMA = """
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
-- v3: индексы под частые запросы (последняя серия тайтла, списки по статусу, чистка кэша)
CREATE INDEX IF NOT EXISTS idx_progress_anime_updated ON progress(anime_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_library_status ON library(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_library_favorite ON library(favorite, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_http_cache_ts ON http_cache(ts);
"""


class Database:
    """Одно соединение на всё приложение (работает в потоке интерфейса: запросы короткие, база локальная)."""

    def __init__(self, path: str):
        try:
            self.conn = sqlite3.connect(path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            # В режиме WAL это надёжно при сбое программы и заметно быстрее на частых записях (прогресс, кэш).
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self._migrate()
        except sqlite3.Error as exc:
            log.exception("Не удалось открыть базу %s", path)
            raise DatabaseError(f"Не удалось открыть базу данных: {exc}") from exc
        self._depth = 0

    def _migrate(self) -> None:
        self.conn.executescript(SCHEMA)
        # v2: прогресс хранится по номеру серии — он общий для всех озвучек.
        self.conn.execute(
            """UPDATE OR IGNORE progress SET episode_id =
                   CASE WHEN ordinal = CAST(ordinal AS INTEGER) THEN CAST(CAST(ordinal AS INTEGER) AS TEXT)
                        ELSE CAST(ordinal AS TEXT) END
               WHERE episode_id LIKE '%-%-%'"""
        )
        self.conn.execute("DELETE FROM progress WHERE episode_id LIKE '%-%-%'")
        self.conn.commit()

    # ------------------------------------------------------------ запросы
    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        try:
            return self.conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            log.exception("Ошибка чтения: %s", sql)
            raise DatabaseError(f"Ошибка базы данных: {exc}") from exc

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> None:
        """Запись; фиксируется сразу, если не внутри transaction()."""
        try:
            self.conn.execute(sql, params)
            if not self._depth:
                self.conn.commit()
        except sqlite3.Error as exc:
            log.exception("Ошибка записи: %s", sql)
            raise DatabaseError(f"Ошибка базы данных: {exc}") from exc

    @contextmanager
    def transaction(self):
        """Несколько записей одной фиксацией (быстрее и атомарно)."""
        self._depth += 1
        try:
            yield self
        except Exception:
            self._depth -= 1
            if not self._depth:
                self.conn.rollback()
            raise
        self._depth -= 1
        if not self._depth:
            try:
                self.conn.commit()
            except sqlite3.Error as exc:
                raise DatabaseError(f"Ошибка базы данных: {exc}") from exc

    def vacuum(self) -> None:
        self.conn.execute("VACUUM")

    def close(self) -> None:
        self.conn.close()
