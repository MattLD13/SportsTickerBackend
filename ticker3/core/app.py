"""The Ticker 3 HTTP API and device stream as one ASGI application.

| Route | Auth | Job |
|---|---|---|
| `GET /v3/health` | none | Core and worker status |
| `GET /v3/features` | none | Feature titles and settings schemas |
| `POST /v3/tickers` | admin | Create a ticker. The answer holds the device token and a pairing code. |
| `POST /v3/pair` | code | Exchange a pairing code for an app token |
| `GET /v3/tickers/{id}` | app | Ticker, playlist, and app errors |
| `PATCH /v3/tickers/{id}` | app | Change the name or time zone |
| `PUT /v3/tickers/{id}/apps` | app | Replace the playlist |
| `GET /v3/tickers/{id}/screens` | app | The current screens for one panel size |
| `GET /v3/tickers/{id}/frame.png` | app | A frame from the reference player |
| `GET /v3/assets/{id}` | none | One logo, resized to `size` |
| `POST /v3/deploy` | admin | Replace the release of one feature |
| `WS /v3/stream` | device | Templates, screens, and deltas |
"""
from __future__ import annotations

import asyncio
import hmac
import io
import json
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ticker3.contract import ContractError
from ticker3.contract.messages import device_message
from ticker3.contract.templates import PANEL, PLACEHOLDER
from ticker3.contract.wire import decode

from .devices import Assets, DeviceSession
from .hub import App, Composition, Hub
from .store import Store

MAX_BODY = 256 * 1024
Image = Callable[[str], Awaitable[bytes | None]]


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


