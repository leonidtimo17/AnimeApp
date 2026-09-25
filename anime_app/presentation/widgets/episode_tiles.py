"""Плитки страницы тайтла: серия с кадром, предстоящая серия, сезон франшизы."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ...core.formatting import fmt_air_date, fmt_duration, fmt_ordinal
from ...domain.episodes import progress_fraction
from ..theme import ACCENT, MUTED
from .layout import icon_label, label
from .thumbs import episode_thumb


class EpisodeTile(QFrame):
    clicked = Signal(dict)
    menu_requested = Signal(dict, object)

    W, TH = 232, 130  # ширина плитки и высота кадра (16:9)

    def __init__(self, ep, prog, current=False, title=None, missing_note=None, images=None, preview=None, poster=None):
        super().__init__()
        self.ep = ep
        self.setObjectName("Episode")
        self.setProperty("current", current)
        self.setProperty("missing", bool(missing_note))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self.W, self.TH + 58)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 8)
        lay.setSpacing(3)
        # Кадр из серии; если его нет — затемнённый постер тайтла с крупным номером
        number = fmt_ordinal(ep.get("ordinal"))
        watched = bool(prog and prog["watched"])
        frac = progress_fraction(prog)
        self.thumb = QLabel()
        self.thumb.setFixedSize(self.W - 2, self.TH)
        lay.addWidget(self.thumb)

        def draw(src):
            self.thumb.setPixmap(episode_thumb(src, self.W - 2, self.TH, number, not preview, frac, watched, current,
                                               radius=9))
        draw(None)
        if images and (preview or poster):
            images.load(preview or poster, self, draw)
        name = ep.get("name") or ep.get("name_english") or ""
        t = label(title or f"{number} серия", "CardTitle")
        t.setContentsMargins(11, 4, 11, 0)
        lay.addWidget(t)
        n = label(missing_note or name or fmt_duration(ep.get("duration")), "CardSub")
        n.setToolTip(missing_note or name)
        n.setContentsMargins(11, 0, 11, 0)
        n.setMaximumWidth(self.W - 2)
        lay.addWidget(n)
        lay.addStretch(1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.ep)
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.ep, e.globalPosition().toPoint())


class UpcomingTile(QFrame):
    """Серия, которой ещё нет: дата выхода или «ждём озвучку»."""

    def __init__(self, item):
        super().__init__()
        self.setObjectName("Upcoming")
        self.setFixedSize(210, 70)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(f"{item['ordinal']} серия", "CardTitle"))
        top.addStretch(1)
        dub = item["state"] in ("no_dub", "dub")
        top.addWidget(icon_label("microphone" if dub else "calendar-days", ACCENT if dub else MUTED, 14))
        lay.addLayout(top)
        if item["state"] == "dub":
            text = "озвучка ≈ " + fmt_air_date(item["date"])
            tip = "Серия уже вышла в Японии. Дата озвучки — примерная, по дню выхода серий."
        elif item["state"] == "no_dub":
            text = "вышла, ждём озвучку"
            tip = "Серия уже вышла в Японии, озвучка появится позже"
        else:
            text = fmt_air_date(item["date"])
            tip = "Дата выхода в Японии (по данным Shikimori), дальше — раз в неделю"
        lay.addWidget(label(text, "CardSub"))
        self.setToolTip(tip)


class SeasonCard(QFrame):
    """Сезон / фильм / OVA франшизы."""

    clicked = Signal(dict)

    def __init__(self, ctx, entry):
        super().__init__()
        self.entry = entry
        self.setObjectName("Season")
        self.setProperty("current", bool(entry.get("current")))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(150, 262)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)
        self.poster = QLabel()
        self.poster.setFixedSize(134, 180)
        self.poster.setObjectName("Poster")
        lay.addWidget(self.poster)
        year = entry.get("year") or "анонс"
        head = label(f"{entry['label']} · {year}", "SeasonCurrent" if entry.get("current") else "CardTitle")
        lay.addWidget(head)
        name = label("", "CardSub")
        name.setWordWrap(True)
        name.setText(entry.get("name") or "")
        name.setToolTip(entry.get("name") or "")
        name.setFixedHeight(34)
        name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(name)
        ctx.images.load_cover(entry.get("poster"), 134, 180, 8, self, self.poster.setPixmap)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self.entry.get("current"):
            self.clicked.emit(self.entry)
