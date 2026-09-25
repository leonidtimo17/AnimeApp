"""Переводы интерфейса: сервис, словари и то, что в коде нет ключей без перевода и русских строк мимо t()."""
import ast
import pathlib
import re

from anime_app.core import i18n
from anime_app.core.i18n import I18n, detect_locale, flatten, load_locales, missing_keys, plural_form

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "anime_app"
LOCALES = load_locales()

DEMO = {
    "ru": {"meta": {"name": "Русский"}, "player": {"play": "Смотреть", "only_ru": "Только по-русски"},
           "dates": {"minutes_ago": {"one": "{n} минуту назад", "few": "{n} минуты назад", "many": "{n} минут назад",
                                     "other": "{n} минуты"}}},
    "sah": {"meta": {"name": "Саха тыла"}, "player": {"play": "Көр"}},
    "en": {"meta": {"name": "English"}, "player": {"play": "Play"},
           "dates": {"minutes_ago": {"one": "{n} minute ago", "other": "{n} minutes ago"}}},
}


def test_switch_language_live():
    svc = I18n(DEMO, "ru", on_missing=lambda *_: None)
    seen = []
    svc.subscribe(seen.append)
    assert svc.t("player.play") == "Смотреть"
    svc.set_locale("sah")
    assert svc.t("player.play") == "Көр"
    svc.set_locale("en")
    assert svc.t("player.play") == "Play"
    assert seen == ["sah", "en"], "интерфейс узнаёт о смене языка и перестраивается"
    assert [x["name"] for x in svc.available] == ["Русский", "Саха тыла", "English"]


def test_fallback_never_empty_and_missing_logged_once():
    missing = []
    svc = I18n(DEMO, "sah", on_missing=lambda k, c: missing.append(f"{c}:{k}"))
    assert svc.t("player.only_ru") == "Только по-русски"
    text = svc.t("player.no_such_key")
    assert text == "no such key" and text not in ("", "None", "undefined", "null")
    svc.t("player.only_ru")
    assert missing == ["sah:player.only_ru", "sah:player.no_such_key", "ru:player.no_such_key"]
    assert svc.set_locale("xx") == "ru"


def test_pending_language_is_quiet():
    missing = []
    svc = I18n(LOCALES, "sah", on_missing=lambda k, c: missing.append(k))
    assert svc.t("common.retry") == "Повторить"
    assert svc.t("navigation.home") == "Сүрүн сирэй"
    assert missing == []


def test_plurals_and_params():
    svc = I18n(DEMO, "ru")
    assert [svc.t("dates.minutes_ago", n=n) for n in (1, 3, 5, 21, 12)] == [
        "1 минуту назад", "3 минуты назад", "5 минут назад", "21 минуту назад", "12 минут назад"]
    svc.set_locale("en")
    assert svc.t("dates.minutes_ago", n=1) == "1 minute ago" and svc.t("dates.minutes_ago", n=7) == "7 minutes ago"
    assert plural_form("ru", 1.5) == "other"


def test_detect_locale():
    assert detect_locale(["sah_RU"], ["ru", "sah", "en"]) == "sah"
    assert detect_locale(["en-US"], ["ru", "sah", "en"]) == "en"
    assert detect_locale(["English_United States"], ["ru", "sah", "en"]) == "en"   # Windows
    assert detect_locale(["de_DE.UTF-8"], ["ru", "sah", "en"]) == "ru"


def test_real_dictionaries():
    assert missing_keys(LOCALES, "en") == [], "английский переведён полностью"
    ru = flatten(LOCALES["ru"])
    def ph(value):   # параметры строки; у множественного числа — всех форм вместе
        forms = value.values() if isinstance(value, dict) else [value]
        return sorted({p for f in forms for p in re.findall(r"\{(\w+)\}", str(f))})
    for code in ("en", "sah"):
        for key, text in flatten(LOCALES[code]).items():
            assert key in ru, f"{code}: лишний ключ {key}"
            assert ph(text) == ph(ru[key]), f"{code}: параметры в {key}"
            assert str(text).strip(), f"{code}: пустой перевод {key}"
    assert LOCALES["sah"]["meta"]["pending"], "неполный перевод саха помечен"


# ---------------------------------------------------------------- код
FAMILIES = ("status.", "anime.kinds.", "shikimori.statuses.", "catalog.types.", "catalog.sorts.", "catalog.seasons.",
            "navigation.", "player.errors.", "sleep.in_minutes:", "sleep.set_minutes:")


def _sources():
    return [p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts]


def _t_keys(tree):
    """Ключи из вызовов t("…") и t(f"…") — для f-строк только постоянное начало (семья ключей)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "t" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield arg.value, False
            elif isinstance(arg, ast.JoinedStr) and arg.values and isinstance(arg.values[0], ast.Constant):
                yield arg.values[0].value, True
            elif isinstance(arg, ast.IfExp):
                for side in (arg.body, arg.orelse):
                    if isinstance(side, ast.Constant):
                        yield side.value, False


def test_every_key_in_code_exists():
    ru = flatten(LOCALES["ru"])
    missing = []
    for path in _sources():
        for key, prefix in _t_keys(ast.parse(path.read_text(encoding="utf-8"))):
            if prefix:
                assert any(key.startswith(f) or f.startswith(key) for f in FAMILIES), f"{path.name}: семья {key}"
                assert any(k.startswith(key) for k in ru), f"{path.name}: нет ключей {key}*"
            elif key not in ru:
                missing.append(f"{path.relative_to(ROOT)}: {key}")
    # ключи в разметке страницы веб-плеера и в её скрипте
    from anime_app.presentation.player.webplayer import JS_KEYS, PAGE
    missing += [f"webplayer: {k}" for k in re.findall(r"\{\{([a-z_.]+)\}\}", PAGE) if k not in ru]
    missing += [f"webplayer JS: {k}" for k in JS_KEYS if k not in ru]
    assert missing == []
    for k in ("watching", "planned", "completed", "postponed", "dropped"):
        assert f"status.{k}" in ru


def test_no_hardcoded_russian_in_interface():
    """Строки интерфейса — только через t(); русский допустим в комментариях, журнале и данных API."""
    allowed = {"comments_panel.py": 1,   # пометка серии для Shikimori (русскоязычный сайт) — нарочно по-русски
               "theme.py": 1}           # комментарий внутри таблицы стилей
    found = {}
    for path in (PKG / "presentation").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        logs = {id(a) for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", "") in ("info", "warning", "debug", "error") for a in ast.walk(n)}
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search("[А-Яа-яЁё]", node.value) \
                    and id(node) not in docstrings and id(node) not in logs:
                if path.name == "webplayer.py":
                    continue   # страница собирается из {{ключей}}; русский там — только в комментариях скрипта
                n += 1
        if n > allowed.get(path.name, 0):
            found[path.name] = n
    assert found == {}


def test_language_setting_restored():
    svc = i18n.service()
    try:
        assert i18n.init("en").locale == "en"
        assert i18n.t("navigation.home") == "Home"
        assert i18n.init("sah").t("navigation.home") == "Сүрүн сирэй"
    finally:
        svc.set_locale("ru")


def test_translation_function_not_shadowed():
    """Локальная переменная `t` рядом с вызовом t("…") ломает перевод (вызывается не та t)."""
    bad = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            own = [n for n in ast.walk(fn)]
            args = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            stores = {n.id for n in own if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            calls = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "t" for n in own)
            if "t" in (args | stores) and calls:
                bad.append(f"{path.relative_to(ROOT)}:{fn.lineno}")
    assert bad == []
