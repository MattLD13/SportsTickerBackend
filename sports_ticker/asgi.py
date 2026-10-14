"""Serve existing Flask routes and own the backend runtime through ASGI lifespan."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

from asgiref.wsgi import WsgiToAsgi
from asgiref.sync import ThreadSensitiveContext
from flask import Flask

from .production import create_production_application, start_runtime


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

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            async with self._http_slots:
                async with ThreadSensitiveContext():
                    await self.http(scope, receive, send)
        elif scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
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
            await self._stop_runtime()

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
