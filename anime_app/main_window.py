from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from . import APP_NAME, APP_VERSION
from .icons import pixmap, toggle_icon
from .catalog_page import CatalogPage
from .franchise import Franchise
from .kodik_page import KodikPage
from .pages import CatalogPage as SearchPage
from .pages import DetailsPage, HistoryPage, HomePage, LibraryPage, SchedulePage
from .recs_page import RecommendationsPage
from .player import PlayerWindow
from .theme import ACCENT, MUTED


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 880)
        self.setMinimumSize(900, 600)

        root = QWidget()
        root.setObjectName("Root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.sidebar = sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 16)
        side.setSpacing(0)
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(20, 18, 20, 14)
        logo_row.setSpacing(10)
        logo_icon = QLabel()
        logo_icon.setPixmap(pixmap("circle-play", ACCENT, 26))
        logo = QLabel("AnimeApp")
        logo.setObjectName("Logo")
        logo_row.addWidget(logo_icon)
        logo_row.addWidget(logo, 1)
        side.addLayout(logo_row)

        # Общий кэш франшиз: страница тайтла и плееры.
        ctx.franchise = Franchise(ctx.api, ctx.sources, self)
        self.stack = QStackedWidget()
        self.pages = {
            "home": HomePage(ctx),
            "recs": RecommendationsPage(ctx),
            "catalog": CatalogPage(ctx),
            "search": SearchPage(ctx),
            "schedule": SchedulePage(ctx),
            "library": LibraryPage(ctx),
            "history": HistoryPage(ctx),
        }
        self.details = DetailsPage(ctx)
        self.details.back.connect(self.go_back)
        for page in list(self.pages.values()) + [self.details]:
            self.stack.addWidget(page)

        # Плееры — экраны этого же окна.
        self.player = PlayerWindow(ctx)
        self.player.progress_saved.connect(self.refresh_current)
        self.player.closed.connect(self._player_closed)
        self.player.pip_toggled.connect(self._pip_toggled)
        self.player.dub_selected.connect(self._switch_dub)
        self.player.season_selected.connect(self._open_season)
        self.stack.addWidget(self.player)
        self.kodik = KodikPage(ctx)
        self.kodik.closed.connect(self._player_closed)
        self.kodik.dub_selected.connect(self._switch_dub)
        self.kodik.season_selected.connect(self._open_season)
        self.stack.addWidget(self.kodik)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons = {}
        for key, glyph, text in (("home", "house", "Главная"), ("recs", "wand-magic-sparkles", "Для вас"),
                                 ("catalog", "table-cells-large", "Каталог"),
                                 ("search", "magnifying-glass", "Поиск"),
                                 ("schedule", "calendar-days", "Расписание"),
                                 ("library", "bookmark", "Библиотека"),
                                 ("history", "clock-rotate-left", "История")):
            btn = QPushButton("  " + text)
            btn.setIcon(toggle_icon((glyph, MUTED, False), (glyph, ACCENT, False), 18))
            btn.setIconSize(QSize(18, 18))
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav.addButton(btn)
            self.nav_buttons[key] = btn
            side.addWidget(btn)
        side.addStretch(1)
        about = QLabel(f"v{APP_VERSION} · AniLibria · AnimeVost · AnimeLib")
        about.setObjectName("Muted")
        about.setWordWrap(True)
        about.setStyleSheet("padding: 0 20px; font-size: 12px;")
        side.addWidget(about)

        lay.addWidget(sidebar)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.history = []
        self._play_token = None
        self._now = None   # (release, dub) того, что сейчас играет

        ctx.open_anime.connect(self.open_anime)
        ctx.play.connect(self.play)
        ctx.library_changed.connect(self.refresh_current)

        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.show_page("search"))
        QShortcut(QKeySequence(Qt.Key.Key_Back), self, self.go_back)
        QShortcut(QKeySequence("Alt+Left"), self, self.go_back)

        self.show_page("home")

    # ------------------------------------------------------------ navigation
    def _in_player(self):
        return self.stack.currentWidget() in (self.player, self.kodik)

    def _current_key(self):
        w = self.stack.currentWidget()
        if w is self.details:
            return ("details", self.details.release["id"] if self.details.release else None)
        return next(((k, None) for k, p in self.pages.items() if p is w), None)

    def _set_current(self, widget):
        self.stack.setCurrentWidget(widget)
        self.sidebar.setVisible(widget not in (self.player, self.kodik))

    def show_page(self, key, remember=True):
        cur = self._current_key()
        if remember and cur and cur != (key, None):
            self.history.append(cur)
            self.history = self.history[-50:]
        page = self.pages[key]
        self.nav_buttons[key].setChecked(True)
        self._set_current(page)
        page.on_show()

    def open_anime(self, release_id, remember=True):
        cur = self._current_key()
        if remember and cur and cur != ("details", release_id):
            self.history.append(cur)
        checked = self.nav.checkedButton()
        if checked:
            self.nav.setExclusive(False)
            checked.setChecked(False)
            self.nav.setExclusive(True)
        self._set_current(self.details)
        self.details.load(release_id)

    def go_back(self):
        if not self.history:
            self.show_page("home", remember=False)
            return
        key, arg = self.history.pop()
        if key == "details":
            self.open_anime(arg, remember=False)
        else:
            self.show_page(key, remember=False)

    def refresh_current(self):
        w = self.stack.currentWidget()
        if w in (self.pages["catalog"], self.pages["search"], self.pages["schedule"], self.pages["recs"],
                 self.player, self.kodik):
            return
        w.on_show()

    # ------------------------------------------------------------ playback
    def play(self, release_id, episode_key, dub_id=""):
        """Свежие данные тайтла → выбранная озвучка → встроенный плеер или плеер Kodik."""
        self._play_token = token = object()
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)

        def stop(msg=None):
            QApplication.restoreOverrideCursor()
            if msg:
                QMessageBox.information(self, APP_NAME, msg)

        def with_release(release):
            def got(dubs, finished):
                if not finished or self._play_token is not token:
                    return
                dub = self.ctx.sources.choose(release, dubs)
                if not dub:
                    stop("Серии этого аниме не нашлись ни в одном источнике.")
                    return

                def eps_ok(eps):
                    stop()
                    if self._play_token is token:
                        self._launch(release, dub, eps, episode_key or None)

                self.ctx.sources.episodes(release, dub, eps_ok,
                                          lambda msg: stop(f"Не удалось загрузить серии: {msg}"))
            self.ctx.sources.find_dubs(release, got)

        def ok(release):
            self.ctx.remember(release, full=True)
            with_release(release)

        def fail(msg):
            cached = self.ctx.db.cached_release(release_id)
            if cached:
                with_release(cached)
            else:
                stop(f"Не удалось загрузить тайтл: {msg}")

        self.ctx.load_release(release_id, ok, fail, fresh=True)

    def _launch(self, release, dub, eps, key, position=None):
        if key and not any(e["key"] == key for e in eps):
            key = None
        if not eps:
            QMessageBox.information(self, APP_NAME, "В этой озвучке пока нет серий.")
            return
        entry = self.ctx.db.library_entry(release["id"])
        if entry.get("status") in (None, "planned", "postponed"):
            self.ctx.db.set_status(release["id"], "watching")
            self.ctx.library_changed.emit()
        if not self._in_player():
            cur = self._current_key()
            if cur:
                self.history.append(cur)
        self._now = (release, dub)
        if dub["native"]:
            self.kodik.stop()
            self.player.current_dub = dub
            self.player.open(release, eps, dub["name"], key, position=position)
            target = self.player
            if not self.player.pip:
                self._set_current(self.player)
                self.player.setFocus()
        else:
            if self.player.pip:
                self.player.close_player()
            self.player.stop()
            self._set_current(self.kodik)
            self.kodik.open(release, dub, eps, key, position=position)
            self.kodik.setFocus()
            target = self.kodik
        # Меню «Озвучка» и «Сезоны и фильмы» в плеере
        self.ctx.sources.find_dubs(release, lambda dubs, _fin: target.set_dubs(dubs, dub["id"]))
        target.set_seasons([])
        self.ctx.franchise.load(release, target.set_seasons)

    def _switch_dub(self, dub):
        """Сменить озвучку прямо из плеера — с той же серии и того же места."""
        if not self._now:
            return
        release = self._now[0]
        source = self.player if self.stack.currentWidget() is self.player or self.player.pip else self.kodik
        key, pos = source.current_state()
        self.ctx.sources.remember_choice(release, dub)

        def ok(eps):
            same = key if any(e["key"] == key for e in eps) else None
            if key and not same:
                QMessageBox.information(self, APP_NAME, f"В озвучке «{dub['name']}» нет {key} серии — "
                                                        "открываем ближайшую доступную.")
            self._launch(release, dub, eps, same, position=pos if same and pos > 5000 else None)

        self.ctx.sources.episodes(release, dub, ok,
                                  lambda msg: QMessageBox.warning(self, APP_NAME, f"Не удалось сменить озвучку: {msg}"))

    def _open_season(self, entry):
        def ok(release_id):
            if release_id:
                self.play(release_id, "")
            else:
                QMessageBox.information(self, APP_NAME, f"«{entry['name']}» пока нет ни в одном источнике.")
        if entry.get("release"):
            self.ctx.remember(entry["release"])
        self.ctx.franchise.resolve(entry, ok)

    def _player_closed(self):
        if self.stack.indexOf(self.player) < 0:
            self.stack.addWidget(self.player)
        if self._in_player():
            self.go_back()

    def _pip_toggled(self, on):
        if on:
            # Плеер уходит в мини-окно поверх всех — возвращаемся к приложению.
            self.stack.removeWidget(self.player)
            self.sidebar.show()
            self.go_back()
        else:
            self.player.hide()
            self.player.setWindowFlags(Qt.WindowType.Widget)
            if self.stack.indexOf(self.player) < 0:
                self.stack.addWidget(self.player)
            cur = self._current_key()
            if cur:
                self.history.append(cur)
            self._set_current(self.player)
            self.player.show()
            self.activateWindow()
            self.player.setFocus()

    def closeEvent(self, e):
        self.player.stop()
        if self.player.pip:
            self.player.hide()
        self.kodik.stop()
        super().closeEvent(e)
