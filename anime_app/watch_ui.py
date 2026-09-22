"""Страница просмотра как на YouTube: блок под видео (название, серия, кнопки, описание)
и список серий справа (вкладки «Все серии / Непросмотренные», строки с кадрами)."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .api import fmt_ordinal, release_title
from .icons import icon
from .images import episode_thumb
from .theme import ACCENT, BORDER, MUTED, SURFACE, SURFACE_2, TEXT

THUMB_W, THUMB_H = 150, 84

PAGE_QSS = f"""
QWidget#WatchPage {{ background: #0f0f12; }}
QLabel#WTitle {{ font-size: 21px; font-weight: 700; color: {TEXT}; }}
QLabel#WSub {{ font-size: 14px; color: {MUTED}; }}
QLabel#WDesc {{ background: {SURFACE}; border-radius: 12px; padding: 10px 14px; color: #d4d4dc; font-size: 13px; }}
QLabel#WHead {{ font-size: 17px; font-weight: 700; color: {TEXT}; }}
QPushButton#WChip {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 16px; padding: 7px 14px;
    color: {TEXT}; font-size: 13px; font-weight: 600; min-width: 0; }}
QPushButton#WChip:hover {{ border-color: {ACCENT}; background: {SURFACE_2}; }}
QPushButton#WChip:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#WChip::menu-indicator {{ width: 0; }}
QPushButton#WTab {{ background: {SURFACE_2}; border: none; border-radius: 8px; padding: 7px 12px; color: {TEXT};
    font-size: 13px; font-weight: 600; min-width: 0; }}
