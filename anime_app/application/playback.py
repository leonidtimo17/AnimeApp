"""Сценарий «Смотреть»: свежие данные тайтла → озвучка → серии → прогресс с Shikimori → кадры серий.

Раньше это жило в главном окне; теперь окно только показывает результат.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..core.errors import AppError, describe
from ..core.i18n import t
from .releases import ReleaseService
from .sources import SourceResolver


@dataclass
class PlaybackPlan:
    release: dict
    dub: dict
    dubs: list[dict]
    episodes: list[dict]
    key: str | None           # серия, которую открыть (None — продолжить просмотр)
    position: int | None = None


class PlaybackService:
    def __init__(self, releases: ReleaseService, sources: SourceResolver, shiki):
        self.releases = releases
        self.sources = sources
        self.shiki = shiki
        self._token = None

    def cancel(self) -> None:
        self._token = None

    def prepare(self, release_id: int, episode_key: str, on_ready: Callable[[PlaybackPlan], None],
                on_error: Callable[[str], None]) -> None:
        """Подготовить просмотр. Если тем временем запросили другой тайтл — этот результат не придёт."""
        self._token = token = object()

        def current():
            return self._token is token

        def with_release(release):
            def got(dubs, finished):
                if not finished or not current():
                    return
                dub = self.sources.choose(release, dubs)
                if not dub:
                    on_error(t("player.no_episodes_anywhere"))
                    return

                def eps_ok(eps):
                    def launch(previews):
                        if not current():
                            return
                        # Кадры серий для списка в плеере — из любой «родной» озвучки, где они есть
                        for e in eps:
                            if not e.get("preview") and previews.get(e["key"]):
                                e["preview"] = previews[e["key"]]
                        on_ready(PlaybackPlan(release, dub, dubs, eps, episode_key or None))

                    def with_progress(_n):
                        # Серии, отмеченные на Shikimori, отмечаем и здесь — продолжим с нужной
                        if dub["native"]:
                            self.sources.previews(release, dubs, launch)
                        else:
                            launch({})
                    self.shiki.pull_progress(release["id"], eps, with_progress)

                self.sources.episodes(release, dub, eps_ok,
                                      lambda err: current() and on_error(describe(err, t("player.episodes_failed"))))
            self.sources.find_dubs(release, got)

        self.releases.load_or_cached(release_id, with_release,
                                     lambda err: current() and on_error(describe(err, t("anime.load_failed"))),
                                     fresh=True)

    def switch_dub(self, release: dict, dub: dict, key: str | None, position_ms: int,
                   on_ready: Callable[[PlaybackPlan, str | None], None], on_error: Callable[[str], None]) -> None:
        """Сменить озвучку с той же серии и того же места. on_ready(план, предупреждение | None)."""
        self.sources.remember_choice(release, dub)

        def ok(eps):
            same = key if any(e["key"] == key for e in eps) else None
            note = (t("player.dub_missing_episode", dub=dub["name"], n=key)
                    if key and not same else None)
            plan = PlaybackPlan(release, dub, [], eps, same, position_ms if same and position_ms > 5000 else None)
            on_ready(plan, note)

        def fail(err: AppError):
            on_error(describe(err, t("player.dub_switch_failed")))
        self.sources.episodes(release, dub, ok, fail)
