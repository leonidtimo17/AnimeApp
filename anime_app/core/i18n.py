"""Переводы интерфейса: один сервис на всё приложение. Правила те же, что в мобильной версии (core/i18n/i18n.js).

- ключи по разделам: t("player.retry"), t("dates.minutes_ago", n=5);
- нет перевода на выбранном языке — русский; нет и там — понятный текст из самого ключа (никогда не None/пусто);
- пропуски пишутся в журнал один раз (язык с пометкой meta.pending — не шумит: он переводится постепенно);
- множественное число: {"one": ..., "few": ..., "many": ..., "other": ...}.

Словари — JSON в assets/locales/<код>.json. Без Qt: язык меняется через set_locale, подписчики перестраивают интерфейс.
"""
from __future__ import annotations

import json
import locale as _locale
import os
from typing import Callable

from .config import ASSETS_DIR
from .logging import get_logger

log = get_logger("i18n")

LOCALES_DIR = os.path.join(ASSETS_DIR, "locales")
DEFAULT = "ru"
ORDER = ("ru", "sah", "en")


def load_locales(folder: str = LOCALES_DIR) -> dict[str, dict]:
    out = {}
    for code in ORDER:
        path = os.path.join(folder, f"{code}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out[code] = json.load(f)
    return out


def plural_form(code: str, n) -> str:
    """Форма множественного числа (как Intl.PluralRules): ru/sah — one/few/many, en — one/other."""
    try:
        n = abs(float(n))
    except (TypeError, ValueError):
        return "other"
    if not n.is_integer():
        return "other"
    n = int(n)
    if code == "en":
        return "one" if n == 1 else "other"
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def humanize(key: str) -> str:
    """Последняя часть ключа как текст: «player.no_such_key» → «no such key»."""
    return key.rsplit(".", 1)[-1].replace("_", " ")


_NAMES = {"russian": "ru", "english": "en", "sakha": "sah", "yakut": "sah"}   # Windows: «Russian_Russia»


def detect_locale(languages: list[str], supported) -> str:
    for lang in languages:
        code = (lang or "").lower().replace("_", "-").split("-")[0].split(".")[0]
        code = _NAMES.get(code, code)
        if code in supported:
            return code
    return DEFAULT


def flatten(tree: dict, prefix: str = "") -> dict[str, object]:
    """{"a": {"b": "x"}} → {"a.b": "x"}; формы множественного числа — одним значением."""
    out = {}
    for k, v in tree.items():
        key = f"{prefix}.{k}" if prefix else k
        if key == "meta":
            continue
        if isinstance(v, dict) and not ({"one", "other"} & set(v)):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def missing_keys(locales: dict[str, dict], code: str) -> list[str]:
    have = flatten(locales.get(code, {}))
    return sorted(k for k in flatten(locales[DEFAULT]) if k not in have)


class I18n:
    def __init__(self, locales: dict[str, dict], locale: str | None = None,
                 on_missing: Callable[[str, str], None] | None = None):
        self._locales = locales
        self._flat = {code: flatten(tree) for code, tree in locales.items()}
        self._code = locale if locale in locales else DEFAULT
        self._on_missing = on_missing or (lambda key, code: log.warning("Нет перевода %s: %s", code, key))
        self._reported: set[tuple[str, str]] = set()
        self._subs: list[Callable[[str], None]] = []

    @property
    def locale(self) -> str:
        return self._code

    @property
    def available(self) -> list[dict]:
        return [{"code": c, "name": (self._locales[c].get("meta") or {}).get("name", c)} for c in self._locales]

    def has(self, key: str) -> bool:
        return key in self._flat.get(self._code, {}) or key in self._flat.get(DEFAULT, {})

    def set_locale(self, code: str) -> str:
        code = code if code in self._locales else DEFAULT
        if code != self._code:
            self._code = code
            for fn in list(self._subs):
                fn(code)
        return code

    def subscribe(self, fn: Callable[[str], None]) -> Callable[[], None]:
        self._subs.append(fn)
        return lambda: fn in self._subs and self._subs.remove(fn)

    def _missing(self, key: str, code: str):
        pending = (self._locales.get(code, {}).get("meta") or {}).get("pending")
        if pending or (key, code) in self._reported:
            return
        self._reported.add((key, code))
        self._on_missing(key, code)

    def _lookup(self, key: str):
        value = self._flat.get(self._code, {}).get(key)
        if value is not None and value != "":
            return value, self._code
        if self._code != DEFAULT:
            self._missing(key, self._code)
        value = self._flat.get(DEFAULT, {}).get(key)
        if value is not None and value != "":
            return value, DEFAULT
        self._missing(key, DEFAULT)
        return None, DEFAULT

    def t(self, key: str, /, **params) -> str:
        value, code = self._lookup(key)
        if value is None:
            return humanize(key)
        if isinstance(value, dict):
            form = plural_form(code, params.get("n"))
            value = value.get(form) or value.get("other") or value.get("many") or next(iter(value.values()))
        text = str(value)
        for name, v in params.items():
            text = text.replace("{" + name + "}", "" if v is None else str(v))
        return text


# ---------------------------------------------------------------- приложение: один сервис
_service: I18n | None = None


def service() -> I18n:
    global _service
    if _service is None:
        locales = load_locales()
        _service = I18n(locales or {DEFAULT: {}}, DEFAULT)
    return _service


def init(saved: str | None) -> I18n:
    """Язык при запуске: сохранённый в настройках, иначе — язык системы."""
    svc = service()
    if saved:
        svc.set_locale(saved)
    else:
        lang = _locale.getlocale()[0] or os.environ.get("LANG", "")
        svc.set_locale(detect_locale([lang], [c["code"] for c in svc.available]))
    return svc


def t(key: str, /, **params) -> str:
    return service().t(key, **params)


if __name__ == "__main__":   # python -m anime_app.core.i18n sah — какие ключи ждут перевода
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "sah"
    keys = missing_keys(load_locales(), code)
    print(f"{code}: не переведено {len(keys)} ключей (показываются по-русски)")
    for k in keys:
        print(" ", k)
