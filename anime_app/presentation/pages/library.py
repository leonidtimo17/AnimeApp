"""Моя библиотека: списки по статусам и избранное, резервная копия, очистка кэша, правовые документы."""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMenu, QMessageBox, QPushButton, QTabWidget, QVBoxLayout

from ...core.errors import AppError
from ...domain.library import STATUSES, status_name
from ..icons import icon
from ..legal import show_doc
from ..theme import TEXT
from ..widgets.cards import CardGrid
from ..widgets.layout import Page, label
from ..widgets.states import error_text
from ...core.i18n import t


class LibraryPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label(t("library.title"), "H1"))
        head.addStretch(1)
        self.stats = label("", "Muted")
        head.addWidget(self.stats)
        backup = QPushButton("  " + t("library.backup"))
        backup.setIcon(icon("file-export", TEXT, 15))
        menu = QMenu(backup)
        menu.addAction(t("library.export"), self._export)
        menu.addAction(t("library.import"), self._import)
        menu.addSeparator()
        menu.addAction(t("library.clear_cache"), self._clear_cache)
        menu.addSeparator()
        menu.addAction(t("legal.terms"), lambda: show_doc(self, "terms"))
        menu.addAction(t("legal.privacy"), lambda: show_doc(self, "privacy"))
        backup.setMenu(menu)
        head.addWidget(backup)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        self.keys = list(STATUSES) + ["favorite"]
        self.grids = {}
        for key in self.keys:
            grid = CardGrid(ctx)
            self.grids[key] = grid
            self.tabs.addTab(grid, "")
        lay.addWidget(self.tabs, 1)

    def on_show(self):
        counts = self.ctx.library.counts()
        for i, key in enumerate(self.keys):
            name = t("library.favorite") if key == "favorite" else status_name(key)
            self.tabs.setTabText(i, f"{name}  {counts.get(key, 0)}")
            rows = self.ctx.library.rows(favorites=True) if key == "favorite" else self.ctx.library.rows(key)
            self.grids[key].set_items([self.ctx.releases.item_from_row(r) for r in rows],
                                      t("library.empty"))
        s = self.ctx.progress.stats()
        self.stats.setText(t("library.stats", n=s["episodes"], hours=f"{s['hours']:.1f}") + "   ")

    def _clear_cache(self):
        n, size = self.ctx.backup.clear_cache()
        QMessageBox.information(self, t("library.cache"), t("library.cache_cleared", n=n, mb=f"{size / 1e6:.1f}"))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, t("library.export_title"), "anime_backup.json", "JSON (*.json)")
        if path:
            try:
                self.ctx.backup.export_json(path)
            except OSError as exc:
                QMessageBox.warning(self, t("common.error"), error_text(exc, t("library.save_failed")))
                return
            QMessageBox.information(self, t("common.done"), t("library.saved"))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, t("library.import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            self.ctx.backup.import_json(path)
        except AppError as exc:
            QMessageBox.warning(self, t("common.error"), error_text(exc, t("library.import_failed")))
            return
        self.ctx.library_changed.emit()
