"""«Для вас»: профиль вкуса по спискам и истории, подбор кандидатов из каталога, необязательный ИИ-разбор."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..core.errors import describe
from ..core.i18n import t
from ..domain import taste
from ..infrastructure.api.ai import AiApi
from ..infrastructure.api.anilibria import AniLibriaApi
from ..infrastructure.database.repositories import AnimeRepository, ProgressRepository
from .library import LibraryService
from .releases import ReleaseService

MISSING_LIMIT = 30   # сколько тайтлов без жанров догружать за раз


@dataclass
class Recommendations:
    profile: taste.TasteProfile
    scored: list                              # [(оценка, релиз, причина)]
    because: list                             # [(понравившийся релиз, [релизы])]
    candidates: int


class RecommendationService:
    def __init__(self, anilibria: AniLibriaApi, releases: ReleaseService, library: LibraryService,
                 progress: ProgressRepository, anime: AnimeRepository, ai: AiApi):
        self.anilibria = anilibria
        self.releases = releases
        self.library = library
        self.progress = progress
        self.anime = anime
        self.ai_api = ai

    def signature(self) -> tuple:
        """Меняется, когда стоит пересчитать рекомендации."""
        return self.library.signature()

    def build_profile(self) -> taste.TasteProfile:
        tracked = self.library.tracked_ids()
        return taste.build_profile(self.library.repo.all(), self.progress.watched_by_anime(),
                                   self.anime.releases(tracked))

    def fetch_missing(self, done: Callable[[], None]) -> None:
        """Тайтлы из библиотеки без жанров в кэше — догружаем (параллельно, не больше MISSING_LIMIT)."""
        tracked = self.library.tracked_ids()
        known = self.anime.releases(tracked)
        ids = [aid for aid in tracked if not taste.genres_of(known.get(aid))][:MISSING_LIMIT]
        if not ids:
            done()
            return
        left = {"n": len(ids)}

        def one(*_):
            left["n"] -= 1
            if left["n"] == 0:
                done()

        for aid in ids:
            self.releases.load(aid, lambda rel: (self.releases.remember(rel, full=True), one()), one)

    def candidates(self, profile: taste.TasteProfile, on_ok: Callable[[list[dict]], None]) -> None:
        """Кандидаты из каталога AniLibria по любимым жанрам, без того, что уже есть в библиотеке."""
        known = set(self.library.tracked_ids())
        pool: dict[int, dict] = {}

        def run(name_to_id):
            queries = taste.candidate_queries(profile, name_to_id)
            left = {"n": len(queries)}

            def fin():
                left["n"] -= 1
                if left["n"] == 0:
                    on_ok([r for r in pool.values() if r["id"] not in known])

            for q in queries:
                def ok(data):
                    for r in data.get("data", []):
                        pool.setdefault(r["id"], r)
                    fin()
                self.anilibria.catalog(ok, lambda _e: fin(), **q)

        self.anilibria.genres(lambda data: run({g["name"]: g["id"] for g in data}), lambda _e: run({}))

    def build(self, on_profile: Callable[[taste.TasteProfile], None],
              on_done: Callable[[Recommendations], None]) -> None:
        """Полный расчёт: догрузить жанры → профиль (сразу показать) → кандидаты → оценки."""
        def with_profile():
            profile = self.build_profile()
            on_profile(profile)

            def with_candidates(releases):
                scored = taste.score(profile, releases)
                on_done(Recommendations(profile, scored, taste.because_of(profile, scored), len(releases)))
            self.candidates(profile, with_candidates)
        self.fetch_missing(with_profile)

    # ------------------------------------------------------------ ИИ
    def ai_analyze(self, profile: taste.TasteProfile, scored, on_ok, on_err) -> None:
        """Разбор вкуса и подборка от ИИ (выбирает только из наших кандидатов).
        on_ok({"analysis", "picks": [(релиз, причина)], "provider"}). Локальная Ollama — первой: приватнее."""
        pool = [rel for _, rel, _ in scored[:45]]
        prompt = taste.ai_prompt(profile, pool)
        state = {"provider": "", "attempt": 0}

        def accept(text) -> str | None:
            res = taste.parse_ai_answer(text, pool)
            if isinstance(res, str):
                return res
            analysis, picks = res
            on_ok({"analysis": analysis, "picks": picks, "provider": state["provider"]})
            return None

        def handle(text):
            error = accept(text)
            if error is None:
                return
            if state["attempt"] < 2:
                pollinations()  # у бесплатной модели бывают неудачные ответы — пробуем ещё раз
            else:
                on_err(error + "\n" + t("recs.try_later"))

        def pollinations():
            state["attempt"] += 1
            state["provider"] = t("recs.provider_cloud")
            self.ai_api.pollinations(taste.ai_system(), prompt, state["attempt"] * 17, handle,
                                     lambda e: on_err(describe(e, t("recs.ai_unavailable"))))

        def ollama(models):
            if not models:
                pollinations()
                return
            state["provider"] = t("recs.provider_local", model=models[0])
            self.ai_api.ollama(models[0], taste.ai_system(), prompt,
                               lambda text: accept(text) is not None and pollinations(),
                               lambda _e: pollinations())

        self.ai_api.ollama_models(ollama, lambda _e: pollinations())
