"""Встроенный видеоплеер (HLS/mp4) с фишками в стиле Кинопоиска.

- продолжение с места остановки;
- «Пропустить заставку» по таймкодам из API (и автопропуск), разметка от AniSkip, если источник её не дал;
- «Следующая серия» с обратным отсчётом на титрах;
- выбор качества без потери позиции, скорость, громкость;
- список серий внутри плеера, полноэкранный режим и «картинка в картинке»;
- горячие клавиши, автоскрытие интерфейса, всплывающие подсказки;
- таймер сна, скорость 2x пока зажата кнопка мыши, масштаб «весь кадр / заполнить экран».

Состав: окно (раскладка и события) + QualityPolicy (какое качество включить) + PlaybackWatchdog
(переподключение при обрыве) + SeekBar/VideoView (виджеты). Скорость интернета плеер не меряет —
берёт единственный замер при запуске приложения из NetworkService.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea,
    QSlider, QVBoxLayout, QWidget,
)

from ...core.formatting import fmt_ms, fmt_ordinal
from ...domain.episodes import progress_fraction, start_position
from ...domain.quality import QualityPolicy
from ...domain.titles import episode_label, release_title
from ..icons import icon as fa_icon
from ..theme import ACCENT
from ..widgets.thumbs import LazyThumbs
from .comments_panel import CommentsPanel
from .menus import OVERLAY_QSS, fill_dub_menu, fill_season_menu, fill_sleep_menu
from .seekbar import SeekBar
from .video_view import VideoView
from .watch_ui import PAGE_QSS, EpisodeSide, WatchInfo
from .watchdog import PlaybackWatchdog

SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
NEXT_COUNTDOWN = 10
HIDE_DELAY_MS = 5000
HOLD_MS = 450            # удержание кнопки мыши на видео — скорость 2x
SAVE_MS = 5000           # прогресс сохраняется каждые 5 с (пока видео играет)
THUMB_W, THUMB_H = 128, 72

I_PLAY, I_PAUSE, I_PREV, I_NEXT = "play", "pause", "backward-step", "forward-step"
I_VOL1, I_VOL3, I_MUTE = "volume-low", "volume-high", "volume-xmark"
I_FULL, I_UNFULL, I_LIST, I_SETTINGS, I_BACK, I_PIP = (
    "expand", "compress", "list-ul", "gear", "arrow-left", "window-restore")
I_BACK10, I_FWD10, I_SKIP = "rotate-left", "rotate-right", "forward"
ICON_SIZE = 18


class PlayerWindow(QWidget):
    """Плеер — экран внутри главного окна (в «картинке в картинке» — маленькое окно поверх всех)."""

    progress_saved = Signal()
    closed = Signal()             # пользователь закрыл плеер
    pip_toggled = Signal(bool)    # главное окно забирает/возвращает виджет
    fs_toggled = Signal(bool)     # то же для полного экрана
    dub_selected = Signal(dict)   # сменить озвучку (с той же серии и места)
    season_selected = Signal(dict)  # открыть другой сезон/фильм

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.prefs = ctx.prefs
        self.sleep = ctx.sleep
        self.setMinimumSize(320, 180)
        self.setObjectName("WatchPage")
        self.setStyleSheet(OVERLAY_QSS + PAGE_QSS)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.release = None
        self._new_source_loading = False
        self.current_dub = None
        self.dub_name = ""
        self.episodes = []
        self.index = 0
        self.pending_seek = None
        # "auto" — качество по скорости интернета (замер при запуске приложения); "1080"/"720"/"480" — выбор
        self.quality = QualityPolicy(self.prefs.get("quality_mode", "auto"),
                                     lambda: ctx.network.state.bandwidth_mbps)
        self.autoskip = self.prefs.get("autoskip_opening", False)
        self.autonext = self.prefs.get("autoplay_next", True)
        self.opening_skipped = False
        self.next_cancelled = False
        self.countdown = 0
        self.pip = False
        self.fs = False          # полный экран: только видео (иначе — страница просмотра как на YouTube)
        self.drag_origin = None
        self._last_mouse = None
        self._skip_asked = set()   # серии, для которых уже спрашивали AniSkip

        # --- медиа
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self.prefs.get("volume", 0.8))
        self.audio.setMuted(self.prefs.get("muted", False))
        self.player.setAudioOutput(self.audio)
        self.view = VideoView(self)
        self.view.set_fill(self.prefs.get("zoom_fill", False))
        self.player.setVideoOutput(self.view.item)
        self._build_page()

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)

        self.hide_timer = QTimer(self, singleShot=True, interval=HIDE_DELAY_MS)
        self.hide_timer.timeout.connect(self._hide_controls)
        self.osd_timer = QTimer(self, singleShot=True, interval=1100)
        self.osd_timer.timeout.connect(self.osd.hide)
        self.save_timer = QTimer(self, interval=SAVE_MS)          # запускается, только пока видео играет
        self.save_timer.timeout.connect(self.save_progress)
        self.count_timer = QTimer(self, interval=1000)
        self.count_timer.timeout.connect(self._tick_countdown)
        self.click_timer = QTimer(self, singleShot=True, interval=230)
        self.click_timer.timeout.connect(self.toggle_play)
        # Удержание кнопки мыши на видео — 2x, пока держите
        self.hold_timer = QTimer(self, singleShot=True, interval=HOLD_MS)
        self.hold_timer.timeout.connect(self._hold_start)
        self._hold_rate = None
        # Таймер сна: тикает, только когда заведён
        self.sleep_timer = QTimer(self, interval=1000)
        self.sleep_timer.timeout.connect(self._sleep_tick)
        self._unsubscribe_sleep = self.sleep.subscribe(self._sleep_changed)
        self._sleep_changed()

        # Восстановление после обрыва сети (смена Wi-Fi, включение/выключение VPN)
        self.watchdog = PlaybackWatchdog(self.player.position, self)
        self.watchdog.frozen.connect(self._recover)
        ctx.network.connection_changed.connect(self._network_changed)

        # Реальное разрешение потоков (подписи вида «480p» у источников бывают неточными)
        self.view.item.nativeSizeChanged.connect(self._on_native_size)
        self.view.viewport().installEventFilter(self)
        self._update_mute_icon()

    # ================================================================ UI
    def _build_page(self):
        # Страница просмотра: слева видео, под ним название, кнопки, описание и обсуждение; справа — серии
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.left = QWidget()
        self.left.setObjectName("WatchPage")
        self.left_lay = QVBoxLayout(self.left)
        self.left_lay.setSpacing(4)
        self.left_lay.addWidget(self.view)
        # Левая колонка прокручивается, как страница YouTube: видео, под ним описание и обсуждение
        self.left_scroll = QScrollArea()
        self.left_scroll.setObjectName("WatchPage")
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setWidget(self.left)
        root.addWidget(self.left_scroll, 1)

        self._build_overlay()

        self.info = WatchInfo(self.ctx, self.dub_menu, self.season_menu)
        self.info.fullscreen_clicked.connect(self.toggle_fullscreen)
        self.left_lay.addWidget(self.info)
        self.side = EpisodeSide(self.ctx)
        self.side.setObjectName("WatchPage")
        self.side.setFixedWidth(400)
        self.side.picked.connect(lambda i: self.play_index(i, None))
        root.addWidget(self.side)

    def _btn(self, text, tip, slot, parent_layout, icon=True):
        b = QPushButton()
        if icon:
            b.setObjectName("Icon")
            b.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self._set_icon(b, text)
        else:
            b.setText(text)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        parent_layout.addWidget(b)
        return b

    @staticmethod
    def _set_icon(button, name):
        button.setIcon(fa_icon(name, "white", ICON_SIZE))

    def _build_overlay(self):
        # Верхняя панель
        self.top = QFrame(self.view)
        self.top.setObjectName("TopBar")
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(18, 12, 18, 30)
        self._btn(I_BACK, "Назад (Esc)", self.close_player, tl)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_lbl = QLabel()
        self.title_lbl.setObjectName("Title")
        self.sub_lbl = QLabel()
        self.sub_lbl.setObjectName("Sub")
        titles.addWidget(self.title_lbl)
        titles.addWidget(self.sub_lbl)
        tl.addLayout(titles, 1)
        self._btn("comments", "Обсуждение серии на Shikimori (C)", self.toggle_comments, tl)

        # Нижняя панель
        self.bottom = QFrame(self.view)
        self.bottom.setObjectName("BottomBar")
        bl = QVBoxLayout(self.bottom)
        bl.setContentsMargins(18, 36, 18, 10)
        bl.setSpacing(2)
        self.seek = SeekBar(self.view)
        self.seek.setParent(self.bottom)
        self.seek.tip.setParent(self.view)
        self.seek.seek_requested.connect(self.seek_to)
        bl.addWidget(self.seek)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.play_btn = self._btn(I_PLAY, "Пауза / воспроизведение (Пробел)", self.toggle_play, row)
        self._btn(I_BACK10, "Назад на 10 секунд (←)", lambda: self.skip(-10_000), row)
        self._btn(I_FWD10, "Вперёд на 10 секунд (→)", lambda: self.skip(10_000), row)
        self.prev_btn = self._btn(I_PREV, "Предыдущая серия (P)", self.prev_episode, row)
        self.next_btn = self._btn(I_NEXT, "Следующая серия (N)", self.next_episode, row)
        self.mute_btn = self._btn(I_VOL3, "Звук (M)", self.toggle_mute, row)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setObjectName("Volume")
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(100)
        self.volume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume.setValue(int(self.audio.volume() * 100))
        self.volume.valueChanged.connect(self._set_volume)
        row.addWidget(self.volume)
        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setObjectName("Time")
        row.addSpacing(10)
        row.addWidget(self.time_lbl)
        row.addStretch(1)
        self.season_btn = self._btn("layer-group", "Сезоны и фильмы", lambda: None, row)
        self.season_menu = QMenu(self)
        self.season_btn.setMenu(self.season_menu)
        self.season_btn.hide()
        self.dub_btn = self._btn("", "Озвучка", lambda: None, row, icon=False)
        self.dub_btn.setIcon(fa_icon("microphone", "white", 15))
        self.dub_menu = QMenu(self)
        self.dub_btn.setMenu(self.dub_menu)
        self.speed_btn = self._btn("1x", "Скорость воспроизведения", lambda: None, row, icon=False)
        self.speed_btn.setMenu(self._speed_menu())
        self.quality_btn = self._btn("HD", "Качество", lambda: None, row, icon=False)
        self.quality_menu = QMenu(self)
        self.quality_menu.aboutToShow.connect(self._fill_quality_menu)   # меню собирается при открытии
        self.quality_btn.setMenu(self.quality_menu)
        self.sleep_btn = self._btn("moon", "Таймер сна", lambda: None, row)
        self.sleep_menu = QMenu(self)
        self.sleep_menu.aboutToShow.connect(
            lambda: fill_sleep_menu(self.sleep_menu, self.sleep, lambda t: self.show_osd(t, 1800)))
        self.sleep_btn.setMenu(self.sleep_menu)
        self.settings_btn = self._btn(I_SETTINGS, "Настройки", lambda: None, row)
        self.settings_btn.setMenu(self._settings_menu())
        self._btn(I_LIST, "Список серий (E)", self.toggle_episodes, row)
        self.pip_btn = self._btn(I_PIP, "Мини-плеер поверх окон (I)", self.toggle_pip, row)
        self.fs_btn = self._btn(I_FULL, "Полный экран (F / двойной клик)", self.toggle_fullscreen, row)
        bl.addLayout(row)

        # Кнопки «Пропустить заставку» / «Следующая серия»
        self.skip_btn = QPushButton("Пропустить заставку  ", self.view)
        self.skip_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.skip_btn.setIcon(fa_icon(I_SKIP, "white", 14))
        self.skip_btn.setObjectName("Pill")
        self.skip_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.clicked.connect(self.skip_opening)
        self.skip_btn.hide()

        self.next_box = QFrame(self.view)
        nl = QHBoxLayout(self.next_box)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(10)
        self.stay_btn = QPushButton("Смотреть титры")
        self.stay_btn.setObjectName("Pill")
        self.stay_btn.clicked.connect(self._cancel_next)
        self.go_next_btn = QPushButton("Следующая серия")
        self.go_next_btn.setIcon(fa_icon(I_NEXT, "white", 14))
        self.go_next_btn.setObjectName("PillAccent")
        self.go_next_btn.clicked.connect(self.next_episode)
        for b in (self.stay_btn, self.go_next_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            nl.addWidget(b)
        self.next_box.hide()

        # Список серий
        self.ep_list = QListWidget(self.view)
        self.ep_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ep_list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.ep_list.setSpacing(2)
        self.ep_list.itemClicked.connect(lambda it: self.play_index(it.data(Qt.ItemDataRole.UserRole)))
        self.ep_thumbs = LazyThumbs(self.ep_list, self.ctx.images, THUMB_W, THUMB_H, 6)
        self.ep_list.hide()

        # Обсуждение серии (комментарии Shikimori)
        self.comments = CommentsPanel(self.ctx, lambda: (self.release, self.current_episode(),
                                                          self.player.position() / 1000), self.view)
        self.comments.seek_requested.connect(
            lambda s: (self.seek_to(s * 1000), self.show_osd(f"Перемотка на {fmt_ms(s * 1000)}")))
        self.comments.closed.connect(lambda: (self._layout_overlay(), self.setFocus()))
        self.comments.hide()

        # Экранные подсказки
        self.osd = QLabel(self.view)
        self.osd.setObjectName("Osd")
        self.osd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.osd.hide()
        self.loading = QLabel("Загрузка…", self.view)
        self.loading.setObjectName("Osd")
        self.loading.hide()

    def set_dubs(self, dubs, current_id):
        fill_dub_menu(self.dub_menu, dubs, current_id, self.dub_selected.emit)
        name = next((d["name"] for d in dubs if d["id"] == current_id), self.dub_name)
        self.dub_btn.setText(" " + name)
        self.info.dub.setText("  " + name)

    def set_seasons(self, entries):
        fill_season_menu(self.season_menu, entries, self.season_selected.emit)
        self.season_btn.setVisible(bool(entries))
        self.info.set_has_seasons(bool(entries))

    def current_state(self):
        """(ключ серии, позиция мс) — чтобы продолжить с того же места в другой озвучке."""
        ep = self.current_episode()
        return (ep["key"] if ep else None), self.player.position()

    def _speed_menu(self):
        menu = QMenu(self)
        self.speed_actions = []
        for s in SPEEDS:
            act = menu.addAction(f"{s:g}x" + ("  (обычная)" if s == 1 else ""), lambda s=s: self.set_speed(s))
            act.setCheckable(True)
            act.setChecked(s == 1.0)
            self.speed_actions.append((s, act))
        return menu

    def _settings_menu(self):
        menu = QMenu(self)
        a1 = menu.addAction("Автопропуск заставки")
        a1.setCheckable(True)
        a1.setChecked(self.autoskip)
        a1.toggled.connect(lambda v: (setattr(self, "autoskip", v), self.prefs.set("autoskip_opening", v)))
        a2 = menu.addAction("Автовоспроизведение следующей серии")
        a2.setCheckable(True)
        a2.setChecked(self.autonext)
        a2.toggled.connect(lambda v: (setattr(self, "autonext", v), self.prefs.set("autoplay_next", v)))
        self.fill_action = menu.addAction("Заполнить экран, без чёрных полос (Z)")
        self.fill_action.setCheckable(True)
        self.fill_action.setChecked(self.view.fill)
        self.fill_action.triggered.connect(lambda _v: self.toggle_fill())
        menu.addSeparator()
        menu.addAction("Горячие клавиши…", self._show_hotkeys)
        return menu

    def _fill_quality_menu(self):
        menu = self.quality_menu
        menu.clear()
        ep = self.current_episode()
        state = self.ctx.network.state
        speed = f" · {state.bandwidth_mbps:.0f} Мбит/с" if state.bandwidth_mbps else ""
        eff = self.quality.effective(ep)
        auto_on = self.quality.mode == "auto"
        now = f" · сейчас {self.quality.height(self.dub_name, eff)}p" if eff and auto_on else ""
        auto = menu.addAction(f"Авто — по скорости интернета{now}{speed}", lambda: self.set_quality("auto"))
        auto.setCheckable(True)
        auto.setChecked(auto_on)
        menu.addSeparator()
        # Только те качества, что есть у этой серии; подпись — по реальному разрешению
        for key in self.quality.available(ep):
            text = self.quality.label(self.dub_name, key) + ("  · рекомендовано" if key == self.quality.recommended else "")
            act = menu.addAction(text, lambda k=key: self.set_quality(k))
            act.setCheckable(True)
            act.setEnabled(bool(ep) and key not in self.quality.bad)
            act.setChecked(not auto_on and key == eff)
        menu.addSeparator()
        check = menu.addAction("Проверяем скорость…" if state.measuring else "Проверить скорость интернета",
                               self.check_speed)
        check.setEnabled(bool(ep) and not state.measuring)

    def _layout_overlay(self):
        w, h = self.view.width(), self.view.height()
        compact = w < 640
        self.top.setGeometry(0, 0, w, self.top.sizeHint().height())
        bh = self.bottom.sizeHint().height()
        self.bottom.setGeometry(0, h - bh, w, bh)
        for widget in (self.speed_btn, self.quality_btn, self.settings_btn, self.volume,
                       self.prev_btn, self.dub_btn, self.sleep_btn):
            widget.setVisible(not compact)
        panel_w = min(360, int(w * 0.4))
        self.ep_list.setGeometry(w - panel_w, 0, panel_w, h)
        comments_w = min(430, int(w * 0.45))
        overlay_comments = self.comments.parent() is self.view
        if overlay_comments:
            self.comments.setGeometry(w - comments_w, 0, comments_w, h)
        margin_bottom = bh + 16 if self.bottom.isVisible() else 40
        side = max(panel_w if self.ep_list.isVisible() else 0,
                   comments_w if overlay_comments and self.comments.isVisible() else 0)
        right = w - side - 32
        self.skip_btn.adjustSize()
        self.skip_btn.move(right - self.skip_btn.width(), h - self.skip_btn.height() - margin_bottom)
        self.next_box.adjustSize()
        self.next_box.move(right - self.next_box.width(), h - self.next_box.height() - margin_bottom)
        self.osd.adjustSize()
        self.osd.move((w - self.osd.width()) // 2, (h - self.osd.height()) // 2)
        self.loading.adjustSize()
        self.loading.move((w - self.loading.width()) // 2, (h - self.loading.height()) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, lambda: (self._fit_video(), self._layout_overlay()))

    # ============================================================ страница / полный экран
    def _video_only(self):
        return self.fs or self.pip

    def _apply_mode(self):
        """Страница просмотра или только видео (полный экран, мини-плеер)."""
        only = self._video_only()
        self.info.setVisible(not only)
        self.side.setVisible(not only)
        self.left_lay.setContentsMargins(0, 0, 0, 0) if only else self.left_lay.setContentsMargins(20, 16, 20, 0)
        self.layout().setContentsMargins(0, 0, 0 if only else 20, 0)
        self.layout().itemAt(1).widget().setContentsMargins(0, 0 if only else 16, 0, 0)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if only
                                                    else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if only:
            # обсуждение — по кнопке поверх видео
            if self.comments.parent() is not self.view:
                self.left_lay.removeWidget(self.comments)
                self.comments.setParent(self.view)
                self.comments.setMinimumHeight(0)
                self.comments.setMaximumHeight(16777215)
                self.comments.hide()
            self.view.setMinimumHeight(0)
            self.view.setMaximumHeight(16777215)
            self.left_scroll.verticalScrollBar().setValue(0)
        else:
            # обсуждение — под видео, как комментарии на YouTube
            if self.comments.parent() is self.view:
                self.comments.setParent(self.left)
                self.left_lay.addWidget(self.comments)
            self.comments.setFixedHeight(620)
            if self.release:
                self.comments.open_panel()
        self._set_icon(self.fs_btn, I_UNFULL if self.fs else I_FULL)
        self._fit_video()
        QTimer.singleShot(0, self._layout_overlay)

    def _fit_video(self):
        """На странице видео 16:9 по ширине колонки, но так, чтобы под ним оставалось место для кнопок."""
        if self._video_only():
            return
        w = max(320, self.left_scroll.viewport().width() - 40)
        h = int(min(w * 9 / 16, self.height() - 150))
        self.view.setFixedHeight(max(200, h))

    # ============================================================ загрузка
    def open(self, release, episodes, dub_name, episode_key=None, position=None):
        """Открыть серии выбранной озвучки. Без episode_key — продолжить с последнего места."""
        self.save_progress()
        self.release = release
        self.dub_name = dub_name
        self.episodes = [e for e in episodes if e.get("streams")]
        if not self.episodes:
            return False
        idx, pos = self.ctx.progress.open_at(release["id"], self.episodes, episode_key)
        self._fill_episode_list()
        self.side.set_episodes(release, self.episodes, idx, self.ctx.releases.poster_url(release))
        self._apply_mode()
        self.play_index(idx, pos if position is None else position, save=False)
        self.ctx.library.mark_watching(release["id"])
        self.setFocus()
        return True

    def _fill_episode_list(self):
        self.ep_list.clear()
        progress = self.ctx.progress.for_anime(self.release["id"])
        poster = self.ctx.releases.poster_url(self.release)
        for i, ep in enumerate(self.episodes):
            prog = progress.get(ep["key"]) or {}
            item = QListWidgetItem(episode_label(ep).replace(" — ", "\n", 1))
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setSizeHint(QSize(0, THUMB_H + 12))
            self.ep_list.addItem(item)
            self.ep_thumbs.set_row(item, ep.get("preview") or poster, fmt_ordinal(ep.get("ordinal")),
                                   not ep.get("preview"), progress_fraction(prog), bool(prog.get("watched")))
        self.ep_list.setCurrentRow(self.index)

    def current_episode(self):
        return self.episodes[self.index] if 0 <= self.index < len(self.episodes) else None

    def _cur_pos(self):
        """Текущая позиция; пока поток перезагружается — та, куда собираемся перемотать."""
        return self.pending_seek or self.player.position()

    def _qlabel(self, q, short=False):
        return self.quality.label(self.dub_name, q, short)

    def _on_native_size(self, size):
        q = self.quality.effective(self.current_episode())
        if self.quality.seen_height(self.dub_name, q, int(size.height())):
            self._update_quality_ui()

    def _update_quality_ui(self):
        q = self.quality.effective(self.current_episode())
        if q:
            self.quality_btn.setText(("Авто · " if self.quality.mode == "auto" else "") + self._qlabel(q, short=True))

    def play_index(self, idx, position=0, save=True):
        if not 0 <= idx < len(self.episodes):
            return
        if save:
            self.save_progress()
            self.progress_saved.emit()
        if position is None:
            position = start_position(self.ctx.progress.for_anime(self.release["id"]).get(self.episodes[idx]["key"]))
        self.index = idx
        self.quality.new_episode()
        ep = self.current_episode()
        self.opening_skipped = False
        self.next_cancelled = False
        self.countdown = 0
        self.count_timer.stop()
        self.next_box.hide()
        self.skip_btn.hide()
        self.ep_list.setCurrentRow(idx)
        self.title_lbl.setText(release_title(self.release))
        self.sub_lbl.setText(episode_label(ep) + f"  ·  {idx + 1} из {len(self.episodes)}  ·  {self.dub_name}")
        self.setWindowTitle(f"{release_title(self.release)} — {fmt_ordinal(ep.get('ordinal'))} серия")
        self.prev_btn.setEnabled(idx > 0)
        self.next_btn.setEnabled(idx < len(self.episodes) - 1)
        self._update_marks()
        self.info.set_episode(self.release, ep, idx, len(self.episodes), self.dub_name)
        if self.side.release is self.release:
            self.side.set_current(idx)
        self.comments.episode_changed()
        self._load_source(position)
        if position and position > 15_000:
            self.show_osd(f"Продолжаем с {fmt_ms(position)}", 2200)

    def _load_source(self, position):
        ep = self.current_episode()
        if not ep:
            return
        q = self.quality.choose(ep)
        if not q:
            return
        self._update_quality_ui()
        self.pending_seek = position if position and position > 3000 else None
        self._new_source_loading = False  # перемотку применяем только к новому потоку (см. _on_status)
        url = QUrl(ep["streams"][q])
        if self.player.source() == url:
            self.player.setSource(QUrl())  # та же ссылка — Qt не перезагрузит поток без сброса
        self.player.setSource(url)
        self.player.play()
        self.loading.show()
        self._layout_overlay()

    def check_speed(self):
        """Проверка скорости по кнопке: замер на этом же видео, потом — подходящее качество."""
        ep = self.current_episode()
        if not ep:
            return
        url = ep["streams"].get(self.quality.available(ep)[0])
        self.show_osd("Проверяем скорость интернета…", 3500)

        def done(state):
            self.quality.bandwidth_updated()
            if state.bandwidth_mbps is None:
                self.show_osd("Не удалось измерить скорость", 2500)
                return
            rec = self.quality.choose(self.current_episode())
            self.show_osd(f"Интернет ~{state.bandwidth_mbps:.0f} Мбит/с → {self._qlabel(rec)} (рекомендовано)", 3000)
            if self.quality.mode == "auto" and rec:
                self._load_source(self._cur_pos())
        self.ctx.network.measure_now(lambda cb: cb(url), done)

    def _update_marks(self):
        ep = self.current_episode() or {}
        marks = []
        for key in ("opening", "ending"):
            r = ep.get(key) or {}
            if r.get("start") is not None and r.get("stop"):
                marks.append((int(r["start"] * 1000), int(r["stop"] * 1000)))
        self.seek.marks = marks

    # ============================================================ playback
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.show_osd("Пауза")
            self.save_progress()
        else:
            self.player.play()
            self.show_osd("Воспроизведение", 700)
        self.poke()

    def skip(self, delta):
        self.seek_to(self.player.position() + delta)
        self.show_osd(("+" if delta > 0 else "−") + f"{abs(delta) // 1000} с")

    def seek_to(self, ms):
        dur = self.player.duration()
        ms = max(0, min(ms, dur - 500 if dur else ms))
        self.player.setPosition(int(ms))
        self.next_cancelled = False
        self.poke()

    def set_speed(self, s):
        self.player.setPlaybackRate(s)
        self.speed_btn.setText(f"{s:g}x")
        for sp, act in self.speed_actions:
            act.setChecked(sp == s)
        self.show_osd(f"Скорость {s:g}x")

    def change_speed(self, direction):
        cur = self.player.playbackRate()
        idx = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - cur))
        self.set_speed(SPEEDS[max(0, min(len(SPEEDS) - 1, idx + direction))])

    def set_quality(self, q):
        self.quality.set_mode(q)
        self.prefs.set("quality_mode", q)
        pos = self._cur_pos()
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self._load_source(pos)
        if not was_playing:
            self.player.pause()
        eff = self.quality.effective(self.current_episode())
        if eff:
            self.show_osd(("Авто: " if q == "auto" else "Качество ") + self._qlabel(eff))

    def _set_volume(self, v):
        self.audio.setVolume(v / 100)
        if v and self.audio.isMuted():
            self.audio.setMuted(False)
        self._update_mute_icon()
        self.prefs.set("volume", v / 100)

    def change_volume(self, delta):
        self.volume.setValue(max(0, min(100, self.volume.value() + delta)))
        self.show_osd(f"Громкость {self.volume.value()}%")

    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())
        self.prefs.set("muted", self.audio.isMuted())
        self._update_mute_icon()
        self.show_osd("Звук выключен" if self.audio.isMuted() else "Звук включён")

    def _update_mute_icon(self):
        v = self.volume.value()
        self._set_icon(self.mute_btn, I_MUTE if self.audio.isMuted() or v == 0 else (I_VOL1 if v < 50 else I_VOL3))

    def next_episode(self):
        if self.index < len(self.episodes) - 1:
            self.play_index(self.index + 1, None)

    def prev_episode(self):
        if self.index > 0:
            self.play_index(self.index - 1, None)

    def skip_opening(self):
        ep = self.current_episode() or {}
        stop = (ep.get("opening") or {}).get("stop")
        if stop:
            self.opening_skipped = True
            self.player.setPosition(int(stop * 1000))
            self.skip_btn.hide()
            self.show_osd("Заставка пропущена")

    def _cancel_next(self):
        self.next_cancelled = True
        self.count_timer.stop()
        self.next_box.hide()

    def _tick_countdown(self):
        self.countdown -= 1
        if self.countdown <= 0:
            self.count_timer.stop()
            self.next_episode()
            return
        self.go_next_btn.setText(f"Следующая серия через {self.countdown}")
        self.next_box.adjustSize()
        self._layout_overlay()

    # ============================================================ signals
    def _on_duration(self, d):
        self.seek.setRange(0, max(0, d))
        ep = self.current_episode()
        sid = ((self.release or {}).get("shikimori") or {}).get("id")
        if not ep or d < 60_000 or not sid:
            return
        have_op = (ep.get("opening") or {}).get("stop")
        have_ed = (ep.get("ending") or {}).get("start")
        key = (self.release["id"], self.dub_name, ep["key"])
        if (have_op and have_ed) or key in self._skip_asked:
            return
        self._skip_asked.add(key)

        def got(res, ep=ep):
            if not res:
                return
            if not (ep.get("opening") or {}).get("stop") and res.get("opening"):
                ep["opening"] = res["opening"]
            if not (ep.get("ending") or {}).get("start") and res.get("ending"):
                ep["ending"] = res["ending"]
            if ep is self.current_episode():
                self._update_marks()
        self.ctx.sources.skip_times(sid, ep.get("ordinal"), d / 1000, got)

    def _on_position(self, pos):
        if not self.seek.dragging:
            self.seek.blockSignals(True)
            self.seek.setValue(pos)
            self.seek.blockSignals(False)
        dur = self.player.duration()
        self.time_lbl.setText(f"{fmt_ms(pos)} / {fmt_ms(dur)}")
        ep = self.current_episode() or {}

        # Заставка
        op = ep.get("opening") or {}
        in_opening = (op.get("stop") and op.get("start") is not None
                      and op["start"] * 1000 <= pos < op["stop"] * 1000 - 1500)
        if in_opening and self.autoskip and not self.opening_skipped:
            self.skip_opening()
            in_opening = False
        if bool(in_opening) != self.skip_btn.isVisible():
            self.skip_btn.setVisible(bool(in_opening))
            self._layout_overlay()

        # Титры → следующая серия
        has_next = self.index < len(self.episodes) - 1
        end = ep.get("ending") or {}
        if end.get("start"):
            in_credits = pos >= end["start"] * 1000
        else:
            in_credits = dur > 300_000 and dur - pos <= 45_000
        show_next = has_next and in_credits and not self.next_cancelled and dur > 0 and not self.sleep.after_episode
        if show_next and not self.next_box.isVisible():
            self.next_box.show()
            if self.autonext:
                self.countdown = NEXT_COUNTDOWN
                self.go_next_btn.setText(f"Следующая серия через {self.countdown}")
                self.count_timer.start()
            else:
                self.go_next_btn.setText("Следующая серия")
            self._layout_overlay()
        elif not show_next and self.next_box.isVisible():
            self.next_box.hide()
            self.count_timer.stop()

    def _on_status(self, status):
        S = QMediaPlayer.MediaStatus
        if status in (S.LoadingMedia, S.BufferingMedia, S.StalledMedia):
            self.loading.show()
            self._layout_overlay()
            if status == S.StalledMedia and self.player.position() > 5000:
                self._on_stall()
        else:
            self.loading.hide()
        if status == S.LoadingMedia:
            self._new_source_loading = True
        # Сразу после смены источника Qt присылает запоздалый «LoadedMedia» от старого потока —
        # перемотку тратим только когда новый поток действительно начал загружаться.
        if status in (S.LoadedMedia, S.BufferedMedia) and self.pending_seek and self._new_source_loading:
            pos, self.pending_seek = self.pending_seek, None
            self.player.setPosition(int(pos))
        if status == S.EndOfMedia:
            self.save_progress(force_end=True)
            if self.sleep.episode_ended():
                self.show_osd("Таймер сна — серия закончилась. Спокойной ночи!", 4000)
            elif self.autonext and self.index < len(self.episodes) - 1 and not self.next_cancelled:
                self.next_episode()
            elif self.index == len(self.episodes) - 1:
                self._maybe_complete()
                self.show_osd("Это была последняя серия", 3000)

    def _on_stall(self):
        """В «Авто»: если видео часто подгружается — понижаем качество (без замеров скорости)."""
        lower = self.quality.stalled(self.current_episode(), time.time())
        if lower:
            self.show_osd(f"Медленный интернет — переключили на {self._qlabel(lower)}", 2500)
            self._load_source(self._cur_pos())

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._set_icon(self.play_btn, I_PAUSE if playing else I_PLAY)
        self._set_icon(self.fs_btn, I_UNFULL if self.fs else I_FULL)
        # Таймеры работают, только пока видео играет
        self.watchdog.playing(playing)
        if playing:
            self.save_timer.start()
        else:
            self.save_timer.stop()
        # Состояние меняется и само — при перезагрузке потока (смена качества, восстановление сети).
        # Панель показываем только на паузе, а при воспроизведении лишь перезапускаем таймер скрытия.
        if playing:
            if self.bottom.isVisible():
                self.hide_timer.start()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._show_controls()
            self.hide_timer.stop()

    # ============================================================ сеть
    def _network_changed(self):
        """ОС сообщила о смене сети: снимаем потолок качества и быстрее проверяем, идёт ли видео.
        Скорость заново не меряем."""
        self.quality.network_changed()
        if self.current_episode():
            self.watchdog.hurry()

    def _recover(self):
        """Переподключиться к потоку с того же места; со второй попытки — со свежими ссылками."""
        self.watchdog.tries += 1
        self.watchdog.reset()
        tries = self.watchdog.tries
        pos = self.pending_seek or self.player.position()
        self.ctx.reset_connections()
        if tries > 3:
            self.show_osd("Нет соединения — пробуем снова… Проверьте интернет или VPN", 4000)
        else:
            self.show_osd("Связь прервалась — переподключаемся…", 2500)
        if tries >= 2:
            self._refresh_streams(pos)
        else:
            self._load_source(pos)

    def _refresh_streams(self, pos):
        """Заново получить ссылки на серии (после смены сети/VPN старые могут не работать)."""
        old, dub = self.release, self.current_dub
        ep = self.current_episode()
        if not old or not dub or not ep:
            self._load_source(pos)
            return
        key = ep["key"]

        def ok(fresh):
            if self.release is not old:          # пользователь уже открыл другое
                return
            new = fresh if fresh.get("id") == old["id"] else old
            self.release = new
            self.ctx.sources.invalidate(new["id"])

            def with_eps(eps):
                eps = [e for e in eps if e.get("streams")]
                if self.release is not new:
                    return
                if eps:
                    self.episodes = eps
                    self.index = next((i for i, e in enumerate(eps) if e["key"] == key), self.index)
                    self.quality.new_episode()
                self._load_source(pos)

            self.ctx.sources.episodes(new, dub, with_eps, lambda _e: self._load_source(pos))

        self.ctx.releases.load(old["id"], ok, lambda _e: self._load_source(pos), fresh=True)

    def _on_error(self, err, text):
        # Обрыв сети посреди просмотра — переподключаемся к тому же качеству, а не понижаем его.
        E = QMediaPlayer.Error
        playing_before = (self.player.position() > 3000 or (self.pending_seek or 0) > 3000
                          or self.watchdog.tries > 0)
        if err == E.NetworkError or (err == E.ResourceError and playing_before):
            QTimer.singleShot(2000, self._recover)
            return
        failed, lower = self.quality.failed(self.current_episode())
        if lower:
            self.show_osd(f"Нет {self._qlabel(failed)}, переключаемся на {self._qlabel(lower)}", 2500)
            self._load_source(self.pending_seek or self.player.position())
        else:
            self.loading.hide()
            self.show_osd(f"Не удалось воспроизвести: {text}", 5000)

    # ============================================================ progress
    def save_progress(self, force_end=False):
        ep = self.current_episode()
        if not ep or not self.release:
            return
        dur = self.player.duration()
        pos = dur if force_end else self.player.position()
        if dur <= 0 or pos < 5000:
            return
        end_start = (ep.get("ending") or {}).get("start")
        _watched, newly = self.ctx.progress.save(self.release["id"], ep, pos, dur,
                                                 end_start * 1000 if end_start else None)
        if newly:
            item = self.ep_list.item(self.index)
            if item:
                self.ep_thumbs.redraw(item, frac=1.0, watched=True)
            if self.index == len(self.episodes) - 1:
                self._maybe_complete()
            # Страницы под плеером обновляем только когда серия досмотрена, а не каждые 5 с.
            self.progress_saved.emit()

    def _maybe_complete(self):
        rel = self.release
        if rel.get("is_ongoing"):
            return
        progress = self.ctx.progress.for_anime(rel["id"])
        if all((progress.get(e["key"]) or {}).get("watched") for e in self.episodes):
            if self.ctx.library.entry(rel["id"]).get("status") != "completed":
                self.ctx.library.set_status(rel["id"], "completed")
                self.show_osd("Тайтл просмотрен полностью 🎉", 3000)

    # ============================================================ controls visibility
    def show_osd(self, text, ms=1100):
        self.osd.setText(text)
        self.osd.show()
        self.osd.raise_()
        self._layout_overlay()
        self.osd_timer.start(ms)

    def poke(self):
        self._show_controls()
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.hide_timer.start()

    def _show_controls(self):
        if not self.bottom.isVisible():
            self.top.show()
            self.bottom.show()
            self._layout_overlay()
        self.view.viewport().unsetCursor()

    def _hide_controls(self):
        over_controls = any(w.isVisible() and w.geometry().contains(self.view.mapFromGlobal(QCursor.pos()))
                            for w in (self.bottom, self.top))   # над списком серий и обсуждением — прячем
        if over_controls or any(m.isVisible() for m in self.findChildren(QMenu)):
            self.hide_timer.start()
            return
        self.top.hide()
        self.bottom.hide()
        self.seek.tip.hide()
        self._layout_overlay()
        self.view.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def toggle_fill(self):
        fill = not self.view.fill
        self.view.set_fill(fill)
        self.prefs.set("zoom_fill", fill)
        self.fill_action.setChecked(fill)
        self.show_osd("Заполнить экран" if fill else "Весь кадр")

    def toggle_comments(self):
        if self.comments.isVisible():
            self.comments.close_panel()
            return
        if self.comments.parent() is self.view:
            self.ep_list.hide()
        self.comments.open_panel()
        self._layout_overlay()

    # ============================================================ таймер сна
    def _sleep_changed(self):
        on = self.sleep.active
        self.sleep_btn.setIcon(fa_icon("moon", ACCENT if on else "white", ICON_SIZE))
        if self.sleep.until:
            self.sleep_timer.start()
        else:
            self.sleep_timer.stop()

    def _sleep_tick(self):
        if self.sleep.due() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.save_progress()
            self.show_osd("Таймер сна — видео остановлено. Спокойной ночи!", 4000)

    def _hold_start(self):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState or self.pip:
            return
        self._hold_rate = self.player.playbackRate()
        self.player.setPlaybackRate(2.0)
        self.show_osd("▶▶  Скорость 2x — пока держите кнопку мыши", 60_000)

    def _hold_end(self):
        """True, если отпустили после ускорения (тогда клик не считается паузой)."""
        self.hold_timer.stop()
        if self._hold_rate is None:
            return False
        self.player.setPlaybackRate(self._hold_rate)
        self._hold_rate = None
        self.osd.hide()
        return True

    def toggle_episodes(self):
        self.ep_list.setVisible(not self.ep_list.isVisible())
        if self.ep_list.isVisible():
            self.ep_list.raise_()
            self.ep_list.scrollToItem(self.ep_list.currentItem())
        self._layout_overlay()

    # ============================================================ window modes
    def toggle_fullscreen(self):
        """Полный экран — отдельное окно поверх всех. Само окно приложения не меняем:
        Windows разворачивает его в два шага, и этот промежуточный кадр видно как мигание."""
        if self.pip:
            self.toggle_pip()
        self.fs = not self.fs
        if self.fs:
            screen = QGuiApplication.screenAt(self.window().geometry().center()) or QGuiApplication.primaryScreen()
            self.fs_toggled.emit(True)      # главное окно отдаёт виджет плеера
            self.setParent(None)
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint)
            self.setGeometry(screen.geometry())
            self._apply_mode()
            self.show()
            self.raise_()
            self.activateWindow()
        else:
            self.fs_toggled.emit(False)     # виджет возвращается в окно приложения
            self._apply_mode()
        self.setFocus()
        self.poke()

    def toggle_pip(self):
        if not self.pip:
            if self.fs:
                self.toggle_fullscreen()
            screen = QGuiApplication.screenAt(self.window().geometry().center()) or QGuiApplication.primaryScreen()
            self.pip = True
            self.pip_toggled.emit(True)     # главное окно убирает плеер из своих экранов
            self.setParent(None)
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
            area = screen.availableGeometry()
            w, h = 480, 270
            self.setGeometry(area.right() - w - 24, area.bottom() - h - 24, w, h)
            self._apply_mode()
            self.show()
            self.show_osd("Мини-плеер · I — вернуть")
        else:
            self.pip = False
            self.pip_toggled.emit(False)    # главное окно встраивает плеер обратно
            self._apply_mode()
        self.setFocus()

    def close_player(self):
        """Закрыть плеер и вернуться туда, откуда пришли."""
        if self.fs and not self.pip:
            self.fs = False
            self.fs_toggled.emit(False)
        self.fs = False
        self._apply_mode()
        self.stop()
        if self.pip:
            self.pip = False
            self.hide()
        self.closed.emit()

    def stop(self):
        self.save_progress()
        self.player.stop()
        self.player.setSource(QUrl())
        self.count_timer.stop()
        self.next_box.hide()
        self.progress_saved.emit()

    def _show_hotkeys(self):
        self.show_osd(
            "Пробел/K — пауза   ←/→ — 10 с   ↑/↓ — громкость\n"
            "F — полный экран   M — звук   N/P — серии   S — пропустить заставку\n"
            "[ / ] — скорость   E — серии   C — обсуждение   I — мини-плеер   Z — заполнить экран   0–9 — перейти в %\n"
            "Зажать кнопку мыши на видео — скорость 2x",
            6000,
        )

    # ============================================================ events
    def eventFilter(self, obj, e):
        t = e.type()
        if t == e.Type.MouseMove:
            if self.pip and self.drag_origin is not None and e.buttons() & Qt.MouseButton.LeftButton:
                delta = e.globalPosition().toPoint() - self.drag_origin[0]
                if delta.manhattanLength() > 4:
                    self.drag_origin = (self.drag_origin[0], self.drag_origin[1], True)
                    self.move(self.drag_origin[1] + delta)
                    self.hold_timer.stop()
            # Когда панель прячется, Qt присылает «движение мыши» без движения (виджеты под курсором сменились) —
            # от него панель снова всплывала. Показываем её только если курсор правда сдвинулся.
            p = e.globalPosition().toPoint()
            if self._last_mouse is None or (p - self._last_mouse).manhattanLength() > 3:
                self._last_mouse = p
                self.poke()
        elif t == e.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
            if self.ep_list.isVisible():
                self.ep_list.hide()
                return True
            self.drag_origin = (e.globalPosition().toPoint(), self.pos(), False)
            self.hold_timer.start()
        elif t == e.Type.MouseButtonRelease and e.button() == Qt.MouseButton.LeftButton:
            moved = self.drag_origin and self.drag_origin[2]
            self.drag_origin = None
            if self._hold_end():
                return True
            if not moved:
                self.click_timer.start()
            return True
        elif t == e.Type.MouseButtonDblClick:
            self.click_timer.stop()
            self.toggle_fullscreen()
            return True
        elif t == e.Type.Wheel:
            if not self._video_only():
                # на странице колесо над видео прокручивает страницу (как на YouTube), громкость — ↑/↓
                QApplication.sendEvent(self.left_scroll.verticalScrollBar(), e)
                return True
            self.change_volume(5 if e.angleDelta().y() > 0 else -5)
            return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):
        k = e.key()
        K = Qt.Key
        if k in (K.Key_Space, K.Key_K, K.Key_MediaPlay, K.Key_MediaTogglePlayPause):
            self.toggle_play()
        elif k in (K.Key_Right, K.Key_L):
            self.skip(30_000 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 10_000)
        elif k in (K.Key_Left, K.Key_J):
            self.skip(-30_000 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else -10_000)
        elif k == K.Key_Up:
            self.change_volume(5)
        elif k == K.Key_Down:
            self.change_volume(-5)
        elif k == K.Key_F:
            self.toggle_fullscreen()
        elif k == K.Key_M:
            self.toggle_mute()
        elif k in (K.Key_N, K.Key_MediaNext):
            self.next_episode()
        elif k in (K.Key_P, K.Key_MediaPrevious):
            self.prev_episode()
        elif k == K.Key_S:
            self.skip_opening()
        elif k == K.Key_E:
            self.toggle_episodes()
        elif k == K.Key_I:
            self.toggle_pip()
        elif k == K.Key_Z:
            self.toggle_fill()
        elif k == K.Key_C:
            self.toggle_comments()
        elif k == K.Key_BracketRight:
            self.change_speed(1)
        elif k == K.Key_BracketLeft:
            self.change_speed(-1)
        elif K.Key_0 <= k <= K.Key_9 and self.player.duration():
            self.seek_to(self.player.duration() * (k - K.Key_0) // 10)
        elif k == K.Key_Escape:
            if self.comments.isVisible() and self.comments.parent() is self.view:
                self.comments.close_panel()
            elif self.ep_list.isVisible():
                self.ep_list.hide()
            elif self.fs and not self.pip:
                self.toggle_fullscreen()
            elif self.pip:
                self.toggle_pip()
            else:
                self.close_player()
        else:
            super().keyPressEvent(e)
            return
        self.poke()

    def closeEvent(self, e):
        # Закрытие окна мини-плеера (Alt+F4) — то же, что «Назад».
        if self.pip:
            e.ignore()
            self.close_player()
            return
        super().closeEvent(e)
