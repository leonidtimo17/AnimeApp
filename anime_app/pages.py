import datetime
import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from .api import SORTINGS, TYPES, WEEKDAYS, episode_label, fmt_ordinal, release_title
from .db import STATUSES
from .bandwidth import quality_name
from .franchise import Franchise, is_movie, upcoming_episodes
from .sources import is_external_id, norm, resume_target
from .icons import icon, toggle_icon
from .theme import ACCENT, MUTED, TEXT
from .images import cover, episode_thumb, rounded
from .legal import show_doc
from .widgets import (
    CardGrid, CardRow, ExpandingLabel, FlowLayout, clear_layout, icon_label, label,
)


EPISODES_PAGE = 100  # серий на одной вкладке-диапазоне


def fmt_duration(sec):
    if not sec:
        return ""
    m = round(sec / 60)
    return f"{m} мин" if m < 60 else f"{m // 60} ч {m % 60} мин"


def fmt_when(ts):
    dt = datetime.datetime.fromtimestamp(ts)
    today = datetime.date.today()
    if dt.date() == today:
        return f"сегодня в {dt:%H:%M}"
    if dt.date() == today - datetime.timedelta(days=1):
        return f"вчера в {dt:%H:%M}"
    return f"{dt:%d.%m.%Y %H:%M}"


def next_air_date(weekday):
    """Ближайшая дата для дня недели (1 = понедельник), включая сегодня."""
    today = datetime.date.today()
    return today + datetime.timedelta(days=(weekday - today.isoweekday()) % 7)


def short_date(d):
    months = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    return f"{d.day} {months[d.month - 1]}"


