"""HttpClient против локального HTTP-сервера: дедупликация, отмена, повторы, кэш, офлайн."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from anime_app.core.errors import ApiError, NetworkError
from anime_app.infrastructure.http.client import HttpClient, RequestScope
from tests.conftest import wait_until


class MemoryStore:
    def __init__(self):
        self.data = {}

    def get(self, key, ttl):
        item = self.data.get(key)
        if not item or (ttl is not None and time.time() - item[0] > ttl):
            return None
        return item[1]

    def put(self, key, body):
        self.data[key] = (time.time(), body)


class Server:
    def __init__(self):
        self.hits = {}
        self.plan = {}         # путь -> список кодов ответа по очереди (последний повторяется)
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                path = self.path.split("?")[0]
                server.hits[path] = server.hits.get(path, 0) + 1
                if path == "/slow":
                    time.sleep(0.4)
                codes = server.plan.get(path, [200])
                code = codes.pop(0) if len(codes) > 1 else codes[0]
                body = b"<html>oops</html>" if path == "/html" else json.dumps({"path": self.path}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = Server()
    yield s
    s.stop()


@pytest.fixture
def client(qapp):
    c = HttpClient(MemoryStore())
    yield c
    c.deleteLater()


def test_get_parses_json_and_encodes_list_params(qapp, client, server):
    got = []
    client.request(f"{server.url}/a", {"f[types]": ["TV", "OVA"], "empty": None}, got.append)
    assert wait_until(qapp, lambda: got)
    assert "f[types][]=TV&f[types][]=OVA" in got[0]["path"] and "empty" not in got[0]["path"]


def test_identical_requests_are_deduplicated(qapp, client, server):
    got = []
    for _ in range(3):
        client.request(f"{server.url}/slow", None, got.append, cache_ttl=60)
    assert wait_until(qapp, lambda: len(got) == 3)
    assert server.hits["/slow"] == 1 and client.stats["deduplicated"] == 2
    got[0]["mutated"] = True
    assert "mutated" not in got[1]          # каждый получил свою копию


def test_cache_ttl_memory_and_persistent(qapp, client, server):
    got = []
    client.request(f"{server.url}/c", None, got.append, cache_ttl=60)
    assert wait_until(qapp, lambda: got)
    client.request(f"{server.url}/c", None, got.append, cache_ttl=60)
    assert wait_until(qapp, lambda: len(got) == 2)
    assert server.hits["/c"] == 1 and client.stats["memory_hits"] == 1
    client.clear_memory()
    client.request(f"{server.url}/c", None, got.append, cache_ttl=60)
    assert wait_until(qapp, lambda: len(got) == 3)
    assert server.hits["/c"] == 1 and client.stats["disk_hits"] == 1
    client.request(f"{server.url}/c", None, got.append)       # без cache_ttl — всегда в сеть
    assert wait_until(qapp, lambda: len(got) == 4)
    assert server.hits["/c"] == 2


def test_cancel_stops_callbacks_and_scope(qapp, client, server):
    got, errors = [], []
    handle = client.request(f"{server.url}/slow", None, got.append, errors.append)
    handle.cancel()
    scope = RequestScope()
    client.request(f"{server.url}/slow?b=1", None, got.append, errors.append, scope=scope)
    scope.cancel()
    wait_until(qapp, lambda: False, timeout=0.8)
    assert got == [] and errors == []


def test_cancel_one_subscriber_keeps_request_for_others(qapp, client, server):
    first, second = [], []
    h1 = client.request(f"{server.url}/slow", None, first.append, cache_ttl=60)
    client.request(f"{server.url}/slow", None, second.append, cache_ttl=60)
    h1.cancel()
    assert wait_until(qapp, lambda: second)
    assert first == [] and server.hits["/slow"] == 1


def test_retry_transient_status_with_backoff(qapp, client, server):
    server.plan["/flaky"] = [503, 200]
    got = []
    client.request(f"{server.url}/flaky", None, got.append)
    assert wait_until(qapp, lambda: got, timeout=5)
    assert server.hits["/flaky"] == 2 and client.stats["retries"] == 1


def test_client_errors_are_not_retried(qapp, client, server):
    server.plan["/missing"] = [404]
    errors = []
    client.request(f"{server.url}/missing", None, None, errors.append)
    assert wait_until(qapp, lambda: errors)
    assert isinstance(errors[0], ApiError) and errors[0].status == 404 and errors[0].is_client_error
    assert server.hits["/missing"] == 1


def test_invalid_json_is_an_error_and_not_cached(qapp, client, server):
    errors = []
    client.request(f"{server.url}/html", None, None, errors.append, cache_ttl=60)
    assert wait_until(qapp, lambda: errors)
    assert isinstance(errors[0], ApiError) and "Некорректный ответ" in str(errors[0])
    assert not client.persistent.data


def test_offline_returns_stale_cache(qapp, client, server):
    got = []
    url = f"{server.url}/stale"
    client.request(url, None, got.append, cache_ttl=1)
    assert wait_until(qapp, lambda: got)
    server.stop()
    client.clear_memory()
    client.persistent.data[url] = (time.time() - 100, client.persistent.data[url][1])   # устарел
    client.reset_connections()
    client.request(url, None, got.append, cache_ttl=1)
    assert wait_until(qapp, lambda: len(got) == 2, timeout=8)
    assert got[1]["path"] == "/stale"


def test_offline_without_cache_is_network_error(qapp, client):
    errors = []
    client.request("http://127.0.0.1:9/nothing", None, None, errors.append, retries=0)
    assert wait_until(qapp, lambda: errors, timeout=8)
    assert isinstance(errors[0], NetworkError)


def test_connectivity_is_reported(qapp, client, server):
    reports = []

    class Listener:
        def report_request(self, ok):
            reports.append(ok)
    client.connectivity = Listener()
    got = []
    client.request(f"{server.url}/ok", None, got.append)
    assert wait_until(qapp, lambda: got)
    assert reports == [True]
