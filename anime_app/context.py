from PySide6.QtCore import QObject, Signal

from .api import release_subtitle, release_title


class AppContext(QObject):
    """Общие сервисы и глобальные сигналы навигации."""

    open_anime = Signal(int)            # открыть карточку тайтла
    play = Signal(int, str)             # release_id, ключ серии ("" — продолжить с последнего места)
    library_changed = Signal()          # списки/прогресс изменились

    def __init__(self, api, db, images, sources=None, data_dir=""):
        super().__init__()
        self.api = api
        self.db = db
        self.images = images
        self.sources = sources
        self.data_dir = data_dir
        if api.cache is None:
            api.cache = db
            db.http_prune()

    def load_release(self, release_id, on_ok, on_err=None, fresh=False):
        """Карточка тайтла: AniLibria или AnimeLib (для тайтлов, которых нет на AniLibria)."""
        from .sources import is_animelib_id, is_shiki_id
        if is_shiki_id(release_id):
            self.sources.shiki_release(release_id, on_ok, on_err)
        elif is_animelib_id(release_id):
            self.sources.animelib_release(release_id, on_ok, on_err)
        else:
            self.api.release(release_id, on_ok, on_err, fresh=fresh)

    def remember(self, release: dict, full=False):
        self.db.cache_anime(release, self.api.poster_url(release), release_subtitle(release), full=full)

    def item_from_release(self, release: dict) -> dict:
        entry = self.db.library_entry(release["id"])
        return {
            "id": release["id"],
            "title": release_title(release),
            "subtitle": release_subtitle(release),
            "poster": self.api.poster_url(release),
            "badge": "Онгоинг" if release.get("is_ongoing") else None,
            "status": entry.get("status"),
            "favorite": entry.get("favorite"),
            "release": release,
        }

    @staticmethod
    def item_from_row(row: dict) -> dict:
        progress = None
        if row.get("duration"):
            progress = min(1.0, (row.get("position") or 0) / row["duration"])
        return {
            "id": row["id"],
            "title": row.get("title") or "",
            "subtitle": row.get("subtitle") or "",
            "poster": row.get("poster"),
            "badge": None,
            "status": row.get("status"),
            "favorite": row.get("favorite"),
            "progress": progress,
        }
