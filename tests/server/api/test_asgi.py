"""Verify HTTP contracts and runtime ownership at the ASGI serving boundary."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from threading import Event, Lock, get_ident
from threading import enumerate as enumerate_threads

import pytest
from asgiref.testing import ApplicationCommunicator
from flask import request

from ticker.server import main as server
from ticker.server.api import asgi
from ticker.server.offline import create_offline_application

pytestmark = pytest.mark.critical


def _offline(path):
    """Return an offline application. TickerASGI reads its backend application."""
    return create_offline_application(path, [])


def _no_engine(flask):
    return lambda: None


def _http_scope(method, path, headers=()):
    return {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "root_path": "",
        "query_string": b"", "headers": list(headers),
        "server": ("localhost", 5000), "client": ("127.0.0.1", 40000),
    }


async def _request(app, method, path, *, body=b"", headers=()):
    communicator = ApplicationCommunicator(app, _http_scope(method, path, headers))
    await communicator.send_input({"type": "http.request", "body": body})
    start = await communicator.receive_output(timeout=5)
    content = b""
    while True:
        message = await communicator.receive_output(timeout=5)
        content += message.get("body", b"")
        if not message.get("more_body", False):
            break
    await communicator.wait()
    return start["status"], dict(start["headers"]), content


@pytest.mark.parametrize("limit", [2, 8])
def test_asgi_runs_flask_requests_concurrently_with_a_bounded_limit(limit, tmp_path):
    """Fill every HTTP slot, keep the next request queued, and preserve separate Flask request contexts."""

    flask = _offline(tmp_path / "concurrency.sqlite3")
    release = [Event() for _ in range(limit + 1)]
    lock = Lock()
    active = 0
    maximum = 0
    threads = set()
    admitted = []

    async def verify():
        nonlocal active, maximum
        loop = asyncio.get_running_loop()
        entered = asyncio.Queue()
        dispatched = asyncio.Queue()

        @flask.get("/request/<int:identifier>")
        def blocked(identifier):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                threads.add(get_ident())
            loop.call_soon_threadsafe(entered.put_nowait, identifier)
            try:
                assert release[identifier].wait(5)
                return {"identifier": identifier, "path": request.path}
            finally:
                with lock:
                    active -= 1

        adapted = asgi.TickerASGI(flask, start=_no_engine, http_threads=limit)
        real_http = adapted.http

        async def observe_http(scope, receive, send):
            admitted.append(scope["path"])
            await real_http(scope, receive, send)

        adapted.http = observe_http

        async def observe_dispatch(scope, receive, send):
            dispatched.put_nowait(scope["path"])
            await adapted(scope, receive, send)

        tasks = [asyncio.create_task(_request(observe_dispatch, "GET", f"/request/{identifier}")) for identifier in range(limit)]
        try:
            first = {await asyncio.wait_for(entered.get(), 5) for _ in range(limit)}
            assert first == set(range(limit))
            assert maximum == limit
            assert len(threads) == limit
            for _ in range(limit):
                await dispatched.get()
            tasks.append(asyncio.create_task(_request(observe_dispatch, "GET", f"/request/{limit}")))
            assert await asyncio.wait_for(dispatched.get(), 5) == f"/request/{limit}"
            assert len(admitted) == limit
            release[0].set()
            assert (await tasks[0])[0] == 200
            assert await asyncio.wait_for(entered.get(), 5) == limit
            assert maximum == limit
        finally:
            for gate in release:
                gate.set()
            results = await asyncio.gather(*tasks)
        for identifier, (status, _, body) in enumerate(results):
            assert status == 200
            assert json.loads(body) == {"identifier": identifier, "path": f"/request/{identifier}"}
        assert active == 0

    asyncio.run(verify())


def test_cancelled_http_request_keeps_its_slot_until_the_worker_stops(monkeypatch, tmp_path):
    """Keep the event loop responsive and retain the concurrency permit during cancelled worker cleanup."""

    flask = _offline(tmp_path / "cancelled.sqlite3")
    release = Event()

    async def verify():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        cleanup_started = asyncio.Event()
        dispatched = asyncio.Event()
        admitted = []
        real_context = asgi.ThreadSensitiveContext

        class ObservedContext(real_context):
            async def __aexit__(self, exc, value, tb):
                cleanup_started.set()
                await super().__aexit__(exc, value, tb)

        monkeypatch.setattr(asgi, "ThreadSensitiveContext", ObservedContext)

        @flask.get("/blocked")
        def blocked():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return {"finished": True}

        @flask.get("/next")
        def next_request():
            return {"next": True}

        adapted = asgi.TickerASGI(flask, start=_no_engine, http_threads=1)
        real_http = adapted.http

        async def observe_http(scope, receive, send):
            admitted.append(scope["path"])
            await real_http(scope, receive, send)

        adapted.http = observe_http
        first = ApplicationCommunicator(adapted, _http_scope("GET", "/blocked"))
        second = None
        try:
            await first.send_input({"type": "http.request", "body": b""})
            await asyncio.wait_for(entered.wait(), 5)
            first.future.cancel()
            await asyncio.wait_for(cleanup_started.wait(), 5)

            async def observe_dispatch(scope, receive, send):
                dispatched.set()
                await adapted(scope, receive, send)

            second = asyncio.create_task(_request(observe_dispatch, "GET", "/next"))
            await asyncio.wait_for(dispatched.wait(), 5)
            assert admitted == ["/blocked"]
        finally:
            release.set()
            await first.wait(timeout=5)
            if second is not None:
                status, _, body = await second
                assert status == 200
                assert json.loads(body) == {"next": True}
        assert admitted == ["/blocked", "/next"]

    asyncio.run(verify())


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_asgi_rejects_invalid_http_thread_settings_before_creating_state(monkeypatch, value):
    """Reject invalid concurrency settings before opening the production database."""

    monkeypatch.setenv("TICKER_HTTP_THREADS", value)
    monkeypatch.setattr(server, "create_application", lambda path: pytest.fail("application factory ran"))
    with pytest.raises(ValueError):
        server.create_asgi_application()


def test_asgi_factory_preserves_http_thread_environment_setting(monkeypatch, tmp_path):
    """Pass the deployment concurrency setting into the bounded HTTP bridge."""

    monkeypatch.setenv("TICKER_HTTP_THREADS", "3")
    monkeypatch.setattr(server, "create_application", lambda path: _offline(tmp_path / "factory.sqlite3"))
    application = server.create_asgi_application()
    assert application.slots._value == 3 and application.start is server.start_engine


def test_asgi_preserves_http_health_security_and_mutation_contracts(tmp_path, monkeypatch):
    """Compare real Flask results with ASGI for health, authorization, and durable mutations."""

    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "deployment-secret")
    monkeypatch.setattr("ticker.server.store.repository.time.time", lambda: 1000)
    flask = create_offline_application(tmp_path / "asgi.sqlite3", [], clock=lambda: 1000)
    adapted = asgi.TickerASGI(flask, start=_no_engine)
    client = flask.test_client()
    registered = client.post("/register", json={"device_id": "asgi-device"}, headers={"X-Device-Token": "a" * 64}).get_json()
    paired = client.post("/pair", json={"pairing_code": registered["pairing_code"]}).get_json()
    auth = ((b"authorization", f"Bearer {paired['controller_token']}".encode()),)

    async def verify():
        cases = [
            ("GET", "/health", b"", ()),
            ("GET", "/fleet", b"", ()),
            ("GET", "/fleet", b"", ((b"x-deployment-token", b"wrong"),)),
            ("GET", "/fleet", b"", ((b"x-deployment-token", b"deployment-secret"),)),
            ("GET", "/tickers", b"", ()),
            ("GET", "/tickers", b"", ((b"authorization", b"Bearer invalid"),)),
            ("GET", "/tickers", b"", auth),
            ("GET", "/tickers/asgi-device/data", b"", ()),
            ("GET", "/data", b"", ((b"x-device-token", b"a" * 64),)),
            ("GET", "/data", b"", ((b"x-device-token", b"b" * 64),)),
            ("PATCH", "/tickers/asgi-device", b'{"name":"Updated"}', auth),
            ("POST", "/register", b"{invalid", ()),
            ("GET", "/api/v2/unknown", b"", ()),
        ]
        for method, path, body, headers in cases:
            if body:
                headers += ((b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()))
            expected = client.open(path, method=method, data=body, headers={k.decode(): v.decode() for k, v in headers})
            status, response_headers, content = await _request(adapted, method, path, body=body, headers=headers)
            assert status == expected.status_code
            assert response_headers[b"content-type"].decode() == expected.content_type
            if expected.is_json:
                assert json.loads(content) == expected.get_json()
            else:
                assert content == expected.data
        assert flask.extensions["ticker.application"].get_ticker("asgi-device").name == "Updated"

    try:
        asyncio.run(verify())
    finally:
        flask.extensions["ticker.application"].close()


def test_asgi_lifespan_starts_the_engine_and_the_stream_once(tmp_path):
    """Start the engine and the stream projector at startup, and stop both at shutdown."""

    flask = _offline(tmp_path / "lifespan.sqlite3")
    calls = []

    def start(app):
        assert app is flask
        calls.append("start")
        return lambda: calls.append("stop")

    application = asgi.TickerASGI(flask, start=start)

    async def verify():
        communicator = ApplicationCommunicator(application, {"type": "lifespan"})
        await communicator.send_input({"type": "lifespan.startup"})
        assert await communicator.receive_output() == {"type": "lifespan.startup.complete"}
        assert application.hub._wake is not None
        assert (await _request(application, "GET", "/health"))[0] == 200
        await communicator.send_input({"type": "lifespan.shutdown"})
        assert await communicator.receive_output(timeout=10) == {"type": "lifespan.shutdown.complete"}
        await communicator.wait()
        assert application.hub._wake is None

    try:
        asyncio.run(verify())
    finally:
        flask.extensions["ticker.application"].close()
    assert calls == ["start", "stop"]


@pytest.mark.parametrize("failure", ["startup", "shutdown", "cancel"])
def test_asgi_lifespan_reports_failures_and_cleans_up_once(tmp_path, failure):
    """Report lifecycle errors and stop an interrupted lifespan exactly once."""

    calls = []

    def start(flask):
        calls.append("start")
        if failure == "startup":
            raise RuntimeError("startup rejected")

        def stop():
            calls.append("stop")
            if failure == "shutdown":
                raise RuntimeError("shutdown rejected")

        return stop

    flask = _offline(tmp_path / "failure.sqlite3")

    async def verify():
        communicator = ApplicationCommunicator(asgi.TickerASGI(flask, start=start), {"type": "lifespan"})
        await communicator.send_input({"type": "lifespan.startup"})
        response = await communicator.receive_output()
        if failure == "startup":
            assert response == {"type": "lifespan.startup.failed", "message": "startup rejected"}
        else:
            assert response == {"type": "lifespan.startup.complete"}
            if failure == "cancel":
                communicator.future.cancel()
            else:
                await communicator.send_input({"type": "lifespan.shutdown"})
                assert await communicator.receive_output() == {"type": "lifespan.shutdown.failed", "message": "shutdown rejected"}
        await communicator.wait()

    try:
        asyncio.run(verify())
    finally:
        flask.extensions["ticker.application"].close()
    assert calls == (["start"] if failure == "startup" else ["start", "stop"])


def test_asgi_import_has_no_database_or_runtime_side_effects(tmp_path):
    """Import the serving modules without creating durable state or starting refresh work."""

    script = (
        "import os, threading; from pathlib import Path; "
        f"os.environ['TICKER_DATABASE_PATH'] = {str(tmp_path / 'unused.sqlite3')!r}; "
        "import ticker.server.main, ticker.server.api.asgi; "
        "assert not Path(os.environ['TICKER_DATABASE_PATH']).exists(); "
        "assert threading.active_count() == 1"
    )
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("host, expected", [("127.0.0.1", "127.0.0.1:5000"), ("0.0.0.0", "0.0.0.0:5000"), ("::1", "[::1]:5000")])
def test_server_bind_configuration_preserves_deployment_settings(monkeypatch, host, expected):
    """Keep deployment bind settings and enforce one process."""

    monkeypatch.setenv("TICKER_BIND_HOST", host)
    monkeypatch.setenv("TICKER_PORT", "5000")
    config = server.server_config()
    assert config.bind == [expected]
    assert config.workers == 1
    assert config.websocket_ping_interval == 20.0


def test_server_main_loads_environment_and_serves_asgi(monkeypatch):
    """Use the ASGI factory after loading environment settings."""

    calls = []
    flask = _offline(":memory:")
    application = asgi.TickerASGI(flask, start=_no_engine)
    monkeypatch.setattr(server.faulthandler, "enable", lambda: None)
    if hasattr(server.faulthandler, "register"):
        monkeypatch.setattr(server.faulthandler, "register", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "load_dotenv", lambda path: calls.append("environment"))
    monkeypatch.setattr(server, "create_asgi_application", lambda: calls.append("factory") or application)

    async def serve(app, config, *, mode):
        assert app is application
        assert config.workers == 1
        assert mode == "asgi"
        calls.append("serve")

    monkeypatch.setattr(server, "serve", serve)
    server.main()
    assert calls == ["environment", "factory", "serve"]
