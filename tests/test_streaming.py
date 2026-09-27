"""Свой загрузчик потока: переписывание плейлиста, работа по сети и отдача плееру."""
import http.server
import socketserver
import threading
import urllib.error
import urllib.request

import pytest

from anime_app.infrastructure.streaming.proxy import StreamProxy, rewrite_playlist

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:11
#EXTINF:10.0,
https://cdn.example.com/video/a/fff0.ts
#EXTINF:10.0,
fff1.ts
#EXT-X-ENDLIST
"""


def test_rewrite_playlist_replaces_segments_and_keeps_tags():
    text, segments = rewrite_playlist(PLAYLIST, "https://cdn.example.com/video/a/list.m3u8", "/3")
    assert segments == ["https://cdn.example.com/video/a/fff0.ts", "https://cdn.example.com/video/a/fff1.ts"]
    assert "/3/0.ts" in text and "/3/1.ts" in text
    assert "#EXT-X-TARGETDURATION:11" in text and text.strip().endswith("#EXT-X-ENDLIST")
    assert "cdn.example.com" not in text        # плеер в интернет не ходит


def test_parse_path():
    assert StreamProxy.parse_path("/7.m3u8") == (7, None)
    assert StreamProxy.parse_path("/7/12.ts") == (7, 12)
    with pytest.raises(ValueError):
        StreamProxy.parse_path("/7/12.mp4")


def test_not_hls_is_left_as_is():
    proxy = StreamProxy()
    assert proxy.local_url("https://cdn.example.com/video.mp4") == "https://cdn.example.com/video.mp4"
    assert proxy.port is None                   # ради файла mp4 сервер не поднимаем


def test_unreachable_source_answers_with_error_not_hang():
    """Источник недоступен: плеер получает ошибку (приложение покажет «Повторить»), а не висит вечно."""
    proxy = StreamProxy()
    try:
        local = proxy.local_url("https://127.0.0.1:1/list.m3u8")     # сюда никто не ответит
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(local, timeout=10)
        assert err.value.code == 502
    finally:
        proxy.stop()


class _Origin:
    """Игрушечный CDN: плейлист, кусочки и переадресация — как у настоящего."""

    def __init__(self, fail_first: bool = False):
        self.hits = []
        self.fail_first = fail_first
        origin = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):                    # noqa: N802 — имя от базового класса
                origin.hits.append(self.path)
                if self.path.endswith(".m3u8"):
                    body = (f"#EXTM3U\n#EXTINF:10.0,\nhttp://127.0.0.1:{origin.port}/s0.ts\n"
                            f"#EXTINF:10.0,\nhttp://127.0.0.1:{origin.port}/s1.ts\n#EXT-X-ENDLIST\n").encode()
                    ctype = "application/vnd.apple.mpegurl"
                elif self.path == "/s0.ts":      # первый кусочек отдаём через переадресацию
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{origin.port}/real0.ts")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                elif self.path == "/real0.ts" and origin.fail_first and len(origin.hits) < 3:
                    self.send_error(503)         # сбой, который должен пережить повтор
                    return
                else:
                    body, ctype = b"G" + b"\x00" * 511, "video/mp2t"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class _PlainProxy(StreamProxy):
    """Тот же загрузчик, но по http — в тестах поднимать https незачем."""

    def _take(self, netloc):
        import http.client
        host, _, port = netloc.partition(":")
        return http.client.HTTPConnection(host, int(port), timeout=5)


def _run_stream(fail_first=False):
    origin = _Origin(fail_first)
    proxy = _PlainProxy()
    try:
        local = proxy.local_url(f"http://127.0.0.1:{origin.port}/list.m3u8")
        assert local.startswith("http://127.0.0.1:") and local.endswith(".m3u8")
        playlist = urllib.request.urlopen(local, timeout=5).read().decode()
        assert "/0.ts" in playlist and f"127.0.0.1:{origin.port}" not in playlist
        first = urllib.request.urlopen(local.replace(".m3u8", "") + "/0.ts", timeout=10).read()
        second = urllib.request.urlopen(local.replace(".m3u8", "") + "/1.ts", timeout=10).read()
        return origin, proxy, first, second
    finally:
        proxy.stop()
        origin.stop()


def test_serves_segments_and_follows_redirect():
    origin, _proxy, first, second = _run_stream()
    assert first.startswith(b"G") and len(first) == 512 and len(second) == 512
    assert "/real0.ts" in origin.hits            # переадресацию прошли мы, а не плеер


def test_retries_broken_segment():
    _origin, _proxy, first, _second = _run_stream(fail_first=True)
    assert len(first) == 512                     # с первого раза сервер ответил ошибкой — помог повтор


def test_forgets_stream_and_frees_memory():
    origin = _Origin()
    proxy = _PlainProxy()
    url = f"http://127.0.0.1:{origin.port}/list.m3u8"
    try:
        proxy.local_url(url)
        assert proxy._streams and proxy._by_url
        proxy.forget(url)
        assert not proxy._streams and not proxy._by_url
    finally:
        proxy.stop()
        origin.stop()
