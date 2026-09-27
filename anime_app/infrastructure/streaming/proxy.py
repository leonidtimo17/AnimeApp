"""Свой загрузчик потока: кусочки видео качает приложение, плеер читает их с 127.0.0.1.

Зачем. Встроенный загрузчик Qt ходит за каждым кусочком сам: новое соединение, переадресация
cache.libria.fun → cacheN.libria.fun с подписью, и только потом данные. На медленном канале
(VPN — это +1,5–2 секунды на каждый запрос) он рано или поздно встаёт совсем: перестаёт качать,
об ошибке не сообщает, и видео замирает намертво.

Здесь запросы делаем мы: соединения переиспользуются, следующий кусочек качается заранее,
зависший запрос обрывается по таймауту и повторяется. Плееру остаётся чтение с локального адреса,
где задержек нет. Замер на живом потоке: 18 % реального времени напрямую против 95 % через загрузчик.

Модуль намеренно на стандартной библиотеке (без Qt): его можно проверить тестами без окна и без сети.
"""
from __future__ import annotations

import http.client
import http.server
import socketserver
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from ...core.logging import get_logger

log = get_logger("streaming")


def _close(conn) -> None:
    try:
        conn.close()
    except OSError:
        pass

PREFETCH = 2               # сколько кусочков качаем заранее
KEEP_BEHIND = 1            # сколько уже просмотренных держим (перемотка чуть назад)
CACHE_BYTES = 96_000_000   # потолок памяти под кусочки
TIMEOUT = 8                # секунд на запрос — дальше обрываем и пробуем снова
RETRIES = 2
MAX_REDIRECTS = 3


def rewrite_playlist(text: str, playlist_url: str, local_prefix: str) -> tuple[str, list[str]]:
    """Плейлист с локальными адресами кусочков + список их настоящих адресов.

    local_prefix — начало локального адреса, например «/7». Кусочки получают имена вида «/7/0.ts»:
    расширение обязательно, иначе плеер не понимает, что это поток MPEG-TS.
    """
    out, segments = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        segments.append(urllib.parse.urljoin(playlist_url, stripped))
        out.append(f"{local_prefix}/{len(segments) - 1}.ts")
    return "\n".join(out) + "\n", segments


class _Stream:
    """Один поток: адрес плейлиста, адреса кусочков и те из них, что уже лежат в памяти.

    Плейлист скачивается не при открытии серии, а когда его попросит плеер: иначе на медленном
    канале окно приложения замирало бы на секунду-другую при каждом запуске серии.
    """

    def __init__(self, sid: int, upstream: str):
        self.sid = sid
        self.upstream = upstream
        self.playlist: bytes | None = None
        self.segments: list[str] = []
        self.data: dict[int, bytes] = {}
        self.pending: set[int] = set()
        self.lock = threading.Lock()
        self.ready = threading.Condition(self.lock)
        self.prepare_lock = threading.Lock()

    def size(self) -> int:
        return sum(len(v) for v in self.data.values())

    def forget_old(self, current: int) -> None:
        """Освобождаем память: просмотренное далеко позади не нужно, и держимся в пределах потолка."""
        for i in [i for i in self.data if i < current - KEEP_BEHIND]:
            self.data.pop(i, None)
        while self.size() > CACHE_BYTES and len(self.data) > 1:
            self.data.pop(min(self.data), None)


