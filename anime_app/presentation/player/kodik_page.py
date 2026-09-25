"""Экран веб-плеера Kodik внутри главного окна.

Сам WebView2 живёт в отдельном процессе (так надёжнее и там есть кодеки H.264),
а его окно встраивается сюда по HWND через QWidget.createWindowContainer.
"""
import json
import os
import sys

from PySide6.QtCore import QProcess, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ...core.config import PROJECT_DIR
from ...core.logging import get_logger
from ...domain.titles import release_title
from ..icons import icon
from ..theme import TEXT
from .comments_panel import CommentsPanel
from .menus import fill_dub_menu, fill_season_menu
from .watch_ui import PAGE_QSS, EpisodeSide, WatchInfo, enter_fullscreen, exit_fullscreen
from ...core.i18n import service as i18n, t

log = get_logger("kodik")


class KodikPage(QWidget):
    closed = Signal()
    dub_selected = Signal(dict)
    season_selected = Signal(dict)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.proc = None
        self.release = None
        self.container = None
        self.eps = []
        self.ep_key = None
        self._launch = None
        self.pos = 0.0
        self.setObjectName("WatchPage")
        self.setStyleSheet(PAGE_QSS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.bar = QWidget()
        self.bar.setStyleSheet("background:#0f0f12;")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(12, 6, 12, 6)
        back = QPushButton("  " + t("common.back"))
        back.setObjectName("Flat")
        back.setIcon(icon("arrow-left", TEXT, 15))
        back.clicked.connect(self.close_player)
        bl.addWidget(back)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight:700;font-size:15px;")
        bl.addWidget(self.title, 1)
        self.season_btn = QPushButton("  " + t("anime.seasons"))
        self.season_btn.setIcon(icon("layer-group", TEXT, 14))
        self.season_menu = QMenu(self)
        self.season_btn.setMenu(self.season_menu)
        self.season_btn.hide()
        bl.addWidget(self.season_btn)
        self.dub_btn = QPushButton()
        self.dub_btn.setIcon(icon("microphone", TEXT, 14))
        self.dub_btn.setStyleSheet("padding-right: 30px;")
        self.dub_menu = QMenu(self)
        self.dub_btn.setMenu(self.dub_menu)
        bl.addWidget(self.dub_btn)
        self.fs_btn = QPushButton()
        self.fs_btn.setObjectName("Flat")
        self.fs_btn.setIcon(icon("expand", TEXT, 16))
        self.fs_btn.setIconSize(QSize(16, 16))
        self.fs_btn.setToolTip(t("player.fullscreen_key", key="F11"))
        self.fs_btn.clicked.connect(self.toggle_fullscreen)
        self.cm_btn = QPushButton()
        self.cm_btn.setObjectName("Flat")
        self.cm_btn.setIcon(icon("comments", TEXT, 16))
        self.cm_btn.setIconSize(QSize(16, 16))
        self.cm_btn.setToolTip(t("comments.tooltip"))
        self.cm_btn.clicked.connect(self.toggle_comments)
        bl.addWidget(self.cm_btn)
        self.ad_btn = QPushButton("  " + t("player.adblock"))
        self.ad_btn.setObjectName("Flat")
        self.ad_btn.setCheckable(True)
        self.ad_btn.setChecked(ctx.prefs.get("kodik_adblock", True))
        self.ad_btn.setToolTip(t("player.adblock_tip"))
        self.ad_btn.toggled.connect(self._toggle_adblock)
        self._paint_ad_btn()
        bl.addWidget(self.ad_btn)
        bl.addWidget(self.fs_btn)
        lay.addWidget(self.bar)

        # Страница просмотра как на YouTube: слева видео и описание, справа серии (или обсуждение)
        self.row = QHBoxLayout()
        self.row.setSpacing(20)
        self.leftw = QWidget()
        self.left_lay = QVBoxLayout(self.leftw)
        self.left_lay.setContentsMargins(0, 0, 0, 0)
        self.holder = QWidget()      # окно веб-плеера (видео + его панель управления)
        self.holder.setStyleSheet("background:#000;")
        self.holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.body = QVBoxLayout(self.holder)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel(t("player.starting"))
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color:#9a9aa6;font-size:15px;")
        self.body.addWidget(self.status, 1)
        self.left_lay.addWidget(self.holder)
        self.info = WatchInfo(ctx, self.dub_menu, self.season_menu)
        self.info.use_comments_button()
        self.info.fullscreen_clicked.connect(self.toggle_fullscreen)
        self.info.comments_clicked.connect(self.toggle_comments)
        self.left_lay.addWidget(self.info)
        self.left_lay.addStretch(1)
        self.row.addWidget(self.leftw, 1)
        self.side = EpisodeSide(ctx)
        self.side.setFixedWidth(400)
        self.side.picked.connect(self._pick)
        self.row.addWidget(self.side)
        # Обсуждение серии справа, вместо списка серий (поверх окна WebView ничего не нарисовать)
        self.comments = CommentsPanel(ctx, lambda: (self.release, self._episode(), self.pos))
        self.comments.setFixedWidth(400)
        self.comments.seek_requested.connect(self._seek)
        self.comments.closed.connect(self._comments_closed)
        self.comments.hide()
        self.row.addWidget(self.comments)
        lay.addLayout(self.row, 1)

    # ------------------------------------------------------------ запуск
    def set_dubs(self, dubs, current_id):
        fill_dub_menu(self.dub_menu, dubs, current_id, self.dub_selected.emit)
        name = next((d["name"] for d in dubs if d["id"] == current_id), "")
        self.dub_btn.setText("  " + name)
        self.info.dub.setText("  " + name)

    def set_seasons(self, entries):
        fill_season_menu(self.season_menu, entries, self.season_selected.emit)
        self.season_btn.setVisible(bool(entries))
        self.info.set_has_seasons(bool(entries))

    # ------------------------------------------------------------ страница / полный экран
    def _apply_mode(self):
        fs = self.window().isFullScreen()
        self.bar.setVisible(not fs)
        self.info.setVisible(not fs)
        self.side.setVisible(not fs and not self.comments.isVisible())
        if fs:
            self.comments.hide()
        self.row.setContentsMargins(0, 0, 0, 0) if fs else self.row.setContentsMargins(20, 14, 20, 12)
        self._fit()

    def _fit(self):
        if self.window().isFullScreen():
            self.holder.setMinimumHeight(0)
            self.holder.setMaximumHeight(16777215)
            return
        # видео 16:9 плюс панель управления веб-плеера под ним, но чтобы описание помещалось
        w = max(320, self.leftw.width())
        h = int(min(w * 9 / 16 + 72, self.height() - self.bar.height() - self.info.sizeHint().height() - 40))
        self.holder.setFixedHeight(max(240, h))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit)

    def _index(self):
        return next((i for i, e in enumerate(self.eps) if e["key"] == self.ep_key), 0)

    def _show_episode(self):
        if not self.release or not self.eps:
            return
        i = self._index()
        name = self.dub_btn.text().strip()
        self.info.set_episode(self.release, self.eps[i], i, len(self.eps), name)
        self.side.set_current(i)

    def _pick(self, i):
        """Серия из списка справа — команда веб-плееру."""
        if self.proc:
            self.proc.write((json.dumps({"cmd": "episode", "i": i}) + "\n").encode())

    def _comments_closed(self):
        self.info.cm.setChecked(False)
        self.side.setVisible(not self.window().isFullScreen())
        if self.container:
            self.container.setFocus()

    def current_state(self):
        """(ключ серии, позиция мс) по последнему сохранённому прогрессу."""
        if not self.release:
            return None, 0
        last = self.ctx.progress.last(self.release["id"])
        return (last["episode_id"], last["position"]) if last else (None, 0)

    def _episode(self):
        return next((e for e in self.eps if e["key"] == self.ep_key), self.eps[0] if self.eps else None)

    def _paint_ad_btn(self):
        on = self.ad_btn.isChecked()
        self.ad_btn.setIcon(icon("check" if on else "xmark", "#3fbf6a" if on else TEXT, 14))

    def _toggle_adblock(self, on):
        self.ctx.prefs.set("kodik_adblock", on)
        self._paint_ad_btn()
        # Перезапускаем плеер с того же места, чтобы настройка сразу подействовала
        if self.release and self._launch:
            release, dub, eps = self._launch
            last = self.ctx.progress.last(release["id"])
            key = self.ep_key or (last["episode_id"] if last else None)
            pos = last["position"] if last and last["episode_id"] == key else None
            self.open(release, dub, eps, key, position=pos)

    def toggle_comments(self):
        if self.comments.isVisible():
            self.comments.close_panel()
        else:
            self.side.hide()
            self.info.cm.setChecked(True)
            self.comments.open_panel()

    def _seek(self, sec):
        """Перемотать видео в процессе веб-плеера (команда через stdin)."""
        if self.proc:
            self.proc.write((json.dumps({"cmd": "seek", "t": sec}) + "\n").encode())

    def open(self, release, dub, eps, key, position=None):
        self.stop()
        self._launch = (release, dub, eps)
        self.release = release
        self.eps = eps
        self.ep_key = key
        self.dub_btn.setText("  " + dub["name"])
        self.side.set_episodes(release, eps, 0, self.ctx.releases.poster_url(release))
        self._apply_mode()
        self.title.setText(release_title(release))
        self.status.setText(t("player.starting"))
        self.status.show()

        idx, pos = self.ctx.progress.open_at(release["id"], eps, key)
        if position is not None:
            pos = position
        job_dir = os.path.join(self.ctx.data_dir, "webplayer")
        os.makedirs(job_dir, exist_ok=True)
        job_path = os.path.join(job_dir, "job.json")
        with open(job_path, "w", encoding="utf-8") as f:
            json.dump({
                "title": release_title(release), "dub": dub["name"], "team_id": dub["id"].split(":", 1)[1],
                "episodes": [{"key": e["key"], "ordinal": e["ordinal"], "name": e.get("name"),
                              "animelib_id": e.get("animelib_id"), "kodik": e.get("kodik"),
                              "opening": e.get("opening"), "ending": e.get("ending")} for e in eps],
                "index": idx, "position": pos,
                "sid": (release.get("shikimori") or {}).get("id"),
                "autoskip": self.ctx.prefs.get("autoskip_opening", False),
                "adblock": self.ctx.prefs.get("kodik_adblock", True), "lang": i18n().locale,
                "zoom_fill": self.ctx.prefs.get("zoom_fill", False),
                "sleep": self.ctx.sleep.to_job(),
            }, f, ensure_ascii=False)

        proc = QProcess(self)
        self.proc = proc
        proc.setProgram(sys.executable)
        if getattr(sys, "frozen", False):
            proc.setArguments(["--webplayer", job_path])
        else:
            main_py = os.path.join(PROJECT_DIR, "main.py")
            proc.setArguments([main_py, "--webplayer", job_path])
        proc.readyReadStandardOutput.connect(lambda: self._output(proc))
        proc.readyReadStandardError.connect(   # технические подробности плеера — в журнал, не на экран
            lambda: log.info("%s", bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()))
        proc.finished.connect(lambda *_: self._finished(proc))
        proc.start()

    def _output(self, proc):
        while proc.canReadLine():
            line = bytes(proc.readLine()).decode("utf-8", "replace").strip()
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "hwnd" and proc is self.proc:
                self._embed(msg["value"])
            elif kind == "progress" and self.release:
                self.ctx.progress.save_raw(self.release["id"], msg["key"], msg["ordinal"], msg["pos"], msg["dur"])
            elif kind == "fullscreen":
                self.toggle_fullscreen()
            elif kind == "escape":
                if self.window().isFullScreen():
                    self.toggle_fullscreen()
                else:
                    self.close_player()
            elif kind == "time":
                self.pos = msg.get("pos") or 0
            elif kind == "episode":
                self.ep_key = msg.get("key")
                self.comments.episode_changed()
                self._show_episode()
            elif kind == "error":
                log.warning("Плеер Kodik: %s", msg.get("message"))
                self.status.setText(t("player.errors.source"))
            elif kind == "setting" and msg.get("key") in ("zoom_fill",):
                self.ctx.prefs.set(msg["key"], msg.get("value"))
            elif kind == "sleep":
                # Таймер сна, заведённый в плеере Kodik, действует и во встроенном плеере
                self.ctx.sleep.from_job(msg.get("until"), msg.get("min"), msg.get("episode"))

    def _embed(self, hwnd):
        win = QWindow.fromWinId(hwnd)
        self.container = QWidget.createWindowContainer(win, self)
        self.container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.status.hide()
        self.body.addWidget(self.container, 1)
        self.container.setFocus()

    def _finished(self, proc):
        if proc is self.proc:
            self.proc = None
            self.ctx.progress.notify_changed()

    # ------------------------------------------------------------ управление
    def toggle_fullscreen(self):
        win = self.window()
        if win.isFullScreen():
            exit_fullscreen(win)
        else:
            enter_fullscreen(win)   # на весь экран — только видео и его панель (Esc/F — выйти)
        self._apply_mode()
        self.fs_btn.setIcon(icon("compress" if win.isFullScreen() else "expand", TEXT, 16))
        if self.container:
            self.container.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        elif e.key() == Qt.Key.Key_Escape:
            if self.window().isFullScreen():
                self.toggle_fullscreen()
            else:
                self.close_player()
        else:
            super().keyPressEvent(e)

    def close_player(self):
        if self.window().isFullScreen():
            self.toggle_fullscreen()
        self.stop()
        self.closed.emit()

    def stop(self):
        if self.container:
            self.container.setParent(None)
            self.container.deleteLater()
            self.container = None
        if self.proc:
            proc, self.proc = self.proc, None
            proc.kill()
            proc.waitForFinished(2000)
            self.ctx.progress.notify_changed()
