"""Verify HTTP contracts and runtime ownership at the ASGI serving boundary."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from threading import Event, Lock, get_ident, enumerate as enumerate_threads

from asgiref.testing import ApplicationCommunicator
from cryptography.fernet import Fernet
from flask import Flask, request
import pytest

from sports_ticker import asgi, server
from sports_ticker.bootstrap_v2 import create_backend_application

pytestmark = pytest.mark.critical


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
def test_asgi_runs_flask_requests_concurrently_with_a_bounded_limit(limit):
    """Fill every HTTP slot, keep the next request queued, and preserve separate Flask request contexts."""

    flask = Flask("concurrency")
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

        adapted = asgi.BackendASGI(flask, http_threads=limit)
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


def test_cancelled_http_request_keeps_its_slot_until_the_worker_stops(monkeypatch):
    """Keep the event loop responsive and retain the concurrency permit during cancelled worker cleanup."""

    flask = Flask("cancelled-http")
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

        adapted = asgi.BackendASGI(flask, http_threads=1)
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
    monkeypatch.setattr(asgi, "create_production_application", lambda path: pytest.fail("production factory ran"))
    with pytest.raises(ValueError):
        asgi.create_asgi_application()


def test_asgi_factory_preserves_http_thread_environment_setting(monkeypatch):
    """Pass the existing deployment concurrency setting into the bounded HTTP bridge."""

    monkeypatch.setenv("TICKER_HTTP_THREADS", "3")
    monkeypatch.setattr(asgi, "create_production_application", lambda path: Flask("factory"))
    application = asgi.create_asgi_application()
    assert application._http_slots._value == 3


def test_asgi_preserves_http_health_security_and_mutation_contracts(tmp_path, monkeypatch):
    """Compare real Flask results with ASGI for health, authorization, and durable mutations."""

    monkeypatch.setenv("TICKER_DEPLOY_TOKEN", "deployment-secret")
    monkeypatch.setattr("sports_ticker.api.routes.time.time", lambda: 1000)
    flask = create_backend_application(tmp_path / "asgi.sqlite3", [], scheduler=None, clock=lambda: 1000)
    adapted = asgi.BackendASGI(flask)
    client = flask.test_client()
    registered = client.post("/api/v2/devices/register", json={"device_id": "asgi-device"}).get_json()
    paired = client.post("/api/v2/pairings/exchange", json={"pairing_code": registered["pairing_code"]}).get_json()
    auth = ((b"authorization", f"Bearer {paired['controller_token']}".encode()),)

    async def verify():
        cases = [
            ("GET", "/api/v2/health", b"", ()),
            ("GET", "/api/v2/fleet/health", b"", ()),
            ("GET", "/api/v2/fleet/health", b"", ((b"x-deployment-token", b"wrong"),)),
            ("GET", "/api/v2/fleet/health", b"", ((b"x-deployment-token", b"deployment-secret"),)),
            ("GET", "/api/v2/tickers", b"", ()),
            ("GET", "/api/v2/tickers", b"", ((b"authorization", b"Bearer invalid"),)),
            ("GET", "/api/v2/tickers", b"", auth),
            ("GET", "/api/v2/tickers/asgi-device/data", b"", ()),
            ("PATCH", "/api/v2/tickers/asgi-device", b'{"name":"Updated"}', auth),
            ("POST", "/api/v2/devices/register", b"{invalid", ()),
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
        assert flask.extensions["sports_ticker.backend_application"].get_ticker("asgi-device").name == "Updated"

    try:
        asyncio.run(verify())
    finally:
        flask.extensions["sports_ticker.backend_application"].close()


def test_production_asgi_lifespan_starts_and_stops_one_runtime(tmp_path, monkeypatch):
    """Run the real production lifecycle with an empty isolated fleet."""

    monkeypatch.delenv("TICKER_INITIAL_TICKER_ID", raising=False)
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "asgi-test")
    monkeypatch.setenv("SPOTIFY_CALLBACK_URI", "https://example.com/callback")
    monkeypatch.setenv("SPOTIFY_APP_RETURN_URI", "sportsticker://spotify")
    monkeypatch.setenv("SPOTIFY_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    application = asgi.create_asgi_application(tmp_path / "production.sqlite3")
    runtime = application.flask_app.extensions["sports_ticker.runtime"]
    assert application.flask_app.extensions["sports_ticker.backend_application"].runtime is None
    assert not any(thread.name == "ticker-v2-refresh" for thread in enumerate_threads())
    calls = []
    real_start = asgi.start_runtime
    real_stop = runtime.stop

    def stop_runtime():
        calls.append("runtime.stop")
        real_stop()

    monkeypatch.setattr(runtime, "stop", stop_runtime)

    def start(flask):
        calls.append("start")
        stop = real_start(flask)

        def close():
            calls.append("stop")
            stop()

        return close

    monkeypatch.setattr(asgi, "start_runtime", start)

    async def verify():
        communicator = ApplicationCommunicator(application, {"type": "lifespan"})
        await communicator.send_input({"type": "lifespan.startup"})
        assert await communicator.receive_output() == {"type": "lifespan.startup.complete"}
        assert len([thread for thread in enumerate_threads() if thread.name == "ticker-v2-refresh"]) == 1
        assert (await _request(application, "GET", "/api/v2/health"))[0] == 200
        await communicator.send_input({"type": "lifespan.shutdown"})
        assert await communicator.receive_output(timeout=10) == {"type": "lifespan.shutdown.complete"}
        await communicator.wait()
        repeated = ApplicationCommunicator(application, {"type": "lifespan"})
        await repeated.send_input({"type": "lifespan.startup"})
        assert (await repeated.receive_output())["type"] == "lifespan.startup.failed"
        await repeated.wait()

    asyncio.run(verify())
    assert calls == ["start", "stop", "runtime.stop"]
    assert not any(thread.name == "ticker-v2-refresh" for thread in enumerate_threads())
    assert application.flask_app.extensions["sports_ticker.backend_application"]._closed


@pytest.mark.parametrize("failure", ["startup", "shutdown", "cancel"])
def test_asgi_lifespan_reports_failures_and_cleans_up_once(monkeypatch, failure):
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

    monkeypatch.setattr(asgi, "start_runtime", start)

    async def verify():
        communicator = ApplicationCommunicator(asgi.BackendASGI(Flask("test")), {"type": "lifespan"})
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

    asyncio.run(verify())
    assert calls == (["start"] if failure == "startup" else ["start", "stop"])


def test_asgi_import_has_no_database_or_runtime_side_effects(tmp_path):
    """Import the serving modules without creating durable state or starting refresh work."""

    script = (
        "import os, threading; from pathlib import Path; "
        f"os.environ['TICKER_DATABASE_PATH'] = {str(tmp_path / 'unused.sqlite3')!r}; "
        "import sports_ticker.server, sports_ticker.asgi; "
        "assert not Path(os.environ['TICKER_DATABASE_PATH']).exists(); "
        "assert not any(t.name == 'ticker-v2-refresh' for t in threading.enumerate())"
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
    """Use the production factory after loading environment settings."""

    calls = []
    application = object()
    monkeypatch.setattr(server, "load_dotenv", lambda: calls.append("environment"))
    monkeypatch.setattr(server, "create_asgi_application", lambda: calls.append("factory") or application)

    async def serve(app, config, *, mode):
        assert app is application
        assert config.workers == 1
        assert mode == "asgi"
        calls.append("serve")

    monkeypatch.setattr(server, "serve", serve)
    server.main()
    assert calls == ["environment", "factory", "serve"]
