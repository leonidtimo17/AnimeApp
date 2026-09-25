"""Журнал приложения: файл app.log в папке данных (до 1 МБ × 3 файла) и консоль при запуске из исходников."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(data_dir: str | None = None, level: int = logging.INFO) -> None:
    root = logging.getLogger("anime_app")
    if root.handlers:
        return
    root.setLevel(level)
    fmt = logging.Formatter(FORMAT)
    if data_dir:
        try:
            handler = RotatingFileHandler(os.path.join(data_dir, "app.log"), maxBytes=1_000_000, backupCount=3,
                                          encoding="utf-8")
            handler.setFormatter(fmt)
            root.addHandler(handler)
        except OSError:
            pass   # нет прав на запись — остаётся консоль
    if sys.stderr is not None and not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("anime_app") else f"anime_app.{name}")
