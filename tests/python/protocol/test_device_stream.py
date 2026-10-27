"""Validate device stream sequencing, replay, and slow client recovery."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sports_ticker.device_stream import DeviceStreamHub, StreamProjection
from ticker_core.protocol import DeviceStreamState, StreamMessage, TickerResponse


pytestmark = pytest.mark.critical
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/display" / "v2_render_snapshot.json"


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


def test_stream_reuses_unchanged_sections_and_detaches_incoming_replacements():
    payload = _payload()
    expected = deepcopy(payload)
    state = DeviceStreamState()
    before = state.apply(_message("snapshot", "stream-a", 1, 1, payload=payload))
    payload["content"]["sports"][0]["data"]["away_score"] = "999"
    changes = {"settings": {**expected["settings"], "brightness": 72}}
    expected.update(deepcopy(changes))
    after = state.apply(_message("delta", "stream-a", 2, 1, changes=changes))
    changes["settings"]["brightness"] = 1

    assert before is not None and after is not None
    assert after.data["content"] is before.data["content"]
    assert after.to_payload() == expected
    assert after == TickerResponse.from_payload(expected)
    assert after.settings.brightness == 72
    assert before.settings.brightness == 100
    with pytest.raises(TypeError):
        after.data["content"]["sports"][0]["data"]["away_score"] = "999"


def test_stream_delta_removal_and_invalid_replacement_preserve_recovery():
    payload = _payload()
    state = DeviceStreamState()
    state.apply(_message("snapshot", "stream-a", 1, 1, payload=payload))
    with pytest.raises(ValueError, match="must be a list"):
        state.apply(_message("delta", "stream-a", 2, 1, changes={"content": {"sports": {}}}))
    assert state.cursor == ("stream-a", 1)
    after = state.apply(_message("delta", "stream-a", 2, 1, changes={}, removed=["events", "meta", "settings"]))
    for key in ("events", "meta", "settings"):
        payload.pop(key)
    assert after == TickerResponse.from_payload(payload)
    assert after is not None and not after.alerts and not after.news
    assert after.settings.mode == "sports"
    with pytest.raises(TypeError):
        after.settings.data["mode"] = "clock"


def test_hub_replays_contiguous_updates_for_a_matching_cursor():
    hub = DeviceStreamHub()
    payload = _payload()
    subscriber, initial = hub.subscribe(
        "ticker-1", StreamProjection.from_payload(payload), resume_stream_id=None, after_seq=None
    )
    initial_value = json.loads(initial[0].encoded)
    assert initial_value["type"] == "snapshot"
    assert initial_value["seq"] == 1
    changed = deepcopy(payload)
    changed["settings"]["brightness"] = 80
    hub.publish("ticker-1", StreamProjection.from_payload(changed))
    queued = subscriber.queue.get_nowait()
    queued_value = json.loads(queued.encoded)
    assert queued_value["type"] == "delta"
    assert queued_value["base_seq"] == 1

    resumed, replay = hub.subscribe(
        "ticker-1",
        StreamProjection.from_payload(changed),
        resume_stream_id=hub.stream_id,
        after_seq=1,
    )
    assert replay == (queued,)
    assert replay[0] is queued
    hub.unsubscribe("ticker-1", subscriber)
    hub.unsubscribe("ticker-1", resumed)


def test_hub_resets_a_slow_client_with_a_full_snapshot():
    hub = DeviceStreamHub(queue_size=1)
    payload = _payload()
    subscriber, _ = hub.subscribe(
        "ticker-1", StreamProjection.from_payload(payload), resume_stream_id=None, after_seq=None
    )
    first = deepcopy(payload)
    first["settings"]["brightness"] = 80
    second = deepcopy(payload)
    second["settings"]["brightness"] = 60
    hub.publish("ticker-1", StreamProjection.from_payload(first))
    hub.publish("ticker-1", StreamProjection.from_payload(second))
    reset = json.loads(subscriber.queue.get_nowait().encoded)
    assert reset["type"] == "snapshot"
    assert reset["seq"] == 3
    assert reset["payload"]["settings"]["brightness"] == 60


def test_hub_detaches_input_and_shares_an_immutable_wire_message():
    hub = DeviceStreamHub()
    payload = _payload()
    first, initial = hub.subscribe("ticker-1", StreamProjection.from_payload(payload), resume_stream_id=None, after_seq=None)
    second, _ = hub.subscribe("ticker-1", StreamProjection.from_payload(payload), resume_stream_id=None, after_seq=None)
    projection = StreamProjection.from_payload({**payload, "settings": {**payload["settings"], "brightness": 80}})
    with pytest.raises(TypeError):
        projection.sections["settings"] = "{}"
    payload["content"]["sports"][0]["data"]["away_score"] = "999"
    hub.publish("ticker-1", projection)
    left, right = first.queue.get_nowait(), second.queue.get_nowait()
    assert left is right
    assert json.loads(left.encoded)["changes"]["settings"]["brightness"] == 80
    assert json.loads(initial[0].encoded)["payload"]["content"]["sports"][0]["data"]["away_score"] == "17"


def test_hub_tracks_removed_and_null_sections_and_ignores_object_key_order():
    hub = DeviceStreamHub()
    payload = {"settings": {"brightness": 80, "name": "é雪\"\n"}, "obsolete": {"value": 1}}
    subscriber, _ = hub.subscribe("ticker-1", StreamProjection.from_payload(payload), resume_stream_id=None, after_seq=None)
    hub.publish("ticker-1", StreamProjection.from_payload({"obsolete": {"value": 1}, "settings": {"name": "é雪\"\n", "brightness": 80}}))
    assert subscriber.queue.empty()
    hub.publish("ticker-1", StreamProjection.from_payload({"settings": payload["settings"], "nullable": None}))
    value = json.loads(subscriber.queue.get_nowait().encoded)
    assert value["removed"] == ["obsolete"]
    assert value["changes"] == {"nullable": None}


def test_projection_encoding_runs_with_the_projector_outside_the_event_loop(monkeypatch):
    import asyncio
    from threading import get_ident
    from sports_ticker.device_stream import StreamProjection

    async def run():
        main_thread = get_ident()
        threads = []
        factory = StreamProjection.from_payload

        def encode(cls, payload):
            threads.append(get_ident())
            return factory(payload)

        def projector(ticker_id):
            threads.append(get_ident())
            return _payload()

        monkeypatch.setattr(StreamProjection, "from_payload", classmethod(encode))
        hub = DeviceStreamHub()
        await hub._refresh_one(projector, "ticker-1")
        assert len(threads) == 2
        assert threads[0] == threads[1] != main_thread
        assert hub.published_deltas == 1

    asyncio.run(run())
