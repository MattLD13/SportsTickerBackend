"""Verify ESPN Fastcast discovery, decoding, patching, and subscriptions."""

from __future__ import annotations

import base64
from collections import deque
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit
import zlib

from sports_ticker.providers.espn_fastcast import (
    EspnFastcastSource,
    _apply_fastcast_payload,
    _decode_fastcast_payload,
    _fastcast_socket_url,
    fastcast_topic,
)


def _snapshot() -> dict:
    return {
        "events": [{
            "id": "401",
            "uid": "s:20~l:28~e:401",
            "status": {"type": {"state": "pre"}},
            "competitions": [{
                "competitors": [{"homeAway": "home", "score": "0"}],
            }],
        }],
    }


def test_fastcast_topic_uses_scoreboard_path_and_group() -> None:
    assert fastcast_topic(
        "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    ) == "scoreboard-football-nfl"
    assert fastcast_topic(
        "https://site.web.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80"
    ) == "scoreboard-football-college-football-80"


def test_fastcast_socket_url_uses_secure_port_and_escapes_token() -> None:
    url = _fastcast_socket_url({
        "ip": "127.0.0.1",
        "securePort": 9573,
        "token": "token/value+one",
    })

    parsed = urlsplit(url)
    assert parsed.scheme == "wss"
    assert parsed.netloc == "127.0.0.1:9573"
    assert parsed.path == "/FastcastService/pubsub/profiles/12000"
    assert parse_qs(parsed.query)["TrafficManager-Token"] == ["token/value+one"]


def test_fastcast_decoder_reads_plain_and_compressed_message_wrappers() -> None:
    payload = [{"op": "replace", "path": "/events/0/status", "value": {}}]
    encoded = base64.b64encode(
        zlib.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    ).decode("ascii")

    assert _decode_fastcast_payload({"pl": json.dumps(payload)}) == payload
    assert _decode_fastcast_payload({"pl": encoded, "~c": True}) == payload


def test_fastcast_patch_supports_uid_relative_and_json_pointer_paths() -> None:
    document = _snapshot()
    updated = _apply_fastcast_payload(
        document,
        [
            {
                "op": "replace",
                "path": "s:20~l:28~e:401/status/type/state",
                "value": "in",
            },
            {
                "op": "replace",
                "path": "/events/0/competitions/0/competitors/0/score",
                "value": "7",
            },
        ],
    )

    assert updated["events"][0]["status"]["type"]["state"] == "in"
    assert updated["events"][0]["competitions"][0]["competitors"][0]["score"] == "7"
    assert document["events"][0]["status"]["type"]["state"] == "pre"


def test_fastcast_source_waits_for_checkpoint_after_a_message_gap() -> None:
    source = EspnFastcastSource({"nfl": "scoreboard-football-nfl"})
    source.prime("nfl", _snapshot())
    source._handle_message({
        "op": "R",
        "tc": "scoreboard-football-nfl",
        "mid": 100,
        "pl": json.dumps([{
            "op": "replace",
            "path": "s:20~l:28~e:401/status/type/state",
            "value": "in",
        }]),
    })
    source._handle_message({
        "op": "P",
        "tc": "scoreboard-football-nfl",
        "mid": 102,
        "pl": json.dumps([{
            "op": "replace",
            "path": "/events/0/status/type/state",
            "value": "post",
        }]),
    })

    assert source.snapshot("nfl")["events"][0]["status"]["type"]["state"] == "in"
    assert source.error("nfl") == "Fastcast message gap 100->102"

    reconciled = _snapshot()
    reconciled["events"][0]["status"]["type"]["state"] = "post"
    source._handle_message({
        "op": "H",
        "tc": "scoreboard-football-nfl",
        "mid": 103,
        "pl": json.dumps(reconciled),
    })

    assert source.snapshot("nfl")["events"][0]["status"]["type"]["state"] == "post"
    assert source.error("nfl") is None


def test_fastcast_source_tracks_event_specific_update_times() -> None:
    clock = [10.0]
    source = EspnFastcastSource(
        {"nfl": "scoreboard-football-nfl"},
        monotonic=lambda: clock[0],
    )
    source.prime("nfl", _snapshot())

    assert source.event_updated_at("nfl", "401") == 10.0

    clock[0] = 16.0
    source._handle_message({
        "op": "P",
        "tc": "scoreboard-football-nfl",
        "pl": json.dumps([{
            "op": "replace",
            "path": "s:20~l:28~e:401/status/type/state",
            "value": "in",
        }]),
    })

    assert source.event_updated_at("nfl", "401") == 16.0


def test_fastcast_source_ignores_non_patch_payloads() -> None:
    source = EspnFastcastSource({"nfl": "scoreboard-football-nfl"})
    source.prime("nfl", _snapshot())

    source._handle_message({
        "op": "P",
        "tc": "scoreboard-football-nfl",
        "pl": "0",
    })

    assert source.snapshot("nfl") == _snapshot()
    assert source.error("nfl") is None


class _FakeSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = deque(json.dumps(message) for message in messages)
        self.closed = threading.Event()
        self.sent: list[dict] = []
        self.timeout = None

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self) -> str:
        if self.messages:
            return self.messages.popleft()
        self.closed.wait(0.05)
        raise TimeoutError("fake receive timeout")

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def close(self) -> None:
        self.closed.set()


def test_fastcast_source_subscribes_once_and_applies_compressed_update() -> None:
    initial = _snapshot()
    update = [{
        "op": "replace",
        "path": "s:20~l:28~e:401/status/type/state",
        "value": "in",
    }]
    encoded = base64.b64encode(
        zlib.compress(json.dumps(update, separators=(",", ":")).encode("utf-8"))
    ).decode("ascii")
    socket = _FakeSocket([
        {"op": "C", "rc": 200, "sid": "session-1"},
        {"op": "S", "rc": 200, "tc": "scoreboard-football-nfl"},
        {
            "op": "P",
            "tc": "scoreboard-football-nfl",
            "pl": encoded,
            "~c": True,
        },
    ])
    source = EspnFastcastSource(
        {"nfl": "scoreboard-football-nfl"},
        discovery_reader=lambda timeout: {"ip": "127.0.0.1", "securePort": 9573, "token": "token"},
        socket_connector=lambda url, timeout: socket,
    )
    source.prime("nfl", initial)
    source.start()

    for _ in range(100):
        snapshot = source.snapshot("nfl")
        if snapshot and snapshot["events"][0]["status"]["type"]["state"] == "in":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Fastcast update was not applied")

    assert source.active("nfl") is True
    assert socket.sent[0] == {"op": "C"}
    assert socket.sent[1] == {"op": "S", "sid": "session-1", "tc": "scoreboard-football-nfl"}
    source.close()
