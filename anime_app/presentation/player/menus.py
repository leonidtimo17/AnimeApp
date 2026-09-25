"""Меню плееров (встроенного и Kodik): озвучки, сезоны, таймер сна; стиль панели управления."""
from __future__ import annotations

from ...domain.dubs import menu_groups
from ...domain.sleep_timer import SleepTimer
from ..theme import ACCENT
from ...core.i18n import t


def fill_dub_menu(menu, dubs, current_id, on_pick):
    """Меню озвучек: встроенный плеер / Kodik-озвучка / Kodik-субтитры."""
    menu.clear()
    for title, items in menu_groups(dubs):
        head = menu.addAction(f"{title}  ({len(items)})")
        head.setEnabled(False)
        for d in items:
            act = menu.addAction(d["name"], lambda d=d: on_pick(d))
            act.setCheckable(True)
            act.setChecked(d["id"] == current_id)
        menu.addSeparator()
    if not dubs:
        menu.addAction(t("dubs.searching_short")).setEnabled(False)


def fill_season_menu(menu, entries, on_pick):
    menu.clear()
    for e in entries:
        text = f"{e['label']} · {e.get('year') or t('anime.announced').lower()} — {e.get('name') or ''}"
        act = menu.addAction(text, lambda e=e: on_pick(e))
        act.setCheckable(True)
        act.setChecked(bool(e.get("current")))
    if not entries:
        menu.addAction(t("anime.no_other_seasons")).setEnabled(False)


def fill_sleep_menu(menu, sleep: SleepTimer, on_change):
    """Меню таймера сна. on_change(text) — показать подсказку."""
    menu.clear()
    left = sleep.minutes_left()
    if left:
        menu.addSection(t("sleep.left", n=left))
    for text, minutes, episode, on in sleep.menu_items():
        act = menu.addAction(text, lambda m=minutes, e=episode: on_change(sleep.set(m, e)))
        act.setCheckable(True)
        act.setChecked(on)


OVERLAY_QSS = f"""
QWidget {{ color: white; font-family: "Segoe UI"; }}
QFrame#TopBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(0,0,0,190), stop:1 rgba(0,0,0,0)); }}
QFrame#BottomBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(0,0,0,0), stop:1 rgba(0,0,0,215)); }}
QPushButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px 10px;
               font-size: 17px; font-weight: 600; min-width: 26px; }}
QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
QPushButton#Icon {{ padding: 9px 11px; }}
QPushButton#Pill {{ background: rgba(20,20,24,0.88); border: 1px solid rgba(255,255,255,0.25);
                    border-radius: 12px; padding: 12px 22px; font-size: 15px; }}
QPushButton#Pill:hover {{ background: rgba(255,255,255,0.95); color: black; }}
QPushButton#PillAccent {{ background: {ACCENT}; border-radius: 12px; padding: 12px 22px; font-size: 15px; }}
QPushButton#PillAccent:hover {{ background: #ff8340; }}
QLabel#Title {{ font-size: 19px; font-weight: 700; }}
QLabel#Sub {{ font-size: 14px; color: rgba(255,255,255,0.75); }}
QLabel#Time {{ font-size: 14px; font-weight: 600; }}
QLabel#Osd {{ background: rgba(0,0,0,0.65); border-radius: 14px; padding: 14px 24px;
              font-size: 20px; font-weight: 700; }}
QLabel#SeekTip {{ background: rgba(0,0,0,0.8); border-radius: 6px; padding: 3px 8px; font-weight: 600; }}
QSlider#Volume::groove:horizontal {{ height: 4px; background: rgba(255,255,255,0.3); border-radius: 2px; }}
QSlider#Volume::sub-page:horizontal {{ background: white; border-radius: 2px; }}
QSlider#Volume::handle:horizontal {{ background: white; width: 12px; margin: -4px 0; border-radius: 6px; }}
QListWidget {{ background: rgba(16,16,20,0.94); border: none; border-left: 1px solid rgba(255,255,255,0.1);
               font-size: 14px; padding: 8px; outline: none; }}
QListWidget::item {{ padding: 11px 12px; border-radius: 8px; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.08); }}
QListWidget::item:selected {{ background: rgba(255,106,26,0.25); color: white; }}
QMenu {{ background: #1c1c22; border: 1px solid #333; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; color: white; }}
QMenu::item:selected {{ background: #2c2c35; }}
QMenu::item:checked {{ color: {ACCENT}; }}
"""
