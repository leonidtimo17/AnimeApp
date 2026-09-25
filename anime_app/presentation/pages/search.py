"""Поиск по названию + фильтры; листает сразу оба каталога (AniLibria, затем полный каталог Shikimori)."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout

from ...infrastructure.api.anilibria import SORTINGS, TYPES
from ..widgets.cards import CardGrid
from ..widgets.layout import Page, label
from ..widgets.states import LOADING

SEARCH_DEBOUNCE_MS = 450   # ищем, когда пользователь перестал печатать


class SearchPage(Page):
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

        self.debounce = QTimer(self, singleShot=True, interval=SEARCH_DEBOUNCE_MS)
        self.debounce.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda: self.debounce.start())
        self.session = None
        self.refs_loaded = False

    def on_show(self):
        self.search.setFocus()
        if not self.refs_loaded:
            self.refs_loaded = True
            self.ctx.anilibria.genres(self._fill_genres, lambda _e: setattr(self, "refs_loaded", False))
            self.ctx.anilibria.years(self._fill_years)
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

    def reload(self):
        if self.session:
            self.session.cancel()      # ответы прошлого поиска больше не нужны
        t = self.type.currentData()
        self.session = self.ctx.search(self.search.text(), {
            "genre": self.genre.currentData(), "types": [t] if t else None,
            "year_from": self.year_from.currentData(), "year_to": self.year_to.currentData(),
            "sorting": self.sorting.currentData()})
        self.grid.clear()
        self.count.setText("")
        self.load_more()

    def load_more(self):
        session = self.session
        if not session or session.loading or session.exhausted:
            return
        self.grid.set_status(LOADING)

        def on_page(page):
            if session is not self.session:
                return
            extra = f" + {page.extra} из полного каталога" if page.extra else ""
            self.count.setText(f"Найдено: {page.total}{extra}")
            self.grid.add_items(page.items)
            self.grid.set_more(page.has_more)
            if page.nothing_found and (page.source == "shikimori" or not session.query):
                self.grid.set_status("Ничего не найдено. Попробуйте другое название." if session.query
                                     else "Ничего не найдено. Попробуйте другие фильтры.")
            elif page.finished and session.query:
                self.grid.set_status("Это всё, что нашлось")
            else:
                self.grid.set_status("")

        def on_err(msg):
            if session is self.session:
                self.grid.set_status(msg)
        session.next_page(on_page, on_err)
