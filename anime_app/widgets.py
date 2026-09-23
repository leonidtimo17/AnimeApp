from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QMenu, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .db import STATUSES
from .icons import pixmap
from .theme import ACCENT
from .images import cover, rounded

CARD_W, POSTER_H = 176, 250


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=16):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            w = item.sizeHint()
            if x + w.width() > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), w))
            x += w.width() + self._spacing
            line_h = max(line_h, w.height())
        return y + line_h - rect.y()


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def label(text="", obj=None, wrap=False):
    lbl = QLabel(text)
    if obj:
        lbl.setObjectName(obj)
    lbl.setWordWrap(wrap)
    return lbl


def pixmap_icon(name, color="#f2f2f5", regular=False):
    return QIcon(pixmap(name, color, 14, regular))


def icon_label(name, color="#f2f2f5", size=16, regular=False):
    lbl = QLabel()
    lbl.setPixmap(pixmap(name, color, size, regular))
    lbl.setFixedSize(size, size)
    return lbl


def elide_lines(text, font, width, lines=2):
    fm = QFontMetrics(font)
    words, out, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if fm.horizontalAdvance(trial) <= width:
            cur = trial
        else:
            out.append(cur)
            cur = word
            if len(out) == lines:
                break
    if len(out) < lines and cur:
        out.append(cur)
    if len(out) == lines and " ".join(out) != text:
        # Не влезло: последняя строка — с многоточием посередине, чтобы был виден конец
        # названия (номер сезона, «Фильм», «Часть 2»).
        rest = text[len(" ".join(out[:-1])):].strip()
        out[-1] = fm.elidedText(rest, Qt.TextElideMode.ElideMiddle, width)
    return "\n".join(o for o in out if o)


class PosterCard(QFrame):
    clicked = Signal(int)

    def __init__(self, ctx, item: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(CARD_W + 12)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 8)
        lay.setSpacing(6)

        self.poster = QLabel()
        self.poster.setFixedSize(CARD_W, POSTER_H)
        self.poster.setStyleSheet("background:#222229;border-radius:10px;")
        lay.addWidget(self.poster)

        # Бейджи поверх постера
        self.badges = QHBoxLayout(self.poster)
        self.badges.setContentsMargins(8, 8, 8, 8)
        self.badges.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._render_badges()

        # Быстрые действия при наведении: избранное и «Хочу посмотреть»
        self.actions = QWidget(self.poster)
        act_lay = QHBoxLayout(self.actions)
        act_lay.setContentsMargins(0, 0, 0, 0)
        act_lay.setSpacing(6)
        self.fav_btn = self._action_btn(act_lay, self.toggle_favorite)
        self.plan_btn = self._action_btn(act_lay, self.toggle_planned)
        self._render_actions()
        self.actions.adjustSize()
        self.actions.move(CARD_W - self.actions.width() - 8, POSTER_H - self.actions.height() - 8)
        self.actions.hide()

        if item.get("progress") is not None:
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(item["progress"] * 1000))
            bar.setTextVisible(False)
            bar.setFixedHeight(4)
            lay.addWidget(bar)

        title = label("", "CardTitle")
        font = QFont(title.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        title.setText(elide_lines(item.get("title", ""), font, CARD_W - 6, 2))
        title.setToolTip(item.get("title", ""))
        title.setFixedHeight(38)
        title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(title)
        sub = label("", "CardSub")
        sub.setText(sub.fontMetrics().elidedText(item.get("subtitle", ""), Qt.TextElideMode.ElideRight, CARD_W))
        sub.setToolTip(item.get("subtitle", ""))
        lay.addWidget(sub)

        ctx.images.load(item.get("poster"), self, self._set_poster)

    def _set_poster(self, pix):
        self.poster.setPixmap(rounded(cover(pix, CARD_W, POSTER_H), 10))

    # ------------------------------------------------------------ списки прямо с карточки
    def _action_btn(self, layout, slot):
        b = QPushButton()
        b.setObjectName("CardAction")
        b.setFixedSize(34, 34)
        b.setIconSize(QSize(16, 16))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        layout.addWidget(b)
        return b

    def _render_badges(self):
        clear_layout(self.badges)
        item = self.item
        if item.get("badge"):
            self.badges.addWidget(label(item["badge"], "Badge"))
        if item.get("status"):
            b = label(STATUSES.get(item["status"], ""), "Badge")
            b.setStyleSheet("background:#2d7d46;")
            self.badges.addWidget(b)
        if item.get("favorite"):
            b = label("", "Badge")
            b.setPixmap(pixmap("heart", "white", 11))
            b.setStyleSheet("background:#c0304a;padding:4px 6px;")
            self.badges.addWidget(b)

    def _render_actions(self):
        fav = bool(self.item.get("favorite"))
        planned = self.item.get("status") == "planned"
        self.fav_btn.setIcon(QIcon(pixmap("heart", "#ff4d6d" if fav else "white", 16, regular=not fav)))
        self.fav_btn.setToolTip("Убрать из избранного" if fav else "В избранное")
        self.plan_btn.setIcon(QIcon(pixmap("bookmark", ACCENT if planned else "white", 16, regular=not planned)))
        self.plan_btn.setToolTip("Убрать из «Хочу посмотреть»" if planned else "Хочу посмотреть")

    def _ensure_cached(self):
        # Для списков нужна запись о тайтле в базе (чтобы библиотека работала офлайн).
        if self.item.get("release"):
            self.ctx.remember(self.item["release"], full=bool(self.item["release"].get("genres")))

    def _changed(self):
        self._render_badges()
        self._render_actions()
        self.ctx.library_changed.emit()

    def toggle_favorite(self):
        self._ensure_cached()
        fav = not self.item.get("favorite")
        self.ctx.db.set_favorite(self.item["id"], fav)
        self.item["favorite"] = int(fav)
        self._changed()

    def toggle_planned(self):
        self.set_status(None if self.item.get("status") == "planned" else "planned")

    def set_status(self, status):
        self._ensure_cached()
        self.ctx.db.set_status(self.item["id"], status)
        self.item["status"] = status
        self._changed()

    def enterEvent(self, e):
        self.actions.show()
        self.actions.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.actions.hide()
        super().leaveEvent(e)

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction(pixmap_icon("circle-play"), "Открыть", lambda: self.ctx.open_anime.emit(self.item["id"]))
        menu.addAction(pixmap_icon("play"), "Смотреть", lambda: self.ctx.play.emit(self.item["id"], ""))
        menu.addSeparator()
        fav = bool(self.item.get("favorite"))
        menu.addAction(pixmap_icon("heart", "#ff4d6d" if fav else "#f2f2f5", regular=not fav),
                       "Убрать из избранного" if fav else "В избранное", self.toggle_favorite)
        menu.addSeparator()
        for key, name in STATUSES.items():
            act = menu.addAction(name, lambda k=key: self.set_status(k))
            act.setCheckable(True)
            act.setChecked(self.item.get("status") == key)
        if self.item.get("status"):
            menu.addAction("Убрать из списков", lambda: self.set_status(None))
        menu.exec(e.globalPos())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.item["id"])
        super().mouseReleaseEvent(e)


