"""Моя библиотека: списки по статусам и избранное, резервная копия, очистка кэша, правовые документы."""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMenu, QMessageBox, QPushButton, QTabWidget, QVBoxLayout

from ...core.errors import AppError
from ...domain.library import STATUSES
from ..icons import icon
from ..legal import show_doc
from ..theme import TEXT
from ..widgets.cards import CardGrid
from ..widgets.layout import Page, label


class LibraryPage(Page):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("Моя библиотека", "H1"))
        head.addStretch(1)
        self.stats = label("", "Muted")
        head.addWidget(self.stats)
        backup = QPushButton("  Резервная копия")
        backup.setIcon(icon("file-export", TEXT, 15))
        menu = QMenu(backup)
        menu.addAction("Экспорт в файл…", self._export)
        menu.addAction("Импорт из файла…", self._import)
        menu.addSeparator()
        menu.addAction("Очистить кэш", self._clear_cache)
        menu.addSeparator()
        menu.addAction("Пользовательское соглашение", lambda: show_doc(self, "terms"))
        menu.addAction("Политика конфиденциальности", lambda: show_doc(self, "privacy"))
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
            name = "Избранное" if key == "favorite" else STATUSES[key]
            self.tabs.setTabText(i, f"{name}  {counts.get(key, 0)}")
            rows = self.ctx.library.rows(favorites=True) if key == "favorite" else self.ctx.library.rows(key)
            self.grids[key].set_items([self.ctx.releases.item_from_row(r) for r in rows],
                                      "Пока пусто. Добавляйте аниме со страницы тайтла.")
        s = self.ctx.progress.stats()
        self.stats.setText(f"Просмотрено серий: {s['episodes']} · {s['hours']:.1f} ч   ")

    def _clear_cache(self):
        n, size = self.ctx.backup.clear_cache()
        QMessageBox.information(self, "Кэш", f"Кэш очищен: {n} ответов сервера ({size / 1e6:.1f} МБ) и постеры.\n"
                                "Ваши списки и история не затронуты.")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт", "anime_backup.json", "JSON (*.json)")
        if path:
            try:
                self.ctx.backup.export_json(path)
            except OSError as exc:
                QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить файл: {exc}")
                return
            QMessageBox.information(self, "Готово", "Библиотека сохранена.")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.ctx.backup.import_json(path)
        except AppError as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self.ctx.library_changed.emit()
