"""Обсуждение серии в плеере: комментарии Shikimori, отметка момента серии, спойлеры."""
import datetime
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout,
)

from .api import fmt_ordinal
from .shikimori import render_body

PANEL_QSS = """
QFrame#Comments { background: rgba(16,16,20,0.97); border-left: 1px solid rgba(255,255,255,0.1); }
QFrame#Comments QLabel, QFrame#Comments QCheckBox { color: #f2f2f5; font-size: 13px; }
QFrame#Comments QPushButton { color: white; background: #24242c; border: 1px solid #34343f; border-radius: 9px;
    padding: 6px 12px; font-size: 13px; font-weight: 600; }
QFrame#Comments QPushButton:checked, QFrame#Comments QPushButton#Send { background: #ff6a1a; border-color: #ff6a1a; }
QFrame#Comments QPushButton:disabled { color: #777; }
QFrame#Comments QTextBrowser { background: transparent; border: none; color: #f2f2f5; font-size: 14px; }
QFrame#Comments QPlainTextEdit { background: #1c1c22; color: white; border: 1px solid #34343f; border-radius: 9px;
    padding: 6px; font-size: 14px; }
"""


def _ago(iso):
    try:
        t = datetime.datetime.fromisoformat(iso)
        s = (datetime.datetime.now(t.tzinfo) - t).total_seconds()
    except (TypeError, ValueError):
        return ""
    if s < 3600:
        return f"{max(1, round(s / 60))} мин назад"
    if s < 86400:
        return f"{round(s / 3600)} ч назад"
    if s < 86400 * 30:
        return f"{round(s / 86400)} дн назад"
    return t.strftime("%d.%m.%Y")


