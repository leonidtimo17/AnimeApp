"""Нативный видеоплеер с фишками в стиле Кинопоиска.

- продолжение с места остановки;
- «Пропустить заставку» по таймкодам из API (и автопропуск);
- «Следующая серия» с обратным отсчётом на титрах;
- выбор качества без потери позиции, скорость, громкость;
- список серий внутри плеера, полноэкранный режим и «картинка в картинке»;
- горячие клавиши, автоскрытие интерфейса, всплывающие подсказки.
"""
from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from .api import episode_label, fmt_ordinal, release_title
from .bandwidth import BandwidthProbe, recommend
from .sources import resume_target
from .icons import icon as fa_icon
from .theme import ACCENT

QUALITIES = [("1080", "1080p"), ("720", "720p"), ("480", "480p")]
SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
NEXT_COUNTDOWN = 10
HIDE_DELAY_MS = 2800
I_PLAY, I_PAUSE, I_PREV, I_NEXT = "play", "pause", "backward-step", "forward-step"
I_VOL1, I_VOL3, I_MUTE = "volume-low", "volume-high", "volume-xmark"
I_FULL, I_UNFULL, I_LIST, I_SETTINGS, I_BACK, I_PIP = (
    "expand", "compress", "list-ul", "gear", "arrow-left", "window-restore")
I_BACK10, I_FWD10, I_SKIP = "rotate-left", "rotate-right", "forward"
ICON_SIZE = 18

OVERLAY_QSS = f"""
QWidget {{ color: white; font-family: "Segoe UI"; }}
QFrame#TopBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(0,0,0,190), stop:1 rgba(0,0,0,0)); }}
QFrame#BottomBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(0,0,0,0), stop:1 rgba(0,0,0,215)); }}
QPushButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px 10px;
               font-size: 17px; font-weight: 600; min-width: 26px; }}
QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
QPushButton#Icon {{ padding: 9px 11px; }}
QPushButton#Pill {{ background: rgba(20,20,24,0.88); border: 1px solid rgba(255,255,255,0.25);
                    border-radius: 12px; padding: 12px 22px; font-size: 15px; }}
QPushButton#Pill:hover {{ background: rgba(255,255,255,0.95); color: black; }}
QPushButton#PillAccent {{ background: {ACCENT}; border-radius: 12px; padding: 12px 22px; font-size: 15px; }}
QPushButton#PillAccent:hover {{ background: #ff8340; }}
QLabel#Title {{ font-size: 19px; font-weight: 700; }}
QLabel#Sub {{ font-size: 14px; color: rgba(255,255,255,0.75); }}
QLabel#Time {{ font-size: 14px; font-weight: 600; }}
QLabel#Osd {{ background: rgba(0,0,0,0.65); border-radius: 14px; padding: 14px 24px;
              font-size: 20px; font-weight: 700; }}
QSlider#Volume::groove:horizontal {{ height: 4px; background: rgba(255,255,255,0.3); border-radius: 2px; }}
QSlider#Volume::sub-page:horizontal {{ background: white; border-radius: 2px; }}
QSlider#Volume::handle:horizontal {{ background: white; width: 12px; margin: -4px 0; border-radius: 6px; }}
QListWidget {{ background: rgba(16,16,20,0.94); border: none; border-left: 1px solid rgba(255,255,255,0.1);
               font-size: 14px; padding: 8px; outline: none; }}
QListWidget::item {{ padding: 11px 12px; border-radius: 8px; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.08); }}
QListWidget::item:selected {{ background: rgba(255,106,26,0.25); color: white; }}
QMenu {{ background: #1c1c22; border: 1px solid #333; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; color: white; }}
QMenu::item:selected {{ background: #2c2c35; }}
QMenu::item:checked {{ color: {ACCENT}; }}
"""


