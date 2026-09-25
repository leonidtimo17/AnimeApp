"""Страница «Для вас»: разбор вкуса и рекомендации (+ необязательный ИИ-разбор)."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ...domain.titles import release_title
from ..icons import icon
from ..theme import ACCENT, MUTED, TEXT
from ..widgets.cards import CardRow
from ..widgets.layout import ExpandingLabel, Page, clear_layout, label, scroll_page_widget
from ...core.i18n import t


class GenreBars(QWidget):
    """Горизонтальные полосы «насколько вам нравится жанр»."""

    def __init__(self):
        super().__init__()
        self.items = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_items(self, items):
        self.items = items[:8]
        self.setFixedHeight(max(1, len(self.items)) * 30)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        label_w = 170
        w = self.width() - label_w - 56
        f = QFont(self.font())
        f.setPixelSize(13)
        p.setFont(f)
        for i, (name, value) in enumerate(self.items):
            y = i * 30
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(0, y, label_w - 10, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, name)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2a2a33"))
            p.drawRoundedRect(QRectF(label_w, y + 8, w, 8), 4, 4)
            color = QColor(ACCENT)
            color.setAlphaF(0.45 + 0.55 * value)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(label_w, y + 8, max(8, w * value), 8), 4, 4)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(label_w + w + 8, y, 48, 24), Qt.AlignmentFlag.AlignVCenter, f"{value:.0%}")
        p.end()


def stat_tile(value, caption):
    box = QFrame()
    box.setObjectName("StatTile")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(2)
    v = label(str(value), "StatValue")
    lay.addWidget(v)
    lay.addWidget(label(caption, "Muted"))
    return box


class RecommendationsPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.service = ctx.recommendations
        self.profile = None
        self.scored = []
        self.signature = None
        self.busy = False

        _area, lay = scroll_page_widget(self)

        head = QHBoxLayout()
        head.addWidget(label(t("navigation.recs"), "H1"))
        head.addStretch(1)
        self.refresh_btn = QPushButton("  " + t("common.refresh"))
        self.refresh_btn.setIcon(icon("rotate-right", TEXT, 14))
        self.refresh_btn.clicked.connect(lambda: self.rebuild(force=True))
        head.addWidget(self.refresh_btn)
        self.ai_btn = QPushButton("  " + t("recs.ai_button"))
        self.ai_btn.setObjectName("Primary")
        self.ai_btn.setIcon(icon("wand-magic-sparkles", "white", 15))
        self.ai_btn.setIconSize(QSize(15, 15))
        self.ai_btn.setToolTip(t("recs.ai_tooltip"))
        self.ai_btn.clicked.connect(self.run_ai)
        head.addWidget(self.ai_btn)
        lay.addLayout(head)

        self.status = label("", "Muted", wrap=True)
        lay.addWidget(self.status)

        # Разбор вкуса
        self.taste_box = QFrame()
        self.taste_box.setObjectName("Panel")
        tb = QVBoxLayout(self.taste_box)
        tb.setContentsMargins(22, 18, 22, 20)
        tb.setSpacing(14)
        th = QHBoxLayout()
        th.addWidget(label(t("recs.your_taste"), "H2"))
        th.addStretch(1)
        tb.addLayout(th)
        self.stats = QGridLayout()
        self.stats.setHorizontalSpacing(12)
        tb.addLayout(self.stats)
        self.taste_text = ExpandingLabel("", "Description")
        tb.addWidget(self.taste_text)
        tb.addWidget(label(t("recs.favorite_genres"), "FilterTitle"))
        self.bars = GenreBars()
        tb.addWidget(self.bars)
        lay.addWidget(self.taste_box)

        # ИИ
        self.ai_box = QFrame()
        self.ai_box.setObjectName("Panel")
        ab = QVBoxLayout(self.ai_box)
        ab.setContentsMargins(22, 18, 22, 20)
        ab.setSpacing(10)
        ah = QHBoxLayout()
        ah.addWidget(label(t("recs.ai_title"), "H2"))
        ah.addStretch(1)
        self.ai_provider = label("", "Muted")
        ah.addWidget(self.ai_provider)
        ab.addLayout(ah)
        self.ai_text = ExpandingLabel("", "AiText")
        ab.addWidget(self.ai_text)
        self.ai_row = CardRow(ctx, t("recs.ai_suggests"))
        ab.addWidget(self.ai_row)
        lay.addWidget(self.ai_box)
        self.ai_box.hide()

        self.main_row = CardRow(ctx, t("recs.recommended"))
        lay.addWidget(self.main_row)
        self.because = QVBoxLayout()
        self.because.setSpacing(24)
        lay.addLayout(self.because)
        lay.addStretch(1)

    # ------------------------------------------------------------ данные
    def on_show(self):
        if self.service.signature() != self.signature:
            self.rebuild()

    def rebuild(self, force=False):
        if self.busy:
            return
        self.busy = True
        self.signature = self.service.signature()
        self.status.setText(t("recs.analyzing"))
        self.service.build(self._with_profile, self._with_recommendations)

    def _with_profile(self, p):
        self.profile = p
        self._render_taste(p)
        if p.empty:
            self.status.setText(t("recs.little_data"))
        else:
            self.status.setText(t("recs.picking"))

    def _with_recommendations(self, rec):
        self.busy = False
        self.scored = rec.scored
        items = []
        for s, rel, reason in rec.scored[:30]:
            it = self.ctx.releases.item(rel)
            if not rec.profile.empty:
                it["subtitle"] = t("recs.match", share=f"{s:.0%}", reason=reason)
            items.append(it)
        self.main_row.set_items(items, t("recs.failed"))
        clear_layout(self.because)
        for liked, picks in rec.because:
            row = CardRow(self.ctx, t("recs.because", title=release_title(liked)))
            row.set_items(self.ctx.releases.items(picks))
            self.because.addWidget(row)
        if not rec.profile.empty:
            self.status.setText(t("recs.analyzed", n=len(rec.profile.titles), candidates=rec.candidates))

    def _render_taste(self, p):
        clear_layout(self.stats)
        fav_type = next(iter(p.types), "—")
        tiles = [
            (sum(p.status_counts.values()), t("recs.stat_in_lists")),
            (p.episodes, t("recs.stat_episodes")),
            (t("recs.hours", n=f"{p.hours:.0f}"), t("recs.stat_hours")),
            (fav_type, t("recs.stat_format")),
        ]
        for i, (v, cap) in enumerate(tiles):
            self.stats.addWidget(stat_tile(v, cap), 0, i)
        self.bars.set_items(list(p.genres.items()))
        self.taste_text.setText(p.describe())
        self.taste_box.setVisible(not p.empty)

    # ------------------------------------------------------------ ИИ
    def run_ai(self):
        if not self.scored or not self.profile:
            self.status.setText(t("recs.wait_first"))
            return
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("  " + t("recs.ai_thinking"))
        self.ai_box.show()
        self.ai_text.setText(t("recs.ai_sending"))
        self.ai_row.set_items([])

        def done():
            self.ai_btn.setEnabled(True)
            self.ai_btn.setText("  " + t("recs.ai_button"))

        def ok(res):
            done()
            self.ai_provider.setText(res["provider"])
            self.ai_text.setText(res["analysis"] or t("recs.ai_no_analysis"))
            items = []
            for rel, reason in res["picks"]:
                it = self.ctx.releases.item(rel)
                it["subtitle"] = reason
                items.append(it)
            self.ai_row.set_items(items, t("recs.ai_no_picks"))

        def err(msg):
            done()
            self.ai_text.setText(f"{msg}\n\n{t('recs.ai_hint')}")

        self.service.ai_analyze(self.profile, self.scored, ok, err)
