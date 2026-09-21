"""Страница «Для вас»: разбор вкуса и рекомендации (+ необязательный ИИ-разбор)."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .api import release_title
from .icons import icon
from .taste import Taste
from .theme import ACCENT, BORDER, MUTED, SURFACE, TEXT
from .widgets import CardRow, ExpandingLabel, clear_layout, label


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


class RecommendationsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        from .pages import scroll_page
        self.ctx = ctx
        self.taste = Taste(ctx, self)
        self.profile = None
        self.scored = []
        self.signature = None
        self.busy = False

        area, lay = scroll_page()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(area)

        head = QHBoxLayout()
        head.addWidget(label("Для вас", "H1"))
        head.addStretch(1)
        self.refresh_btn = QPushButton("  Обновить")
        self.refresh_btn.setIcon(icon("rotate-right", TEXT, 14))
        self.refresh_btn.clicked.connect(lambda: self.rebuild(force=True))
        head.addWidget(self.refresh_btn)
        self.ai_btn = QPushButton("  ИИ-разбор вкуса")
        self.ai_btn.setObjectName("Primary")
        self.ai_btn.setIcon(icon("wand-magic-sparkles", "white", 15))
        self.ai_btn.setIconSize(QSize(15, 15))
        self.ai_btn.setToolTip("Локальная Ollama (если установлена) или бесплатный Pollinations.\n"
                               "ИИ получает только названия, жанры и годы из ваших списков.")
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
        th.addWidget(label("Ваш вкус", "H2"))
        th.addStretch(1)
        tb.addLayout(th)
        self.stats = QGridLayout()
        self.stats.setHorizontalSpacing(12)
        tb.addLayout(self.stats)
        self.taste_text = ExpandingLabel("")
        self.taste_text.setStyleSheet("color:#d0d0d8;")
        tb.addWidget(self.taste_text)
        tb.addWidget(label("Любимые жанры", "FilterTitle"))
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
        ah.addWidget(label("Разбор от ИИ", "H2"))
        ah.addStretch(1)
        self.ai_provider = label("", "Muted")
        ah.addWidget(self.ai_provider)
        ab.addLayout(ah)
        self.ai_text = ExpandingLabel("")
        self.ai_text.setStyleSheet("color:#e6e6ec;font-size:15px;")
        ab.addWidget(self.ai_text)
        self.ai_row = CardRow(ctx, "ИИ советует")
        ab.addWidget(self.ai_row)
        lay.addWidget(self.ai_box)
        self.ai_box.hide()

        self.main_row = CardRow(ctx, "Рекомендуем вам")
        lay.addWidget(self.main_row)
        self.because = QVBoxLayout()
        self.because.setSpacing(24)
        lay.addLayout(self.because)
        lay.addStretch(1)

    # ------------------------------------------------------------ данные
    def _signature(self):
        db = self.ctx.db
        a = db.conn.execute("SELECT COUNT(*), COALESCE(SUM(favorite),0), COALESCE(MAX(updated_at),0) FROM library").fetchone()
        b = db.conn.execute("SELECT COALESCE(SUM(watched),0) FROM progress").fetchone()
        return tuple(a) + tuple(b)

    def on_show(self):
        if self._signature() != self.signature:
            self.rebuild()

    def rebuild(self, force=False):
        if self.busy:
            return
        self.busy = True
        self.signature = self._signature()
        self.status.setText("Анализируем ваши списки…")
        self.taste.fetch_missing(self._with_profile)

    def _with_profile(self):
        self.profile = p = self.taste.build_profile()
        self._render_taste(p)
        if p.empty:
            self.status.setText("Пока мало данных: добавьте несколько аниме в «Избранное», «Просмотрено» "
                                "или «Смотрю» — и рекомендации станут точнее. А пока — популярное.")
        else:
            self.status.setText("Подбираем аниме под ваш вкус…")
        self.taste.candidates(p, self._with_candidates)

    def _with_candidates(self, releases):
        self.busy = False
        self.scored = self.taste.score(self.profile, releases)
        top = self.scored[:30]
        items = []
        for s, rel, reason in top:
            it = self.ctx.item_from_release(rel)
            it["subtitle"] = f"{s:.0%} совпадение · {reason}" if not self.profile.empty else it["subtitle"]
            items.append(it)
        self.main_row.set_items(items, "Не удалось подобрать — проверьте интернет")
        clear_layout(self.because)
        for liked, picks in self.taste.because_of(self.profile, self.scored):
            row = CardRow(self.ctx, f"Потому что вам понравилось «{release_title(liked)}»")
            row.set_items([self.ctx.item_from_release(r) for r in picks])
            self.because.addWidget(row)
        if not self.profile.empty:
            self.status.setText(f"Проанализировано тайтлов: {len(self.profile.titles)}, "
                                f"кандидатов: {len(releases)}.")

    def _render_taste(self, p):
        clear_layout(self.stats)
        fav_type = next(iter(p.types), "—")
        tiles = [
            (sum(p.status_counts.values()), "в ваших списках"),
            (p.episodes, "серий просмотрено"),
            (f"{p.hours:.0f} ч", "проведено за просмотром"),
            (fav_type, "любимый формат"),
        ]
        for i, (v, cap) in enumerate(tiles):
            self.stats.addWidget(stat_tile(v, cap), 0, i)
        self.bars.set_items(list(p.genres.items()))
        self.taste_text.setText(self._describe(p))
        self.taste_box.setVisible(not p.empty)

    @staticmethod
    def _describe(p):
        if p.empty:
            return ""
        g = list(p.genres)
        parts = []
        if len(g) >= 2:
            parts.append(f"Вам больше всего заходят {g[0].lower()} и {g[1].lower()}"
                         + (f", часто — {g[2].lower()}" if len(g) > 2 else "") + ".")
        if p.year_mean:
            decade = int(p.year_mean) // 10 * 10
            parts.append(f"Предпочитаете аниме {decade}-х годов." if p.year_spread < 8
                         else f"Смотрите аниме разных лет, в среднем около {int(p.year_mean)} года.")
        if p.types:
            t, v = next(iter(p.types.items()))
            parts.append(f"Формат: чаще {t.lower()} ({v:.0%}).")
        if p.status_counts.get("dropped"):
            parts.append(f"Брошено: {p.status_counts['dropped']} — такие жанры рекомендуем реже.")
        return " ".join(parts)

    # ------------------------------------------------------------ ИИ
    def run_ai(self):
        if not self.scored or not self.profile:
            self.status.setText("Сначала дождитесь подбора рекомендаций.")
            return
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("  ИИ думает…")
        self.ai_box.show()
        self.ai_text.setText("Отправляем ИИ ваш профиль (только названия, жанры и годы)…")
        self.ai_row.set_items([])

        def done():
            self.ai_btn.setEnabled(True)
            self.ai_btn.setText("  ИИ-разбор вкуса")

        def ok(res):
            done()
            self.ai_provider.setText(res["provider"])
            self.ai_text.setText(res["analysis"] or "ИИ не написал разбор.")
            items = []
            for rel, reason in res["picks"]:
                it = self.ctx.item_from_release(rel)
                it["subtitle"] = reason
                items.append(it)
            self.ai_row.set_items(items, "ИИ не выбрал аниме — попробуйте ещё раз")

        def err(msg):
            done()
            self.ai_text.setText(f"{msg}\n\nРекомендации ниже работают и без ИИ. Для приватного локального ИИ "
                                 "установите Ollama (ollama.com) и скачайте модель, например: ollama pull qwen2.5")

        self.taste.ai_analyze(self.profile, self.scored, ok, err)
