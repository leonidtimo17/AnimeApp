"""ИИ-разбор вкуса: локальная Ollama (приватно, офлайн), если установлена, иначе бесплатный Pollinations без ключа."""
from __future__ import annotations

from ...core.config import OLLAMA, POLLINATIONS
from ..http.client import HttpClient


class AiApi:
    def __init__(self, http: HttpClient):
        self.http = http

    def ollama_models(self, on_ok, on_err):
        """Список моделей локальной Ollama (быстрый отказ, если её нет)."""
        self.http.request(f"{OLLAMA}/api/tags", None,
                          lambda tags: on_ok([m["name"] for m in (tags or {}).get("models") or []]),
                          on_err, timeout=1500, retries=0)

    def ollama(self, model: str, system: str, prompt: str, on_ok, on_err):
        body = {"model": model, "system": system, "prompt": prompt, "stream": False, "format": "json"}
        self.http.request(f"{OLLAMA}/api/generate", None, lambda d: on_ok(d.get("response", "")), on_err,
                          json_body=body, timeout=180_000)

    def pollinations(self, system: str, prompt: str, seed: int, on_ok, on_err):
        body = {"model": "openai", "jsonMode": True, "private": True, "seed": seed,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        self.http.request(POLLINATIONS, None, on_ok, on_err, json_body=body, timeout=90_000, raw=True)
