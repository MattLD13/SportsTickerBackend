"""Check pooled provider reads at real HTTP connection boundaries."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import json
import socket
from threading import Lock, Thread

import pytest

from sports_ticker.providers.http import JsonHttpError, PooledJsonHttpClient, PooledTextHttpClient


pytestmark = pytest.mark.critical


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            with self.server.lock:
                self.server.paths.append(self.path)
                self.server.requests.append(dict(self.headers))
                version = self.server.versions.get(self.path, 1)
            status = 200
            headers = {}
            body = b'{"value":7}'
            if self.path in ("/etag", "/etag-no-store", "/modified"):
                body = json.dumps({"version": version}).encode()
                if self.path == "/modified":
                    validator, sent = f"Mon, 0{version} Jan 2026 00:00:00 GMT", self.headers.get("If-Modified-Since")
                    headers["Last-Modified"] = validator
                else:
                    validator, sent = f'"v{version}"', self.headers.get("If-None-Match")
                    headers["ETag"] = validator
                if self.path == "/etag-no-store":
                    headers["Cache-Control"] = "no-store"
                if sent == validator:
                    status, body = 304, b""
            elif self.path == "/gzip":
                body = json.dumps({"encoding": self.headers.get("Accept-Encoding")}).encode()
                if "gzip" in self.headers.get("Accept-Encoding", ""):
                    body = gzip.compress(body)
                    headers["Content-Encoding"] = "gzip"
            elif self.path == "/redirect":
                status, headers, body = 302, {"Location": "/json"}, b""
            elif self.path == "/loop":
                status, headers, body = 302, {"Location": "/loop"}, b""
            elif self.path == "/unavailable":
                status, headers, body = 503, {"Retry-After": "0"}, b"unavailable"
            elif self.path == "/bad-json":
                body = b"not JSON"
            elif self.path == "/bad-utf8":
                body = b"\xff"
            elif self.path == "/headers":
                body = json.dumps({"accept": self.headers["Accept"], "agent": self.headers["User-Agent"]}).encode()
            elif self.path == "/close":
                headers["Connection"] = "close"
                self.close_connection = True
            elif self.path == "/truncated":
                headers["Connection"] = "close"
                self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Length", str(len(body) + (20 if self.path == "/truncated" else 0)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def get_request(self):
            connection, address = super().get_request()
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self.lock:
                self.connections += 1
            return connection, address

    instance = Server(("127.0.0.1", 0), Handler)
    instance.lock = Lock()
    instance.connections = 0
    instance.paths = []
    instance.requests = []
    instance.versions = {}
    worker = Thread(target=lambda: instance.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    instance.url = f"http://127.0.0.1:{instance.server_port}"
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        worker.join(timeout=2)


@contextmanager
def _client(kind=PooledJsonHttpClient, **kwargs):
    client = kind(**kwargs)
    try:
        yield client
    finally:
        client.close()


def test_reuses_connections_across_threads_and_follows_redirects(server):
    with _client() as client:
        for _ in range(3):
            assert client.get_json(server.url + "/json", timeout=1) == {"value": 7}
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(client.get_json, server.url + "/redirect", timeout=1).result() == {"value": 7}
        assert server.connections == 1
        assert server.paths == ["/json", "/json", "/json", "/redirect", "/json"]


def test_concurrent_reads_preserve_each_response(server):
    with _client() as client, ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.get_json(server.url + "/json", timeout=2), range(32)))
        assert responses == [{"value": 7}] * 32
        assert 1 <= server.connections <= 8


def test_closed_connection_recovers_on_the_next_read(server):
    with _client() as client:
        assert client.get_json(server.url + "/close", timeout=1) == {"value": 7}
        assert client.get_json(server.url + "/json", timeout=1) == {"value": 7}
        assert server.connections == 2


@pytest.mark.parametrize("path,match", [
    ("/unavailable", "HTTP 503"),
    ("/truncated", "request failed"),
    ("/bad-json", "invalid JSON"),
    ("/bad-utf8", "not UTF-8"),
])
def test_failed_reads_do_not_retry_or_poison_the_next_response(server, path, match):
    with _client() as client:
        with pytest.raises(JsonHttpError, match=match):
            client.get_json(server.url + path, timeout=1)
        assert server.paths == [path]
        assert client.get_json(server.url + "/json", timeout=1) == {"value": 7}


def test_redirect_loop_has_a_fixed_limit(server):
    with _client() as client:
        with pytest.raises(JsonHttpError, match="request failed"):
            client.get_json(server.url + "/loop", timeout=1)
        assert len(server.paths) == 6


def test_json_and_text_ports_keep_their_headers(server):
    with _client(user_agent="ticker-test") as client:
        assert client.get_json(server.url + "/headers", timeout=1) == {"accept": "application/json", "agent": "ticker-test"}
    with _client(PooledTextHttpClient) as client:
        headers = json.loads(client.get_text(server.url + "/headers", timeout=1))
        assert headers["accept"] == "text/html"


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_rejects_invalid_timeouts_before_opening_a_connection(server, timeout):
    with _client() as client:
        with pytest.raises(ValueError, match="finite positive"):
            client.get_json(server.url + "/json", timeout=timeout)
        assert server.connections == 0


def test_pool_retains_verified_tls_configuration():
    import ssl

    with _client() as client:
        context = client._pool.connection_pool_kw["ssl_context"]
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname


def test_reads_ask_for_gzip_and_decode_it(server):
    with _client() as client:
        assert client.get_json(server.url + "/gzip", timeout=1) == {"encoding": "gzip, deflate"}


@pytest.mark.parametrize("path,header", [("/etag", "If-None-Match"), ("/modified", "If-Modified-Since")])
def test_unchanged_source_answers_304_and_the_client_returns_the_kept_body(server, path, header):
    with _client() as client:
        assert client.get_json(server.url + path, timeout=1) == {"version": 1}
        assert client.get_json(server.url + path, timeout=1) == {"version": 1}
        server.versions[path] = 2
        assert client.get_json(server.url + path, timeout=1) == {"version": 2}
        assert client.get_json(server.url + path, timeout=1) == {"version": 2}

    assert server.paths == [path] * 4
    sent = [request.get(header) for request in server.requests]
    assert sent[0] is None and sent[1] == sent[2] and sent[3] not in (None, sent[2])


def test_body_without_validators_or_with_no_store_is_not_kept(server):
    with _client() as client:
        for path in ("/json", "/json", "/etag-no-store", "/etag-no-store"):
            client.get_json(server.url + path, timeout=1)

    assert [request.get("If-None-Match") for request in server.requests] == [None] * 4


def test_kept_bodies_stay_within_the_size_limit(server):
    with _client(stored_characters=len('{"version": 1}')) as client:
        for path in ("/etag", "/modified", "/modified", "/etag"):
            client.get_json(server.url + path, timeout=1)

    # The limit holds one body, so the /modified body replaces the /etag body.
    assert [request.get("If-None-Match") or request.get("If-Modified-Since") for request in server.requests] == [
        None, None, "Mon, 01 Jan 2026 00:00:00 GMT", None]


def test_failed_read_after_a_kept_body_raises_and_keeps_the_body(server):
    with _client() as client:
        assert client.get_json(server.url + "/etag", timeout=1) == {"version": 1}
        with pytest.raises(JsonHttpError, match="HTTP 503"):
            client.get_json(server.url + "/unavailable", timeout=1)
        assert client.get_json(server.url + "/etag", timeout=1) == {"version": 1}

    assert server.requests[-1]["If-None-Match"] == '"v1"'
