"""Каталог: фильтры (жанры, тип, статус, сезон, годы) и сортировка. Фильтры запоминаются."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...infrastructure.api.anilibria import seasons, sortings, types
from ...infrastructure.http.client import RequestScope
from ..widgets.cards import CardGrid
from ..widgets.layout import FlowLayout, Page, clear_layout, label
from ..widgets.states import error_text, loading
from ...core.i18n import t

FILTER_DEBOUNCE_MS = 250   # несколько щелчков по фильтрам подряд — один запрос

DEFAULTS = {"sorting": "RATING_DESC", "types": [], "genres": [], "status": None, "season": None,
            "year_from": None, "year_to": None}


class CatalogPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.f = dict(DEFAULTS, **(ctx.prefs.get("catalog_filters") or {}))
        self.scope = RequestScope()
        self.page = 0
        self.total_pages = 1
        self.loading = False
        self.token = 0
        self.refs_loaded = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------------------------------------------------------- панель фильтров
        panel_scroll = QScrollArea()
        panel_scroll.setObjectName("FilterPanel")
        panel_scroll.setFixedWidth(300)
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        panel.setObjectName("FilterPanelBody")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(22, 28, 18, 24)
        pl.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label(t("catalog.filters"), "H2"))
        head.addStretch(1)
        reset = QPushButton(t("catalog.reset"))
        reset.setObjectName("Flat")
        reset.clicked.connect(self.reset)
        head.addWidget(reset)
        pl.addLayout(head)

        pl.addWidget(label(t("catalog.sort"), "FilterTitle"))
        self.sorting = QComboBox()
        for value, name in sortings():
            self.sorting.addItem(name, value)
        self.sorting.currentIndexChanged.connect(lambda: self._set("sorting", self.sorting.currentData()))
        pl.addWidget(self.sorting)

        pl.addWidget(label(t("catalog.status"), "FilterTitle"))
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_group = QButtonGroup(self)
        for value, name in ((None, t("catalog.statuses.all")), (True, t("catalog.statuses.ongoing")),
                            (False, t("catalog.statuses.finished"))):
            b = self._chip(name)
            b.setProperty("value", value)
            self.status_group.addButton(b)
            b.clicked.connect(lambda _=False, v=value: self._set("status", v))
            status_row.addWidget(b)
        status_row.addStretch(1)
        pl.addLayout(status_row)

        pl.addWidget(label(t("catalog.type"), "FilterTitle"))
        types_host = QWidget()
        self.types_flow = FlowLayout(types_host, spacing=6)
        self.type_buttons = {}
        for value, name in types():
            b = self._chip(name)
            b.clicked.connect(lambda _=False, v=value: self._toggle("types", v))
            self.types_flow.addWidget(b)
            self.type_buttons[value] = b
        pl.addWidget(types_host)

        pl.addWidget(label(t("catalog.season"), "FilterTitle"))
        self.season = QComboBox()
        self.season.addItem(t("catalog.any"), None)
        for value, name in seasons():
            self.season.addItem(name, value)
        self.season.currentIndexChanged.connect(lambda: self._set("season", self.season.currentData()))
        pl.addWidget(self.season)

        pl.addWidget(label(t("catalog.years"), "FilterTitle"))
        years = QHBoxLayout()
        self.year_from = QComboBox()
        self.year_to = QComboBox()
        self.year_from.addItem(t("catalog.from"), None)
        self.year_to.addItem(t("catalog.to"), None)
        self.year_from.currentIndexChanged.connect(lambda: self._set("year_from", self.year_from.currentData()))
        self.year_to.currentIndexChanged.connect(lambda: self._set("year_to", self.year_to.currentData()))
        years.addWidget(self.year_from)
        years.addWidget(self.year_to)
        pl.addLayout(years)

        genre_head = QHBoxLayout()
        genre_head.addWidget(label(t("catalog.genres"), "FilterTitle"))
        genre_head.addStretch(1)
        self.genre_hint = label("", "Muted")
        genre_head.addWidget(self.genre_hint)
        pl.addLayout(genre_head)
        genres_host = QWidget()
        self.genres_flow = FlowLayout(genres_host, spacing=6)
        self.genre_buttons = {}
        pl.addWidget(genres_host)
        pl.addStretch(1)
        panel_scroll.setWidget(panel)
        root.addWidget(panel_scroll)

        # ---------------------------------------------------------------- результаты
        right = QVBoxLayout()
        right.setContentsMargins(28, 28, 28, 0)
        right.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(label(t("navigation.catalog"), "H1"))
        top.addStretch(1)
        self.count = label("", "Muted")
        top.addWidget(self.count)
        right.addLayout(top)
        self.active = label("", "Muted", wrap=True)
        right.addWidget(self.active)
        self.grid = CardGrid(ctx)
        self.grid.need_more.connect(self.load_more)
        right.addWidget(self.grid, 1)
        root.addLayout(right, 1)

        self.debounce = QTimer(self, singleShot=True, interval=FILTER_DEBOUNCE_MS)
        self.debounce.timeout.connect(self.reload)
        self._sync_controls()

    # ------------------------------------------------------------ helpers
    def _chip(self, text):
        b = QPushButton(text)
        b.setObjectName("FilterChip")
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _set(self, key, value):
        if self.f.get(key) == value:
            return
        self.f[key] = value
        self._changed()

    def _toggle(self, key, value):
        items = list(self.f.get(key) or [])
        if value in items:
            items.remove(value)
        else:
            items.append(value)
        self.f[key] = items
        self._changed()

    def _changed(self):
        self.ctx.prefs.set("catalog_filters", self.f)
        self._sync_controls()
        self.debounce.start()

    def reset(self):
        self.f = dict(DEFAULTS)
        self._changed()

    def _sync_controls(self):
        for box, key in ((self.sorting, "sorting"), (self.season, "season"),
                         (self.year_from, "year_from"), (self.year_to, "year_to")):
            box.blockSignals(True)
            idx = box.findData(self.f.get(key))
            box.setCurrentIndex(max(0, idx))
            box.blockSignals(False)
        for b in self.status_group.buttons():
            b.setChecked(b.property("value") == self.f.get("status"))
        for value, b in self.type_buttons.items():
            b.setChecked(value in self.f["types"])
        for gid, b in self.genre_buttons.items():
            b.setChecked(gid in self.f["genres"])
        n = len(self.f["genres"])
        self.genre_hint.setText(t("catalog.selected_all", n=n) if n > 1 else (t("catalog.selected", n=n) if n else ""))
        self._describe()

    def _describe(self):
        parts = []
        names = {gid: b.text() for gid, b in self.genre_buttons.items()}
        if self.f["genres"]:
            parts.append(" + ".join(names.get(g, str(g)) for g in self.f["genres"]))
        if self.f["types"]:
            parts.append(", ".join(dict(types()).get(c, c) for c in self.f["types"]))
        if self.f["status"] is not None:
            parts.append(t("catalog.statuses.ongoing" if self.f["status"] else "catalog.statuses.finished").lower())
        if self.f["season"]:
            parts.append(dict(seasons())[self.f["season"]].lower())
        if self.f["year_from"] or self.f["year_to"]:
            parts.append(f"{self.f['year_from'] or '…'}–{self.f['year_to'] or '…'}")
        self.active.setText(t("catalog.active", filters=" · ".join(parts)) if parts else t("catalog.all_anime"))

    # ------------------------------------------------------------ data
    def on_show(self):
        if not self.refs_loaded:
            self.refs_loaded = True
            self.ctx.anilibria.genres(self._fill_genres, lambda _e: setattr(self, "refs_loaded", False))
            self.ctx.anilibria.years(self._fill_years)
            self.reload()

    def _fill_genres(self, data):
        clear_layout(self.genres_flow)
        self.genre_buttons = {}
        for g in sorted(data, key=lambda g: g["name"]):
            b = self._chip(g["name"])
            b.clicked.connect(lambda _=False, gid=g["id"]: self._toggle("genres", gid))
            self.genres_flow.addWidget(b)
            self.genre_buttons[g["id"]] = b
        self._sync_controls()

    def _fill_years(self, data):
        for box in (self.year_from, self.year_to):
            box.blockSignals(True)
            for y in sorted(data, reverse=True):
                box.addItem(str(y), y)
            box.blockSignals(False)
        self._sync_controls()

    def reload(self):
        self.scope.cancel()          # ответы по старым фильтрам больше не нужны
        self.token += 1
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
        self.grid.set_status(loading())

        def ok(data):
            if token != self.token:
                return
            self.loading = False
            pag = data.get("meta", {}).get("pagination", {})
            self.total_pages = pag.get("total_pages", 1)
            self.page = pag.get("current_page", self.page + 1)
            self.count.setText(t("search.found", n=pag.get("total", 0)))
            items = self.ctx.releases.items(data.get("data", []))
            self.grid.add_items(items)
            self.grid.set_more(self.page < self.total_pages)
            if self.page == 1 and not items:
                self.grid.set_status(t("catalog.nothing"))
            else:
                self.grid.set_status("")

        def fail(err):
            if token == self.token:
                self.loading = False
                self.grid.set_status(error_text(err))

        f = self.f
        self.ctx.anilibria.catalog(ok, fail, page=self.page + 1, limit=30, sorting=f["sorting"],
                                   types=f["types"] or None, genres=f["genres"], ongoing=f["status"],
                                   season=f["season"], year_from=f["year_from"], year_to=f["year_to"],
                                   scope=self.scope)
