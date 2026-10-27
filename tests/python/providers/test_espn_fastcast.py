"""Verify ESPN Fastcast discovery, decoding, patching, and subscriptions."""

from __future__ import annotations

import base64
from collections import deque
from collections.abc import Mapping
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit
import zlib

import pytest

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


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_plain(child) for child in value]
    return value


def test_source_versions_wake_waiters_and_change_after_worker_restart() -> None:
    source = EspnFastcastSource({"nfl": "scoreboard-football-nfl"})
    source.prime("nfl", _snapshot())
    before = source.versions()
    result = []
    ready = threading.Event()

    def wait():
        ready.set()
        result.append(source.wait_for_changes(before, 2))

    thread = threading.Thread(target=wait)
    thread.start()
    assert ready.wait(1)
    source._handle_message({"op": "P", "tc": "scoreboard-football-nfl", "mid": 1,
                            "pl": json.dumps([{"op": "replace", "path": "/events/0/competitions/0/competitors/0/score", "value": "7"}])})
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert result == [source.versions()]
    assert result[0] != before
    restarted = EspnFastcastSource({"nfl": "scoreboard-football-nfl"})
    assert restarted.wait_for_changes(source.versions(), 0) != source.versions()


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

    assert _plain(source.snapshot("nfl")) == _snapshot()
    assert source.error("nfl") is None


def test_snapshot_views_detach_input_and_retain_unchanged_events() -> None:
    document = _snapshot()
    document["events"].append({"id": "402", "uid": "s:20~l:28~e:402", "name": "unchanged"})
    source = EspnFastcastSource({"nfl": "scoreboard-football-nfl"})
    source.prime("nfl", document)
    before = source.snapshot("nfl")
    assert source.snapshot("nfl") is before
    document["events"][0]["status"]["type"]["state"] = "caller-change"
    assert before["events"][0]["status"]["type"]["state"] == "pre"
    with pytest.raises(TypeError):
        before["events"][0]["status"]["type"]["state"] = "reader-change"
    source._handle_message({
        "op": "P", "tc": "scoreboard-football-nfl",
        "pl": json.dumps([{"op": "replace", "path": "/events/0/status/type/state", "value": "in"}]),
    })
    after = source.snapshot("nfl")
    assert after["events"][0]["status"]["type"]["state"] == "in"
    assert before["events"][0]["status"]["type"]["state"] == "pre"
    assert after["events"][1] is before["events"][1]


def test_failed_patch_batch_keeps_the_complete_previous_snapshot() -> None:
    source = EspnFastcastSource({"nfl": "scoreboard-football-nfl"})
    source.prime("nfl", _snapshot())
    before = source.snapshot("nfl")
    source._handle_message({
        "op": "P", "tc": "scoreboard-football-nfl",
        "pl": json.dumps([
            {"op": "replace", "path": "/events/0/status/type/state", "value": "in"},
            {"op": "remove", "path": "/events/0/missing"},
        ]),
    })
    assert source.snapshot("nfl") is before
    assert _plain(before) == _snapshot()
    assert source.error("nfl") is not None


def test_patch_arrays_copy_move_test_and_escaped_paths() -> None:
    original = {"a/b": [1, {"~key": [2, 3]}], "keep": {"value": ["unchanged"]}}
    updated = _apply_fastcast_payload(original, [
        {"op": "test", "path": "/a~1b/1/~0key", "value": [2, 3]},
        {"op": "copy", "from": "/a~1b/1", "path": "/a~1b/-"},
        {"op": "replace", "path": "/a~1b/1/~0key/0", "value": 8},
        {"op": "move", "from": "/a~1b/0", "path": "/a~1b/1/~0key/-"},
        {"op": "remove", "path": "/a~1b/0/~0key/1"},
    ])
    assert _plain(updated) == {"a/b": [{"~key": [8]}, {"~key": [2, 3, 1]}], "keep": {"value": ["unchanged"]}}
    assert original == {"a/b": [1, {"~key": [2, 3]}], "keep": {"value": ["unchanged"]}}


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
