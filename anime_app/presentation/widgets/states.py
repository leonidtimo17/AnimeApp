"""Единые тексты состояний экрана: загрузка, пусто, ошибка, нет сети."""
from __future__ import annotations

from ...core.errors import describe
from ...core.i18n import t


def loading() -> str:
    return t("common.loading")


def error_text(err, what: str | None = None) -> str:
    """Понятное сообщение по типу ошибки (подробности — в журнал)."""
    return describe(err, what)
