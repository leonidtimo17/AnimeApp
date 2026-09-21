"""Экран веб-плеера Kodik внутри главного окна.

Сам WebView2 живёт в отдельном процессе (так надёжнее и там есть кодеки H.264),
а его окно встраивается сюда по HWND через QWidget.createWindowContainer.
"""
import json
import os
import sys

from PySide6.QtCore import QProcess, QSize, Qt, Signal
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from .api import release_title
from .icons import icon
from .player import fill_dub_menu, fill_season_menu
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
        bl.addWidget(self.fs_btn)
        lay.addWidget(self.bar)

        self.body = QVBoxLayout()
        self.status = QLabel("Запускаем плеер…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color:#9a9aa6;font-size:15px;")
        self.body.addWidget(self.status, 1)
        lay.addLayout(self.body, 1)

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

    def open(self, release, dub, eps, key, position=None):
        self.stop()
        self.release = release
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
                              "animelib_id": e["animelib_id"]} for e in eps],
                "index": idx, "position": pos,
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
            elif kind == "error":
                self.status.setText(msg.get("message", "Ошибка плеера"))

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
