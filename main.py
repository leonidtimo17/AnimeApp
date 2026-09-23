import os
import sys


def main():
    # Отдельный процесс окна веб-плеера (озвучки через Kodik).
    if len(sys.argv) > 2 and sys.argv[1] == "--webplayer":
        from anime_app.webplayer import run
        run(sys.argv[2])
        return

    from PySide6.QtCore import QStandardPaths
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from anime_app import APP_NAME
    from anime_app.api import Api
    from anime_app.context import AppContext
    from anime_app.db import Database
    from anime_app.images import ImageLoader
    from anime_app.main_window import MainWindow
    from anime_app.sources import Sources
    from anime_app.theme import QSS

    if sys.platform == "win32":
        # Своя иконка в панели задач, а не иконка python.exe.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AnimeApp.Desktop")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "anime_app", "assets", "icon.ico")))

    data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    cache_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    api = Api()
    db = Database(os.path.join(data_dir, "library.db"))
    images = ImageLoader(os.path.join(cache_dir, "images"))
    ctx = AppContext(api, db, images, Sources(api, db), data_dir)

    window = MainWindow(ctx)
    window.show()

    # Первый запуск: пользовательское соглашение и политика конфиденциальности
    from anime_app.legal import ensure_accepted
    if not ensure_accepted(window, db):
        sys.exit(0)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
