"""Сервисы приложения на настоящей базе SQLite: библиотека, прогресс, Shikimori, сторож плеера."""
from anime_app.application.library import LibraryService, ProgressService
from anime_app.application.playback import PlaybackService
from anime_app.application.shikimori import ShikimoriAccount
from anime_app.infrastructure.database.repositories import (AnimeRepository, LibraryRepository, ProgressRepository,
                                                           SettingsRepository)
from anime_app.presentation.player.watchdog import PlaybackWatchdog
from tests.conftest import wait_until

EPS = [{"key": str(i), "ordinal": float(i), "duration": 1440} for i in range(1, 6)]


def test_library_service_signals(qapp, db):
    lib = LibraryService(LibraryRepository(db))
    changed, entries = [], []
    lib.changed.connect(lambda: changed.append(1))
    lib.entry_changed.connect(lambda kind, aid: entries.append((kind, aid)))
    lib.set_status(1, "planned")
    lib.set_favorite(1, True)
    lib.set_score(1, 8)
    assert entries == [("status", 1), ("favorite", 1), ("score", 1)] and len(changed) == 3
    assert lib.mark_watching(1) and lib.entry(1)["status"] == "watching"
    assert not lib.mark_watching(1)                       # уже смотрю — без изменений
    lib.set_status(1, "completed")
    assert not lib.mark_watching(1)                       # «Просмотрено» не сбрасываем
    lib.import_entry(2, "dropped", None)                  # с Shikimori — без сигналов
    assert entries[-1] == ("status", 1)


def test_progress_service(qapp, db):
    progress = ProgressService(ProgressRepository(db))
    newly = []
    progress.episode_changed.connect(newly.append)
    assert progress.save(1, EPS[0], 23 * 60_000, 24 * 60_000) == (True, True)
    assert progress.save(1, EPS[0], 23 * 60_000, 24 * 60_000) == (True, False)
    assert newly == [1]
    assert progress.resume(1, EPS) == (1, 0)
    assert progress.open_at(1, EPS, "1") == (0, 0)          # досмотренную открываем с начала
    progress.save(1, EPS[2], 5 * 60_000, 24 * 60_000)
    assert progress.open_at(1, EPS, "3") == (2, 5 * 60_000)
    progress.set_watched(1, EPS[:3], True)
    assert all(progress.for_anime(1)[k]["watched"] for k in ("1", "2", "3"))
    assert progress.mark_watched_quiet(1, EPS, 4) == 1       # отмечена только 4-я
    progress.restart(1, EPS[0])
    assert progress.for_anime(1)["1"]["watched"] == 0


class FakeShikiApi:
    def __init__(self):
        self.calls = []

    def authorized(self, path, token, app, on_ok, on_err=None, params=None, json_body=None, method=None):
        self.calls.append((method or ("POST" if json_body else "GET"), path, json_body))
        if path == "/api/v2/user_rates" and not json_body:
            on_ok([{"id": 77, "episodes": 1, "status": "watching"}])
        else:
            on_ok({})


def make_account(db):
    settings = SettingsRepository(db)
    settings.set("shiki_auth", {"access": "t", "expires": 9e12, "user": {"id": 5, "nickname": "me"}})
    anime = AnimeRepository(db)
    anime.save({"id": 1, "name": {"main": "A"}, "shikimori": {"id": 321}}, None, "", full=True)
    from anime_app.application.library import Preferences
    lib = LibraryService(LibraryRepository(db))
    progress = ProgressService(ProgressRepository(db))
    api = FakeShikiApi()
    acc = ShikimoriAccount(api, Preferences(settings), lib, progress, anime,
                           {"id": "x", "secret": "y", "app": "AnimeApp", "redirect": "oob"})
    return acc, api, lib, progress


def test_shikimori_sync_debounces_and_cleans_timers(qapp, db, monkeypatch):
    import anime_app.application.shikimori as sh
    monkeypatch.setattr(sh, "PUSH_DELAY_MS", 50)
    acc, api, lib, progress = make_account(db)
    lib.set_status(1, "watching")
    lib.set_score(1, 9)
    lib.set_favorite(1, True)                    # избранное на Shikimori не уходит
    progress.save(1, EPS[0], 23 * 60_000, 24 * 60_000)
    assert wait_until(qapp, lambda: any(c[0] == "PATCH" for c in api.calls), timeout=3)
    patches = [c for c in api.calls if c[0] == "PATCH"]
    assert len(patches) == 1                     # несколько изменений — один запрос
    assert patches[0][2]["user_rate"] == {"episodes": 1, "status": "watching", "score": 9}
    assert acc._timers == {}                     # одноразовые таймеры не копятся


def test_shikimori_pull_progress(qapp, db):
    acc, api, _lib, progress = make_account(db)
    got = []
    acc.pull_progress(1, EPS, got.append)
    assert got == [1] and progress.for_anime(1)["1"]["watched"] == 1


def test_watchdog_runs_only_while_playing(qapp):
    pos = [0]
    now = [0.0]
    dog = PlaybackWatchdog(lambda: pos[0], clock=lambda: now[0])
    frozen = []
    dog.frozen.connect(lambda: frozen.append(1))
    assert not dog.running
    dog.playing(True)
    assert dog.running
    dog._check()                  # позиция не меняется…
    now[0] = 13
    dog._check()                  # …дольше 12 секунд — переподключаемся
    assert frozen == [1]
    pos[0] = 5000
    dog._check()
    dog.playing(False)
    assert not dog.running


class FakeReleaseService:
    def __init__(self):
        self.loads = 0

    def load_or_cached(self, rid, on_ok, on_err, fresh=False):
        self.loads += 1
        self.pending = lambda: on_ok({"id": rid, "episodes": []})


class FakeResolver:
    def find_dubs(self, release, cb):
        cb([{"id": "anilibria", "name": "AniLibria", "native": True}], True)

    def choose(self, release, dubs):
        return dubs[0]

    def episodes(self, release, dub, ok, err):
        ok([{"key": "1"}])

    def previews(self, release, dubs, cb):
        cb({"1": "p1"})


class FakeShiki:
    def pull_progress(self, rid, eps, cb):
        cb(0)


def test_playback_only_latest_request_is_delivered():
    releases = FakeReleaseService()
    service = PlaybackService(releases, FakeResolver(), FakeShiki())
    ready = []
    service.prepare(1, "", ready.append, ready.append)
    first = releases.pending
    service.prepare(2, "", ready.append, ready.append)     # пользователь сразу открыл другой тайтл
    first()                                                  # ответ по первому пришёл позже
    releases.pending()
    assert len(ready) == 1 and ready[0].release["id"] == 2 and ready[0].episodes[0]["preview"] == "p1"