QPushButton#WTab:checked {{ background: #f2f2f5; color: #111; }}
QListWidget#WList {{ background: transparent; border: none; outline: none; font-size: 14px; }}
QListWidget#WList::item {{ padding: 6px; border-radius: 10px; color: {TEXT}; }}
QListWidget#WList::item:hover {{ background: rgba(255,255,255,0.06); }}
QListWidget#WList::item:selected {{ background: rgba(255,106,26,0.25); color: white; }}
"""


def chip(text, glyph=None, checkable=False):
    b = QPushButton(("  " if glyph else "") + text)
    b.setObjectName("WChip")
    if glyph:
        b.setIcon(icon(glyph, TEXT, 14))
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


class WatchInfo(QWidget):
    """Название, серия, кнопки (озвучка, избранное, «хочу посмотреть», сезоны, полный экран), описание."""

    fullscreen_clicked = Signal()
    comments_clicked = Signal()

    def __init__(self, ctx, dub_menu, season_menu, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.release = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 0)
        lay.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("WTitle")
        self.title.setWordWrap(True)
        self.sub = QLabel()
        self.sub.setObjectName("WSub")
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 2)
        row.setSpacing(8)
        self.dub = chip("Озвучка", "microphone")
        self.dub.setMenu(dub_menu)
        self.fav = chip("Избранное", "heart", checkable=True)
        self.plan = chip("Хочу посмотреть", "bookmark", checkable=True)
        self.seasons = chip("Сезоны и фильмы", "layer-group")
        self.seasons.setMenu(season_menu)
        self.seasons.hide()
        self.fs = chip("На весь экран", "expand")
        self.cm = chip("Обсуждение", "comments", checkable=True)   # плеер Kodik: обсуждение справа вместо серий
        self.cm.hide()
        self.cm.clicked.connect(self.comments_clicked.emit)
        for b in (self.dub, self.fav, self.plan, self.seasons, self.cm, self.fs):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.fav.clicked.connect(self._fav)
        self.plan.clicked.connect(self._plan)
        self.fs.clicked.connect(self.fullscreen_clicked.emit)
        self.desc = QLabel()
        self.desc.setObjectName("WDesc")
        self.desc.setWordWrap(True)
        self.desc.setCursor(Qt.CursorShape.PointingHandCursor)
        self.desc.mousePressEvent = lambda _e: self._toggle_desc()
        self.desc.setToolTip("Нажмите, чтобы развернуть описание")
        lay.addWidget(self.desc)
        self.head = QLabel("Обсуждение")
        self.head.setObjectName("WHead")
        lay.addWidget(self.head)
        self._full = ""
        self._open = False

    def set_episode(self, release, ep, idx, total, dub_name):
        self.release = release
        self.title.setText(release_title(release))
        name = f" · {ep['name']}" if ep and ep.get("name") else ""
        self.sub.setText(f"{fmt_ordinal((ep or {}).get('ordinal'))} серия{name} · {idx + 1} из {total}")
        self.dub.setText("  " + dub_name)
        entry = self.ctx.db.library_entry(release["id"])
        self.fav.setChecked(bool(entry.get("favorite")))
        self.plan.setChecked(entry.get("status") == "planned")
        full = (release.get("description") or "").strip()
        if full != self._full:
            self._full, self._open = full, False
            self._render_desc()

    def use_comments_button(self):
        """Обсуждение не под видео, а по кнопке (плеер Kodik — его окно нельзя прокручивать)."""
        self.cm.show()
        self.head.hide()

    def set_has_seasons(self, has):
        self.seasons.setVisible(has)

    def _render_desc(self):
        self.desc.setVisible(bool(self._full))
        text = self._full if self._open or len(self._full) < 260 else self._full[:250].rsplit(" ", 1)[0] + "…  ещё"
        self.desc.setText(text)

    def _toggle_desc(self):
        self._open = not self._open
        self._render_desc()

    def _fav(self):
        rid = self.release["id"]
        self.ctx.db.set_favorite(rid, self.fav.isChecked())
        self.ctx.library_changed.emit()

    def _plan(self):
        rid = self.release["id"]
        self.ctx.db.set_status(rid, "planned" if self.plan.isChecked() else "watching")
        self.ctx.library_changed.emit()


class EpisodeSide(QWidget):
    """Список серий справа: вкладки и строки с кадром, номером, названием, прогрессом."""

    picked = Signal(int)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.release, self.eps, self.current, self.poster = None, [], 0, None
        self.filter = "all"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.all_btn = QPushButton("Все серии")
        self.new_btn = QPushButton("Непросмотренные")
        for b, f in ((self.all_btn, "all"), (self.new_btn, "new")):
            b.setObjectName("WTab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, f=f: self._set_filter(f))
            tabs.addWidget(b)
        tabs.addStretch(1)
        lay.addLayout(tabs)
        self.list = QListWidget()
        self.list.setObjectName("WList")
        self.list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.list.setSpacing(2)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.itemClicked.connect(lambda it: self.picked.emit(it.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.list, 1)
        self._set_filter("all", render=False)

    def set_episodes(self, release, eps, current, poster):
        self.release, self.eps, self.current, self.poster = release, eps, current, poster
        self.render()

    def set_current(self, current):
        self.current = current
        self.render()

    def _set_filter(self, f, render=True):
        self.filter = f
        self.all_btn.setChecked(f == "all")
        self.new_btn.setChecked(f == "new")
        if render:
            self.render()

    def render(self):
        if not self.release:
            return
        self.all_btn.setText(f"Все серии · {len(self.eps)}")
        self.list.clear()
        progress = self.ctx.db.progress_for(self.release["id"])
        cur_item = None
        for i, ep in enumerate(self.eps):
            prog = progress.get(ep["key"]) or {}
            if self.filter == "new" and prog.get("watched") and i != self.current:
                continue
            text = f"{fmt_ordinal(ep.get('ordinal'))} серия" + (f"\n{ep['name']}" if ep.get("name") else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setSizeHint(QSize(0, THUMB_H + 14))
            self.list.addItem(item)
            frac = 1.0 if prog.get("watched") else (prog["position"] / prog["duration"] if prog.get("duration") else 0)
            self._thumb(item, ep.get("preview") or self.poster, fmt_ordinal(ep.get("ordinal")), not ep.get("preview"),
                        frac, bool(prog.get("watched")), i == self.current)
            if i == self.current:
                cur_item = item
        if cur_item:
            self.list.setCurrentItem(cur_item)
            self.list.scrollToItem(cur_item, QListWidget.ScrollHint.PositionAtCenter)

    def _thumb(self, item, url, number, fallback, frac, watched, current):
        def draw(src):
            try:
                item.setIcon(QPixmap(episode_thumb(src, THUMB_W, THUMB_H, number, fallback, frac, watched, current,
                                                   radius=8)))
            except RuntimeError:   # список уже перестроен
                pass
        draw(None)
        if url:
            self.ctx.images.load(url, self, draw)