def _fmt(sec):
    sec = int(max(0, sec or 0))
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class CommentsPanel(QFrame):
    """ctx.shiki — связь с Shikimori; get_state() → (release, episode, секунды)."""

    seek_requested = Signal(int)     # секунды
    closed = Signal()

    def __init__(self, ctx, get_state, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.get_state = get_state
        self.setObjectName("Comments")
        self.setStyleSheet(PANEL_QSS)
        self.mode = "ep"
        self.topic = None
        self.page = 1
        self.for_key = None
        self.items_html = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.ep_btn = QPushButton("Эта серия")
        self.all_btn = QPushButton("Всё аниме")
        for b, m in ((self.ep_btn, "ep"), (self.all_btn, "all")):
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            head.addWidget(b)
        head.addStretch(1)
        close = QPushButton("✕")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.close_panel)
        head.addWidget(close)
        lay.addLayout(head)

        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        lay.addWidget(self.view, 1)
        self.more = QPushButton("Показать ещё")
        self.more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more.clicked.connect(lambda: self.load(more=True))
        self.more.hide()
        lay.addWidget(self.more)

        self.login_hint = QLabel("Чтобы писать комментарии, войдите через Shikimori в «Моей библиотеке».")
        self.login_hint.setWordWrap(True)
        lay.addWidget(self.login_hint)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Комментарий к серии…")
        self.edit.setFixedHeight(80)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        self.moment = QCheckBox("Момент 0:00")
        self.moment.setChecked(True)
        self.spoiler = QCheckBox("Спойлер")
        row.addWidget(self.moment)
        row.addWidget(self.spoiler)
        row.addStretch(1)
        self.send_btn = QPushButton("Отправить")
        self.send_btn.setObjectName("Send")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        self.form = [self.edit, self.moment, self.spoiler, self.send_btn]
        lay.addLayout(row)

    # ------------------------------------------------------------ показ
    def open_panel(self):
        rel, ep, _t = self.get_state()
        if not rel or not ep:
            return
        logged = self.ctx.shiki.logged_in()
        self.login_hint.setVisible(not logged)
        for w in self.form:
            w.setVisible(logged)
        self.ep_btn.setText(f"{fmt_ordinal(ep.get('ordinal'))} серия")
        key = (rel["id"], ep["key"], self.mode)
        if key != self.for_key:
            self.for_key = key
            self.load()
        self.tick()
        self.show()
        self.raise_()

    def close_panel(self):
        self.hide()
        self.closed.emit()

    def episode_changed(self):
        self.for_key = None
        if self.isVisible():
            self.open_panel()

    def tick(self):
        """Обновить подпись «Момент 12:34» (вызывается плеером раз в секунду)."""
        if self.isVisible():
            self.moment.setText(f"Момент {_fmt(self.get_state()[2])}")

    def set_mode(self, mode):
        self.mode = mode
        self.for_key = None
        self.open_panel()

    # ------------------------------------------------------------ загрузка
    def load(self, more=False):
        self.ep_btn.setChecked(self.mode == "ep")
        self.all_btn.setChecked(self.mode == "all")
        rel, ep, _t = self.get_state()
        sid = self.ctx.shiki.sid_of(rel["id"])
        if not sid:
            self._show_msg("Этого тайтла нет на Shikimori — обсуждение недоступно.")
            return
        if more:
            self.page += 1
            self._fetch()
            return
        self.page = 1
        self.items_html = []
        self._show_msg("Загружаем обсуждение…")
        want = self.for_key

        def got_topic(t):
            if want != self.for_key:
                return
            self.topic = t
            if not t:
                self._show_msg("На Shikimori нет темы для обсуждения.")
                return
            if self.mode == "ep" and not t["episode"]:
                self.items_html.append('<p style="color:#9a9aa6">Отдельной темы у этой серии нет — показано общее '
                                       'обсуждение тайтла, ваш комментарий будет подписан номером серии.</p>')
            self._fetch()
        if self.mode == "ep":
            self.ctx.shiki.topic(sid, ep.get("ordinal"), got_topic)
        else:
            self.ctx.shiki.anime_topic(sid, got_topic)

    def _fetch(self):
        want = self.for_key

        def ok(items):
            if want != self.for_key:
                return
            # Shikimori отдаёт на один комментарий больше, если есть следующая страница
            for c in (items or [])[:30]:
                u = c.get("user") or {}
                self.items_html.append(
                    f'<p style="margin:10px 0 2px"><b>{html.escape(u.get("nickname") or "")}</b>'
                    f'&nbsp;&nbsp;<span style="color:#9a9aa6;font-size:12px">{_ago(c.get("created_at"))}</span></p>'
                    f'<div style="margin-bottom:8px">{render_body(c.get("body"))}</div>'
                    '<hr style="border:none;background:#2a2a33;height:1px">')
            if not items and self.page == 1:
                self.items_html.append('<p style="color:#9a9aa6">Пока никто не написал — будьте первым.</p>')
            self.more.setVisible(len(items or []) > 30)
            bar = self.view.verticalScrollBar()
            keep = bar.value() if self.page > 1 else 0
            self.view.setHtml("".join(self.items_html))
            bar.setValue(keep)

        self.ctx.shiki.comments(self.topic["id"], self.page, ok,
                                lambda m: self._show_msg(f"Не удалось загрузить обсуждение: {m}"))

    def _show_msg(self, text):
        self.more.hide()
        self.view.setHtml(f'<p style="color:#9a9aa6">{html.escape(text)}</p>')

    def _link(self, url):
        s = url.toString()
        if s.startswith("t:"):
            self.seek_requested.emit(int(s[2:]))

    # ------------------------------------------------------------ отправка
    def send(self):
        text = self.edit.toPlainText().strip()
        if not text or not self.topic:
            return
        _rel, ep, t = self.get_state()
        tag = [] if self.topic["episode"] else [f"{fmt_ordinal(ep.get('ordinal'))} серия"]
        if self.moment.isChecked():
            tag.append(_fmt(t))
        body = (f"[b]{', '.join(tag)}[/b] " if tag else "") + (f"[spoiler]{text}[/spoiler]" if self.spoiler.isChecked()
                                                                else text)
        self.send_btn.setEnabled(False)

        def ok(_d):
            self.send_btn.setEnabled(True)
            self.edit.clear()
            self.for_key = None
            self.open_panel()

        def fail(msg):
            self.send_btn.setEnabled(True)
            self._show_msg(f"Не удалось отправить: {msg}")
        self.ctx.shiki.post_comment(self.topic["id"], body, ok, fail)
