"""Экран веб-плеера Kodik внутри главного окна.

Сам WebView2 живёт в отдельном процессе (так надёжнее и там есть кодеки H.264),
а его окно встраивается сюда по HWND через QWidget.createWindowContainer.
"""
import json
import os
import sys
import time

from PySide6.QtCore import QProcess, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from .api import release_title
from .comments_panel import CommentsPanel
from .icons import icon
from .player import SLEEP, fill_dub_menu, fill_season_menu
from .sources import resume_target
from .theme import TEXT


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
        self.pos = 0.0
        self.setStyleSheet("background:#000;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.bar = QWidget()
        self.bar.setStyleSheet("background:#0f0f12;")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(12, 6, 12, 6)
        back = QPushButton("  Назад")
        back.setObjectName("Flat")
        back.setIcon(icon("arrow-left", TEXT, 15))
        back.clicked.connect(self.close_player)
        bl.addWidget(back)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight:700;font-size:15px;")
        bl.addWidget(self.title, 1)
        self.season_btn = QPushButton("  Сезоны и фильмы")
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
        self.fs_btn.setToolTip("Полный экран (F11)")
        self.fs_btn.clicked.connect(self.toggle_fullscreen)
        self.cm_btn = QPushButton()
        self.cm_btn.setObjectName("Flat")
        self.cm_btn.setIcon(icon("comments", TEXT, 16))
        self.cm_btn.setIconSize(QSize(16, 16))
        self.cm_btn.setToolTip("Обсуждение серии на Shikimori")
        self.cm_btn.clicked.connect(self.toggle_comments)
        bl.addWidget(self.cm_btn)
        bl.addWidget(self.fs_btn)
        lay.addWidget(self.bar)

        self.body = QVBoxLayout()
        self.status = QLabel("Запускаем плеер…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color:#9a9aa6;font-size:15px;")
        self.body.addWidget(self.status, 1)
        row = QHBoxLayout()
        row.setSpacing(0)
        row.addLayout(self.body, 1)
        # Обсуждение серии справа от видео (поверх окна WebView ничего не нарисовать)
        self.comments = CommentsPanel(ctx, lambda: (self.release, self._episode(), self.pos))
        self.comments.setFixedWidth(400)
        self.comments.seek_requested.connect(self._seek)
        self.comments.closed.connect(lambda: self.container and self.container.setFocus())
        self.comments.hide()
        row.addWidget(self.comments)
        lay.addLayout(row, 1)
        self.tick = QTimer(self, interval=1000)
        self.tick.timeout.connect(self.comments.tick)
        self.tick.start()

    # ------------------------------------------------------------ запуск
    def set_dubs(self, dubs, current_id):
        fill_dub_menu(self.dub_menu, dubs, current_id, self.dub_selected.emit)
        name = next((d["name"] for d in dubs if d["id"] == current_id), "")
        self.dub_btn.setText("  " + name)

    def set_seasons(self, entries):
        fill_season_menu(self.season_menu, entries, self.season_selected.emit)
        self.season_btn.setVisible(bool(entries))

    def current_state(self):
        """(ключ серии, позиция мс) по последнему сохранённому прогрессу."""
        if not self.release:
            return None, 0
        last = self.ctx.db.last_progress(self.release["id"])
        return (last["episode_id"], last["position"]) if last else (None, 0)

    def _episode(self):
        return next((e for e in self.eps if e["key"] == self.ep_key), self.eps[0] if self.eps else None)

    def toggle_comments(self):
        if self.comments.isVisible():
            self.comments.close_panel()
        else:
            self.comments.open_panel()

    def _seek(self, sec):
        """Перемотать видео в процессе веб-плеера (команда через stdin)."""
        if self.proc:
            self.proc.write((json.dumps({"cmd": "seek", "t": sec}) + "\n").encode())

    def open(self, release, dub, eps, key, position=None):
        self.stop()
        self.release = release
        self.eps = eps
        self.ep_key = key
        self.title.setText(release_title(release))
        self.status.setText("Запускаем плеер…")
        self.status.show()

        progress = self.ctx.db.progress_for(release["id"])
        if key:
            idx = next((i for i, e in enumerate(eps) if e["key"] == key), 0)
            prog = progress.get(eps[idx]["key"]) or {}
            pos = 0 if prog.get("watched") else prog.get("position", 0)
        else:
            idx, pos = resume_target(release["id"], eps, self.ctx.db)
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
                "autoskip": self.ctx.db.setting("autoskip_opening", False),
                "zoom_fill": self.ctx.db.setting("zoom_fill", False),
                "sleep": {"until": SLEEP["until"] * 1000 if SLEEP["until"] > time.time() else 0,
                          "min": SLEEP["min"], "episode": SLEEP["episode"]},
            }, f, ensure_ascii=False)

        proc = QProcess(self)
        self.proc = proc
        proc.setProgram(sys.executable)
        if getattr(sys, "frozen", False):
            proc.setArguments(["--webplayer", job_path])
        else:
            main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
            proc.setArguments([main_py, "--webplayer", job_path])
        proc.readyReadStandardOutput.connect(lambda: self._output(proc))
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
                self.ctx.db.save_progress(self.release["id"], msg["key"], msg["ordinal"], msg["pos"], msg["dur"])
            elif kind == "time":
                self.pos = msg.get("pos") or 0
            elif kind == "episode":
                self.ep_key = msg.get("key")
                self.comments.episode_changed()
            elif kind == "error":
                self.status.setText(msg.get("message", "Ошибка плеера"))
            elif kind == "setting" and msg.get("key") in ("zoom_fill",):
                self.ctx.db.set_setting(msg["key"], msg.get("value"))
            elif kind == "sleep":
                # Таймер сна, заведённый в плеере Kodik, действует и во встроенном плеере
                SLEEP.update(until=(msg.get("until") or 0) / 1000, min=msg.get("min") or 0,
                             episode=bool(msg.get("episode")))

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
            self.ctx.library_changed.emit()

    # ------------------------------------------------------------ управление
    def toggle_fullscreen(self):
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
            self.bar.show()
        else:
            win.showFullScreen()
        self.fs_btn.setIcon(icon("compress" if win.isFullScreen() else "expand", TEXT, 16))

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
            self.ctx.library_changed.emit()