def fill_dub_menu(menu, dubs, current_id, on_pick):
    """Меню озвучек: встроенный плеер / Kodik-озвучка / Kodik-субтитры."""
    menu.clear()
    groups = [
        ("Встроенный плеер", [d for d in dubs if d["native"]]),
        ("Плеер Kodik — озвучка", [d for d in dubs if not d["native"] and d["kind"] == "voice"]),
        ("Плеер Kodik — субтитры", [d for d in dubs if not d["native"] and d["kind"] == "sub"]),
    ]
    for title, items in groups:
        if not items:
            continue
        head = menu.addAction(f"{title}  ({len(items)})")
        head.setEnabled(False)
        for d in items:
            act = menu.addAction(d["name"], lambda d=d: on_pick(d))
            act.setCheckable(True)
            act.setChecked(d["id"] == current_id)
        menu.addSeparator()
    if not dubs:
        menu.addAction("Ищем озвучки…").setEnabled(False)


def fill_season_menu(menu, entries, on_pick):
    menu.clear()
    for e in entries:
        text = f"{e['label']} · {e.get('year') or 'анонс'} — {e.get('name') or ''}"
        act = menu.addAction(text, lambda e=e: on_pick(e))
        act.setCheckable(True)
        act.setChecked(bool(e.get("current")))
    if not entries:
        menu.addAction("Других сезонов и фильмов нет").setEnabled(False)