class CoreApp:
    def __init__(self, hub: Hub, store: Store, *, admin_token: str | None, supervisor=None, fetch_image: Image | None = None,
                 ping_seconds: float = 20) -> None:
        self.hub, self.store, self.admin_token, self.supervisor = hub, store, admin_token, supervisor
        self.fetch_image, self.ping_seconds = fetch_image, ping_seconds
        self.assets = Assets()
        self.sessions: dict[str, set[DeviceSession]] = {}
        self._images: OrderedDict[tuple[str, int], bytes] = OrderedDict()
        hub.on_screens = self._screens_changed
        hub.on_manifest = self._manifest_changed
        self.started_at = time.time()

    # Hub callbacks

    def _screens_changed(self, ticker: str, composition: Composition) -> None:
        templates = self.hub.templates()
        for session in list(self.sessions.get(ticker, ())):
            session.update(templates, composition)

    def _manifest_changed(self, manifest: dict[str, Any]) -> None:
        self.store.save_manifest(manifest)
        templates = self.hub.templates()
        for ticker, sessions in self.sessions.items():
            for session in list(sessions):
                session.update(templates, self.hub.composition(ticker))

    # ASGI

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "websocket":
            await self._stream(scope, receive, send)
        elif scope["type"] == "http":
            await self._http(scope, receive, send)

    async def _http(self, scope, receive, send) -> None:
        status, headers, body = 200, [(b"content-type", b"application/json")], b""
        try:
            request = Request(scope, await _body(receive))
            result = await self._route(request)
            if isinstance(result, tuple):
                content_type, body = result
                headers = [(b"content-type", content_type.encode()), (b"cache-control", b"max-age=86400")]
            else:
                body = json.dumps(result).encode()
        except HttpError as error:
            status, body = error.status, json.dumps({"error": error.message}).encode()
        except ContractError as error:
            status, body = 400, json.dumps({"error": str(error)}).encode()
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _route(self, request: Request):
        path, method = request.path, request.method
        if path == "/v3/health" and method == "GET":
            return {"ok": True, "uptime": round(time.time() - self.started_at),
                    "workers": self.supervisor.status() if self.supervisor else {}}
        if path == "/v3/features" and method == "GET":
            return [{key: manifest[key] for key in ("feature", "title", "version", "settings")}
                    for manifest in self.hub.manifests.values()]
        if path == "/v3/tickers" and method == "POST":
            self._admin(request)
            data = request.json()
            created = self.store.create_ticker(_text(data, "name", 32, "Ticker"), _zone(data.get("timezone", "America/New_York")))
            self._load(created.ticker.id)
            return {"id": created.ticker.id, "device_token": created.device_token, "pairing_code": created.pairing_code}
        if path == "/v3/pair" and method == "POST":
            paired = self.store.pair(str(request.json().get("code", "")))
            if paired is None:
                raise HttpError(403, "the pairing code is not valid")
            return {"ticker_id": paired[0], "app_token": paired[1]}
        if path == "/v3/deploy" and method == "POST":
            self._admin(request)
            data = request.json()
            if self.supervisor is None:
                raise HttpError(409, "this core runs no supervisor")
            try:
                return {"promoted": await self.supervisor.deploy(str(data.get("feature")), str(data.get("release")))}
            except (KeyError, RuntimeError) as error:
                raise HttpError(409, str(error)) from error
        match = re.fullmatch(r"/v3/assets/([0-9a-f]{16})", path)
        if match and method == "GET":
            return await self._asset(match.group(1), request)
        match = re.fullmatch(r"/v3/tickers/([0-9a-f]{12})(/apps|/screens|/frame\.png)?", path)
        if match:
            ticker = self._app(request, match.group(1))
            part = match.group(2)
            if part is None and method == "GET":
                return self._ticker_view(ticker.id)
            if part is None and method == "PATCH":
                data = request.json()
                self.store.update_ticker(ticker.id, name=_text(data, "name", 32) if "name" in data else None,
                                         timezone=_zone(data["timezone"]) if "timezone" in data else None)
                self._load(ticker.id)
                return self._ticker_view(ticker.id)
            if part == "/apps" and method == "PUT":
                apps = _apps(request.json())
                self.hub.set_playlist(ticker.id, apps)
                self.store.set_apps(ticker.id, apps)
                return self._ticker_view(ticker.id)
            if part == "/screens" and method == "GET":
                panel = _panel(request)
                session = DeviceSession(ticker.id, panel, lambda message: None, self.assets)
                session.start(self.hub.templates(), self.hub.composition(ticker.id), None)
                return {"panel": panel, "screens": list(session.screens.values()), "errors": list(self.hub.composition(ticker.id).errors)}
            if part == "/frame.png" and method == "GET":
                return "image/png", await self._frame(ticker.id, _panel(request), int(request.query.get("offset", "0")))
        raise HttpError(404, "no such route")

    def _ticker_view(self, ticker: str) -> dict[str, Any]:
        record = next(item for item in self.store.tickers() if item.id == ticker)
        return {"id": record.id, "name": record.name, "timezone": record.timezone,
                "apps": [{"id": app.id, "feature": app.feature, "settings": app.settings} for app in self.hub.playlists.get(ticker, ())],
                "errors": list(self.hub.composition(ticker).errors)}

    def _load(self, ticker: str) -> None:
        record = next(item for item in self.store.tickers() if item.id == ticker)
        self.hub.set_ticker_values(ticker, {"tz": record.timezone})
        if ticker not in self.hub.playlists:
            self.hub.set_playlist(ticker, self.store.apps(ticker), strict=False)

    def _admin(self, request: Request) -> None:
        token = request.bearer()
        if not self.admin_token or not token or not hmac.compare_digest(token, self.admin_token):
            raise HttpError(403, "this route needs the admin token")

    def _app(self, request: Request, ticker: str):
        token = request.bearer()
        found = self.store.ticker_for_app(token, ticker) if token else None
        if found is None:
            raise HttpError(403, "this route needs an app token for the ticker")
        return found

    async def _asset(self, identifier: str, request: Request):
        url = self.assets.urls.get(identifier)
        if url is None or self.fetch_image is None:
            raise HttpError(404, "unknown asset")
        size = max(4, min(64, int(request.query.get("size", "16"))))
        key = (identifier, size)
        if key not in self._images:
            data = await self.fetch_image(url)
            if data is None:
                raise HttpError(502, "the asset source failed")
            self._images[key] = await asyncio.to_thread(_resize, data, size)
            while len(self._images) > 512:
                self._images.popitem(last=False)
        self._images.move_to_end(key)
        return "image/png", self._images[key]

    async def _frame(self, ticker: str, panel: str, offset: int) -> bytes:
        from ticker3.player import draw_frame

        templates = self.hub.templates()
        blocks = [(templates[screen["template"]]["panels"][panel], screen["values"]) for screen in self.hub.composition(ticker).screens
                  if panel in templates[screen["template"]]["panels"]]
        images: dict[tuple[str, int], Any] = {}
        if self.fetch_image is not None:
            for block, values in blocks:
                for part in block["parts"]:
                    for key in PLACEHOLDER.findall(part["value"]) if part["part"] == "logo" else ():
                        url = values.get(key)
                        if isinstance(url, str) and url.startswith("http"):
                            data = await self.fetch_image(url)
                            if data:
                                images[(url, part["size"])] = await asyncio.to_thread(_logo, data, part["size"])

        def render() -> bytes:
            frame = draw_frame(panel, blocks, now=time.time(), offset=offset, logos=lambda url, size: images.get((url, size)))
            output = io.BytesIO()
            frame.save(output, "PNG")
            return output.getvalue()

        return await asyncio.to_thread(render)

    # Device stream

    async def _stream(self, scope, receive, send) -> None:
        if scope["path"] != "/v3/stream":
            await send({"type": "websocket.close", "code": 4404})
            return
        if (await receive())["type"] != "websocket.connect":
            return
        await send({"type": "websocket.accept"})
        outgoing: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)
        session = None
        try:
            hello = device_message(decode((await asyncio.wait_for(receive(), timeout=10)).get("text", "").encode()))
            if hello["t"] != "hello":
                raise ContractError("the first device message must be hello")
            ticker = self.store.ticker_for_device(hello["token"])
            if ticker is None:
                await send({"type": "websocket.send", "text": json.dumps({"t": "error", "error": "unknown device token"})})
                await send({"type": "websocket.close", "code": 4403})
                return
            self._load(ticker.id)

            def deliver(message: dict[str, Any]) -> None:
                try:
                    outgoing.put_nowait(message)
                except asyncio.QueueFull:
                    # A device that cannot keep up gets a full sync on its next connection.
                    while not outgoing.empty():
                        outgoing.get_nowait()
                    outgoing.put_nowait(None)

            session = DeviceSession(ticker.id, hello["panel"], deliver, self.assets)
            session.start(self.hub.templates(), self.hub.composition(ticker.id), hello.get("bundle"))
            self.sessions.setdefault(ticker.id, set()).add(session)
            writer = asyncio.create_task(self._write(outgoing, send))
            try:
                while True:
                    event = await receive()
                    if event["type"] == "websocket.disconnect":
                        break
                    if event.get("text"):
                        device_message(decode(event["text"].encode()))
            finally:
                writer.cancel()
        except (ContractError, asyncio.TimeoutError, UnicodeError):
            await send({"type": "websocket.close", "code": 4400})
        finally:
            if session is not None:
                self.sessions.get(session.ticker, set()).discard(session)

    async def _write(self, outgoing: asyncio.Queue, send) -> None:
        while True:
            try:
                message = await asyncio.wait_for(outgoing.get(), timeout=self.ping_seconds)
            except asyncio.TimeoutError:
                message = {"t": "ping"}
            if message is None:
                await send({"type": "websocket.close", "code": 4408})
                return
            await send({"type": "websocket.send", "text": json.dumps(message, separators=(",", ":"), ensure_ascii=False)})


