"""Обсуждение серии в плеере: комментарии Shikimori, отметка момента серии, спойлеры."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout,
)

from ...core.formatting import ago, fmt_ordinal, fmt_seconds
from ...domain.shikimori import render_body
from ...infrastructure.http.client import RequestScope
from ..widgets.states import error_text
from ...core.i18n import t

PAGE_SIZE = 30

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
        self.scope = RequestScope()
        # Подпись «Момент 12:34» обновляется раз в секунду — только пока панель видна
        self._moment_timer = QTimer(self, interval=1000)
        self._moment_timer.timeout.connect(self.tick)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.ep_btn = QPushButton(t("comments.this_episode"))
        self.all_btn = QPushButton(t("comments.whole_anime"))
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
        self.more = QPushButton(t("common.show_more"))
        self.more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more.clicked.connect(lambda: self.load(more=True))
        self.more.hide()
        lay.addWidget(self.more)

        self.login_hint = QLabel(t("comments.login_hint"))
        self.login_hint.setWordWrap(True)
        lay.addWidget(self.login_hint)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(t("comments.placeholder"))
        self.edit.setFixedHeight(80)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        self.moment = QCheckBox(t("comments.moment", time="0:00"))
        self.moment.setChecked(True)
        self.spoiler = QCheckBox(t("comments.spoiler"))
        row.addWidget(self.moment)
        row.addWidget(self.spoiler)
        row.addStretch(1)
        self.send_btn = QPushButton(t("comments.send"))
        self.send_btn.setObjectName("Send")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        self.form = [self.edit, self.moment, self.spoiler, self.send_btn]
        lay.addLayout(row)

    # ------------------------------------------------------------ показ
    def showEvent(self, e):
        super().showEvent(e)
        self._moment_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._moment_timer.stop()

    def open_panel(self):
        rel, ep, _t = self.get_state()
        if not rel or not ep:
            return
        logged = self.ctx.shiki.logged_in()
        self.login_hint.setVisible(not logged)
        for w in self.form:
            w.setVisible(logged)
        self.ep_btn.setText(t("player.episode_n", n=fmt_ordinal(ep.get("ordinal"))))
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
        self.scope.cancel()      # обсуждение прошлой серии больше не нужно
        if self.isVisible():
            self.open_panel()

    def tick(self):
        """Обновить подпись «Момент 12:34»."""
        if self.isVisible():
            self.moment.setText(t("comments.moment", time=fmt_seconds(self.get_state()[2])))

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
            self._show_msg(t("comments.not_on_shikimori"))
            return
        if more:
            self.page += 1
            self._fetch()
            return
        self.scope.cancel()
        self.page = 1
        self.items_html = []
        self._show_msg(t("comments.loading"))
        want = self.for_key

        def got_topic(topic):
            if want != self.for_key:
                return
            self.topic = topic
            if not topic:
                self._show_msg(t("comments.no_topic"))
                return
            if self.mode == "ep" and not topic["episode"]:
                self.items_html.append(f'<p style="color:#9a9aa6">{html.escape(t("comments.no_episode_topic"))}</p>')
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
            for c in (items or [])[:PAGE_SIZE]:
                u = c.get("user") or {}
                nick = html.escape(u.get("nickname") or "")
                self.items_html.append(
                    f'<p style="margin:10px 0 2px"><b>{nick}</b>'
                    f'&nbsp;&nbsp;<span style="color:#9a9aa6;font-size:12px">{ago(c.get("created_at"))}</span>'
                    f'&nbsp;&nbsp;<a href="r:{c.get("id")};{nick}" style="color:#9a9aa6;font-size:12px;'
                    f'text-decoration:none">{html.escape(t("comments.reply"))}</a></p>'
                    f'<div style="margin-bottom:8px">{render_body(c.get("body"))}</div>'
                    '<hr style="border:none;background:#2a2a33;height:1px">')
            if not items and self.page == 1:
                self.items_html.append(f'<p style="color:#9a9aa6">{html.escape(t("comments.empty"))}</p>')
            self.more.setVisible(len(items or []) > PAGE_SIZE)
            bar = self.view.verticalScrollBar()
            keep = bar.value() if self.page > 1 else 0
            self.view.setHtml("".join(self.items_html))
            bar.setValue(keep)

        self.ctx.shiki.comments(self.topic["id"], self.page, ok,
                                lambda err: self._show_msg(error_text(err, t("comments.load_failed"))),
                                scope=self.scope)

    def _show_msg(self, text):
        self.more.hide()
        self.view.setHtml(f'<p style="color:#9a9aa6">{html.escape(text)}</p>')

    def _link(self, url):
        s = url.toString()
        if s.startswith("t:"):
            self.seek_requested.emit(int(s[2:]))
        elif s.startswith("r:"):   # ответ цитатой, как на Shikimori
            cid, _, nick = s[2:].partition(";")
            self.edit.setPlainText(f"[comment={cid}]{nick}[/comment], " + self.edit.toPlainText())
            self.edit.setFocus()
            cursor = self.edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.edit.setTextCursor(cursor)

    # ------------------------------------------------------------ отправка
    def send(self):
        text = self.edit.toPlainText().strip()
        if not text or not self.topic:
            return
        _rel, ep, at = self.get_state()
        self.send_btn.setEnabled(False)

        def ok(_d):
            self.send_btn.setEnabled(True)
            self.edit.clear()
            self.for_key = None
            self.open_panel()

        def fail(err):
            self.send_btn.setEnabled(True)
            self._show_msg(error_text(err, t("comments.send_failed")))
        self.ctx.shiki.post_comment(
            self.topic["id"], text,
            # пометка уходит на Shikimori (русскоязычный сайт) — по-русски при любом языке интерфейса
            episode_label=None if self.topic["episode"] else f"{fmt_ordinal(ep.get('ordinal'))} серия",
            moment=fmt_seconds(at) if self.moment.isChecked() else None,
            spoiler=self.spoiler.isChecked(), on_ok=ok, on_err=fail)
