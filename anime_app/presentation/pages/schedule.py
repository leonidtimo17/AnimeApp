"""Расписание выхода серий на неделю."""
from __future__ import annotations

import datetime

from ...core.formatting import WEEKDAYS, next_air_date, short_date
from ..widgets.cards import CardRow
from ..widgets.layout import Page, label, scroll_page_widget
from ..widgets.states import LOADING, error_text


class SchedulePage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        _area, self.lay = scroll_page_widget(self)
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
        self.status = label(LOADING, "Muted", wrap=True)
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
                it = self.ctx.releases.item(rel)
                nxt = entry.get("next_release_episode_number")
                if nxt and day:
                    it["subtitle"] = f"Ожидается {nxt} серия · {short_date(next_air_date(day))}"
                by_day.setdefault(day, []).append(it)
            for row in self.rows:
                row.set_items(by_day.get(row.day, []), "В этот день ничего не выходит")

        def fail(err):
            self.loaded = False
            self.status.setText(error_text(err, "Не удалось загрузить расписание"))

        self.ctx.anilibria.schedule(ok, fail)
