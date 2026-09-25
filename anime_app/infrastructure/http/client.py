"""HTTP-клиент приложения поверх QNetworkAccessManager (запросы асинхронные — интерфейс не ждёт сеть).

- один менеджер на всё приложение: соединения переиспользуются (keep-alive, пул на хост);
- таймаут на каждый запрос;
- повтор только временных ошибок (обрыв соединения, 429/502/503/504) с экспоненциальной паузой;
- одинаковые GET-запросы, которые уже в пути, не дублируются — ответ получат все, кто его ждёт;
- отмена: запрос прерывается, когда его результат больше никому не нужен;
- кэш: в памяти (LRU) → в SQLite (cache_ttl) → без интернета последний сохранённый ответ любой давности.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from PySide6.QtCore import QObject, QTimer, QUrl, QUrlQuery
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ...core.cache import TTLCache
from ...core.config import REQUEST_TIMEOUT_MS, USER_AGENT
from ...core.errors import ApiError, AppError, NetworkError
from ...core.logging import get_logger

log = get_logger("http")

OnOk = Callable[[Any], None]
OnErr = Callable[[AppError], None]

RETRY_STATUSES = {429, 502, 503, 504}
E = QNetworkReply.NetworkError
# Сбои, после которых стоит повторить тот же запрос. Таймаут и «сервер не найден» не повторяем:
# это долго и почти никогда не помогает (у AniLibria в этом случае переключается зеркало).
TRANSIENT_ERRORS = {E.RemoteHostClosedError, E.TemporaryNetworkFailureError, E.NetworkSessionFailedError,
                    E.ProxyConnectionClosedError, E.UnknownNetworkError}
BACKOFF_MS = 600
MAX_BACKOFF_MS = 5000


class PersistentCache(Protocol):
    def get(self, key: str, ttl: float | None) -> str | None: ...
    def put(self, key: str, body: str) -> None: ...


class ConnectivityListener(Protocol):
    def report_request(self, ok: bool) -> None: ...


@dataclass(eq=False)
class _Subscriber:
    on_ok: OnOk | None
    on_err: OnErr | None
    raw: bool
    active: bool = True


@dataclass(eq=False)
class _Call:
    """Запрос в пути (с одним или несколькими подписчиками)."""
    key: str | None
    raw: bool
    build: Callable[[], QNetworkReply]
    idempotent: bool
    retries: int
    cache_key: str | None
    cache_ttl: float
    subscribers: list[_Subscriber] = field(default_factory=list)
    reply: QNetworkReply | None = None
    attempt: int = 0
    cancelled: bool = False
    finished: bool = False


class RequestHandle:
    """Результат request(): cancel() — ответ больше не нужен этому подписчику."""

    def __init__(self, client: "HttpClient | None" = None, call: _Call | None = None, sub: _Subscriber | None = None):
        self._client, self._call, self._sub = client, call, sub

    def cancel(self) -> None:
        if not self._sub or not self._sub.active:
            return
        if self._client and self._call:
            self._client._unsubscribe(self._call, self._sub)
        else:
            self._sub.active = False   # ответ из кэша ещё не отдан — не отдаём

    @property
    def done(self) -> bool:
        return not (self._sub and self._sub.active)


class RequestScope:
    """Запросы одного экрана: cancel() отменяет те, что ещё не пришли (пользователь ушёл на другой тайтл).
    Запрос, которого ждут и другие части приложения, продолжится для них."""

    def __init__(self):
        self._handles: list[RequestHandle] = []

    def add(self, handle: RequestHandle | None) -> RequestHandle | None:
        if handle is not None and not handle.done:
            self._handles = [h for h in self._handles if not h.done] + [handle]
        return handle

    def cancel(self) -> None:
        handles, self._handles = self._handles, []
        for h in handles:
            h.cancel()


class HttpClient(QObject):
    def __init__(self, persistent: PersistentCache | None = None, parent=None, *,
                 memory: TTLCache | None = None, user_agent: str = USER_AGENT):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self.persistent = persistent
        self.memory: TTLCache[str, str] = memory or TTLCache(max_size=200, max_weight=16_000_000, weigher=len)
        self.user_agent = user_agent
        self.connectivity: ConnectivityListener | None = None
        self._inflight: dict[str, _Call] = {}
        self.stats = {"sent": 0, "deduplicated": 0, "memory_hits": 0, "disk_hits": 0, "retries": 0}

    # ------------------------------------------------------------------ публичный API
    def request(self, url: str, params: dict | None = None, on_ok: OnOk | None = None, on_err: OnErr | None = None,
                *, headers: dict | None = None, form: dict | None = None, json_body=None, method: str | None = None,
                raw: bool = False, timeout: int = REQUEST_TIMEOUT_MS, cache_ttl: float = 0, retries: int | None = None,
                scope: RequestScope | None = None) -> RequestHandle:
        """GET, POST-форма (form), POST JSON (json_body) или другой метод (method).
        raw=True — отдать текст ответа, а не разобранный JSON. on_err получает AppError."""
        qurl = build_url(url, params)
        headers = dict(headers or {})
        authorized = "Authorization" in headers
        cacheable = json_body is None and method is None and not authorized
        cache_key = None
        if cacheable:
            cache_key = qurl.toString() + ("|" + json.dumps(form, sort_keys=True, ensure_ascii=False) if form else "")
        sub = _Subscriber(on_ok, on_err, raw)

        if cache_key and cache_ttl:
            text = self._cached(cache_key, cache_ttl)
            if text is not None:
                QTimer.singleShot(0, lambda: self._deliver_text(sub, text, from_cache=True))
                return self._scoped(RequestHandle(sub=sub), scope)

        # Уже в пути такой же запрос — ждём его ответа, второй не отправляем
        if cache_key and cache_key in self._inflight:
            call = self._inflight[cache_key]
            call.subscribers.append(sub)
            call.cache_ttl = max(call.cache_ttl, cache_ttl)
            self.stats["deduplicated"] += 1
            return self._scoped(RequestHandle(self, call, sub), scope)

        def build() -> QNetworkReply:
            req = QNetworkRequest(qurl)
            req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, self.user_agent)
            req.setRawHeader(b"Accept", b"application/json")
            for k, v in headers.items():
                req.setRawHeader(k.encode(), str(v).encode())
            req.setTransferTimeout(timeout)
            if method:  # PATCH/PUT/DELETE — например, изменить запись в списке Shikimori
                req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
                body = json.dumps(json_body, ensure_ascii=False).encode("utf-8") if json_body is not None else b""
                return self.nam.sendCustomRequest(req, method.encode(), body)
            if json_body is not None:
                req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
                return self.nam.post(req, json.dumps(json_body, ensure_ascii=False).encode("utf-8"))
            if form is not None:
                req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/x-www-form-urlencoded")
                return self.nam.post(req, encode_form(form))
            return self.nam.get(req)

        idempotent = json_body is None and method in (None, "GET", "PUT", "DELETE")
        call = _Call(key=cache_key, raw=raw, build=build, idempotent=idempotent,
                     retries=(1 if idempotent else 0) if retries is None else retries,
                     cache_key=cache_key, cache_ttl=cache_ttl, subscribers=[sub])
        if cache_key:
            self._inflight[cache_key] = call
        self._send(call)
        return self._scoped(RequestHandle(self, call, sub), scope)

    def reset_connections(self) -> None:
        """После смены сети/VPN старые соединения «висят» — сбрасываем их."""
        self.nam.clearConnectionCache()

    def clear_memory(self) -> None:
        self.memory.clear()

    # ------------------------------------------------------------------ кэш
    def _cached(self, key: str, ttl: float | None) -> str | None:
        text = self.memory.get(key) if ttl is not None else None
        if text is not None:
            self.stats["memory_hits"] += 1
            return text
        if self.persistent is None:
            return None
        text = self.persistent.get(key, ttl)
        if text is not None and ttl is not None:
            self.stats["disk_hits"] += 1
            self.memory.set(key, text, ttl)
        return text

    # ------------------------------------------------------------------ отправка
    @staticmethod
    def _scoped(handle: RequestHandle, scope: RequestScope | None) -> RequestHandle:
        if scope is not None:
            scope.add(handle)
        return handle

    def _send(self, call: _Call) -> None:
        if call.cancelled:
            return
        self.stats["sent"] += 1
        reply = call.build()
        call.reply = reply
        reply.finished.connect(lambda c=call, r=reply: self._finished(c, r))

    def _unsubscribe(self, call: _Call, sub: _Subscriber) -> None:
        sub.active = False
        if sub in call.subscribers:
            call.subscribers.remove(sub)
        if call.subscribers or call.finished:
            return
        # Ответ больше никому не нужен — прерываем загрузку
        call.cancelled = True
        if call.key and self._inflight.get(call.key) is call:
            self._inflight.pop(call.key)
        if call.reply is not None and call.reply.isRunning():
            call.reply.abort()

    def _finished(self, call: _Call, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if call.cancelled:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        if error == E.NoError:
            text = bytes(reply.readAll()).decode("utf-8", "replace")
            self._report(True)
            self._complete(call, text=text)
            return

        # Временная ошибка — повторяем с нарастающей паузой
        transient = status in RETRY_STATUSES if status is not None else error in TRANSIENT_ERRORS
        if transient and call.idempotent and call.attempt < call.retries:
            delay = min(MAX_BACKOFF_MS, BACKOFF_MS * 2 ** call.attempt)
            retry_after = reply.rawHeader(b"Retry-After").data().decode() if status == 429 else ""
            if retry_after.isdigit():
                delay = min(MAX_BACKOFF_MS, int(retry_after) * 1000)
            call.attempt += 1
            self.stats["retries"] += 1
            log.info("Повтор %s через %d мс (%s)", reply.url().toString(), delay, status or reply.errorString())
            QTimer.singleShot(delay, lambda: self._send(call))
            return

        if status is None:
            self._report(False)
            # Нет сети — отдаём последний сохранённый ответ (офлайн-режим)
            stale = self._cached(call.cache_key, None) if call.cache_key else None
            if stale is not None:
                self._complete(call, text=stale, store=False)
                return
            self._complete(call, error=NetworkError(network_message(error, reply.errorString()),
                                                    transient=error in TRANSIENT_ERRORS))
            return
        self._report(True)   # сервер ответил — значит, интернет есть
        log.warning("HTTP %s: %s", status, reply.url().toString())
        self._complete(call, error=ApiError(f"HTTP {status}: {reply.errorString()}", status=int(status)))

    def _complete(self, call: _Call, *, text: str | None = None, error: AppError | None = None,
                  store: bool = True) -> None:
        call.finished = True
        if call.key and self._inflight.get(call.key) is call:
            self._inflight.pop(call.key)
        data = None
        if text is not None and error is None:
            data = text
            if not call.raw:
                try:
                    data = json.loads(text)
                except ValueError as exc:
                    error, store = ApiError(f"Некорректный ответ сервера: {exc}"), False
            # В кэш — только разобранный без ошибок ответ
            if store and error is None and call.cache_key and call.cache_ttl:
                self.memory.set(call.cache_key, text, call.cache_ttl)
                if self.persistent is not None:
                    self.persistent.put(call.cache_key, text)
        first = True
        for sub in list(call.subscribers):
            if not sub.active:
                continue
            sub.active = False
            if error is not None:
                if sub.on_err:
                    sub.on_err(error)
            elif sub.raw == call.raw and first:
                first = False            # первому — уже разобранный ответ, остальным — свою копию
                if sub.on_ok:
                    sub.on_ok(data)
            else:
                self._deliver_text(sub, text, from_cache=False, mark=False)

    def _deliver_text(self, sub: _Subscriber, text: str, *, from_cache: bool, mark: bool = True) -> None:
        if mark:
            if not sub.active:
                return
            sub.active = False
        try:
            data = text if sub.raw else json.loads(text)
        except ValueError as exc:
            if sub.on_err:
                sub.on_err(ApiError(f"Некорректный ответ сервера: {exc}"))
            return
        if sub.on_ok:
            sub.on_ok(data)

    def _report(self, ok: bool) -> None:
        if self.connectivity is not None:
            self.connectivity.report_request(ok)


def network_message(error, fallback: str) -> str:
    """Понятный текст сетевой ошибки."""
    if error in (E.OperationCanceledError, E.TimeoutError):
        return "Сервер не отвечает — проверьте интернет или VPN"
    if error in (E.HostNotFoundError, E.ConnectionRefusedError, E.UnknownNetworkError, E.NetworkSessionFailedError):
        return f"Нет соединения с сервером ({fallback})"
    return fallback


def build_url(url: str, params: dict | None) -> QUrl:
    """Адрес с параметрами; списки передаются как key[]=a&key[]=b, пустые значения пропускаются."""
    qurl = QUrl(url)
    query = QUrlQuery(qurl.query()) if qurl.hasQuery() else QUrlQuery()
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                query.addQueryItem(f"{key}[]", str(item))
        else:
            query.addQueryItem(key, str(value))
    if not query.isEmpty():
        qurl.setQuery(query)
    return qurl


def encode_form(form: dict) -> bytes:
    body = QUrlQuery()
    for k, v in form.items():
        body.addQueryItem(k, str(v).replace("+", "%2B").replace("&", "%26"))
    return body.query(QUrl.ComponentFormattingOption.FullyEncoded).encode()
