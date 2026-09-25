"""Резервная копия библиотеки (экспорт/импорт JSON) и очистка кэша."""
from __future__ import annotations

import json

from ..core.errors import ValidationError
from ..infrastructure.database.connection import Database
from ..infrastructure.database.repositories import (AnimeRepository, HttpCacheRepository, LibraryRepository,
                                                    ProgressRepository)

# Какие столбцы можно брать из файла: имена столбцов подставляются в SQL, поэтому — только из этого списка.
COLUMNS = {
    "anime": {"id", "alias", "title", "title_en", "poster", "subtitle", "episodes_total", "is_ongoing"},
    "library": {"anime_id", "status", "favorite", "score", "added_at", "updated_at"},
    "progress": {"anime_id", "episode_id", "ordinal", "position", "duration", "watched", "updated_at"},
}


class BackupService:
    def __init__(self, db: Database, anime: AnimeRepository, library: LibraryRepository,
                 progress: ProgressRepository, http_cache: HttpCacheRepository, http_client=None, images=None):
        self.db = db
        self.anime = anime
        self.library = library
        self.progress = progress
        self.http_cache = http_cache
        self.http_client = http_client
        self.images = images

    def export_json(self, path: str) -> None:
        dump = {"version": 1, "anime": self.anime.export_rows(), "library": self.library.export_rows(),
                "progress": self.progress.export_rows()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False, indent=1)

    def import_json(self, path: str) -> int:
        """Возвращает число записей. ValidationError — если файл не резервная копия AnimeApp."""
        try:
            with open(path, encoding="utf-8") as f:
                dump = json.load(f)
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Не удалось прочитать файл: {exc}") from exc
        if not isinstance(dump, dict) or not any(isinstance(dump.get(t), list) for t in COLUMNS):
            raise ValidationError("Это не резервная копия AnimeApp")
        n = 0
        with self.db.transaction():
            for table, allowed in COLUMNS.items():
                for row in dump.get(table) or []:
                    if not isinstance(row, dict):
                        continue
                    row = {k: v for k, v in row.items() if k in allowed}
                    if not row:
                        continue
                    cols = ",".join(row)
                    marks = ",".join("?" * len(row))
                    if table == "anime" and "id" in row:
                        # Не затираем сохранённые полные карточки (в копии их нет)
                        updates = ",".join(f"{c}=excluded.{c}" for c in row if c != "id") or "id=id"
                        sql = f"INSERT INTO anime ({cols}) VALUES ({marks}) ON CONFLICT(id) DO UPDATE SET {updates}"
                    else:
                        sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})"
                    self.db.execute(sql, tuple(row.values()))
                    n += 1
        self.anime.forget_cache()
        return n

    def clear_cache(self) -> tuple[int, int]:
        """Очистить ответы серверов и картинки. Возвращает (число ответов, байт) до очистки."""
        n, size = self.http_cache.stats()
        self.http_cache.clear()
        if self.http_client is not None:
            self.http_client.clear_memory()
        if self.images is not None:
            self.images.clear()
        return n, size