def fmt_ms(ms):
    s = max(0, int(ms // 1000))
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class SeekBar(QSlider):
    """Полоса перемотки: клик в любое место, превью времени, отметки опенинга/эндинга."""

    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMouseTracking(True)
        self.setFixedHeight(26)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.marks = []           # [(start_ms, stop_ms)]
        self.hover_x = None
        self.dragging = False
        self.buffer = 0.0
        self.tip = QLabel(parent)
        self.tip.setStyleSheet("background:rgba(0,0,0,0.8);border-radius:6px;padding:3px 8px;font-weight:600;")
        self.tip.hide()

    def _value_at(self, x):
        w = max(1, self.width())
        return int(self.maximum() * min(max(x, 0), w) / w)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.setValue(self._value_at(e.position().x()))
            e.accept()

    def mouseMoveEvent(self, e):
        self.hover_x = e.position().x()
        if self.dragging:
            self.setValue(self._value_at(self.hover_x))
        self._show_tip()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.seek_requested.emit(self._value_at(e.position().x()))

    def leaveEvent(self, e):
        self.hover_x = None
        self.tip.hide()
        self.update()

    def _show_tip(self):
        if self.hover_x is None or self.maximum() <= 0:
            return
        ms = self._value_at(self.hover_x)
        text = fmt_ms(ms)
        for a, b in self.marks:
            if a <= ms <= b:
                text += "  · заставка" if a < self.maximum() / 2 else "  · титры"
        self.tip.setText(text)
        self.tip.adjustSize()
        p = self.mapTo(self.tip.parentWidget(), QPointF(self.hover_x, 0).toPoint())
        self.tip.move(int(p.x() - self.tip.width() / 2), p.y() - self.tip.height() - 6)
        self.tip.show()
        self.tip.raise_()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        hover = self.hover_x is not None or self.dragging
        bar_h = 6 if hover else 4
        y = (h - bar_h) / 2
        mx = max(1, self.maximum())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(QRectF(0, y, w, bar_h), 2, 2)
        if self.buffer > 0:
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawRoundedRect(QRectF(0, y, w * self.buffer, bar_h), 2, 2)
        for a, b in self.marks:
            p.setBrush(QColor(255, 210, 120, 120))
            p.drawRect(QRectF(w * a / mx, y, max(2, w * (b - a) / mx), bar_h))
        if self.hover_x is not None:
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawRoundedRect(QRectF(0, y, self.hover_x, bar_h), 2, 2)
        played = w * self.value() / mx
        p.setBrush(QColor(ACCENT))
        p.drawRoundedRect(QRectF(0, y, played, bar_h), 2, 2)
        if hover:
            p.setBrush(QColor("white"))
            p.drawEllipse(QPointF(played, h / 2), 7, 7)
        p.end()


class VideoView(QGraphicsView):
    """Видео через QGraphicsVideoItem — поверх него можно рисовать свой интерфейс."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.item = QGraphicsVideoItem()
        self.item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.scene_.addItem(self.item)
        self.setBackgroundBrush(QColor("black"))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h = self.viewport().width(), self.viewport().height()
        self.scene_.setSceneRect(0, 0, w, h)
        self.item.setSize(QSizeF(w, h))
        self.item.setPos(0, 0)
        self.fitInView(QRectF(0, 0, w, h))


class PlayerWindow(QWidget):
    """Плеер — экран внутри главного окна (в «картинке в картинке» — маленькое окно поверх всех)."""

    progress_saved = Signal()
    closed = Signal()             # пользователь закрыл плеер
    pip_toggled = Signal(bool)    # главное окно забирает/возвращает виджет
    dub_selected = Signal(dict)   # сменить озвучку (с той же серии и места)
    season_selected = Signal(dict)  # открыть другой сезон/фильм

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.db = ctx.db
        self.setMinimumSize(320, 180)
        self.setStyleSheet(OVERLAY_QSS)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.release = None
        self._bad_q = set()
        self.dub_name = ""
        self.episodes = []
        self.index = 0
        self.pending_seek = None
        # "auto" — качество по скорости интернета; "1080"/"720"/"480" — выбор пользователя.
        self.quality = self.db.setting("quality_mode", "auto")
        self.recommended = recommend(BandwidthProbe.cached())
        self.probe = BandwidthProbe(self)
        self._probing = False
        self._stalls = []
        self.autoskip = self.db.setting("autoskip_opening", False)
        self.autonext = self.db.setting("autoplay_next", True)
        self.opening_skipped = False
        self.next_cancelled = False
        self.countdown = 0
        self.pip = False
        self.normal_geometry = None
        self.drag_origin = None

        # --- медиа
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self.db.setting("volume", 0.8))
        self.audio.setMuted(self.db.setting("muted", False))
        self.player.setAudioOutput(self.audio)
        self.view = VideoView(self)
        self.player.setVideoOutput(self.view.item)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.view)

        self._build_overlay()

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)

        self.hide_timer = QTimer(self, singleShot=True, interval=HIDE_DELAY_MS)
        self.hide_timer.timeout.connect(self._hide_controls)
        self.osd_timer = QTimer(self, singleShot=True, interval=1100)
        self.osd_timer.timeout.connect(self.osd.hide)
        self.save_timer = QTimer(self, interval=5000)
        self.save_timer.timeout.connect(self.save_progress)
        self.save_timer.start()
        self.count_timer = QTimer(self, interval=1000)
        self.count_timer.timeout.connect(self._tick_countdown)
        self.click_timer = QTimer(self, singleShot=True, interval=230)
        self.click_timer.timeout.connect(self.toggle_play)

        self.view.viewport().installEventFilter(self)
        self._update_mute_icon()

    # ================================================================ UI
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
        self.ep_list.itemClicked.connect(lambda it: self.play_index(it.data(Qt.ItemDataRole.UserRole)))
        self.ep_list.hide()

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

    def set_seasons(self, entries):
        fill_season_menu(self.season_menu, entries, self.season_selected.emit)
        self.season_btn.setVisible(bool(entries))

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
        a1.toggled.connect(lambda v: (setattr(self, "autoskip", v), self.db.set_setting("autoskip_opening", v)))
        a2 = menu.addAction("Автовоспроизведение следующей серии")
        a2.setCheckable(True)
        a2.setChecked(self.autonext)
        a2.toggled.connect(lambda v: (setattr(self, "autonext", v), self.db.set_setting("autoplay_next", v)))
        menu.addSeparator()
        menu.addAction("Горячие клавиши…", self._show_hotkeys)
        return menu

    def _quality_menu(self):
        menu = QMenu(self)
        ep = self.current_episode()
        mbps = BandwidthProbe.cached()
        speed = f" · {mbps:.0f} Мбит/с" if mbps else ""
        auto = menu.addAction(f"Авто — по скорости интернета{speed}", lambda: self.set_quality("auto"))
        auto.setCheckable(True)
        auto.setChecked(self.quality == "auto")
        menu.addSeparator()
        for key, name in QUALITIES:
            text = name + ("  · рекомендовано" if key == self.recommended else "")
            act = menu.addAction(text, lambda k=key: self.set_quality(k))
            act.setCheckable(True)
            act.setEnabled(bool(ep and ep["streams"].get(key)))
            act.setChecked(self.quality != "auto" and key == self._effective_quality())
        self.quality_btn.setMenu(menu)

    def _layout_overlay(self):
        w, h = self.view.width(), self.view.height()
        compact = w < 640
        self.top.setGeometry(0, 0, w, self.top.sizeHint().height())
        bh = self.bottom.sizeHint().height()
        self.bottom.setGeometry(0, h - bh, w, bh)
        for widget in (self.speed_btn, self.quality_btn, self.settings_btn, self.volume,
                       self.prev_btn, self.dub_btn):
            widget.setVisible(not compact)
        panel_w = min(360, int(w * 0.4))
        self.ep_list.setGeometry(w - panel_w, 0, panel_w, h)
        margin_bottom = bh + 16 if self.bottom.isVisible() else 40
        right = w - (panel_w if self.ep_list.isVisible() else 0) - 32
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
        QTimer.singleShot(0, self._layout_overlay)

    # ============================================================ loading
    def open(self, release, episodes, dub_name, episode_key=None, position=None):
        """Открыть серии выбранной озвучки. Без episode_key — продолжить с последнего места."""
        self.save_progress()
        self.release = release
        self.dub_name = dub_name
        self.episodes = [e for e in episodes if e.get("streams")]
        if not self.episodes:
            return False
        if episode_key:
            idx = next((i for i, e in enumerate(self.episodes) if e["key"] == episode_key), 0)
            prog = self.db.progress_for(release["id"]).get(self.episodes[idx]["key"])
            pos = 0 if not prog or prog["watched"] else prog["position"]
        else:
            idx, pos = resume_target(release["id"], self.episodes, self.db)
        self._fill_episode_list()
        self.play_index(idx, pos if position is None else position, save=False)
        self._mark_watching()
        self.setFocus()
        return True

    def _mark_watching(self):
        entry = self.db.library_entry(self.release["id"])
        if entry.get("status") in (None, "planned", "postponed"):
            self.db.set_status(self.release["id"], "watching")
            self.ctx.library_changed.emit()

    def _fill_episode_list(self):
        self.ep_list.clear()
        progress = self.db.progress_for(self.release["id"])
        for i, ep in enumerate(self.episodes):
            prog = progress.get(ep["key"])
            item = QListWidgetItem(self._ep_icon(bool(prog and prog["watched"])), episode_label(ep))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.ep_list.addItem(item)
        self.ep_list.setCurrentRow(self.index)

    @staticmethod
    def _ep_icon(watched):
        if watched:
            return fa_icon("circle-check", "#3fbf6a", 16)
        return fa_icon("circle-play", "#8a8a96", 16, regular=True)

    def current_episode(self):
        return self.episodes[self.index] if 0 <= self.index < len(self.episodes) else None

    def _effective_quality(self):
        ep = self.current_episode() or {}
        order = [q for q, _ in QUALITIES]
        pref = self.recommended if self.quality == "auto" else self.quality
        start = order.index(pref) if pref in order else 1
        for q in order[start:] + order[:start][::-1]:
            if ep.get("streams", {}).get(q) and q not in self._bad_q:
                return q
        return None

    def play_index(self, idx, position=0, save=True):
        if not 0 <= idx < len(self.episodes):
            return
        if save:
            self.save_progress()
            self.progress_saved.emit()
        if position is None:
            prog = self.db.progress_for(self.release["id"]).get(self.episodes[idx]["key"])
            position = 0 if not prog or prog["watched"] else prog["position"]
        self.index = idx
        self._bad_q = set()
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
        self._load_source(position)
        if position and position > 15_000:
            self.show_osd(f"Продолжаем с {fmt_ms(position)}", 2200)

    def _load_source(self, position):
        ep = self.current_episode()
        if not ep:
            return
        if self.quality == "auto" and BandwidthProbe.cached() is None:
            # Первый запуск: сначала меряем скорость на кусочке этого же видео.
            self._probe_then_load(ep, position)
            return
        if self.quality == "auto":
            self.recommended = recommend(BandwidthProbe.cached(), tuple(ep["streams"]))
        q = self._effective_quality()
        if not q:
            return
        label = {"1080": "FHD", "720": "HD", "480": "SD"}[q]
        self.quality_btn.setText(("Авто · " + label) if self.quality == "auto" else label)
        self._quality_menu()
        self.pending_seek = position if position and position > 3000 else None
        self.player.setSource(QUrl(self.current_episode()["streams"][q]))
        self.player.play()
        self.loading.show()
        self._layout_overlay()

    def _probe_then_load(self, ep, position):
        if self._probing:
            return
        self._probing = True
        self.player.stop()
        self.loading.setText("Проверяем скорость интернета…")
        self.loading.show()
        self._layout_overlay()
        streams = ep["streams"]
        url = streams.get("720") or streams.get("480") or next(iter(streams.values()))

        def done(mbps):
            self._probing = False
            self.loading.setText("Загрузка…")
            if self.current_episode() is not ep:
                return
            self.recommended = recommend(mbps, tuple(ep["streams"]))
            if mbps is None:
                BandwidthProbe._last = (__import__("time").time(), 5.0)  # не мерить снова каждую серию
            self._load_source(position)
            if mbps:
                self.show_osd(f"Интернет ~{mbps:.0f} Мбит/с → {self.recommended}p (рекомендовано)", 2500)

        self.probe.measure(url, done)

    def _on_stall(self):
        """В «Авто»: если видео часто подгружается — понижаем качество."""
        if self.quality != "auto" or self._probing:
            return
        now = __import__("time").time()
        self._stalls = [t for t in self._stalls if now - t < 60] + [now]
        order = [q for q, _ in QUALITIES]
        q = self._effective_quality()
        if len(self._stalls) >= 3 and q and order.index(q) < len(order) - 1:
            ep = self.current_episode() or {}
            lower = next((x for x in order[order.index(q) + 1:] if ep.get("streams", {}).get(x)), None)
            if lower:
                self._stalls = []
                self.recommended = lower
                self.show_osd(f"Медленный интернет — переключили на {lower}p", 2500)
                self._load_source(self.player.position())

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
        self.quality = q
        self.db.set_setting("quality_mode", q)
        pos = self.player.position()
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self._load_source(pos)
        if not was_playing:
            self.player.pause()
        eff = self._effective_quality()
        if eff:
            self.show_osd(("Авто: " if q == "auto" else "Качество ") + dict(QUALITIES)[eff])

    def _set_volume(self, v):
        self.audio.setVolume(v / 100)
        if v and self.audio.isMuted():
            self.audio.setMuted(False)
        self._update_mute_icon()
        self.db.set_setting("volume", v / 100)

    def change_volume(self, delta):
        self.volume.setValue(max(0, min(100, self.volume.value() + delta)))
        self.show_osd(f"Громкость {self.volume.value()}%")

    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())
        self.db.set_setting("muted", self.audio.isMuted())
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
        show_next = has_next and in_credits and not self.next_cancelled and dur > 0
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
        if status in (S.LoadedMedia, S.BufferedMedia) and self.pending_seek:
            pos, self.pending_seek = self.pending_seek, None
            self.player.setPosition(int(pos))
        if status == S.EndOfMedia:
            self.save_progress(force_end=True)
            if self.autonext and self.index < len(self.episodes) - 1 and not self.next_cancelled:
                self.next_episode()
            elif self.index == len(self.episodes) - 1:
                self._maybe_complete()
                self.show_osd("Это была последняя серия", 3000)

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._set_icon(self.play_btn, I_PAUSE if playing else I_PLAY)
        self._set_icon(self.fs_btn, I_UNFULL if self.window().isFullScreen() else I_FULL)
        if playing:
            self.poke()
        else:
            self._show_controls()
            self.hide_timer.stop()

    def _on_error(self, _err, text):
        q = self._effective_quality()
        order = [k for k, _ in QUALITIES]
        lower = [k for k in order[order.index(q) + 1:] if (self.current_episode() or {}).get("streams", {}).get(k)] if q else []
        if lower:
            self.show_osd(f"Нет {q}p, переключаемся на {lower[0]}p", 2500)
            pos = self.pending_seek or self.player.position()
            self._bad_q.add(q)
            self._load_source(pos)
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
        was = (self.db.progress_for(self.release["id"]).get(ep["key"]) or {}).get("watched")
        watched = self.db.save_progress(self.release["id"], ep["key"], ep.get("ordinal"), pos, dur,
                                        end_start * 1000 if end_start else None)
        if watched and not was:
            item = self.ep_list.item(self.index)
            if item:
                item.setIcon(self._ep_icon(True))
            if self.index == len(self.episodes) - 1:
                self._maybe_complete()
            # Страницы под плеером обновляем только когда серия досмотрена, а не каждые 5 с.
            self.progress_saved.emit()

    def _maybe_complete(self):
        rel = self.release
        if rel.get("is_ongoing"):
            return
        progress = self.db.progress_for(rel["id"])
        if all((progress.get(e["key"]) or {}).get("watched") for e in self.episodes):
            if self.db.library_entry(rel["id"]).get("status") != "completed":
                self.db.set_status(rel["id"], "completed")
                self.show_osd("Тайтл просмотрен полностью 🎉", 3000)
                self.ctx.library_changed.emit()

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
                            for w in (self.bottom, self.top, self.ep_list))
        if over_controls or any(m.isVisible() for m in self.findChildren(QMenu)):
            self.hide_timer.start()
            return
        self.top.hide()
        self.bottom.hide()
        self.seek.tip.hide()
        self._layout_overlay()
        self.view.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def toggle_episodes(self):
        self.ep_list.setVisible(not self.ep_list.isVisible())
        if self.ep_list.isVisible():
            self.ep_list.raise_()
            self.ep_list.scrollToItem(self.ep_list.currentItem())
        self._layout_overlay()

    # ============================================================ window modes
    def toggle_fullscreen(self):
        if self.pip:
            self.toggle_pip()
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()
        self._set_icon(self.fs_btn, I_UNFULL if win.isFullScreen() else I_FULL)
        self.setFocus()
        self.poke()

    def toggle_pip(self):
        if not self.pip:
            if self.window().isFullScreen():
                self.window().showNormal()
            screen = QGuiApplication.screenAt(self.window().geometry().center()) or QGuiApplication.primaryScreen()
            self.pip = True
            self.pip_toggled.emit(True)     # главное окно убирает плеер из своих экранов
            self.setParent(None)
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
            area = screen.availableGeometry()
            w, h = 480, 270
            self.setGeometry(area.right() - w - 24, area.bottom() - h - 24, w, h)
            self.show()
            self.show_osd("Мини-плеер · I — вернуть")
        else:
            self.pip = False
            self.pip_toggled.emit(False)    # главное окно встраивает плеер обратно
        self.setFocus()

    def close_player(self):
        """Закрыть плеер и вернуться туда, откуда пришли."""
        if self.window().isFullScreen() and not self.pip:
            self.window().showNormal()
            self._set_icon(self.fs_btn, I_FULL)
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
            "[ / ] — скорость   E — серии   I — мини-плеер   0–9 — перейти в %",
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
            self.poke()
        elif t == e.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
            if self.ep_list.isVisible():
                self.ep_list.hide()
                return True
            self.drag_origin = (e.globalPosition().toPoint(), self.pos(), False)
        elif t == e.Type.MouseButtonRelease and e.button() == Qt.MouseButton.LeftButton:
            moved = self.drag_origin and self.drag_origin[2]
            self.drag_origin = None
            if not moved:
                self.click_timer.start()
            return True
        elif t == e.Type.MouseButtonDblClick:
            self.click_timer.stop()
            self.toggle_fullscreen()
            return True
        elif t == e.Type.Wheel:
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
        elif k == K.Key_BracketRight:
            self.change_speed(1)
        elif k == K.Key_BracketLeft:
            self.change_speed(-1)
        elif K.Key_0 <= k <= K.Key_9 and self.player.duration():
            self.seek_to(self.player.duration() * (k - K.Key_0) // 10)
        elif k == K.Key_Escape:
            if self.ep_list.isVisible():
                self.ep_list.hide()
            elif self.window().isFullScreen() and not self.pip:
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
