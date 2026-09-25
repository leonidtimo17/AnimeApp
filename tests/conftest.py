import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(app, cond, timeout=5.0):
    """Крутить цикл событий Qt, пока cond() не станет истинным."""
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


@pytest.fixture
def db(tmp_path):
    from anime_app.infrastructure.database.connection import Database
    database = Database(str(tmp_path / "library.db"))
    yield database
    database.close()
