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


def describe(err, what: str | None = None) -> str:
    """Понятный пользователю текст по типу ошибки; технические подробности — только в журнал.

    what — что не получилось («Не удалось загрузить серии»).
    """
    from .i18n import t
    from .logging import get_logger
    log = get_logger("errors")
    what = what or t("errors.load_failed")
    if isinstance(err, NetworkError):
        log.info("%s: %s", what, err)
        return t("errors.network", what=what[:1].lower() + what[1:])
    if isinstance(err, AuthenticationError):
        return t("errors.auth", what=what)
    if isinstance(err, (ApiError, DatabaseError)) or not isinstance(err, AppError):
        log.warning("%s: %r", what, err)
        return t("errors.generic", what=what)
    return f"{what}: {err}"   # AppError/ValidationError — текст уже понятный и переведённый
