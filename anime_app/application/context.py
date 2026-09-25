"""Общие сервисы приложения и сигналы навигации — то, что получает каждый экран.

Собирается один раз в anime_app/app.py (точка сборки зависимостей).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal


class AppContext(QObject):
    open_anime = Signal(int)            # открыть карточку тайтла
    play = Signal(int, str)             # release_id, ключ серии ("" — продолжить с последнего места)
    library_changed = Signal()          # списки/прогресс изменились

    def __init__(self, services: "Services"):
        super().__init__()
        self.services = services
        s = services
        self.data_dir = s.data_dir
        self.prefs = s.prefs
        self.library = s.library
        self.progress = s.progress
        self.releases = s.releases
        self.sources = s.sources
        self.franchise = s.franchise
        self.playback = s.playback
        self.recommendations = s.recommendations
        self.shiki = s.shiki
        self.backup = s.backup
        self.network = s.network
        self.images = s.images
        self.anilibria = s.anilibria
        self.shikimori_api = s.shikimori_api
        self.sleep = s.sleep
        s.library.changed.connect(self.library_changed.emit)
        s.progress.changed.connect(self.library_changed.emit)

    def reset_connections(self) -> None:
        """После смены сети/VPN старые соединения «висят» — сбрасываем их."""
        self.services.http.reset_connections()

    def search(self, query: str, filters: dict | None = None):
        from .search import SearchSession
        return SearchSession(self.anilibria, self.shikimori_api, self.releases, query, filters)


@dataclass
class Services:
    data_dir: str
    http: object
    prefs: object
    library: object
    progress: object
    releases: object
    sources: object
    franchise: object
    playback: object
    recommendations: object
    shiki: object
    backup: object
    network: object
    images: object
    anilibria: object
    shikimori_api: object
    sleep: object