class CardGrid(QScrollArea):
    """Сетка карточек с бесконечной прокруткой (сигнал need_more)."""

    need_more = Signal()

    def __init__(self, ctx, on_click=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_click = on_click or ctx.open_anime.emit
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 0, 0)
        self.flow_host = QWidget()
        self.flow = FlowLayout(self.flow_host, spacing=8)
        outer.addWidget(self.flow_host)
        self.status = label("", "Muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setMinimumHeight(40)
        outer.addWidget(self.status)
        # Кнопка на случай, если прокруткой пользоваться неудобно
        self.more_btn = QPushButton("Показать ещё")
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.clicked.connect(self.need_more.emit)
        self.more_btn.hide()
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.more_btn)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.setWidget(inner)
        self.verticalScrollBar().valueChanged.connect(self._check_scroll)

    def _check_scroll(self, value):
        bar = self.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum() - 400:
            self.need_more.emit()

    def set_more(self, has_more):
        """Показать/скрыть кнопку «Показать ещё» под сеткой."""
        self.more_btn.setVisible(bool(has_more))
        self.more_btn.setEnabled(True)
        self.more_btn.setText("Показать ещё")

    def clear(self):
        clear_layout(self.flow)
        self.more_btn.hide()
        self.verticalScrollBar().setValue(0)

    def add_items(self, items):
        for item in items:
            card = PosterCard(self.ctx, item)
            card.clicked.connect(self.on_click)
            self.flow.addWidget(card)
        self.flow_host.updateGeometry()

    def set_items(self, items, empty_text="Ничего не найдено"):
        self.clear()
        self.add_items(items)
        self.set_status("" if items else empty_text)

    def set_status(self, text):
        self.status.setText(text)


class CardRow(QWidget):
    """Горизонтальная лента с заголовком — для главной и расписания."""

    def __init__(self, ctx, title, on_click=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.on_click = on_click or (lambda item: ctx.open_anime.emit(item["id"]))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.title = label(title, "H2")
        lay.addWidget(self.title)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(POSTER_H + 115)
        self.host = QWidget()
        self.row = QHBoxLayout(self.host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.row.addStretch(1)
        self.scroll.setWidget(self.host)
        lay.addWidget(self.scroll)
        self.empty = label("", "Muted")
        lay.addWidget(self.empty)
        self.empty.hide()
        self.scroll.wheelEvent = self._wheel

    def _wheel(self, e):
        bar = self.scroll.horizontalScrollBar()
        if bar.maximum() == 0:
            e.ignore()
            return
        bar.setValue(bar.value() - e.angleDelta().y())
        e.accept()

    def set_items(self, items, empty_text=None):
        clear_layout(self.row)
        for item in items:
            card = PosterCard(self.ctx, item)
            card.clicked.connect(lambda _id, it=item: self.on_click(it))
            self.row.addWidget(card)
        self.row.addStretch(1)
        has = bool(items)
        self.scroll.setVisible(has)
        self.empty.setVisible(not has and bool(empty_text))
        self.empty.setText(empty_text or "")
        self.setVisible(has or bool(empty_text))


class ExpandingLabel(QLabel):
    def __init__(self, text="", obj=None):
        super().__init__(text)
        if obj:
            self.setObjectName(obj)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
