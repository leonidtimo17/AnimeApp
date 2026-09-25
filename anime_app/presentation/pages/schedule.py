"""Расписание выхода серий на неделю."""
from __future__ import annotations

import datetime

from ...core.formatting import next_air_date, short_date, weekdays
from ..widgets.cards import CardRow
from ..widgets.layout import Page, label, scroll_page_widget
from ..widgets.states import error_text, loading
from ...core.i18n import t


class SchedulePage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        _area, self.lay = scroll_page_widget(self)
        self.lay.addWidget(label(t("schedule.title"), "H1"))
        self.rows = []
        today = datetime.date.today().isoweekday()
        order = [((today - 1 + i) % 7) + 1 for i in range(7)]
        for day in order:
            title = f"{weekdays()[day - 1]}, {short_date(next_air_date(day))}" + (f" — {t('schedule.today')}" if day == today else "")
            row = CardRow(ctx, title)
            row.day = day
            self.rows.append(row)
            self.lay.addWidget(row)
        self.status = label(loading(), "Muted", wrap=True)
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
                    it["subtitle"] = t("schedule.expected_on", n=nxt, date=short_date(next_air_date(day)))
                by_day.setdefault(day, []).append(it)
            for row in self.rows:
                row.set_items(by_day.get(row.day, []), t("schedule.nothing"))

        def fail(err):
            self.loaded = False
            self.status.setText(error_text(err, t("schedule.failed")))

        self.ctx.anilibria.schedule(ok, fail)
