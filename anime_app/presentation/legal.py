"""Правовые документы: пользовательское соглашение и политика конфиденциальности.

Тексты лежат рядом с программой (TERMS.md, PRIVACY.md). При первом запуске соглашение
показывается один раз; позже его можно открыть из «Моей библиотеки».
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from ..core.config import PROJECT_DIR
from ..core.i18n import service as i18n, t

TERMS_VERSION = "2026-09-23"   # меняется вместе с текстом соглашения
DOCS = {"terms": ("TERMS.md", "legal.terms"), "privacy": ("PRIVACY.md", "legal.privacy")}   # файл, ключ заголовка


def _base_dir():
    if getattr(sys, "frozen", False):                      # собранная программа
        return os.path.dirname(sys.executable)
    return PROJECT_DIR


def read_doc(key):
    name, _title = DOCS[key]
    for folder in (_base_dir(), os.path.join(_base_dir(), "docs"), getattr(sys, "_MEIPASS", _base_dir())):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return t("legal.missing_file", name=name) + "\n\nhttps://github.com/leonidtimo17/AnimeApp"


def _with_note(text):
    """Документы — юридические тексты на русском; на других языках — пометка сверху."""
    return text if i18n().locale == "ru" else f"**{t('legal.russian_only')}**\n\n{text}"


def _md_to_html(text):
    """Очень простой Markdown → HTML: заголовки, списки, таблицы оставляем как есть, ссылки кликабельны."""
    import html
    import re
    out = []
    for line in html.escape(text).splitlines():
        if line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            out.append(f"<div>&nbsp;•&nbsp;{line[2:]}</div>")
        elif not line.strip():
            out.append("<br>")
        else:
            out.append(f"<div>{line}</div>")
    html_text = "\n".join(out)
    html_text = re.sub(r"`([^`]+)`", r"<code>\1</code>", html_text)
    html_text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", html_text)
    return re.sub(r"(https?://[^\s<)]+)", r'<a href="\1" style="color:#ff6a1a">\1</a>', html_text)


def show_doc(parent, key):
    """Показать документ в отдельном окне."""
    _name, title = DOCS[key]
    dlg = QDialog(parent)
    dlg.setWindowTitle(t(title))
    dlg.resize(760, 620)
    lay = QVBoxLayout(dlg)
    view = QTextBrowser()
    view.setOpenExternalLinks(True)
    view.setHtml(_md_to_html(_with_note(read_doc(key))))
    lay.addWidget(view)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    box.rejected.connect(dlg.reject)
    box.accepted.connect(dlg.accept)
    lay.addWidget(box)
    dlg.exec()


def ensure_accepted(parent, prefs):
    """Первый запуск: показать соглашение. False — пользователь не принял, программу нужно закрыть."""
    if prefs.get("terms_accepted") == TERMS_VERSION:
        return True
    dlg = QDialog(parent)
    dlg.setWindowTitle(t("legal.terms"))
    dlg.resize(760, 640)
    lay = QVBoxLayout(dlg)
    view = QTextBrowser()
    view.setOpenExternalLinks(True)
    view.setHtml(_md_to_html(_with_note(read_doc("terms") + "\n\n---\n\n" + read_doc("privacy"))))
    lay.addWidget(view)
    agree = QCheckBox(t("legal.agree"))
    lay.addWidget(agree)
    box = QDialogButtonBox()
    ok = box.addButton(t("common.continue"), QDialogButtonBox.ButtonRole.AcceptRole)
    box.addButton(t("common.quit"), QDialogButtonBox.ButtonRole.RejectRole)
    ok.setEnabled(False)
    agree.toggled.connect(ok.setEnabled)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    lay.addWidget(box)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    prefs.set("terms_accepted", TERMS_VERSION)
    return True
