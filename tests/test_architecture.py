"""Правила слоёв: проверяются по импортам в исходниках.

core, domain — без Qt и без других слоёв; infrastructure и application не знают об интерфейсе;
замер скорости запускает только NetworkService (плеер и страницы его не вызывают).
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "anime_app"


def imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    rel_parts = path.relative_to(ROOT).with_suffix("").parts
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(rel_parts[:-node.level])
                out.add(".".join(base + ([node.module] if node.module else [])))
            else:
                out.add(node.module or "")
    return out


def files(layer):
    return list((PKG / layer).rglob("*.py"))


def test_core_and_domain_are_pure():
    for layer in ("core", "domain"):
        for f in files(layer):
            bad = {m for m in imports(f) if m.startswith("PySide6") or re.match(
                r"anime_app\.(infrastructure|application|presentation)", m)}
            assert not bad, f"{f.relative_to(ROOT)} импортирует {bad}"


def test_infrastructure_and_application_do_not_know_ui():
    for layer in ("infrastructure", "application"):
        for f in files(layer):
            bad = {m for m in imports(f) if m.startswith("anime_app.presentation") or m.startswith("PySide6.QtWidgets")}
            assert not bad, f"{f.relative_to(ROOT)} импортирует {bad}"


def test_ui_does_not_touch_database_directly():
    for f in files("presentation"):
        text = f.read_text(encoding="utf-8")
        assert "anime_app.infrastructure.database" not in imports(f), f
        assert "ctx.db" not in text and ".conn.execute" not in text, f


def test_only_network_service_measures_bandwidth():
    users = []
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        if "BandwidthProbe(" in text or "measure_now(" in text or ".measure(" in text:
            users.append(f.relative_to(PKG).as_posix())
    assert sorted(users) == sorted([
        "app.py",                                        # создаёт замерщик для NetworkService
        "infrastructure/network/bandwidth.py",
        "infrastructure/network/service.py",
        "presentation/player/window.py",                 # только кнопка «Проверить скорость» (measure_now)
    ]), users
    player = (PKG / "presentation/player/window.py").read_text(encoding="utf-8")
    assert player.count("measure_now(") == 1 and "def check_speed" in player


def test_no_bare_except_pass():
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"except Exception:\s*\n\s*pass\b", text), f
