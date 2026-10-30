"""Serve the Flask routes and the device stream as one ASGI application."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.parse import parse_qs

from asgiref.sync import ThreadSensitiveContext
from asgiref.wsgi import WsgiToAsgi
from flask import Flask

from ticker.server.api.stream import SUBPROTOCOL, Projection, StreamHub

REAUTHORIZE_SECONDS = 5


class TickerASGI:
    def __init__(self, app: Flask, *, start: Callable[[Flask], Callable[[], None]], http_threads: int = 8) -> None:
        if http_threads < 1:
            raise ValueError("http_threads must be positive")
        self.app, self.start = app, start
        self.http = WsgiToAsgi(app)
        self.slots = asyncio.Semaphore(http_threads)
        self.hub = StreamHub()
        app.extensions["ticker.stream"] = self.hub
        application = app.extensions["ticker.application"]
        application.snapshot_store.add_change_listener(self.hub.changed)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            async with self.slots, ThreadSensitiveContext():
                await self.http(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._stream(scope, receive, send)
        elif scope["type"] == "lifespan":
            await self._lifespan(receive, send)

    async def _lifespan(self, receive, send) -> None:
        stop_engine, stop_stream, projector = None, asyncio.Event(), None
        application = self.app.extensions["ticker.application"]
        try:
            if (await receive())["type"] != "lifespan.startup":
                return
            try:
                stop_engine = await asyncio.to_thread(self.start, self.app)
            except Exception as error:
                await send({"type": "lifespan.startup.failed", "message": str(error)})
                return
            projector = asyncio.create_task(self.hub.run(application.project_data, stop_stream))
            await send({"type": "lifespan.startup.complete"})
            if (await receive())["type"] == "lifespan.shutdown":
                stop_stream.set()
                await projector
                projector = None
                stop, stop_engine = stop_engine, None
                try:
                    await asyncio.to_thread(stop)
                except Exception as error:
                    await send({"type": "lifespan.shutdown.failed", "message": str(error)})
                    return
                await send({"type": "lifespan.shutdown.complete"})
        finally:
            stop_stream.set()
            if projector is not None:
                projector.cancel()
            if stop_engine is not None:
                await asyncio.to_thread(stop_engine)

    async def _stream(self, scope, receive, send) -> None:
        """Serve one device stream at /stream. The X-Device-Token header names the ticker."""
        application = self.app.extensions["ticker.application"]
        if scope.get("path") != "/stream":
            await send({"type": "websocket.close", "code": 1008})
            return
        if SUBPROTOCOL not in scope.get("subprotocols", ()):
            await send({"type": "websocket.close", "code": 1002})
            return
        headers = {bytes(key).lower(): bytes(value) for key, value in scope.get("headers", ())}
        token = headers.get(b"x-device-token", b"").decode("ascii", errors="ignore")
        ticker_id = await asyncio.to_thread(application.repository.ticker_for_device_token, token) if token else None
        if ticker_id is None:
            await send({"type": "websocket.close", "code": 4401 if not token else 4403})
            return
        query = parse_qs(bytes(scope.get("query_string", b"")).decode("ascii", errors="ignore"))
        stream_id, after = query.get("stream_id", [None])[0], query.get("after_seq", [None])[0]
        try:
            after_seq = None if after is None else int(after)
        except ValueError:
            after_seq = -1
        if (stream_id is None) != (after is None) or (after_seq is not None and after_seq < 0):
            await send({"type": "websocket.close", "code": 1008})
            return
        if (await receive()).get("type") != "websocket.connect":
            return
        await send({"type": "websocket.accept", "subprotocol": SUBPROTOCOL})
        projection = await asyncio.to_thread(lambda: Projection.of(application.project_data(ticker_id)))
        subscriber, first = self.hub.subscribe(ticker_id, projection, stream_id=stream_id, after_seq=after_seq)
        incoming = asyncio.create_task(receive())
        outgoing = asyncio.create_task(subscriber.queue.get())
        loop = asyncio.get_running_loop()
        checked = loop.time()
        try:
            for message in first:
                await send({"type": "websocket.send", "text": message.text})
            while True:
                done, _ = await asyncio.wait({incoming, outgoing}, timeout=REAUTHORIZE_SECONDS,
                                             return_when=asyncio.FIRST_COMPLETED)
                if loop.time() - checked >= REAUTHORIZE_SECONDS:
                    # A deleted ticker or a rotated token ends the stream.
                    if await asyncio.to_thread(application.repository.ticker_for_device_token, token) != ticker_id:
                        await send({"type": "websocket.close", "code": 4403})
                        return
                    checked = loop.time()
                if incoming in done:
                    event = incoming.result()
                    if event.get("type") == "websocket.disconnect":
                        return
                    # The stream is one-way. A client message ends it.
                    await send({"type": "websocket.close", "code": 1008})
                    return
                if outgoing in done:
                    await send({"type": "websocket.send", "text": outgoing.result().text})
                    outgoing = asyncio.create_task(subscriber.queue.get())
        finally:
            incoming.cancel()
            outgoing.cancel()
            self.hub.unsubscribe(ticker_id, subscriber)