def scroll_page():
    """Возвращает (scroll_area, content_layout) с отступами как у страниц."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(32, 28, 32, 32)
    lay.setSpacing(24)
    area.setWidget(host)
    return area, lay


class Page(QWidget):
    def on_show(self):
        pass


# ============================================================== Главная
class HomePage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        area, lay = scroll_page()
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(area)

        lay.addWidget(label("Главная", "H1"))
        self.continue_row = CardRow(ctx, "Продолжить просмотр", on_click=self._resume)
        self.today_row = CardRow(ctx, "Выходит сегодня")
        self.latest_row = CardRow(ctx, "Новые серии")
        self.top_row = CardRow(ctx, "Популярное на AniLibria")
        self.wish_row = CardRow(ctx, "Хочу посмотреть")
        for row in (self.continue_row, self.today_row, self.latest_row, self.wish_row, self.top_row):
            lay.addWidget(row)
        self.error = label("", "Muted")
        lay.addWidget(self.error)
        lay.addStretch(1)
        self._loaded_at = 0

    def _resume(self, item):
        self.ctx.play.emit(item["id"], "")

    def on_show(self):
        self.refresh_local()
        if time.time() - self._loaded_at > 600:
            self._loaded_at = time.time()
            self.load_remote()

    def refresh_local(self):
        rows = self.ctx.db.continue_watching()
        items = []
        for r in rows:
            it = self.ctx.item_from_row(r)
            it["subtitle"] = f"{fmt_ordinal(r['ordinal'])} серия · {fmt_when(r['watched_at'])}"
            if r["watched"]:
                it["subtitle"] = f"{fmt_ordinal(r['ordinal'])} серия просмотрена · далее следующая"
            items.append(it)
        self.continue_row.set_items(items)
        wish = [self.ctx.item_from_row(r) for r in self.ctx.db.library("planned")[:20]]
        self.wish_row.set_items(wish)

    def load_remote(self):
        def fail(msg):
            self.error.setText(f"Не удалось загрузить данные: {msg}")
            self._loaded_at = 0

        self.ctx.api.latest(lambda data: self.latest_row.set_items(
            [self.ctx.item_from_release(r) for r in data]), fail, limit=24)
        self.ctx.api.catalog(lambda data: self.top_row.set_items(
            [self.ctx.item_from_release(r) for r in data.get("data", [])]), fail,
            limit=24, sorting="RATING_DESC")

        def schedule(data):
            today = datetime.date.today().isoweekday()
            items = []
            for entry in data:
                rel = entry.get("release") or {}
                if (rel.get("publish_day") or {}).get("value") == today:
                    it = self.ctx.item_from_release(rel)
                    nxt = entry.get("next_release_episode_number")
                    if nxt:
                        it["subtitle"] = f"Ожидается {nxt} серия · сегодня"
                    items.append(it)
            self.today_row.set_items(items)
        self.ctx.api.schedule(schedule, fail)


# ============================================================== Каталог/поиск
class CatalogPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 0)
        lay.setSpacing(14)
        lay.addWidget(label("Поиск аниме", "H1"))

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Название на русском, английском или японском…")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.genre = QComboBox()
        self.genre.addItem("Все жанры", None)
        self.type = QComboBox()
        self.type.addItem("Все типы", None)
        for value, name in TYPES:
            self.type.addItem(name, value)
        self.year_from = QComboBox()
        self.year_to = QComboBox()
        self.year_from.addItem("Год от", None)
        self.year_to.addItem("Год до", None)
        self.sorting = QComboBox()
        for value, name in SORTINGS:
            self.sorting.addItem(name, value)
        for w in (self.genre, self.type, self.year_from, self.year_to, self.sorting):
            w.setMinimumWidth(140)
            filters.addWidget(w)
            w.currentIndexChanged.connect(self.reload)
        filters.addStretch(1)
        self.count = label("", "Muted")
        filters.addWidget(self.count)
        lay.addLayout(filters)

        self.grid = CardGrid(ctx)
        self.grid.need_more.connect(self.load_more)
        lay.addWidget(self.grid, 1)

        self.debounce = QTimer(self, singleShot=True, interval=450)
        self.debounce.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda: self.debounce.start())

        self.page = 0
        self.total_pages = 1
        self.loading = False
        self.token = 0
        self.seen_names = set()
        self.al_total = 0
        self.other_total = 0
        self.refs_loaded = False

    def on_show(self):
        self.search.setFocus()
        if not self.refs_loaded:
            self.refs_loaded = True
            self.ctx.api.genres(self._fill_genres, lambda _e: setattr(self, "refs_loaded", False))
            self.ctx.api.years(self._fill_years)
            self.reload()

    def _fill_genres(self, data):
        self.genre.blockSignals(True)
        for g in sorted(data, key=lambda g: g["name"]):
            self.genre.addItem(g["name"], g["id"])
        self.genre.blockSignals(False)

    def _fill_years(self, data):
        for box in (self.year_from, self.year_to):
            box.blockSignals(True)
            for y in sorted(data, reverse=True):
                box.addItem(str(y), y)
            box.blockSignals(False)

    def _update_count(self):
        extra = f" + {self.other_total} из полного каталога" if self.other_total else ""
        self.count.setText(f"Найдено: {self.al_total}{extra}")

    def _search_other(self, query, token):
        """Тайтлы, которых нет на AniLibria, — из полного каталога Shikimori (серии ищутся в AnimeVost и AnimeLib)."""
        def ok(results):
            if token != self.token:
                return
            items = []
            for x in results:
                names = {norm(x.get("name")), norm(x.get("russian"))} - {""}
                if names & self.seen_names or int(x["id"]) in self.seen_shiki:
                    continue
                item = self.ctx.sources.shiki_item(x)
                entry = self.ctx.db.library_entry(item["id"])
                item["status"], item["favorite"] = entry.get("status"), entry.get("favorite")
                items.append(item)
            self.other_total = len(items)
            self._update_count()
            self.grid.add_items(items)
            if not items and self.al_total == 0:
                self.grid.set_status("Ничего не найдено. Попробуйте другое название.")
        self.ctx.sources.shiki_search(query, ok)

    def reload(self):
        self.token += 1
        self.seen_names = set()
        self.seen_shiki = set()
        self.al_total = 0
        self.other_total = 0
        self.page = 0
        self.total_pages = 1
        self.loading = False
        self.grid.clear()
        self.load_more()

    def load_more(self):
        if self.loading or self.page >= self.total_pages:
            return
        self.loading = True
        token = self.token
        self.grid.set_status("Загрузка…")
        t = self.type.currentData()

        def ok(data):
            if token != self.token:
                return
            self.loading = False
            pag = data.get("meta", {}).get("pagination", {})
            self.total_pages = pag.get("total_pages", 1)
            self.page = pag.get("current_page", self.page + 1)
            self.al_total = pag.get("total", 0)
            self._update_count()
            releases = data.get("data", [])
            for r in releases:
                name = r.get("name") or {}
                self.seen_names |= {norm(name.get("main")), norm(name.get("english"))} - {""}
                if (r.get("shikimori") or {}).get("id"):
                    self.seen_shiki.add(int(r["shikimori"]["id"]))
            items = [self.ctx.item_from_release(r) for r in releases]
            self.grid.add_items(items)
            query = self.search.text().strip()
            if self.page == 1 and query:
                self._search_other(query, token)
            if self.page == 1 and not items and not query:
                self.grid.set_status("Ничего не найдено. Попробуйте другие фильтры.")
            else:
                self.grid.set_status("" if self.page < self.total_pages else "")

        def fail(msg):
            if token != self.token:
                return
            self.loading = False
            self.grid.set_status(f"Ошибка сети: {msg}")

        self.ctx.api.catalog(
            ok, fail, page=self.page + 1, limit=30,
            search=self.search.text().strip() or None,
            genre=self.genre.currentData(),
            types=[t] if t else None,
            year_from=self.year_from.currentData(),
            year_to=self.year_to.currentData(),
            sorting=self.sorting.currentData(),
        )


# ============================================================== Расписание
class SchedulePage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        area, self.lay = scroll_page()
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(area)
        self.lay.addWidget(label("Расписание выхода серий", "H1"))
        self.rows = []
        today = datetime.date.today().isoweekday()
        order = [((today - 1 + i) % 7) + 1 for i in range(7)]
        for day in order:
            title = f"{WEEKDAYS[day - 1]}, {short_date(next_air_date(day))}" + (" — сегодня" if day == today else "")
            row = CardRow(ctx, title)
            row.day = day
            self.rows.append(row)
            self.lay.addWidget(row)
        self.status = label("Загрузка…", "Muted")
        self.lay.addWidget(self.status)
        self.lay.addStretch(1)
        self.loaded = False

    def on_show(self):
        if self.loaded:
            return
        self.loaded = True

        def ok(data):
            self.status.setText("")
            by_day = {}
            for entry in data:
                rel = entry.get("release") or {}
                day = (rel.get("publish_day") or {}).get("value")
                it = self.ctx.item_from_release(rel)
                nxt = entry.get("next_release_episode_number")
                if nxt and day:
                    it["subtitle"] = f"Ожидается {nxt} серия · {short_date(next_air_date(day))}"
                by_day.setdefault(day, []).append(it)
            for row in self.rows:
                row.set_items(by_day.get(row.day, []), "В этот день ничего не выходит")

        def fail(msg):
            self.loaded = False
            self.status.setText(f"Ошибка: {msg}")

        self.ctx.api.schedule(ok, fail)


# ============================================================== Библиотека
class LibraryPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("Моя библиотека", "H1"))
        head.addStretch(1)
        self.stats = label("", "Muted")
        head.addWidget(self.stats)
        backup = QPushButton("  Резервная копия")
        backup.setIcon(icon("file-export", TEXT, 15))
        menu = QMenu(backup)
        menu.addAction("Экспорт в файл…", self._export)
        menu.addAction("Импорт из файла…", self._import)
        menu.addSeparator()
        menu.addAction("Очистить кэш", self._clear_cache)
        menu.addSeparator()
        menu.addAction("Пользовательское соглашение", lambda: show_doc(self, "terms"))
        menu.addAction("Политика конфиденциальности", lambda: show_doc(self, "privacy"))
        backup.setMenu(menu)
        head.addWidget(backup)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        self.keys = list(STATUSES) + ["favorite"]
        self.grids = {}
        for key in self.keys:
            grid = CardGrid(ctx)
            self.grids[key] = grid
            self.tabs.addTab(grid, "")
        lay.addWidget(self.tabs, 1)

    def on_show(self):
        db = self.ctx.db
        counts = db.library_counts()
        for i, key in enumerate(self.keys):
            name = "Избранное" if key == "favorite" else STATUSES[key]
            self.tabs.setTabText(i, f"{name}  {counts.get(key, 0)}")
            rows = db.library(favorites=True) if key == "favorite" else db.library(key)
            self.grids[key].set_items([self.ctx.item_from_row(r) for r in rows],
                                      "Пока пусто. Добавляйте аниме со страницы тайтла.")
        s = db.stats()
        self.stats.setText(f"Просмотрено серий: {s['episodes']} · {s['hours']:.1f} ч   ")

    def _clear_cache(self):
        n, size = self.ctx.db.http_stats()
        self.ctx.db.http_clear()
        disk = self.ctx.images.nam.cache()
        if disk:
            disk.clear()
        QMessageBox.information(self, "Кэш", f"Кэш очищен: {n} ответов сервера ({size / 1e6:.1f} МБ) и постеры.\n"
                                "Ваши списки и история не затронуты.")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", "anime_backup.json", "JSON (*.json)")
        if path:
            self.ctx.db.export_json(path)
            QMessageBox.information(self, "Готово", "Библиотека сохранена.")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "JSON (*.json)")
        if path:
            try:
                self.ctx.db.import_json(path)
            except Exception as exc:  # noqa: BLE001 — показать пользователю любую ошибку файла
                QMessageBox.warning(self, "Ошибка", str(exc))
                return
            self.on_show()
            self.ctx.library_changed.emit()


# ============================================================== История
class HistoryRow(QFrame):
    def __init__(self, ctx, row):
        super().__init__()
        self.ctx = ctx
        self.row = row
        self.setObjectName("HistoryRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 16, 10)
        lay.setSpacing(14)
        self.thumb = QLabel()
        self.thumb.setFixedSize(54, 76)
        lay.addWidget(self.thumb)
        text = QVBoxLayout()
        text.addWidget(label(row["title"], "CardTitle"))
        state = "просмотрено" if row["watched"] else \
            f"{row['position'] // 60000}:{row['position'] // 1000 % 60:02d} из {row['duration'] // 60000} мин"
        text.addWidget(label(f"{fmt_ordinal(row['ordinal'])} серия · {state}", "Muted"))
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(1000 if row["watched"] else int(1000 * row["position"] / max(1, row["duration"])))
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setMaximumWidth(320)
        text.addWidget(bar)
        lay.addLayout(text, 1)
        lay.addWidget(label(fmt_when(row["updated_at"]), "Muted"))
        ctx.images.load(row["poster"], self, lambda p: self.thumb.setPixmap(rounded(cover(p, 54, 76), 6)))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.ctx.play.emit(self.row["id"], self.row["episode_id"])
        elif e.button() == Qt.MouseButton.RightButton:
            menu = QMenu(self)
            menu.addAction("Открыть страницу аниме", lambda: self.ctx.open_anime.emit(self.row["id"]))
            menu.exec(e.globalPosition().toPoint())


class HistoryPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        area, lay = scroll_page()
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(area)
        head = QHBoxLayout()
        head.addWidget(label("История просмотра", "H1"))
        head.addStretch(1)
        clear = QPushButton("  Очистить историю")
        clear.setIcon(icon("trash-can", TEXT, 15))
        clear.clicked.connect(self._clear)
        head.addWidget(clear)
        lay.addLayout(head)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        lay.addLayout(self.list)
        lay.addStretch(1)

    def on_show(self):
        clear_layout(self.list)
        rows = self.ctx.db.history(limit=120)
        if not rows:
            self.list.addWidget(label("Здесь появятся серии, которые вы смотрели.", "Muted"))
        for r in rows:
            self.list.addWidget(HistoryRow(self.ctx, r))

    def _clear(self):
        if QMessageBox.question(self, "История", "Очистить историю? Отметки «просмотрено» сохранятся.") \
                == QMessageBox.StandardButton.Yes:
            self.ctx.db.clear_history()
            self.on_show()
            self.ctx.library_changed.emit()


# ============================================================== Страница тайтла
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def fmt_air_date(d):
    if not d:
        return "дата пока неизвестна"
    text = f"{d.day} {MONTHS[d.month - 1]}, {WEEKDAYS_SHORT[d.weekday()]}"
    if d.hour or d.minute:
        text += f" · {d:%H:%M}"
    return text


class EpisodeTile(QFrame):
    clicked = Signal(dict)
    menu_requested = Signal(dict, object)

    W, TH = 232, 130  # ширина плитки и высота кадра (16:9)

    def __init__(self, ep, prog, current=False, title=None, missing_note=None, images=None, preview=None, poster=None):
        super().__init__()
        self.ep = ep
        self.setObjectName("Episode")
        self.setProperty("current", current)
        self.setProperty("missing", bool(missing_note))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.W, self.TH + 58)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 8)
        lay.setSpacing(3)
        # Кадр из серии; если его нет — затемнённый постер тайтла с крупным номером
        number = fmt_ordinal(ep.get("ordinal"))
        watched = bool(prog and prog["watched"])
        frac = 1.0 if watched else (prog["position"] / prog["duration"] if prog and prog["duration"] else 0)
        self.thumb = QLabel()
        self.thumb.setFixedSize(self.W - 2, self.TH)
        lay.addWidget(self.thumb)

        def draw(src):
            pix = episode_thumb(src, self.W - 2, self.TH, number, not preview, frac, watched, current)
            self.thumb.setPixmap(rounded(pix, 9))
        self._draw = draw
        draw(None)
        if images and (preview or poster):
            images.load(preview or poster, self, draw)
        name = ep.get("name") or ep.get("name_english") or ""
        t = label(title or f"{number} серия", "CardTitle")
        t.setContentsMargins(11, 4, 11, 0)
        lay.addWidget(t)
        n = label(missing_note or name or fmt_duration(ep.get("duration")), "CardSub")
        n.setToolTip(missing_note or name)
        n.setContentsMargins(11, 0, 11, 0)
        n.setMaximumWidth(self.W - 2)
        lay.addWidget(n)
        lay.addStretch(1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.ep)
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.ep, e.globalPosition().toPoint())


class UpcomingTile(QFrame):
    """Серия, которой ещё нет: дата выхода или «ждём озвучку»."""

    def __init__(self, item):
        super().__init__()
        self.setObjectName("Upcoming")
        self.setFixedSize(210, 70)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(f"{item['ordinal']} серия", "CardTitle"))
        top.addStretch(1)
        dub = item["state"] in ("no_dub", "dub")
        top.addWidget(icon_label("microphone" if dub else "calendar-days", ACCENT if dub else MUTED, 14))
        lay.addLayout(top)
        if item["state"] == "dub":
            text = "озвучка ≈ " + fmt_air_date(item["date"])
            tip = "Серия уже вышла в Японии. Дата озвучки — примерная, по дню выхода серий."
        elif item["state"] == "no_dub":
            text = "вышла, ждём озвучку"
            tip = "Серия уже вышла в Японии, озвучка появится позже"
        else:
            text = fmt_air_date(item["date"])
            tip = "Дата выхода в Японии (по данным Shikimori), дальше — раз в неделю"
        lay.addWidget(label(text, "CardSub"))
        self.setToolTip(tip)


class SeasonCard(QFrame):
    """Сезон / фильм / OVA франшизы."""

    clicked = Signal(dict)

    def __init__(self, ctx, entry):
        super().__init__()
        self.entry = entry
        self.setObjectName("Season")
        self.setProperty("current", bool(entry.get("current")))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(150, 262)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)
        self.poster = QLabel()
        self.poster.setFixedSize(134, 180)
        self.poster.setStyleSheet("background:#222229;border-radius:8px;")
        lay.addWidget(self.poster)
        year = entry.get("year") or "анонс"
        head = label(f"{entry['label']} · {year}", "CardTitle")
        head.setStyleSheet(f"color:{ACCENT};" if entry.get("current") else "")
        lay.addWidget(head)
        name = label("", "CardSub")
        name.setWordWrap(True)
        name.setText(entry.get("name") or "")
        name.setToolTip(entry.get("name") or "")
        name.setFixedHeight(34)
        name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(name)
        ctx.images.load(entry.get("poster"), self,
                        lambda p: self.poster.setPixmap(rounded(cover(p, 134, 180), 8)))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self.entry.get("current"):
            self.clicked.emit(self.entry)


class DetailsPage(Page):
    back = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.release = None
        self.dubs = []
        self.dub = None
        self.dub_eps = []
        self.user_picked = False
        self.dubs_finished = False
        area, lay = scroll_page()
        self.area = area
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(area)

        back = QPushButton("  Назад")
        back.setIcon(icon("arrow-left", TEXT, 15))
        back.setObjectName("Flat")
        back.clicked.connect(self.back.emit)
        lay.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)

        top = QHBoxLayout()
        top.setSpacing(32)
        self.poster = QLabel()
        self.poster.setFixedSize(270, 385)
        self.poster.setStyleSheet("background:#222229;border-radius:14px;")
        top.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(10)
        self.title = ExpandingLabel("", "H1")
        self.title_en = label("", "Muted", wrap=True)
        info.addWidget(self.title)
        info.addWidget(self.title_en)
        self.ratings = QHBoxLayout()
        info.addLayout(self.ratings)
        self.meta = QGridLayout()
        self.meta.setHorizontalSpacing(24)
        self.meta.setVerticalSpacing(6)
        info.addLayout(self.meta)
        self.genres_host = QWidget()
        self.genres = FlowLayout(self.genres_host, spacing=6)
        info.addWidget(self.genres_host)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.play_btn = QPushButton("Смотреть")
        self.play_btn.setIcon(icon("play", "white", 16))
        self.play_btn.setIconSize(QSize(16, 16))
        self.play_btn.setObjectName("Primary")
        self.play_btn.setMinimumHeight(44)
        self.play_btn.clicked.connect(lambda: self._play(""))
        actions.addWidget(self.play_btn)
        self.status_btn = QPushButton()
        self.status_btn.setMinimumHeight(44)
        self.status_menu = QMenu(self.status_btn)
        self.status_btn.setMenu(self.status_menu)
        actions.addWidget(self.status_btn)
        self.fav_btn = QPushButton("В избранное")
        self.fav_btn.setIcon(toggle_icon(("heart", TEXT, True), ("heart", ACCENT, False), 16))
        self.fav_btn.setObjectName("Fav")
        self.fav_btn.setCheckable(True)
        self.fav_btn.setMinimumHeight(44)
        self.fav_btn.clicked.connect(self._toggle_fav)
        actions.addWidget(self.fav_btn)
        self.score_btn = QPushButton()
        self.score_btn.setMinimumHeight(44)
        score_menu = QMenu(self.score_btn)
        for s in range(10, 0, -1):
            score_menu.addAction(icon("star", "#ffc83d", 14), str(s), lambda s=s: self._set_score(s))
        score_menu.addSeparator()
        score_menu.addAction("Убрать оценку", lambda: self._set_score(None))
        self.score_btn.setMenu(score_menu)
        actions.addWidget(self.score_btn)
        actions.addStretch(1)
        info.addLayout(actions)

        self.description = ExpandingLabel("")
        self.description.setStyleSheet("color:#d0d0d8;line-height:140%;")
        info.addWidget(self.description)
        info.addStretch(1)
        top.addLayout(info, 1)
        lay.addLayout(top)

        self.notice = label("", "Muted", wrap=True)
        lay.addWidget(self.notice)

        # Сезоны и фильмы франшизы
        self.seasons_box = QWidget()
        sb = QVBoxLayout(self.seasons_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(8)
        sb.addWidget(label("Сезоны и фильмы", "H2"))
        self.seasons_scroll = QScrollArea()
        self.seasons_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.seasons_scroll.setWidgetResizable(True)
        self.seasons_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.seasons_scroll.setFixedHeight(282)
        seasons_host = QWidget()
        self.seasons = QHBoxLayout(seasons_host)
        self.seasons.setContentsMargins(0, 0, 0, 0)
        self.seasons.setSpacing(10)
        self.seasons_scroll.setWidget(seasons_host)
        sb.addWidget(self.seasons_scroll)
        self.seasons_box.hide()  # добавляется в раскладку ниже, под сериями

        ep_head = QHBoxLayout()
        ep_head.setSpacing(12)
        self.ep_title = label("Серии", "H2")
        ep_head.addWidget(self.ep_title)
        self.dub_btn = QPushButton("  Озвучка: ищем…")
        self.dub_btn.setIcon(icon("microphone", TEXT, 14))
        self.dub_btn.setStyleSheet("padding-right: 34px;")
        self.dub_btn.setToolTip("Выбрать озвучку или субтитры")
        self.dub_menu = QMenu(self.dub_btn)
        self.dub_btn.setMenu(self.dub_menu)
        ep_head.addWidget(self.dub_btn)
        self.dub_note = label("", "Muted")
        ep_head.addWidget(self.dub_note)
        ep_head.addStretch(1)
        self.mark_all = QPushButton("Отметить всё просмотренным")
        self.mark_all.setObjectName("Flat")
        self.mark_all.setIcon(icon("check", TEXT, 14))
        self.mark_all.clicked.connect(self._mark_all)
        ep_head.addWidget(self.mark_all)
        lay.addLayout(ep_head)
        self.range_host = QWidget()
        self.ranges = FlowLayout(self.range_host, spacing=6)
        lay.addWidget(self.range_host)
        self.range_host.hide()
        self.ep_host = QWidget()
        self.episodes = FlowLayout(self.ep_host, spacing=10)
        lay.addWidget(self.ep_host)

        self.upcoming_box = QWidget()
        ub = QVBoxLayout(self.upcoming_box)
        ub.setContentsMargins(0, 8, 0, 0)
        ub.setSpacing(10)
        self.upcoming_title = label("Предстоящие серии", "H2")
        ub.addWidget(self.upcoming_title)
        up_host = QWidget()
        self.upcoming = FlowLayout(up_host, spacing=10)
        ub.addWidget(up_host)
        lay.addWidget(self.upcoming_box)
        self.upcoming_box.hide()
        self.similar_row = CardRow(ctx, "Похожее")   # подборка Shikimori
        self.similar_row.hide()
        lay.addWidget(self.similar_row)
        lay.addSpacing(8)
        lay.addWidget(self.seasons_box)
        lay.addStretch(1)

        self.franchise = getattr(ctx, "franchise", None) or Franchise(ctx.api, ctx.sources, self)
        self.union = {}          # ключ серии -> {"ep": ..., "groups": set()}
        self.union_for = None
        self.range_idx = None
        self._dirty = set()
        self._render_timer = QTimer(self, singleShot=True, interval=40)
        self._render_timer.timeout.connect(self._flush_render)
        self.shiki_info = None

    # ------------------------------------------------------------ loading
    def load(self, release_id):
        self.area.verticalScrollBar().setValue(0)
        cached = self.ctx.db.cached_release(release_id)
        if cached:
            self.render(cached)
        else:
            self.release = None
            self.title.setText("Загрузка…")
            self.title_en.setText("")
            self.description.setText("")
            self.poster.clear()
            clear_layout(self.episodes)
            self.play_btn.setEnabled(False)

        def ok(data):
            self.ctx.remember(data, full=True)
            if self.release is None or self.release["id"] == data["id"]:
                self.render(data)

        def fail(msg):
            if not cached:
                self.title.setText("Не удалось загрузить")
                self.description.setText(msg)

        self.ctx.load_release(release_id, ok, fail)

    def _load_similar(self, rel):
        sid = (rel.get("shikimori") or {}).get("id")
        self.similar_row.hide()
        if not sid:
            return

        def ok(items):
            if self.release is not rel:
                return
            cards = [self.ctx.sources.shiki_item(x) for x in items or []
                     if x.get("kind") not in ("music", "pv", "cm")][:20]
            self.similar_row.set_items(cards)
            self.similar_row.setVisible(bool(cards))
        self.ctx.api.fetch(f"https://shikimori.io/api/animes/{sid}/similar", None, ok, lambda _e: None,
                           cache_ttl=86400)

    def _load_franchise(self, rel):
        def ok(entries):
            if self.release is not rel and (not self.release or self.release["id"] != rel["id"]):
                return
            clear_layout(self.seasons)
            for e in entries:
                card = SeasonCard(self.ctx, e)
                card.clicked.connect(self._open_season)
                self.seasons.addWidget(card)
            self.seasons.addStretch(1)
            self.seasons_box.setVisible(bool(entries))
            current = next((i for i, e in enumerate(entries) if e.get("current")), 0)
            QTimer.singleShot(0, lambda: self.seasons_scroll.horizontalScrollBar().setValue(max(0, current * 160 - 160)))

        def info_ok(info):
            if self.release and self.release["id"] == rel["id"]:
                self.shiki_info = info
                self._render_upcoming()

        self.franchise.load(rel, ok)
        self.franchise.info(rel, info_ok)

    def _open_season(self, entry):
        def ok(release_id):
            if release_id:
                self.ctx.open_anime.emit(release_id)
            else:
                QMessageBox.information(self, "Сезоны и фильмы",
                                        f"«{entry['name']}» пока нет ни в одном источнике.")
        if entry.get("release"):
            self.ctx.remember(entry["release"])
        self.franchise.resolve(entry, ok)

    def on_show(self):
        if self.release:
            self._render_library()
            self._render_episodes()

    def render(self, rel):
        new_title = not self.release or self.release["id"] != rel["id"]
        self.release = rel
        self.title.setText(release_title(rel))
        name = rel.get("name") or {}
        self.title_en.setText(" / ".join(x for x in (name.get("english"), name.get("alternative")) if x))
        self.description.setText((rel.get("description") or "").strip())

        clear_layout(self.ratings)
        for key, caption in (("shikimori", "Shikimori"), ("mal", "MyAnimeList")):
            r = rel.get(key) or {}
            if r.get("rating"):
                self.ratings.addWidget(icon_label("star", "#ffc83d", 15))
                lbl = label(f"{r['rating']:.2f}  <span style='color:#9a9aa6;font-weight:400'>{caption}</span>",
                            "Rating")
                lbl.setTextFormat(Qt.TextFormat.RichText)
                self.ratings.addWidget(lbl)
        self.ratings.addStretch(1)

        clear_layout(self.meta)
        rows = [
            ("Тип", (rel.get("type") or {}).get("description")),
            ("Год", rel.get("year")),
            ("Сезон", (rel.get("season") or {}).get("description")),
            ("Эпизоды", rel.get("episodes_total")),
            ("Длительность", fmt_duration((rel.get("average_duration_of_episode") or 0) * 60)),
            ("Возраст", (rel.get("age_rating") or {}).get("label")),
            ("Статус", "Выходит" if rel.get("is_ongoing") else "Завершён"),
            ("Выход серий", (rel.get("publish_day") or {}).get("description") if rel.get("is_ongoing") else None),
        ]
        i = 0
        for k, v in rows:
            if v:
                self.meta.addWidget(label(k, "Muted"), i // 2, (i % 2) * 2)
                self.meta.addWidget(label(str(v)), i // 2, (i % 2) * 2 + 1)
                i += 1

        clear_layout(self.genres)
        for g in rel.get("genres") or []:
            self.genres.addWidget(label(g.get("name", ""), "Chip"))

        self.ctx.images.load(self.ctx.api.poster_url(rel), self,
                             lambda p: self.poster.setPixmap(rounded(cover(p, 270, 385), 14)))
        self._render_library()
        if new_title:
            self.dubs, self.dub, self.dub_eps = [], None, []
            self.user_picked = self.dubs_finished = False
            self.union, self.shiki_info, self.union_for, self.range_idx = {}, None, None, None
            self.seasons_box.hide()
            self.upcoming_box.hide()
            self._render_episodes()
            self._load_franchise(rel)
            self._load_similar(rel)
        self._load_dubs()

    def _render_library(self):
        rid = self.release["id"]
        entry = self.ctx.db.library_entry(rid)
        status = entry.get("status")
        self.status_btn.setText(("  " + STATUSES[status]) if status else "  В список")
        self.status_btn.setIcon(icon("check", "#3fbf6a", 14) if status else icon("plus", TEXT, 14))
        self.status_menu.clear()
        for key, name in STATUSES.items():
            act = self.status_menu.addAction(name, lambda k=key: self._set_status(k))
            act.setCheckable(True)
            act.setChecked(key == status)
        if status:
            self.status_menu.addSeparator()
            self.status_menu.addAction("Убрать из списков", lambda: self._set_status(None))
        self.fav_btn.setChecked(bool(entry.get("favorite")))
        self.fav_btn.setText("  В избранном" if entry.get("favorite") else "  В избранное")
        self.score_btn.setText(f"  {entry['score']}" if entry.get("score") else "  Оценить")
        self.score_btn.setIcon(icon("star", "#ffc83d", 15) if entry.get("score") else icon("star", TEXT, 15, regular=True))

    # ------------------------------------------------------------ озвучки
    def _load_dubs(self):
        rel = self.release
        if not self.dubs:
            self.dub_btn.setText("  Озвучка: ищем…")
            self.dub_note.setText("")

        def got(dubs, finished):
            if self.release is not rel:
                return
            self.dubs = dubs
            self.dubs_finished = finished
            self._fill_dub_menu()
            if not self.user_picked:
                best = self.ctx.sources.choose(rel, dubs)
                if best and (not self.dub or best["id"] != self.dub["id"]):
                    self._select_dub(best)
            if finished:
                self._load_union()
            if finished and not dubs:
                self.dub_btn.setText("  Озвучки не найдены")
                self._render_episodes()

        self.ctx.sources.find_dubs(rel, got)

    def _fill_dub_menu(self):
        self.dub_menu.clear()
        groups = [
            ("Встроенный плеер", [d for d in self.dubs if d["native"]]),
            ("Плеер Kodik — озвучка", [d for d in self.dubs if not d["native"] and d["kind"] == "voice"]),
            ("Плеер Kodik — субтитры", [d for d in self.dubs if not d["native"] and d["kind"] == "sub"]),
        ]
        for title, items in groups:
            if not items:
                continue
            head = self.dub_menu.addAction(f"{title}  ({len(items)})")
            head.setEnabled(False)
            for d in items:
                act = self.dub_menu.addAction(d["name"], lambda d=d: self._select_dub(d, user=True))
                act.setCheckable(True)
                act.setChecked(bool(self.dub and d["id"] == self.dub["id"]))
            self.dub_menu.addSeparator()
        if not self.dubs_finished:
            self.dub_menu.addAction("Ищем ещё озвучки…").setEnabled(False)

    def _select_dub(self, dub, user=False):
        rel = self.release
        self.dub = dub
        if user:
            self.user_picked = True
            self.ctx.sources.remember_choice(rel, dub)
        self.dub_btn.setText(f"  {dub['name']}")
        self.dub_btn.setMinimumWidth(self.dub_btn.fontMetrics().horizontalAdvance(dub["name"]) + 90)
        self.dub_note.setText("встроенный плеер" if dub["native"] else "веб-плеер Kodik")
        self._fill_dub_menu()

        def ok(eps):
            if self.release is rel and self.dub is dub:
                self.dub_eps = eps
                heights = [int(q) for e in eps for q, url in (e.get("streams") or {}).items() if url]
                if heights:
                    top = max(heights)
                    self.dub_note.setText(f"встроенный плеер · до {top}p ({quality_name(top)})")
                self._render_episodes()
                self._render_upcoming()

        self.ctx.sources.episodes(rel, dub, ok, lambda _e: ok([]))

    @staticmethod
    def _group(dub):
        return dub["id"] if dub["native"] else "kodik"

    def _load_union(self):
        """Серии из всех источников: чтобы показать все, даже если в выбранной озвучке их нет."""
        rel = self.release
        if self.union_for == rel["id"]:
            return
        self.union_for = rel["id"]
        reps = {}
        for d in self.dubs:
            reps.setdefault(self._group(d), d)
        for group, dub in reps.items():
            def ok(eps, group=group):
                if self.release is not rel:
                    return
                for e in eps:
                    slot = self.union.setdefault(e["key"], {"ep": e, "groups": set(), "preview": None})
                    slot["groups"].add(group)
                    slot["preview"] = slot["preview"] or e.get("preview")
                self._render_episodes()
                self._render_upcoming()
            self.ctx.sources.episodes(rel, dub, ok, lambda _e: None)

    def _alt_dub(self, groups):
        """Озвучка, в которой есть серия: сначала встроенный плеер, потом Kodik (любимая команда)."""
        for d in self.dubs:
            if d["native"] and d["id"] in groups:
                return d
        if "kodik" in groups:
            kodik = [d for d in self.dubs if not d["native"]]
            return self.ctx.sources.choose(self.release, kodik) if kodik else None
        return None

    def _set_range(self, i):
        self.range_idx = i
        self._render_episodes()

    def _play_any(self, ep):
        slot = self.union.get(ep["key"])
        if self.dub and (not slot or self._group(self.dub) in slot["groups"]):
            self._play(ep["key"])
            return
        alt = self._alt_dub(slot["groups"]) if slot else None
        if alt:
            self._select_dub(alt, user=True)
            self._play(ep["key"])

    def _render_upcoming(self):
        self._dirty.add("upcoming")
        self._render_timer.start()

    def _flush_render(self):
        dirty, self._dirty = self._dirty, set()
        if not self.release:
            return
        if "episodes" in dirty:
            self._do_render_episodes()
        if "upcoming" in dirty:
            self._do_render_upcoming()

    def _do_render_upcoming(self):
        rel = self.release
        info = self.shiki_info
        own_al = len([e for e in self.dub_eps]) if self.dub and self.dub["id"] == "anilibria" else 0
        dubbing = rel.get("is_ongoing") or (rel.get("episodes_total") and 0 < own_al < rel["episodes_total"])
        weekday = (rel.get("publish_day") or {}).get("value") if dubbing else None
        keys = list(self.union) or [e["key"] for e in self.dub_eps]
        if weekday and self.dub and self.dub["id"] == "anilibria" and self.dub_eps:
            # Расписание озвучки — это расписание AniLibria: считаем от её собственных серий.
            keys = [e["key"] for e in self.dub_eps]
        if not keys and not self.dubs_finished:
            return
        items = upcoming_episodes(rel, info, keys, dub_weekday=weekday)
        clear_layout(self.upcoming)
        for it in items:
            self.upcoming.addWidget(UpcomingTile(it))
        waiting = sum(1 for it in items if it["state"] in ("no_dub", "dub"))
        title = "Предстоящие серии"
        if info and info.get("episodes"):
            title += f"  ·  всего серий: {info['episodes']}"
        if waiting:
            title += f"  ·  ждут озвучки: {waiting}"
        self.upcoming_title.setText(title)
        self.upcoming_box.setVisible(bool(items))

    def _play(self, key):
        if self.dub:
            self.ctx.sources.remember_choice(self.release, self.dub)
        self.ctx.play.emit(self.release["id"], key)

    def _render_episodes(self):
        self._dirty.add("episodes")
        self._render_timer.start()

    def _do_render_episodes(self):
        rel = self.release
        eps = self.dub_eps
        progress = self.ctx.db.progress_for(rel["id"])
        last = self.ctx.db.last_progress(rel["id"])
        clear_layout(self.episodes)
        # Показываем все серии из всех источников; те, что есть только в другой озвучке, — пунктиром.
        own = {e["key"] for e in eps}
        shown = list(eps) + [s["ep"] for k, s in self.union.items() if k not in own]
        shown.sort(key=lambda e: e["ordinal"])
        movie = is_movie(rel) and len(shown) == 1
        total = len(shown)
        self.ep_title.setText(("Фильм" if movie else f"Серии  {total}") if shown else "Серии")
        self.mark_all.setVisible(bool(eps))
        notice = ""
        if self.dubs_finished and not self.dubs:
            notice = ("Серии не найдены ни в одном источнике. "
                      "Добавьте в «Хочу посмотреть», чтобы не потерять.")
        self.notice.setText(notice)
        self.notice.setVisible(bool(notice))
        names = {self._group(d): d["name"] for d in self.dubs if d["native"]}
        names["kodik"] = "Kodik"
        poster = self.ctx.api.poster_url(rel)
        clear_layout(self.ranges)
        if len(shown) > EPISODES_PAGE:
            pages = (len(shown) + EPISODES_PAGE - 1) // EPISODES_PAGE
            if self.range_idx is None:
                # По умолчанию — диапазон, где серия, с которой продолжать.
                target = resume_target(rel["id"], eps, self.ctx.db)[0] if eps else 0
                key = eps[target]["key"] if eps else None
                pos = next((i for i, e in enumerate(shown) if e["key"] == key), 0)
                self.range_idx = pos // EPISODES_PAGE
            self.range_idx = min(self.range_idx, pages - 1)
            for i in range(pages):
                a, b = shown[i * EPISODES_PAGE], shown[min(len(shown), (i + 1) * EPISODES_PAGE) - 1]
                btn = QPushButton(f"{fmt_ordinal(a['ordinal'])}–{fmt_ordinal(b['ordinal'])}")
                btn.setObjectName("Range")
                btn.setCheckable(True)
                btn.setChecked(i == self.range_idx)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _=False, i=i: self._set_range(i))
                self.ranges.addWidget(btn)
            shown = shown[self.range_idx * EPISODES_PAGE:(self.range_idx + 1) * EPISODES_PAGE]
        self.range_host.setVisible(self.ranges.count() > 0)
        self.range_host.updateGeometry()
        for ep in shown:
            note = None
            if ep["key"] not in own:
                groups = (self.union.get(ep["key"]) or {}).get("groups", set())
                note = "есть в: " + ", ".join(sorted(names.get(g, g) for g in groups))
            tile = EpisodeTile(ep, progress.get(ep["key"]), current=bool(last and last["episode_id"] == ep["key"]),
                               title="Смотреть фильм" if movie else None, missing_note=note, images=self.ctx.images,
                               preview=ep.get("preview") or (self.union.get(ep["key"]) or {}).get("preview"),
                               poster=poster)
            tile.clicked.connect(self._play_any)
            tile.menu_requested.connect(self._episode_menu)
            self.episodes.addWidget(tile)
        self.ep_host.updateGeometry()

        self.play_btn.setEnabled(bool(eps))
        if eps:
            idx, _pos = resume_target(rel["id"], eps, self.ctx.db)
            ep = eps[idx]
            if last:
                self.play_btn.setText(f"  Продолжить: {fmt_ordinal(ep['ordinal'])} серия")
            elif len(eps) > 1:
                self.play_btn.setText(f"  Смотреть с {fmt_ordinal(ep['ordinal'])} серии")
            else:
                self.play_btn.setText("  Смотреть")
        else:
            self.play_btn.setText("  Смотреть")

    # ------------------------------------------------------------ actions
    def _set_status(self, status):
        self.ctx.db.set_status(self.release["id"], status)
        self._render_library()
        self.ctx.library_changed.emit()

    def _toggle_fav(self):
        self.ctx.db.set_favorite(self.release["id"], self.fav_btn.isChecked())
        self._render_library()
        self.ctx.library_changed.emit()

    def _set_score(self, score):
        self.ctx.db.set_score(self.release["id"], score)
        self._render_library()

    def _episode_menu(self, ep, pos):
        rid = self.release["id"]
        prog = self.ctx.db.progress_for(rid).get(ep["key"])
        watched = bool(prog and prog["watched"])
        menu = QMenu(self)
        menu.addAction(icon("play", TEXT, 14), "Смотреть", lambda: self._play(ep["key"]))
        menu.addAction("Смотреть с начала", lambda: (
            self.ctx.db.set_watched(rid, ep["key"], ep.get("ordinal"), False, (ep.get("duration") or 0) * 1000),
            self._play(ep["key"])))
        menu.addSeparator()
        if watched:
            menu.addAction("Снять отметку «просмотрено»", lambda: self._mark([ep], False))
        else:
            menu.addAction("Отметить просмотренной", lambda: self._mark([ep], True))
        eps = self.dub_eps
        idx = next((i for i, e in enumerate(eps) if e["key"] == ep["key"]), 0)
        menu.addAction("Отметить все до этой включительно", lambda: self._mark(eps[: idx + 1], True))
        menu.exec(pos)

    def _mark(self, eps, watched):
        rid = self.release["id"]
        for ep in eps:
            self.ctx.db.set_watched(rid, ep["key"], ep.get("ordinal"), watched, (ep.get("duration") or 0) * 1000)
        self._render_episodes()
        self.ctx.library_changed.emit()

    def _mark_all(self):
        self._mark(self.dub_eps, True)
        if not self.release.get("is_ongoing"):
            self._set_status("completed")

