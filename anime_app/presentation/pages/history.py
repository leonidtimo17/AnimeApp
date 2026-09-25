"""История просмотра."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

from ...core.formatting import fmt_ordinal, fmt_when
from ..icons import icon
from ..theme import TEXT
from ..widgets.layout import Page, clear_layout, label, scroll_page_widget
from ...core.i18n import t

HISTORY_LIMIT = 120


class HistoryRow(QFrame):
    def __init__(self, ctx, row):
        super().__init__()
        self.ctx = ctx
        self.row = row
        self.setObjectName("HistoryRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 16, 10)
        lay.setSpacing(14)
        self.thumb = QLabel()
        self.thumb.setFixedSize(54, 76)
        lay.addWidget(self.thumb)
        text = QVBoxLayout()
        text.addWidget(label(row["title"], "CardTitle"))
        state = t("history.watched") if row["watched"] else t(
            "history.position", pos=f"{row['position'] // 60000}:{row['position'] // 1000 % 60:02d}",
            total=row["duration"] // 60000)
        text.addWidget(label(f"{t('player.episode_n', n=fmt_ordinal(row['ordinal']))} · {state}", "Muted"))
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(1000 if row["watched"] else int(1000 * row["position"] / max(1, row["duration"])))
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setMaximumWidth(320)
        text.addWidget(bar)
        lay.addLayout(text, 1)
        lay.addWidget(label(fmt_when(row["updated_at"]), "Muted"))
        ctx.images.load_cover(row["poster"], 54, 76, 6, self, self.thumb.setPixmap)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.ctx.play.emit(self.row["id"], self.row["episode_id"])
        elif e.button() == Qt.MouseButton.RightButton:
            menu = QMenu(self)
            menu.addAction(t("anime.open_page"), lambda: self.ctx.open_anime.emit(self.row["id"]))
            menu.exec(e.globalPosition().toPoint())


class HistoryPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        _area, lay = scroll_page_widget(self)
        head = QHBoxLayout()
        head.addWidget(label(t("history.title"), "H1"))
        head.addStretch(1)
        clear = QPushButton("  " + t("history.clear"))
        clear.setIcon(icon("trash-can", TEXT, 15))
        clear.clicked.connect(self._clear)
        head.addWidget(clear)
        lay.addLayout(head)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        lay.addLayout(self.list)
        lay.addStretch(1)
        self._shown = None

    def on_show(self):
        rows = self.ctx.progress.history(limit=HISTORY_LIMIT)
        signature = [(r["id"], r["episode_id"], r["position"], r["watched"], r["updated_at"]) for r in rows]
        if signature == self._shown:      # ничего не изменилось — не пересоздаём 120 строк
            return
        self._shown = signature
        clear_layout(self.list)
        if not rows:
            self.list.addWidget(label(t("history.empty"), "Muted"))
        for r in rows:
            self.list.addWidget(HistoryRow(self.ctx, r))

    def _clear(self):
        if QMessageBox.question(self, t("navigation.history"), t("history.clear_confirm")) \
                == QMessageBox.StandardButton.Yes:
            self.ctx.progress.clear_history()
