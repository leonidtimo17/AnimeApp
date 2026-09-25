"""Страница тайтла: описание, рейтинги, списки, серии всех озвучек, предстоящие серии, сезоны, «Похожее»."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QMenu, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core.formatting import fmt_duration, fmt_ordinal
from ...domain.dubs import alternative_dub, menu_groups, representatives
from ...domain.episodes import EPISODES_PAGE, EpisodeUnion, dub_group, episode_ranges, resume_target
from ...domain.franchise import is_movie
from ...domain.library import STATUSES, status_name
from ...domain.quality import quality_name
from ...domain.shikimori import HIDDEN_KINDS
from ...domain.titles import release_title
from ...domain.upcoming import upcoming_episodes
from ...infrastructure.http.client import RequestScope
from ..icons import icon, toggle_icon
from ..theme import ACCENT, STAR, TEXT
from ..widgets.cards import CardRow
from ..widgets.episode_tiles import EpisodeTile, SeasonCard, UpcomingTile
from ..widgets.layout import ExpandingLabel, FlowLayout, Page, clear_layout, icon_label, label, scroll_page_widget
from ..widgets.states import error_text, loading
from ...core.i18n import t

RENDER_BATCH_MS = 40   # ответы нескольких источников подряд — одна перерисовка серий


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
        self.scope = RequestScope()
        self.area, lay = scroll_page_widget(self)

        back = QPushButton("  " + t("common.back"))
        back.setIcon(icon("arrow-left", TEXT, 15))
        back.setObjectName("Flat")
        back.clicked.connect(self.back.emit)
        lay.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)

        top = QHBoxLayout()
        top.setSpacing(32)
        self.poster = label()
        self.poster.setObjectName("Poster")
        self.poster.setFixedSize(270, 385)
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
        info.addLayout(self._build_actions())

        self.description = ExpandingLabel("", "Description")
        info.addWidget(self.description)
        info.addStretch(1)
        top.addLayout(info, 1)
        lay.addLayout(top)

        self.notice = label("", "Muted", wrap=True)
        lay.addWidget(self.notice)
        self.seasons_box = self._build_seasons()   # добавляется в раскладку ниже, под сериями
        lay.addLayout(self._build_episode_header())
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
        self.upcoming_title = label(t("anime.upcoming"), "H2")
        ub.addWidget(self.upcoming_title)
        up_host = QWidget()
        self.upcoming = FlowLayout(up_host, spacing=10)
        ub.addWidget(up_host)
        lay.addWidget(self.upcoming_box)
        self.upcoming_box.hide()
        self.similar_row = CardRow(ctx, t("anime.similar"))   # подборка Shikimori
        self.similar_row.hide()
        lay.addWidget(self.similar_row)
        lay.addSpacing(8)
        lay.addWidget(self.seasons_box)
        lay.addStretch(1)

        self.union = EpisodeUnion()
        self.union_for = None
        self.range_idx = None
        self._dirty = set()
        self._render_timer = QTimer(self, singleShot=True, interval=RENDER_BATCH_MS)
        self._render_timer.timeout.connect(self._flush_render)
        self.shiki_info = None

    # ------------------------------------------------------------ построение
    def _build_actions(self):
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.play_btn = QPushButton(t("anime.watch"))
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
        self.fav_btn = QPushButton(t("library.add_favorite"))
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
            score_menu.addAction(icon("star", STAR, 14), str(s), lambda s=s: self._set_score(s))
        score_menu.addSeparator()
        score_menu.addAction(t("anime.remove_score"), lambda: self._set_score(None))
        self.score_btn.setMenu(score_menu)
        actions.addWidget(self.score_btn)
        actions.addStretch(1)
        return actions

    def _build_seasons(self):
        box = QWidget()
        sb = QVBoxLayout(box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(8)
        sb.addWidget(label(t("anime.seasons"), "H2"))
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
        box.hide()
        return box

    def _build_episode_header(self):
        ep_head = QHBoxLayout()
        ep_head.setSpacing(12)
        self.ep_title = label(t("anime.episodes"), "H2")
        ep_head.addWidget(self.ep_title)
        self.dub_btn = QPushButton("  " + t("dubs.searching"))
        self.dub_btn.setIcon(icon("microphone", TEXT, 14))
        self.dub_btn.setObjectName("DubButton")
        self.dub_btn.setToolTip(t("dubs.choose"))
        self.dub_menu = QMenu(self.dub_btn)
        self.dub_btn.setMenu(self.dub_menu)
        ep_head.addWidget(self.dub_btn)
        self.dub_note = label("", "Muted")
        ep_head.addWidget(self.dub_note)
        ep_head.addStretch(1)
        self.mark_all = QPushButton(t("anime.mark_all"))
        self.mark_all.setObjectName("Flat")
        self.mark_all.setIcon(icon("check", TEXT, 14))
        self.mark_all.clicked.connect(self._mark_all)
        ep_head.addWidget(self.mark_all)
        return ep_head

    # ------------------------------------------------------------ загрузка
    def load(self, release_id):
        self.scope.cancel()     # запросы прошлого тайтла больше не нужны
        self.area.verticalScrollBar().setValue(0)
        cached = self.ctx.releases.cached(release_id)
        if cached:
            self.render(cached)
        else:
            self.release = None
            self.title.setText(loading())
            self.title_en.setText("")
            self.description.setText("")
            self.poster.clear()
            clear_layout(self.episodes)
            self.play_btn.setEnabled(False)

        def ok(data):
            self.ctx.releases.remember(data, full=True)
            if self.release is None or self.release["id"] == data["id"]:
                self.render(data)

        def fail(err):
            if not cached:
                self.title.setText(t("errors.load_failed"))
                self.description.setText(error_text(err))

        self.ctx.releases.load(release_id, ok, fail, scope=self.scope)

    def _load_similar(self, rel):
        sid = (rel.get("shikimori") or {}).get("id")
        self.similar_row.hide()
        if not sid:
            return

        def ok(items):
            if self.release is not rel:
                return
            cards = [self.ctx.releases.shiki_card(x) for x in items or [] if x.get("kind") not in HIDDEN_KINDS][:20]
            self.similar_row.set_items(cards)
            self.similar_row.setVisible(bool(cards))
        self.ctx.shikimori_api.similar(sid, ok, lambda _e: None, scope=self.scope)

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

        self.ctx.franchise.load(rel, ok)
        self.ctx.franchise.info(rel, info_ok)

    def _open_season(self, entry):
        def ok(release_id):
            if release_id:
                self.ctx.open_anime.emit(release_id)
            else:
                QMessageBox.information(self, t("anime.seasons"), t("anime.not_in_sources", name=entry["name"]))
        if entry.get("release"):
            self.ctx.releases.remember(entry["release"])
        self.ctx.franchise.resolve(entry, ok)

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
        self._render_ratings(rel)
        self._render_meta(rel)
        clear_layout(self.genres)
        for g in rel.get("genres") or []:
            self.genres.addWidget(label(g.get("name", ""), "Chip"))
        self.ctx.images.load_cover(self.ctx.releases.poster_url(rel), 270, 385, 14, self, self.poster.setPixmap)
        self._render_library()
        if new_title:
            self.dubs, self.dub, self.dub_eps = [], None, []
            self.user_picked = self.dubs_finished = False
            self.union, self.shiki_info, self.union_for, self.range_idx = EpisodeUnion(), None, None, None
            self.seasons_box.hide()
            self.upcoming_box.hide()
            self._render_episodes()
            self._load_franchise(rel)
            self._load_similar(rel)
        self._load_dubs()

    def _render_ratings(self, rel):
        clear_layout(self.ratings)
        for key, caption in (("shikimori", "Shikimori"), ("mal", "MyAnimeList")):
            r = rel.get(key) or {}
            if r.get("rating"):
                self.ratings.addWidget(icon_label("star", STAR, 15))
                lbl = label(f"{r['rating']:.2f}  <span style='color:#9a9aa6;font-weight:400'>{caption}</span>",
                            "Rating")
                lbl.setTextFormat(Qt.TextFormat.RichText)
                self.ratings.addWidget(lbl)
        self.ratings.addStretch(1)

    def _render_meta(self, rel):
        clear_layout(self.meta)
        rows = [
            (t("anime.info.type"), (rel.get("type") or {}).get("description")),
            (t("anime.info.year"), rel.get("year")),
            (t("anime.info.season"), (rel.get("season") or {}).get("description")),
            (t("anime.info.episodes"), rel.get("episodes_total")),
            (t("anime.info.duration"), fmt_duration((rel.get("average_duration_of_episode") or 0) * 60)),
            (t("anime.info.age"), (rel.get("age_rating") or {}).get("label")),
            (t("anime.info.status"), t("anime.info.ongoing") if rel.get("is_ongoing") else t("anime.info.finished")),
            (t("anime.info.airs"), (rel.get("publish_day") or {}).get("description") if rel.get("is_ongoing") else None),
        ]
        i = 0
        for k, v in rows:
            if v:
                self.meta.addWidget(label(k, "Muted"), i // 2, (i % 2) * 2)
                self.meta.addWidget(label(str(v)), i // 2, (i % 2) * 2 + 1)
                i += 1

    def _render_library(self):
        entry = self.ctx.library.entry(self.release["id"])
        status = entry.get("status")
        self.status_btn.setText("  " + (status_name(status) if status else t("anime.add_to_list")))
        self.status_btn.setIcon(icon("check", "#3fbf6a", 14) if status else icon("plus", TEXT, 14))
        self.status_menu.clear()
        for key in STATUSES:
            act = self.status_menu.addAction(status_name(key), lambda k=key: self._set_status(k))
            act.setCheckable(True)
            act.setChecked(key == status)
        if status:
            self.status_menu.addSeparator()
            self.status_menu.addAction(t("anime.remove_from_list"), lambda: self._set_status(None))
        self.fav_btn.setChecked(bool(entry.get("favorite")))
        self.fav_btn.setText("  " + t("library.in_favorites" if entry.get("favorite") else "library.add_favorite"))
        self.score_btn.setText(f"  {entry['score']}" if entry.get("score") else "  " + t("anime.rate"))
        self.score_btn.setIcon(icon("star", STAR, 15) if entry.get("score") else icon("star", TEXT, 15, regular=True))

    # ------------------------------------------------------------ озвучки
    def _load_dubs(self):
        rel = self.release
        if not self.dubs:
            self.dub_btn.setText("  " + t("dubs.searching"))
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
                self.dub_btn.setText("  " + t("dubs.none"))
                self._render_episodes()

        self.ctx.sources.find_dubs(rel, got)

    def _fill_dub_menu(self):
        self.dub_menu.clear()
        for title, items in menu_groups(self.dubs):
            head = self.dub_menu.addAction(f"{title}  ({len(items)})")
            head.setEnabled(False)
            for d in items:
                act = self.dub_menu.addAction(d["name"], lambda d=d: self._select_dub(d, user=True))
                act.setCheckable(True)
                act.setChecked(bool(self.dub and d["id"] == self.dub["id"]))
            self.dub_menu.addSeparator()
        if not self.dubs_finished:
            self.dub_menu.addAction(t("dubs.searching_more")).setEnabled(False)

    def _select_dub(self, dub, user=False):
        rel = self.release
        self.dub = dub
        if user:
            self.user_picked = True
            self.ctx.sources.remember_choice(rel, dub)
        self.dub_btn.setText(f"  {dub['name']}")
        self.dub_btn.setMinimumWidth(self.dub_btn.fontMetrics().horizontalAdvance(dub["name"]) + 90)
        self.dub_note.setText(t("dubs.note_builtin") if dub["native"] else t("dubs.note_kodik"))
        self._fill_dub_menu()

        def ok(eps):
            if self.release is rel and self.dub is dub:
                self.dub_eps = eps
                heights = [int(q) for e in eps for q, url in (e.get("streams") or {}).items() if url]
                if heights:
                    top = max(heights)
                    self.dub_note.setText(t("dubs.note_quality", q=top, name=quality_name(top)))
                self._render_episodes()
                self._render_upcoming()

        self.ctx.sources.episodes(rel, dub, ok, lambda _e: ok([]))

    def _load_union(self):
        """Серии из всех источников: чтобы показать все, даже если в выбранной озвучке их нет."""
        rel = self.release
        if self.union_for == rel["id"]:
            return
        self.union_for = rel["id"]
        for dub in representatives(self.dubs):
            def ok(eps, group=dub_group(dub)):
                if self.release is not rel:
                    return
                self.union.add(group, eps)
                self._render_episodes()
                self._render_upcoming()
            self.ctx.sources.episodes(rel, dub, ok, lambda _e: None)

    def _set_range(self, i):
        self.range_idx = i
        self._render_episodes()

    def _play_any(self, ep):
        groups = self.union.groups(ep["key"])
        if self.dub and (not self.union.has(ep["key"]) or dub_group(self.dub) in groups):
            self._play(ep["key"])
            return
        alt = alternative_dub(self.dubs, groups, lambda kodik: self.ctx.sources.choose(self.release, kodik))
        if alt:
            self._select_dub(alt, user=True)
            self._play(ep["key"])

    # ------------------------------------------------------------ отрисовка (пачками)
    def _render_upcoming(self):
        self._dirty.add("upcoming")
        self._render_timer.start()

    def _render_episodes(self):
        self._dirty.add("episodes")
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
        own_al = len(self.dub_eps) if self.dub and self.dub["id"] == "anilibria" else 0
        dubbing = rel.get("is_ongoing") or (rel.get("episodes_total") and 0 < own_al < rel["episodes_total"])
        weekday = (rel.get("publish_day") or {}).get("value") if dubbing else None
        keys = self.union.keys() or [e["key"] for e in self.dub_eps]
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
        title = t("anime.upcoming")
        if info and info.get("episodes"):
            title += "  ·  " + t("anime.total_episodes", n=info["episodes"])
        if waiting:
            title += "  ·  " + t("anime.waiting_dub", n=waiting)
        self.upcoming_title.setText(title)
        self.upcoming_box.setVisible(bool(items))

    def _do_render_episodes(self):
        rel = self.release
        eps = self.dub_eps
        progress = self.ctx.progress.for_anime(rel["id"])     # один раз на всю отрисовку
        last = self.ctx.progress.last(rel["id"])
        resume_idx = resume_target(eps, progress, last)[0] if eps else 0
        self.ep_host.setUpdatesEnabled(False)
        clear_layout(self.episodes)
        # Показываем все серии из всех источников; те, что есть только в другой озвучке, — пунктиром.
        own = {e["key"] for e in eps}
        shown = self.union.shown(eps)
        movie = is_movie(rel) and len(shown) == 1
        self.ep_title.setText((t("anime.kinds.movie") if movie else f"{t('anime.episodes')}  {len(shown)}") if shown
                              else t("anime.episodes"))
        self.mark_all.setVisible(bool(eps))
        notice = ""
        if self.dubs_finished and not self.dubs:
            notice = t("anime.no_episodes_notice")
        self.notice.setText(notice)
        self.notice.setVisible(bool(notice))
        names = {dub_group(d): d["name"] for d in self.dubs if d["native"]}
        names["kodik"] = "Kodik"
        poster = self.ctx.releases.poster_url(rel)
        clear_layout(self.ranges)
        ranges = episode_ranges(shown)
        if ranges:
            if self.range_idx is None:
                # По умолчанию — диапазон, где серия, с которой продолжать.
                key = eps[resume_idx]["key"] if eps else None
                pos = next((i for i, e in enumerate(shown) if e["key"] == key), 0)
                self.range_idx = pos // EPISODES_PAGE
            self.range_idx = min(self.range_idx, len(ranges) - 1)
            for i, (a, b) in enumerate(ranges):
                btn = QPushButton(f"{a}–{b}")
                btn.setObjectName("Range")
                btn.setCheckable(True)
                btn.setChecked(i == self.range_idx)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _=False, i=i: self._set_range(i))
                self.ranges.addWidget(btn)
            shown = shown[self.range_idx * EPISODES_PAGE:(self.range_idx + 1) * EPISODES_PAGE]
        self.range_host.setVisible(bool(ranges))
        self.range_host.updateGeometry()
        for ep in shown:
            note = None
            if ep["key"] not in own:
                note = t("anime.available_in", names=", ".join(sorted(names.get(g, g) for g in self.union.groups(ep["key"]))))
            tile = EpisodeTile(ep, progress.get(ep["key"]), current=bool(last and last["episode_id"] == ep["key"]),
                               title=t("anime.watch_movie") if movie else None, missing_note=note, images=self.ctx.images,
                               preview=ep.get("preview") or self.union.preview(ep["key"]), poster=poster)
            tile.clicked.connect(self._play_any)
            tile.menu_requested.connect(self._episode_menu)
            self.episodes.addWidget(tile)
        self.ep_host.setUpdatesEnabled(True)
        self.ep_host.updateGeometry()

        self.play_btn.setEnabled(bool(eps))
        if eps:
            ep = eps[resume_idx]
            if last:
                self.play_btn.setText("  " + t("anime.continue_n", n=fmt_ordinal(ep["ordinal"])))
            elif len(eps) > 1:
                self.play_btn.setText("  " + t("anime.watch_from_n", n=fmt_ordinal(ep["ordinal"])))
            else:
                self.play_btn.setText("  " + t("anime.watch"))
        else:
            self.play_btn.setText("  " + t("anime.watch"))

    # ------------------------------------------------------------ действия
    def _play(self, key):
        if self.dub:
            self.ctx.sources.remember_choice(self.release, self.dub)
        self.ctx.play.emit(self.release["id"], key)

    def _set_status(self, status):
        self.ctx.library.set_status(self.release["id"], status)

    def _toggle_fav(self):
        self.ctx.library.set_favorite(self.release["id"], self.fav_btn.isChecked())

    def _set_score(self, score):
        self.ctx.library.set_score(self.release["id"], score)

    def _episode_menu(self, ep, pos):
        rid = self.release["id"]
        prog = self.ctx.progress.for_anime(rid).get(ep["key"])
        watched = bool(prog and prog["watched"])
        menu = QMenu(self)
        menu.addAction(icon("play", TEXT, 14), t("anime.watch"), lambda: self._play(ep["key"]))
        menu.addAction(t("anime.watch_from_start"), lambda: (self.ctx.progress.restart(rid, ep), self._play(ep["key"])))
        menu.addSeparator()
        if watched:
            menu.addAction(t("anime.unmark_watched"), lambda: self._mark([ep], False))
        else:
            menu.addAction(t("anime.mark_watched"), lambda: self._mark([ep], True))
        eps = self.dub_eps
        idx = next((i for i, e in enumerate(eps) if e["key"] == ep["key"]), 0)
        menu.addAction(t("anime.mark_up_to"), lambda: self._mark(eps[: idx + 1], True))
        menu.exec(pos)

    def _mark(self, eps, watched):
        self.ctx.progress.set_watched(self.release["id"], eps, watched)

    def _mark_all(self):
        self._mark(self.dub_eps, True)
        if not self.release.get("is_ongoing"):
            self._set_status("completed")
