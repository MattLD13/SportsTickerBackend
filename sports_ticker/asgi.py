"""Serve existing Flask routes and own the backend runtime through ASGI lifespan."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs

from asgiref.wsgi import WsgiToAsgi
from asgiref.sync import ThreadSensitiveContext
from flask import Flask, request

from .production import create_production_application, start_runtime
from .device_stream import DeviceStreamHub, SUBPROTOCOL, encode_message


class BackendASGI:
    """Own one runtime lifecycle and adapt the unchanged Flask HTTP application."""

    def __init__(self, app: Flask, *, http_threads: int = 8) -> None:
        if http_threads < 1:
            raise ValueError("TICKER_HTTP_THREADS must be positive")
        self.flask_app = app
        self.http = WsgiToAsgi(app)
        self._http_slots = asyncio.Semaphore(http_threads)
        self._lifespan_claimed = False
        self._stop: Callable[[], None] | None = None
        self._stream_hub = DeviceStreamHub()
        self._stream_stop: asyncio.Event | None = None
        self._stream_task: asyncio.Task | None = None
        self._snapshot_store = self.flask_app.extensions.get("sports_ticker.snapshot_store")
        self._snapshot_listener = self._stream_hub.notify_ticker_changed
        if self._snapshot_store is not None:
            add_listener = getattr(self._snapshot_store, "add_change_listener", None)
            if callable(add_listener):
                add_listener(self._snapshot_listener)

        @self.flask_app.after_request
        def notify_streams_after_mutation(response):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                view_args = request.view_args or {}
                ticker_id = view_args.get("ticker_id") or view_args.get("device_id")
                if not ticker_id:
                    payload = request.get_json(silent=True)
                    if isinstance(payload, dict):
                        ticker_id = payload.get("device_id")
                        targets = payload.get("target_ticker_ids", payload.get("ticker_ids"))
                        if isinstance(targets, list):
                            for target in targets:
                                if isinstance(target, str) and target.strip():
                                    self._stream_hub.notify_ticker_changed(target.strip())
                            return response
                if isinstance(ticker_id, str) and ticker_id.strip():
                    self._stream_hub.notify_ticker_changed(ticker_id.strip())
                else:
                    self._stream_hub.notify_all_changed()
            return response

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            async with self._http_slots:
                async with ThreadSensitiveContext():
                    await self.http(scope, receive, send)
        elif scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "websocket":
            await self._device_stream(scope, receive, send)
        else:
            raise ValueError(f"unsupported ASGI scope: {scope['type']}")

    async def _lifespan(self, receive, send) -> None:
        if self._lifespan_claimed:
            await send({
                "type": "lifespan.startup.failed",
                "message": "backend lifespan already claimed",
            })
            return
        self._lifespan_claimed = True
        try:
            message = await receive()
            if message["type"] != "lifespan.startup":
                raise ValueError("backend lifespan requires startup")
            try:
                self._stop = start_runtime(self.flask_app)
            except Exception as exc:
                await send({"type": "lifespan.startup.failed", "message": str(exc)})
                return
            backend_application = self.flask_app.extensions.get("sports_ticker.backend_application")
            if backend_application is not None:
                self._stream_stop = asyncio.Event()
                self._stream_task = asyncio.create_task(self._stream_hub.serve_updates(
                    backend_application.project_data,
                    self._stream_stop,
                ))
            await send({"type": "lifespan.startup.complete"})
            message = await receive()
            if message["type"] != "lifespan.shutdown":
                raise ValueError("backend lifespan requires shutdown")
            try:
                await self._stop_runtime()
            except Exception as exc:
                await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                return
            await send({"type": "lifespan.shutdown.complete"})
        finally:
            await self._stop_stream_projector()
            await self._stop_runtime()
            if self._snapshot_store is not None:
                remove_listener = getattr(self._snapshot_store, "remove_change_listener", None)
                if callable(remove_listener):
                    remove_listener(self._snapshot_listener)

    async def _stop_stream_projector(self) -> None:
        stop, self._stream_stop = self._stream_stop, None
        task, self._stream_task = self._stream_task, None
        if stop is not None:
            stop.set()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _device_stream(self, scope, receive, send) -> None:
        """Serve one registered ticker's effective V2 projection stream."""
        parts = str(scope.get("path", "")).strip("/").split("/")
        if len(parts) != 5 or parts[:3] != ["api", "v2", "tickers"] or parts[4] != "stream":
            await send({"type": "websocket.close", "code": 1008})
            return
        ticker_id = parts[3]
        if SUBPROTOCOL not in scope.get("subprotocols", ()):
            await send({"type": "websocket.close", "code": 1002})
            return
        application = self.flask_app.extensions.get("sports_ticker.backend_application")
        headers = {bytes(key).lower(): bytes(value) for key, value in scope.get("headers", ())}
        token = headers.get(b"x-device-token", b"").decode("ascii", errors="ignore")
        if not token:
            await send({"type": "websocket.close", "code": 4401})
            return
        if application is None or not await asyncio.to_thread(application.authorize_device, ticker_id, token):
            await send({"type": "websocket.close", "code": 4403})
            return
        query = parse_qs(bytes(scope.get("query_string", b"")).decode("ascii", errors="ignore"))
        resume_stream_id = query.get("stream_id", [None])[0]
        after_raw = query.get("after_seq", [None])[0]
        if (resume_stream_id is None) != (after_raw is None):
            await send({"type": "websocket.close", "code": 1008})
            return
        try:
            after_seq = None if after_raw is None else int(after_raw)
            if after_seq is not None and after_seq < 0:
                raise ValueError
        except ValueError:
            await send({"type": "websocket.close", "code": 1008})
            return
        first = await receive()
        if first.get("type") != "websocket.connect":
            await send({"type": "websocket.close", "code": 1002})
            return
        await send({"type": "websocket.accept", "subprotocol": SUBPROTOCOL})
        subscriber = None
        receive_task = None
        queue_task = None
        try:
            while True:
                generation = self._stream_hub.generation
                payload = await asyncio.to_thread(application.project_data, ticker_id)
                if generation != self._stream_hub.generation:
                    continue
                subscriber, initial_messages = self._stream_hub.subscribe(
                    ticker_id,
                    payload,
                    resume_stream_id=resume_stream_id,
                    after_seq=after_seq,
                )
                break
            for message in initial_messages:
                await send({"type": "websocket.send", "text": encode_message(message)})
            receive_task = asyncio.create_task(receive())
            queue_task = asyncio.create_task(subscriber.queue.get())
            while True:
                if not await asyncio.to_thread(application.authorize_device, ticker_id, token):
                    await send({"type": "websocket.close", "code": 4403})
                    return
                done, _ = await asyncio.wait(
                    {receive_task, queue_task},
                    return_when=asyncio.FIRST_COMPLETED, timeout=5,
                )
                if receive_task in done:
                    incoming = receive_task.result()
                    if incoming.get("type") == "websocket.disconnect":
                        return
                    if incoming.get("type") == "websocket.receive":
                        await send({"type": "websocket.close", "code": 1008})
                        return
                    receive_task = asyncio.create_task(receive())
                if queue_task in done:
                    if not await asyncio.to_thread(application.authorize_device, ticker_id, token):
                        await send({"type": "websocket.close", "code": 4403})
                        return
                    message = queue_task.result()
                    await send({"type": "websocket.send", "text": encode_message(message)})
                    queue_task = asyncio.create_task(subscriber.queue.get())
        except Exception:
            await send({"type": "websocket.close", "code": 1011})
        finally:
            for task in (receive_task, queue_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (receive_task, queue_task) if task is not None), return_exceptions=True)
            if subscriber is not None:
                self._stream_hub.unsubscribe(ticker_id, subscriber)

    async def _stop_runtime(self) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            await asyncio.to_thread(stop)


def create_asgi_application(database_path: str | Path | None = None) -> BackendASGI:
    """Compose one dormant production backend without starting refresh work."""

    http_threads = int(os.environ.get("TICKER_HTTP_THREADS", "8"))
    if http_threads < 1:
        raise ValueError("TICKER_HTTP_THREADS must be positive")
    return BackendASGI(create_production_application(database_path), http_threads=http_threads)


__all__ = ["BackendASGI", "create_asgi_application"]
