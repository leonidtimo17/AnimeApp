"""Ошибки приложения.

str(ошибка) — понятный пользователю текст (его можно показать как есть), а тип говорит,
что случилось: интерфейс по нему решает, показать «нет сети», «войдите заново» или «ошибка».
"""
from __future__ import annotations


class AppError(Exception):
    """Базовая ошибка приложения."""


class NetworkError(AppError):
    """Сервер не ответил: нет интернета, таймаут, обрыв соединения."""

    def __init__(self, message: str, *, transient: bool = True):
        super().__init__(message)
        self.transient = transient


class ApiError(AppError):
    """Сервер ответил ошибкой (HTTP 4xx/5xx) или непонятным ответом."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def is_client_error(self) -> bool:
        return self.status is not None and 400 <= self.status < 500


class AuthenticationError(ApiError):
    """Нет входа или доступ отозван (Shikimori)."""


class DatabaseError(AppError):
    """Не удалось прочитать или записать локальную базу."""


class PlayerError(AppError):
    """Видео не воспроизводится."""


class ValidationError(AppError):
    """Неверные данные: например, файл резервной копии не того формата."""
