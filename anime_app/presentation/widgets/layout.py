"""Базовые элементы раскладки: поток, подписи, прокручиваемая страница."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..icons import pixmap


class FlowLayout(QLayout):
    """Элементы в строку с переносом (как flex-wrap)."""

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


class ExpandingLabel(QLabel):
    def __init__(self, text="", obj=None):
        super().__init__(text)
        if obj:
            self.setObjectName(obj)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


def scroll_page():
    """Возвращает (scroll_area, content_layout) с отступами как у страниц."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(32, 28, 32, 32)
    lay.setSpacing(24)
    area.setWidget(host)
    return area, lay


class Page(QWidget):
    """Экран главного окна. on_show() вызывается при каждом показе."""

    def on_show(self):
        pass


def scroll_page_widget(page: QWidget):
    """Сделать страницу прокручиваемой; возвращает (area, layout содержимого)."""
    area, lay = scroll_page()
    QVBoxLayout(page).setContentsMargins(0, 0, 0, 0)
    page.layout().addWidget(area)
    return area, lay
