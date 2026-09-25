"""Иконки Font Awesome Free 6 (шрифты лежат в assets/fonts, лицензия там же)."""
import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPixmap

from ..core.config import FONTS_DIR

GLYPHS = {
    "play": 0xF04B, "pause": 0xF04C, "backward-step": 0xF048, "forward-step": 0xF051,
    "forward": 0xF04E, "rotate-left": 0xF2EA, "rotate-right": 0xF2F9,
    "volume-high": 0xF028, "volume-low": 0xF027, "volume-xmark": 0xF6A9,
    "expand": 0xF065, "compress": 0xF066, "list-ul": 0xF0CA, "gear": 0xF013,
    "arrow-left": 0xF060, "window-restore": 0xF2D2,
    "house": 0xF015, "magnifying-glass": 0xF002, "calendar-days": 0xF073,
    "bookmark": 0xF02E, "clock-rotate-left": 0xF1DA,
    "heart": 0xF004, "star": 0xF005, "plus": 0x2B, "check": 0xF00C,
    "circle-play": 0xF144, "circle-check": 0xF058, "file-export": 0xF56E,
    "trash-can": 0xF2ED, "xmark": 0xF00D, "microphone": 0xF130,
    "layer-group": 0xF5FD, "film": 0xF008, "filter": 0xF0B0, "robot": 0xF544,
    "wand-magic-sparkles": 0xE2CA, "chart-simple": 0xE473, "table-cells-large": 0xF009,
    "thumbs-up": 0xF164, "sliders": 0xF1DE, "fire": 0xF06D, "moon": 0xF186, "comments": 0xF086, "link": 0xF0C1,
}

_families = {}
_cache = {}


def _family(regular: bool) -> str:
    key = "regular" if regular else "solid"
    if key not in _families:
        path = os.path.join(FONTS_DIR, "fa-regular-400.ttf" if regular else "fa-solid-900.ttf")
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _families[key] = fams[0] if fams else ""
    return _families[key]


def pixmap(name: str, color="#f2f2f5", size: int = 20, regular: bool = False) -> QPixmap:
    key = (name, QColor(color).name(QColor.NameFormat.HexArgb), size, regular)
    if key in _cache:
        return _cache[key]
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    px = int(size * max(dpr, 2.0))  # рисуем с запасом — чётко на любом масштабе
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    font = QFont(_family(regular))
    font.setPixelSize(int(px * 0.86))
    font.setWeight(QFont.Weight.Normal if regular else QFont.Weight.Black)
    p = QPainter(pix)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, chr(GLYPHS[name]))
    p.end()
    pix.setDevicePixelRatio(px / size)
    _cache[key] = pix
    return pix


def icon(name: str, color="#f2f2f5", size: int = 20, regular: bool = False) -> QIcon:
    return QIcon(pixmap(name, color, size, regular))


def toggle_icon(off: tuple, on: tuple, size: int = 20) -> QIcon:
    """Иконка для checkable-кнопок: off/on = (name, color, regular)."""
    ic = QIcon()
    ic.addPixmap(pixmap(off[0], off[1], size, off[2]), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(on[0], on[1], size, on[2]), QIcon.Mode.Normal, QIcon.State.On)
    return ic
