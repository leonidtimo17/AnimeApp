"""Единые тексты состояний экрана: загрузка, пусто, ошибка, нет сети."""
from __future__ import annotations

from ...core.errors import AuthenticationError, NetworkError

LOADING = "Загрузка…"


def error_text(err, what: str = "Не удалось загрузить") -> str:
    """Понятное сообщение по типу ошибки."""
    if isinstance(err, NetworkError):
        return f"Нет подключения к интернету — {what.lower()}. Проверьте сеть или VPN и попробуйте ещё раз."
    if isinstance(err, AuthenticationError):
        return f"{what}: войдите в Shikimori заново."
    return f"{what}: {err}"
