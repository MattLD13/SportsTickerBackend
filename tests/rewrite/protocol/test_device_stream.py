"""Validate device stream sequencing, replay, and slow client recovery."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sports_ticker.device_stream import DeviceStreamHub
from ticker_core.protocol import DeviceStreamState, StreamMessage


pytestmark = pytest.mark.critical
FIXTURE = Path(__file__).resolve().parents[1] / "debug" / "v2_render_snapshot.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _message(kind, stream_id, seq, base_seq, **fields):
    return StreamMessage.from_payload({
        "type": kind,
        "protocol_version": 1,
        "stream_id": stream_id,
        "seq": seq,
        "base_seq": base_seq,
        "server_time": "2026-10-14T00:00:00+00:00",
        **fields,
    })


def test_client_applies_delta_and_ignores_duplicate_sequence():
    payload = _payload()
    state = DeviceStreamState()
    initial = _message("snapshot", "stream-a", 1, 1, payload=payload)
    response = state.apply(initial)
    assert response is not None
    assert response.content[0].data["away_score"] == "17"

    changed = deepcopy(payload)
    changed["content"]["sports"][0]["data"]["away_score"] = "24"
    updated = _message(
        "delta",
        "stream-a",
        2,
        1,
        changes={"content": changed["content"]},
        removed=[],
    )
    response = state.apply(updated)
    assert response is not None
    assert response.content[0].data["away_score"] == "24"
    assert state.apply(updated) is None
    assert state.cursor == ("stream-a", 2)


def test_client_rejects_missing_and_reordered_deltas():
    state = DeviceStreamState()
    with pytest.raises(ValueError, match="without its matching snapshot"):
        state.apply(_message("delta", "stream-a", 2, 1, changes={}, removed=[]))

    state.apply(_message("snapshot", "stream-a", 1, 1, payload=_payload()))
    with pytest.raises(ValueError, match="sequence is stale or has a gap"):
        state.apply(_message("delta", "stream-a", 3, 2, changes={}, removed=[]))


def test_hub_replays_contiguous_updates_for_a_matching_cursor():
    hub = DeviceStreamHub()
    payload = _payload()
    subscriber, initial = hub.subscribe(
        "ticker-1", payload, resume_stream_id=None, after_seq=None
    )
    assert initial[0]["type"] == "snapshot"
    assert initial[0]["seq"] == 1
    changed = deepcopy(payload)
    changed["settings"]["brightness"] = 80
    hub.publish("ticker-1", changed)
    queued = subscriber.queue.get_nowait()
    assert queued["type"] == "delta"
    assert queued["base_seq"] == 1

    resumed, replay = hub.subscribe(
        "ticker-1",
        changed,
        resume_stream_id=hub.stream_id,
        after_seq=1,
    )
    assert replay == (queued,)
    hub.unsubscribe("ticker-1", subscriber)
    hub.unsubscribe("ticker-1", resumed)


def test_hub_resets_a_slow_client_with_a_full_snapshot():
    hub = DeviceStreamHub(queue_size=1)
    payload = _payload()
    subscriber, _ = hub.subscribe(
        "ticker-1", payload, resume_stream_id=None, after_seq=None
    )
    first = deepcopy(payload)
    first["settings"]["brightness"] = 80
    second = deepcopy(payload)
    second["settings"]["brightness"] = 60
    hub.publish("ticker-1", first)
    hub.publish("ticker-1", second)
    reset = subscriber.queue.get_nowait()
    assert reset["type"] == "snapshot"
    assert reset["seq"] == 3
    assert reset["payload"]["settings"]["brightness"] == 60

\n