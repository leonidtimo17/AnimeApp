"""Библиотека и прогресс просмотра: списки, избранное, оценки, продолжение просмотра, история.

Все изменения идут через эти сервисы: они сохраняют данные и сообщают об изменении
(интерфейс обновляется, Shikimori получает статус и прогресс).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..domain.episodes import resume_target, start_position
from ..domain.library import AUTO_WATCHING_FROM
from ..infrastructure.database.repositories import LibraryRepository, ProgressRepository, SettingsRepository


class Preferences:
    """Настройки пользователя (качество, громкость, выбранные озвучки, фильтры…)."""

    def __init__(self, repo: SettingsRepository):
        self._repo = repo

    def get(self, key: str, default=None):
        return self._repo.get(key, default)

    def set(self, key: str, value) -> None:
        self._repo.set(key, value)


class LibraryService(QObject):
    changed = Signal()                 # списки изменились — обновить экраны
    entry_changed = Signal(str, int)   # (что: "status" | "score" | "favorite", id тайтла) — для Shikimori

    def __init__(self, repo: LibraryRepository, parent=None):
        super().__init__(parent)
        self.repo = repo

    def entry(self, anime_id) -> dict:
        return self.repo.entry(anime_id)

    def set_status(self, anime_id, status) -> None:
        self.repo.update(anime_id, status=status)
        self.entry_changed.emit("status", int(anime_id))
        self.changed.emit()

    def set_favorite(self, anime_id, favorite: bool) -> None:
        self.repo.update(anime_id, favorite=int(bool(favorite)))
        self.entry_changed.emit("favorite", int(anime_id))
        self.changed.emit()

    def set_score(self, anime_id, score) -> None:
        self.repo.update(anime_id, score=score)
        self.entry_changed.emit("score", int(anime_id))
        self.changed.emit()

    def toggle_planned(self, anime_id, planned: bool) -> None:
        """«Хочу посмотреть» на странице просмотра: снятие отметки возвращает в «Смотрю»."""
        self.set_status(anime_id, "planned" if planned else "watching")

    def mark_watching(self, anime_id) -> bool:
        """Начали смотреть: «Хочу посмотреть»/«Отложено»/без списка → «Смотрю»."""
        if self.repo.entry(anime_id).get("status") in AUTO_WATCHING_FROM:
            self.set_status(anime_id, "watching")
            return True
        return False

    def import_entry(self, anime_id, status, score) -> None:
        """Запись с Shikimori — обратно туда не отправляется."""
        self.repo.update(anime_id, status=status, score=score)

    def rows(self, status: str | None = None, favorites: bool = False, limit: int | None = None) -> list[dict]:
        return self.repo.list(status, favorites, limit)

    def counts(self) -> dict[str, int]:
        return self.repo.counts()

    def tracked_ids(self) -> list[int]:
        return self.repo.tracked_ids()

    def signature(self) -> tuple:
        return self.repo.signature()


class ProgressService(QObject):
    """Прогресс серий. Ключ серии — её номер, поэтому при смене озвучки продолжаете с того же места."""

    changed = Signal()               # серия досмотрена или отметки изменены — обновить экраны
    episode_changed = Signal(int)    # id тайтла — для Shikimori

    def __init__(self, repo: ProgressRepository, parent=None):
        super().__init__(parent)
        self.repo = repo

    def for_anime(self, anime_id) -> dict[str, dict]:
        return self.repo.for_anime(anime_id)

    def last(self, anime_id) -> dict | None:
        return self.repo.last(anime_id)

    def resume(self, anime_id, episodes: list[dict]) -> tuple[int, int]:
        """(индекс серии, позиция мс), с которых продолжить."""
        return resume_target(episodes, self.repo.for_anime(anime_id), self.repo.last(anime_id))

    def open_at(self, anime_id, episodes: list[dict], key: str | None) -> tuple[int, int]:
        """Конкретная серия (с сохранённого места) или продолжение просмотра."""
        if key:
            idx = next((i for i, e in enumerate(episodes) if e["key"] == key), 0)
            return idx, start_position(self.repo.for_anime(anime_id).get(episodes[idx]["key"]))
        return self.resume(anime_id, episodes)

    def save(self, anime_id, ep: dict, position_ms, duration_ms, ending_start_ms=None) -> tuple[bool, bool]:
        """(просмотрена, досмотрена только что)."""
        watched, newly = self.repo.save(anime_id, ep["key"], ep.get("ordinal"), position_ms, duration_ms,
                                        ending_start_ms)
        if newly:
            self.episode_changed.emit(int(anime_id))
        return watched, newly

    def save_raw(self, anime_id, key, ordinal, position_ms, duration_ms) -> None:
        """Прогресс из плеера Kodik (отдельный процесс присылает ключ и номер серии)."""
        self.save(anime_id, {"key": key, "ordinal": ordinal}, position_ms, duration_ms)

    def set_watched(self, anime_id, episodes: list[dict], watched: bool) -> None:
        self.repo.set_watched_many(anime_id, [(e["key"], e.get("ordinal"), (e.get("duration") or 0) * 1000)
                                              for e in episodes], watched)
        self.episode_changed.emit(int(anime_id))
        self.changed.emit()

    def restart(self, anime_id, ep: dict) -> None:
        """«Смотреть с начала»: снять отметку и позицию."""
        self.set_watched(anime_id, [ep], False)

    def mark_watched_quiet(self, anime_id, episodes: list[dict], upto: int) -> int:
        """Отметить просмотренными серии до номера upto (данные с Shikimori, обратно не отправляются)."""
        progress = self.repo.for_anime(anime_id)
        n = 0
        with self.repo.db.transaction():
            for e in episodes:
                o = e.get("ordinal")
                if o is None or float(o) != int(float(o)) or float(o) > upto:
                    continue
                if not (progress.get(e["key"]) or {}).get("watched"):
                    self.repo.mark_watched_quiet(anime_id, e["key"], o)
                    n += 1
        return n

    def notify_changed(self) -> None:
        """Прогресс записан не через этот сервис по одной серии (плеер Kodik закрылся) — обновить экраны."""
        self.changed.emit()

    def continue_watching(self, limit=20) -> list[dict]:
        return self.repo.continue_watching(limit)

    def history(self, limit=300) -> list[dict]:
        return self.repo.history(limit)

    def clear_history(self) -> None:
        self.repo.clear_history()
        self.changed.emit()

    def stats(self) -> dict:
        return self.repo.stats()
