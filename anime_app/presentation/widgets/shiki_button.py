"""Кнопка «Войти через Shikimori» внизу бокового меню: вход, отправка прогресса, загрузка списка."""
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLineEdit, QMenu, QMessageBox, QPushButton, QVBoxLayout

from ...domain.shikimori import shiki_status_name
from ..icons import icon
from ..theme import ACCENT, TEXT
from .layout import label
from .states import error_text
from ...core.i18n import t


class ShikimoriButton(QPushButton):
    """Не вошли — нажатие сразу открывает вход; вошли — аватар и ник, по нажатию меню аккаунта."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.shiki_btn = self
        self.setObjectName("ShikiButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(22, 22))
        self.setToolTip(t("shikimori.tooltip"))
        self.shiki_menu = QMenu(self)
        self.clicked.connect(self._clicked)
        ctx.shiki.changed.connect(self._update_shiki_btn)
        self._update_shiki_btn()

    def _clicked(self):
        sh = self.ctx.shiki
        if not sh.configured:
            QMessageBox.information(self, "Shikimori", t("shikimori.not_configured_long"))
            return
        if not sh.logged_in():
            self._shiki_login()
            return
        self._fill_shiki_menu()
        # Кнопка внизу окна — меню открываем над ней
        pos = self.mapToGlobal(QPoint(0, 0))
        self.shiki_menu.exec(QPoint(pos.x(), pos.y() - self.shiki_menu.sizeHint().height()))

    def _update_shiki_btn(self):
        u = self.ctx.shiki.user()
        self.setProperty("logged", bool(u))
        self.style().unpolish(self)
        self.style().polish(self)
        if not u:
            self.setText(" " + t("shikimori.sign_in"))
            self.setIcon(icon("link", ACCENT, 17))
            return
        self.setText(f"  {u['nickname']}")
        self.setIcon(icon("circle-check", "#3fbf6a", 17))
        if u.get("avatar"):
            self.ctx.images.load_cover(u["avatar"], 44, 44, 22, self, lambda p: self.setIcon(QIcon(p)))

    def _fill_shiki_menu(self):
        sh = self.ctx.shiki
        m = self.shiki_menu
        m.clear()
        if not sh.configured:
            m.addAction(t("shikimori.not_configured")).setEnabled(False)
            return
        if not sh.logged_in():
            m.addAction(t("shikimori.sign_in_dots"), self._shiki_login)
            m.addSection(t("shikimori.benefits"))
            for line in t("shikimori.benefits_text").split("\n"):
                m.addAction(line).setEnabled(False)
            return
        self._stats_act = m.addSection(self._stats_text())
        self.ctx.shiki.stats(self._got_stats)
        sync = m.addAction(t("shikimori.sync"))
        sync.setCheckable(True)
        sync.setChecked(sh.sync_on())
        sync.toggled.connect(sh.set_sync)
        m.addAction(t("shikimori.push_all"), self._shiki_push_all)
        m.addAction(t("shikimori.import"), self._shiki_import)
        m.addSeparator()
        m.addAction(t("shikimori.sign_out"), sh.logout)

    def _stats_text(self):
        st = getattr(self, "_stats", None)
        if not st:
            return t("shikimori.my_list")
        parts = [f"{v} {shiki_status_name(k)}" for k, v in st.items() if v]
        return t("shikimori.on_site", list=", ".join(parts)) if parts else t("shikimori.empty")

    def _got_stats(self, st):
        self._stats = st or {}
        act = getattr(self, "_stats_act", None)   # меню уже открыто — обновляем строку на месте
        if act is not None and act in self.shiki_menu.actions():
            act.setText(self._stats_text())

    def _shiki_login(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(t("shikimori.sign_in_title"))
        v = QVBoxLayout(dlg)
        v.addWidget(label(t("shikimori.sign_in_steps"), wrap=True))
        open_btn = QPushButton("  " + t("shikimori.open_sign_in"))
        open_btn.setIcon(icon("link", TEXT, 14))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.ctx.shiki.authorize_url())))
        v.addWidget(open_btn)
        code = QLineEdit()
        code.setPlaceholderText(t("shikimori.code"))
        v.addWidget(code)
        msg = label("", "Muted", wrap=True)
        v.addWidget(msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(t("shikimori.sign_in_short"))
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)

        def go():
            if not code.text().strip():
                msg.setText(t("shikimori.paste_code"))
                return
            msg.setText(t("shikimori.signing_in"))
            self.ctx.shiki.login(code.text(), lambda u: (dlg.accept(), QMessageBox.information(
                self, "Shikimori", t("shikimori.signed_in", name=u["nickname"]))),
                lambda e: msg.setText(error_text(e, t("shikimori.sign_in_failed"))))
        bb.accepted.connect(go)
        dlg.resize(460, 0)
        dlg.exec()

    def _shiki_push_all(self):
        self.shiki_btn.setEnabled(False)

        def step(i, n):
            self.shiki_btn.setText("  " + t("shikimori.sending", i=i, n=n))

        def done(ok):
            self.shiki_btn.setEnabled(True)
            self._update_shiki_btn()
            QMessageBox.information(self, "Shikimori", t("shikimori.sent", n=ok))
        self.ctx.shiki.push_all(step, done)

    def _shiki_import(self):
        def done(n):
            QMessageBox.information(self, "Shikimori", t("shikimori.imported", n=n))
        self.ctx.shiki.import_list(done, lambda e: QMessageBox.warning(self, "Shikimori", error_text(e, t("shikimori.import_failed"))))

