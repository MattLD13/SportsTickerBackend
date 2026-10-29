"""Verify the device stream route and its registration gate."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from asgiref.testing import ApplicationCommunicator

from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.fleet import PairingState
from sports_ticker.fleet.device_credentials import device_token_hash
from ticker3.api.asgi import TickerASGI
from ticker3.offline import create_offline_application

pytestmark = pytest.mark.critical
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/display" / "render_snapshot.json"


def _app(tmp_path, *, registered=True):
    flask = create_offline_application(tmp_path / "ticker.sqlite3", [])
    if registered:
        flask.extensions["ticker.application"].repository.create_ticker(
            "stream-device",
            display_settings=DisplaySettings(mode="sports"),
            pairing=PairingState(paired=True),
            credential_hash=device_token_hash("a" * 64))
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        content = tuple(
            ContentItem(
                id=item["id"], family=item["family"], kind=item["kind"], data=item["data"]
            )
            for item in fixture["content"]["sports"]
        )
        flask.extensions["ticker.application"].snapshot_store.replace(
            TickerSnapshot(
                ticker_id="stream-device",
                revision=1,
                observed_at=datetime.now(timezone.utc),
                content=content,
                alerts=(),
                news=(),
                effective_settings=DisplaySettings(mode="sports"),
            )
        )
    return flask


def _asgi(flask):
    return TickerASGI(flask, start=lambda app: lambda: None)


def _scope(token=b"a" * 64, *, subprotocols=("ticker",), query=b""):
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/stream",
        "root_path": "",
        "query_string": query,
        "headers": [(b"x-device-token", token)],
        "subprotocols": list(subprotocols),
        "server": ("127.0.0.1", 5000),
        "client": ("127.0.0.1", 40000),
    }


def test_device_stream_sends_a_projected_snapshot(tmp_path):
    flask = _app(tmp_path)

    async def verify():
        communicator = ApplicationCommunicator(_asgi(flask), _scope())
        await communicator.send_input({"type": "websocket.connect"})
        accepted = await communicator.receive_output(timeout=5)
        initial = await communicator.receive_output(timeout=5)
        assert accepted == {"type": "websocket.accept", "subprotocol": "ticker"}
        assert initial["type"] == "websocket.send"
        message = json.loads(initial["text"])
        assert message["type"] == "snapshot"
        assert message["seq"] == message["base_seq"]
        assert message["payload"]["content"]["sports"][0]["data"]["away_score"] == "17"
        await communicator.send_input({"type": "websocket.disconnect", "code": 1000})
        await communicator.wait()

    try:
        asyncio.run(verify())
    finally:
        flask.extensions["ticker.application"].close()


def test_device_stream_rejects_unknown_ticker_and_missing_subprotocol(tmp_path):
    flask = _app(tmp_path, registered=False)

    async def verify():
        unknown = ApplicationCommunicator(_asgi(flask), _scope(b"b" * 64))
        await unknown.send_input({"type": "websocket.connect"})
        assert await unknown.receive_output(timeout=5) == {"type": "websocket.close", "code": 4403}
        await unknown.wait()

        invalid_protocol = ApplicationCommunicator(
            _asgi(flask), _scope(subprotocols=())
        )
        await invalid_protocol.send_input({"type": "websocket.connect"})
        assert await invalid_protocol.receive_output(timeout=5) == {
            "type": "websocket.close",
            "code": 1002,
        }
        await invalid_protocol.wait()

    try:
        asyncio.run(verify())
    finally:
        flask.extensions["ticker.application"].close()


def test_device_stream_rejects_missing_credentials_and_closes_after_rotation(tmp_path):
    flask = _app(tmp_path)
    application = flask.extensions["ticker.application"]

    async def verify():
        scope = _scope()
        scope["headers"] = []
        anonymous = ApplicationCommunicator(_asgi(flask), scope)
        await anonymous.send_input({"type": "websocket.connect"})
        assert await anonymous.receive_output(timeout=5) == {"type": "websocket.close", "code": 4401}
        await anonymous.wait()
        active = ApplicationCommunicator(_asgi(flask), _scope())
        await active.send_input({"type": "websocket.connect"})
        assert (await active.receive_output(timeout=5))["type"] == "websocket.accept"
        assert (await active.receive_output(timeout=5))["type"] == "websocket.send"
        application.enroll_device_credential("stream-device", device_token_hash("b" * 64))
        assert await active.receive_output(timeout=7) == {"type": "websocket.close", "code": 4403}
        await active.wait()

    try:
        asyncio.run(verify())
    finally:
        application.close()