class StreamProxy:
    """Локальный сервер: отдаёт плееру плейлист и кусочки, а в интернет ходит сам.

    fetch_playlist — чем скачать плейлист (по умолчанию тем же способом, что и кусочки).
    """

    def __init__(self, user_agent: str = "AnimeApp", host: str = "127.0.0.1"):
        self.user_agent = user_agent
        self.host = host
        self.port: int | None = None
        self._streams: dict[int, _Stream] = {}
        self._by_url: dict[str, int] = {}
        self._next_id = 0
        self._conns: dict[str, list[http.client.HTTPConnection]] = {}
        self._conn_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="segments")
        self._server: socketserver.TCPServer | None = None

    # ------------------------------------------------------------------ загрузка из сети
    def _take(self, netloc: str) -> http.client.HTTPConnection:
        """Свободное соединение к хосту (их несколько — кусочки качаются параллельно)."""
        with self._conn_lock:
            free = self._conns.setdefault(netloc, [])
            if free:
                return free.pop()
        host, _, port = netloc.partition(":")
        return http.client.HTTPSConnection(host, int(port) if port else 443, timeout=TIMEOUT)

    def _put_back(self, netloc: str, conn: http.client.HTTPConnection) -> None:
        with self._conn_lock:
            free = self._conns.setdefault(netloc, [])
            if len(free) < 4:
                free.append(conn)
                return
        _close(conn)

    def download(self, url: str) -> bytes:
        """Скачивает адрес, переиспользуя соединения; сам идёт по переадресациям и повторяет при сбое."""
        last: Exception | None = None
        for _ in range(RETRIES + 1):
            try:
                return self._download_once(url)
            except Exception as exc:  # noqa: BLE001 — любая сетевая беда: пробуем ещё раз на новом соединении
                last = exc
        raise last if last else RuntimeError(url)

    def _download_once(self, url: str, depth: int = 0) -> bytes:
        parts = urllib.parse.urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        conn = self._take(parts.netloc)
        try:
            conn.request("GET", path, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
            resp = conn.getresponse()
            status, location = resp.status, resp.getheader("Location")
            reusable = resp.getheader("Connection", "").lower() != "close"
            body = resp.read()
        except Exception:
            _close(conn)
            raise
        if reusable:
            self._put_back(parts.netloc, conn)
        else:
            _close(conn)
        if status in (301, 302, 303, 307, 308) and location and depth < MAX_REDIRECTS:
            return self._download_once(urllib.parse.urljoin(url, location), depth + 1)
        if status != 200:
            raise OSError(f"{status} {url}")
        return body

    # ------------------------------------------------------------------ кусочки
    def _segment(self, stream: _Stream, index: int) -> bytes:
        with stream.lock:
            if index in stream.data:
                data = stream.data[index]
                stream.forget_old(index)
                return data
            if index in stream.pending:
                while index not in stream.data:
                    if not stream.ready.wait(TIMEOUT * (RETRIES + 2)):
                        raise TimeoutError(f"кусочек {index} так и не пришёл")
                return stream.data[index]
            stream.pending.add(index)
        try:
            data = self.download(stream.segments[index])
        except Exception:
            with stream.lock:
                stream.pending.discard(index)
                stream.ready.notify_all()
            raise
        with stream.lock:
            stream.data[index] = data
            stream.pending.discard(index)
            stream.forget_old(index)
            stream.ready.notify_all()
        return data

    def _prefetch(self, stream: _Stream, index: int) -> None:
        for i in range(index + 1, min(index + 1 + PREFETCH, len(stream.segments))):
            with stream.lock:
                if i in stream.data or i in stream.pending:
                    continue
            self._pool.submit(self._quiet, stream, i)

    def _quiet(self, stream: _Stream, index: int) -> None:
        try:
            self._segment(stream, index)
        except Exception as exc:  # noqa: BLE001 — заранее качаем «на удачу», ошибку просто запоминаем
            log.debug("не удалось скачать кусочек %s заранее: %s", index, exc)

    # ------------------------------------------------------------------ сервер
    def start(self) -> int:
        if self.port is not None:
            return self.port
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):    # молчим: своё пишем через журнал приложения
                pass

            def _send(self, data: bytes, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):                # noqa: N802 — имя задано базовым классом
                try:
                    sid, index = proxy.parse_path(self.path)
                except ValueError:
                    self.send_error(404)
                    return
                stream = proxy._streams.get(sid)
                if stream is None:
                    self.send_error(404)
                    return
                try:
                    proxy.prepare(stream)
                except Exception as exc:  # noqa: BLE001 — плейлист не скачался: плеер покажет ошибку и повторит
                    log.info("плейлист не скачался: %s", exc)
                    self.send_error(502)
                    return
                if index is None:
                    self._send(stream.playlist, "application/vnd.apple.mpegurl")
                    return
                try:
                    data = proxy._segment(stream, index)
                except Exception as exc:  # noqa: BLE001 — плееру нужен ответ, а не исключение в потоке
                    log.info("кусочек %s не скачался: %s", index, exc)
                    self.send_error(502)
                    return
                proxy._prefetch(stream, index)
                try:
                    self._send(data, "video/mp2t")
                except (ConnectionError, OSError):
                    pass                      # плеер закрыл соединение (перемотка, смена серии)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server((self.host, 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True, name="stream-proxy").start()
        log.info("Загрузчик потока слушает %s:%s", self.host, self.port)
        return self.port

    @staticmethod
    def parse_path(path: str) -> tuple[int, int | None]:
        """«/7.m3u8» → (7, None); «/7/12.ts» → (7, 12)."""
        path = path.split("?")[0].strip("/")
        if path.endswith(".m3u8"):
            return int(path[:-5]), None
        sid, _, seg = path.partition("/")
        if not seg.endswith(".ts"):
            raise ValueError(path)
        return int(sid), int(seg[:-3])

    # ------------------------------------------------------------------ публичное
    def prepare(self, stream: _Stream) -> None:
        """Скачать и переписать плейлист (один раз на поток); сразу начать качать первый кусочек."""
        if stream.playlist is not None:
            return
        with stream.prepare_lock:
            if stream.playlist is not None:
                return
            text = self.download(stream.upstream).decode("utf-8", "replace")
            playlist, segments = rewrite_playlist(text, stream.upstream, f"/{stream.sid}")
            if not segments:
                raise OSError(f"в плейлисте нет кусочков: {stream.upstream}")
            stream.segments = segments
            stream.playlist = playlist.encode("utf-8")
        self._pool.submit(self._quiet, stream, 0)

    def local_url(self, url: str) -> str:
        """Адрес того же потока, но на 127.0.0.1. Не HLS или сервер не поднялся — исходный адрес.

        Возвращается сразу: в сеть за плейлистом сходим, когда его попросит плеер.
        """
        if ".m3u8" not in url.split("?")[0]:
            return url
        try:
            port = self.start()
        except OSError as exc:
            log.warning("Загрузчик потока не запустился (%s) — плеер будет качать сам", exc)
            return url
        sid = self._by_url.get(url)
        if sid is None:
            sid = self._next_id
            self._next_id += 1
            self._streams[sid] = _Stream(sid, url)
            self._by_url[url] = sid
        return f"http://{self.host}:{port}/{sid}.m3u8"

    def forget(self, url: str) -> None:
        """Забыть поток (сменили серию или озвучку) — освобождаем память."""
        sid = self._by_url.pop(url, None)
        if sid is not None:
            self._streams.pop(sid, None)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self.port = None
        with self._conn_lock:
            for free in self._conns.values():
                for conn in free:
                    _close(conn)
            self._conns.clear()
        self._streams.clear()
        self._by_url.clear()
