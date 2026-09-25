"""Главная: «Продолжить просмотр», «Выходит сегодня», новые серии, популярное, «Хочу посмотреть»."""
from __future__ import annotations

import datetime
import time

from ...core.formatting import fmt_ordinal, fmt_when
from ..widgets.cards import CardRow
from ..widgets.layout import Page, label, scroll_page_widget
from ..widgets.states import error_text

REMOTE_REFRESH_SEC = 600


class HomePage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        _area, lay = scroll_page_widget(self)
        lay.addWidget(label("Главная", "H1"))
        self.continue_row = CardRow(ctx, "Продолжить просмотр", on_click=self._resume)
        self.today_row = CardRow(ctx, "Выходит сегодня")
        self.latest_row = CardRow(ctx, "Новые серии")
        self.top_row = CardRow(ctx, "Популярное на AniLibria")
        self.wish_row = CardRow(ctx, "Хочу посмотреть")
        for row in (self.continue_row, self.today_row, self.latest_row, self.wish_row, self.top_row):
            lay.addWidget(row)
        self.error = label("", "Muted", wrap=True)
        lay.addWidget(self.error)
        lay.addStretch(1)
        self._loaded_at = 0.0

    def _resume(self, item):
        self.ctx.play.emit(item["id"], "")

    def on_show(self):
        self.refresh_local()
        if time.time() - self._loaded_at > REMOTE_REFRESH_SEC:
            self._loaded_at = time.time()
            self.load_remote()

    def refresh_local(self):
        items = []
        for r in self.ctx.progress.continue_watching():
            it = self.ctx.releases.item_from_row(r)
            if r["watched"]:
                it["subtitle"] = f"{fmt_ordinal(r['ordinal'])} серия просмотрена · далее следующая"
            else:
                it["subtitle"] = f"{fmt_ordinal(r['ordinal'])} серия · {fmt_when(r['watched_at'])}"
            items.append(it)
        self.continue_row.set_items(items)
        self.wish_row.set_items([self.ctx.releases.item_from_row(r)
                                 for r in self.ctx.library.rows("planned", limit=20)])

    def load_remote(self):
        self.error.setText("")

        def fail(err):
            self.error.setText(error_text(err, "Не удалось загрузить данные"))
            self._loaded_at = 0

        api, releases = self.ctx.anilibria, self.ctx.releases
        api.latest(lambda data: self.latest_row.set_items(releases.items(data)), fail, limit=24)
        api.catalog(lambda data: self.top_row.set_items(releases.items(data.get("data", []))), fail,
                    limit=24, sorting="RATING_DESC")

        def schedule(data):
            today = datetime.date.today().isoweekday()
            items = []
            for entry in data:
                rel = entry.get("release") or {}
                if (rel.get("publish_day") or {}).get("value") == today:
                    it = releases.item(rel)
                    nxt = entry.get("next_release_episode_number")
                    if nxt:
                        it["subtitle"] = f"Ожидается {nxt} серия · сегодня"
                    items.append(it)
            self.today_row.set_items(items)
        api.schedule(schedule, fail)
