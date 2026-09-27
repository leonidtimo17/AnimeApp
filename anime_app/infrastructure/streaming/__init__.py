"""Доставка видео плееру: приложение само качает кусочки потока и отдаёт их с 127.0.0.1."""
from .proxy import StreamProxy, rewrite_playlist

__all__ = ["StreamProxy", "rewrite_playlist"]
