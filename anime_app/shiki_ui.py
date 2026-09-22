"""Кнопка «Войти через Shikimori» внизу бокового меню: вход, отправка прогресса, загрузка списка."""
from PySide6.QtWidgets import QLineEdit, QMenu, QMessageBox, QPushButton, QVBoxLayout

from .icons import icon
from .theme import TEXT
from .widgets import label


class ShikimoriButton(QPushButton):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.shiki_btn = self
        self.setObjectName("NavButton")
        self.setIcon(icon("link", TEXT, 17))
        self.setToolTip("Статистика просмотров и обсуждения серий на Shikimori")
        self.shiki_menu = QMenu(self)
        self.shiki_menu.aboutToShow.connect(self._fill_shiki_menu)
        self.setMenu(self.shiki_menu)
        self.setStyleSheet("QPushButton::menu-indicator { width: 0; }")
        ctx.shiki.changed.connect(self._update_shiki_btn)
        self._update_shiki_btn()

    def _update_shiki_btn(self):
        u = self.ctx.shiki.user()
        self.shiki_btn.setText(f"  Shikimori: {u['nickname']}" if u else "  Войти через Shikimori")

    def _fill_shiki_menu(self):
        sh = self.ctx.shiki
        m = self.shiki_menu
        m.clear()
        if not sh.configured:
            m.addAction("Вход через Shikimori не настроен в этой сборке").setEnabled(False)
            return
        if not sh.logged_in():
            m.addAction("Войти…", self._shiki_login)
            m.addSection("Что это даёт")
            for t in ("Просмотренные серии, статусы и оценки попадают", "в ваш список на Shikimori — там статистика.",
                      "В плеере можно обсуждать серии (клавиша C)."):
                m.addAction(t).setEnabled(False)
            return
        sync = m.addAction("Отправлять прогресс на Shikimori")
        sync.setCheckable(True)
        sync.setChecked(sh.sync_on())
        sync.toggled.connect(sh.set_sync)
        m.addAction("Отправить весь список сейчас", self._shiki_push_all)
        m.addAction("Загрузить мой список с Shikimori", self._shiki_import)
        m.addSeparator()
        m.addAction("Выйти из Shikimori", sh.logout)

    def _shiki_login(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Вход через Shikimori")
        v = QVBoxLayout(dlg)
        v.addWidget(label("1. Откройте страницу Shikimori и разрешите доступ приложению.\n"
                          "2. Скопируйте код, который покажет Shikimori, и вставьте его сюда.", wrap=True))
        open_btn = QPushButton("  Открыть страницу входа")
        open_btn.setIcon(icon("link", TEXT, 14))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.ctx.shiki.authorize_url())))
        v.addWidget(open_btn)
        code = QLineEdit()
        code.setPlaceholderText("Код с Shikimori")
        v.addWidget(code)
        msg = label("", "Muted", wrap=True)
        v.addWidget(msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Войти")
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)

        def go():
            if not code.text().strip():
                msg.setText("Сначала вставьте код со страницы Shikimori.")
                return
            msg.setText("Входим…")
            self.ctx.shiki.login(code.text(), lambda u: (dlg.accept(), QMessageBox.information(
                self, "Shikimori", f"Вы вошли как {u['nickname']}.\nПросмотренные серии будут отмечаться в вашем списке.")),
                lambda e: msg.setText(f"Не удалось войти: {e}. Получите код ещё раз."))
        bb.accepted.connect(go)
        dlg.resize(460, 0)
        dlg.exec()

    def _shiki_push_all(self):
        self.shiki_btn.setEnabled(False)

        def step(i, n):
            self.shiki_btn.setText(f"  Отправляем… {i} из {n}")

        def done(ok):
            self.shiki_btn.setEnabled(True)
            self._update_shiki_btn()
            QMessageBox.information(self, "Shikimori", f"Отправлено на Shikimori: {ok}")
        self.ctx.shiki.push_all(step, done)

    def _shiki_import(self):
        def done(n):
            self.ctx.library_changed.emit()
            QMessageBox.information(self, "Shikimori", f"Загружено с Shikimori: {n}")
        self.ctx.shiki.import_list(done, lambda e: QMessageBox.warning(self, "Shikimori", f"Ошибка: {e}"))

