ACCENT = "#ff6a1a"
ACCENT_HOVER = "#ff8340"
BG = "#0f0f12"
SURFACE = "#18181d"
SURFACE_2 = "#222229"
BORDER = "#2c2c35"
TEXT = "#f2f2f5"
MUTED = "#9a9aa6"

QSS = f"""
* {{
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QWidget#Root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {BG};
}}
QWidget#Sidebar {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QLabel#Logo {{
    font-size: 22px; font-weight: 800; color: {ACCENT};
}}
QPushButton#NavButton {{
    text-align: left; padding: 10px 20px; border: none; border-radius: 8px;
    margin: 2px 10px; color: {MUTED}; font-size: 15px; background: transparent;
}}
QPushButton#NavButton:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#NavButton:checked {{ background: {SURFACE_2}; color: {TEXT}; font-weight: 600; }}

QLabel#H1 {{ font-size: 30px; font-weight: 800; }}
QLabel#H2 {{ font-size: 20px; font-weight: 700; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Chip {{
    background: {SURFACE_2}; border-radius: 12px; padding: 4px 12px; color: {TEXT}; font-size: 13px;
}}
QLabel#Rating {{ font-size: 15px; font-weight: 700; }}

QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 9px 18px; font-weight: 600;
}}
QPushButton:hover {{ background: #2c2c35; }}
QPushButton:disabled {{ color: #55555f; }}
QPushButton#Primary {{ background: {ACCENT}; border: none; color: white; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Flat {{ background: transparent; border: none; padding: 6px 10px; }}
QPushButton#Flat:hover {{ background: {SURFACE_2}; }}
QPushButton#Fav:checked {{ color: {ACCENT}; border-color: {ACCENT}; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit#Search {{ font-size: 16px; padding: 11px 16px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {SURFACE_2};
    outline: none; padding: 4px;
}}

QFrame#Card {{ background: transparent; border-radius: 12px; }}
QFrame#Card:hover {{ background: {SURFACE}; }}
QLabel#CardTitle {{ font-weight: 600; font-size: 13px; }}
QLabel#CardSub {{ color: {MUTED}; font-size: 12px; }}
QPushButton#CardAction {{
    background: rgba(12,12,16,0.78); border: 1px solid rgba(255,255,255,0.18); border-radius: 17px; padding: 0;
}}
QPushButton#CardAction:hover {{ background: rgba(40,40,48,0.95); border-color: {ACCENT}; }}
QLabel#Badge {{
    background: {ACCENT}; color: white; border-radius: 6px; padding: 2px 7px;
    font-size: 11px; font-weight: 700;
}}

QFrame#Episode {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QFrame#Episode:hover {{ border-color: {ACCENT}; }}
QFrame#Episode[current="true"] {{ border-color: {ACCENT}; }}

QFrame#Episode[missing="true"] {{ border-style: dashed; background: transparent; }}
QFrame#Upcoming {{ background: transparent; border: 1px dashed {BORDER}; border-radius: 10px; }}
QFrame#Season {{ background: transparent; border: 1px solid transparent; border-radius: 12px; }}
QFrame#Season:hover {{ background: {SURFACE}; }}
QFrame#Season[current="true"] {{ background: {SURFACE}; border-color: {ACCENT}; }}

QPushButton#Range {{ padding: 6px 12px; border-radius: 8px; font-weight: 600; }}
QPushButton#Range:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}

QScrollArea#FilterPanel, QWidget#FilterPanelBody {{ background: {SURFACE}; }}
QScrollArea#FilterPanel {{ border-right: 1px solid {BORDER}; }}
QLabel#FilterTitle {{ color: {MUTED}; font-size: 12px; font-weight: 700; margin-top: 8px; }}
QPushButton#FilterChip {{ padding: 5px 11px; border-radius: 14px; font-weight: 500; font-size: 13px;
    background: {SURFACE_2}; }}
QPushButton#FilterChip:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QFrame#Panel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#StatTile {{ background: {SURFACE_2}; border-radius: 12px; }}
QLabel#StatValue {{ font-size: 22px; font-weight: 800; }}

QFrame#HistoryRow {{ background: {SURFACE}; border-radius: 10px; }}
QFrame#HistoryRow:hover {{ background: {SURFACE_2}; }}

QProgressBar {{ background: #33333d; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QTabBar::tab {{
    background: transparent; padding: 10px 16px; color: {MUTED}; border: none;
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabWidget::pane {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3a3a44; border-radius: 5px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: #50505c; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #3a3a44; border-radius: 5px; min-width: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_2}; }}
QMenu::item:checked {{ color: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolTip {{ background: {SURFACE_2}; border: 1px solid {BORDER}; padding: 4px 8px; }}
QMessageBox {{ background: {SURFACE}; }}
"""