class Request:
    def __init__(self, scope, body: bytes) -> None:
        self.method, self.path, self.body = scope["method"], scope["path"], body
        from urllib.parse import parse_qsl

        self.query = dict(parse_qsl(scope.get("query_string", b"").decode()))
        self.headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}

    def json(self) -> dict[str, Any]:
        try:
            data = json.loads(self.body or b"{}")
        except ValueError as error:
            raise HttpError(400, "the body must be JSON") from error
        if not isinstance(data, dict):
            raise HttpError(400, "the body must be a JSON object")
        return data

    def bearer(self) -> str | None:
        value = self.headers.get("authorization", "")
        return value[7:].strip() if value.lower().startswith("bearer ") else None


async def _body(receive) -> bytes:
    chunks, size = [], 0
    while True:
        event = await receive()
        chunk = event.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            raise HttpError(413, "the body is too large")
        chunks.append(chunk)
        if not event.get("more_body"):
            return b"".join(chunks)


def _apps(data: dict[str, Any]) -> list[App]:
    apps = data.get("apps")
    if not isinstance(apps, list) or len(apps) > 32:
        raise HttpError(400, "apps must be a list of at most 32 apps")
    result = []
    for item in apps:
        if not isinstance(item, dict) or not isinstance(item.get("settings", {}), dict):
            raise HttpError(400, "each app needs id, feature, and settings")
        result.append(App(str(item.get("id", "")), str(item.get("feature", "")), item.get("settings", {})))
    return result


def _panel(request: Request) -> str:
    panel = request.query.get("panel", "w384h32")
    if not PANEL.match(panel):
        raise HttpError(400, "panel must look like w64h32")
    return panel


def _text(data: dict[str, Any], key: str, limit: int, default: str | None = None) -> str:
    value = str(data.get(key, default) if default is not None else data.get(key, "")).strip()
    if not 1 <= len(value) <= limit:
        raise HttpError(400, f"{key} must be 1 to {limit} characters")
    return value


def _zone(value: Any) -> str:
    try:
        ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise HttpError(400, f"unknown time zone {value!r}") from error
    return str(value)


def _logo(data: bytes, size: int):
    from PIL import Image as PillowImage

    logo = PillowImage.open(io.BytesIO(data)).convert("RGBA")
    logo.thumbnail((size, size), PillowImage.LANCZOS)
    square = PillowImage.new("RGBA", (size, size), (0, 0, 0, 0))
    square.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
    return square


def _resize(data: bytes, size: int) -> bytes:
    output = io.BytesIO()
    _logo(data, size).save(output, "PNG")
    return output.getvalue()
