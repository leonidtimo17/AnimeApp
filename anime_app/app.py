"""Точка сборки приложения: создаёт сервисы, связывает слои и запускает окно.

Здесь — единственное место, где «знают» обо всех слоях сразу. Остальной код получает зависимости готовыми.
"""
from __future__ import annotations

import os
import sys

from . import APP_NAME, APP_VERSION
from .core import i18n
from .core.logging import get_logger, setup_logging

log = get_logger("app")


def build_services(data_dir: str, cache_dir: str):
    """Все сервисы приложения (без окон). Нужен QApplication/QCoreApplication."""
    from .application.backup import BackupService
    from .application.context import Services
    from .application.franchise import FranchiseService
    from .application.library import LibraryService, Preferences, ProgressService
    from .application.playback import PlaybackService
    from .application.recommendations import RecommendationService
    from .application.releases import ReleaseService
    from .application.shikimori import ShikimoriAccount, load_config
    from .application.sources import SourceResolver
    from .domain.sleep_timer import SleepTimer
    from .infrastructure.api.ai import AiApi
    from .infrastructure.api.anilibria import AniLibriaApi
    from .infrastructure.api.shikimori import ShikimoriApi
    from .infrastructure.api.sources import AniSkipApi, AnimeLibApi, AnimeVostApi, YaniApi
    from .infrastructure.database.connection import Database
    from .infrastructure.database.repositories import (AnimeRepository, HttpCacheRepository, LibraryRepository,
                                                       ProgressRepository, SettingsRepository)
    from .infrastructure.http.client import HttpClient
    from .infrastructure.images.loader import ImageLoader
    from .infrastructure.network.bandwidth import BandwidthProbe
    from .infrastructure.network.service import NetworkService

    db = Database(os.path.join(data_dir, "library.db"))
    anime_repo, library_repo = AnimeRepository(db), LibraryRepository(db)
    progress_repo, settings_repo, http_cache = ProgressRepository(db), SettingsRepository(db), HttpCacheRepository(db)
    http_cache.prune()

    http = HttpClient(http_cache)
    network = NetworkService(BandwidthProbe(http.nam), settings_repo)
    http.connectivity = network
    images = ImageLoader(os.path.join(cache_dir, "images"))

    anilibria, shikimori_api = AniLibriaApi(http), ShikimoriApi(http)
    animelib = AnimeLibApi(http)
    prefs = Preferences(settings_repo)
    library, progress = LibraryService(library_repo), ProgressService(progress_repo)
    releases = ReleaseService(anilibria, shikimori_api, animelib, anime_repo, library_repo)
    sources = SourceResolver(animelib, AnimeVostApi(http), YaniApi(http), AniSkipApi(http), prefs)
    shiki = ShikimoriAccount(shikimori_api, prefs, library, progress, anime_repo, load_config())
    return Services(
        data_dir=data_dir, http=http, prefs=prefs, library=library, progress=progress, releases=releases,
        sources=sources, franchise=FranchiseService(anilibria, shikimori_api),
        playback=PlaybackService(releases, sources, shiki),
        recommendations=RecommendationService(anilibria, releases, library, progress_repo, anime_repo, AiApi(http)),
        shiki=shiki, backup=BackupService(db, anime_repo, library_repo, progress_repo, http_cache, http, images),
        network=network, images=images, anilibria=anilibria, shikimori_api=shikimori_api, sleep=SleepTimer(),
    )


def start_network(services) -> None:
    """Один замер скорости за запуск: на последней серии свежего релиза, когда постеры главной догрузятся."""
    from .infrastructure.api.anilibria import sample_stream

    def provider(cb):
        services.anilibria.latest(lambda data: services.images.call_when_idle(lambda: cb(sample_stream(data))),
                                  lambda _e: cb(None))
    services.network.start(provider)


def run() -> int:
    from PySide6.QtCore import QStandardPaths
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .application.context import AppContext
    from .presentation.legal import ensure_accepted
    from .presentation.main_window import MainWindow
    from .presentation.theme import QSS

    if sys.platform == "win32":
        # Своя иконка в панели задач, а не иконка python.exe.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AnimeApp.Desktop")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "assets", "icon.ico")))

    data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    cache_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)
    setup_logging(data_dir)
    log.info("Запуск %s %s", APP_NAME, APP_VERSION)

    services = build_services(data_dir, cache_dir)
    i18n.init(services.prefs.get("language"))
    ctx = AppContext(services)
    holder = {"window": None}

    def make_window(previous=None):
        """Окно на текущем языке. После смены языка — новое окно на месте старого, на той же странице."""
        window = MainWindow(ctx)
        window.language_selected.connect(change_language)
        if previous is not None:
            state = previous.current_state()
            window.setGeometry(previous.geometry())
            if previous.isMaximized():
                window.showMaximized()
            else:
                window.show()
            if state and state[0] == "details" and state[1]:
                window.open_anime(state[1], remember=False)
            elif state and state[0] in window.pages:
                window.show_page(state[0], remember=False)
            previous.close()
            previous.deleteLater()
        else:
            window.show()
        holder["window"] = window
        return window

    def change_language(code):
        if code == i18n.service().locale:
            return
        services.prefs.set("language", i18n.service().set_locale(code))
        log.info("Язык интерфейса: %s", code)
        make_window(holder["window"])

    make_window()
    start_network(services)

    # Первый запуск: пользовательское соглашение и политика конфиденциальности
    if not ensure_accepted(holder["window"], ctx.prefs):
        return 0
    return app.exec()
