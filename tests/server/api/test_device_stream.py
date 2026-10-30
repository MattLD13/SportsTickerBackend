"""Validate device stream sequencing, replay, and slow client recovery."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ticker.server.api import stream
from ticker.server.api.stream import Projection, StreamHub
from ticker.six.protocol import DeviceStreamState, StreamMessage, TickerResponse


pytestmark = pytest.mark.critical
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/display" / "render_snapshot.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _message(kind, stream_id, seq, base_seq, **fields):
    return StreamMessage.from_payload({
        "type": kind,
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


def _subscribe(hub, payload, *, stream_id=None, after_seq=None):
    return hub.subscribe("ticker-1", Projection.of(payload), stream_id=stream_id, after_seq=after_seq)


def test_hub_replays_contiguous_updates_for_a_matching_cursor():
    hub = StreamHub()
    payload = _payload()
    subscriber, initial = _subscribe(hub, payload)
    initial_value = json.loads(initial[0].text)
    assert initial_value["type"] == "snapshot"
    assert initial_value["seq"] == initial_value["base_seq"] == 1
    # The client model reads the server message without a version field.
    assert StreamMessage.from_payload(initial_value).kind == "snapshot"
    changed = deepcopy(payload)
    changed["settings"]["brightness"] = 80
    hub.publish("ticker-1", Projection.of(changed))
    queued = subscriber.queue.get_nowait()
    queued_value = json.loads(queued.text)
    assert queued_value["type"] == "delta"
    assert queued_value["base_seq"] == 1 and queued_value["seq"] == 2

    resumed, replay = _subscribe(hub, changed, stream_id=hub.stream_id, after_seq=1)
    assert replay == [queued]
    assert replay[0] is queued
    current, ready = _subscribe(hub, changed, stream_id=hub.stream_id, after_seq=2)
    assert json.loads(ready[0].text)["type"] == "ready"
    _, fresh = _subscribe(hub, changed, stream_id="other-server", after_seq=2)
    assert json.loads(fresh[0].text)["type"] == "snapshot"
    for client in (subscriber, resumed, current):
        hub.unsubscribe("ticker-1", client)
    assert hub.active == ("ticker-1",)


def test_client_state_follows_the_hub_messages():
    hub = StreamHub()
    payload = _payload()
    subscriber, initial = _subscribe(hub, payload)
    state = DeviceStreamState()
    assert state.apply(StreamMessage.from_payload(json.loads(initial[0].text))).settings.brightness == 100
    changed = deepcopy(payload)
    changed["settings"]["brightness"] = 80
    hub.publish("ticker-1", Projection.of(changed))
    response = state.apply(StreamMessage.from_payload(json.loads(subscriber.queue.get_nowait().text)))
    assert response.settings.brightness == 80
    assert response == TickerResponse.from_payload(changed)


def test_hub_resets_a_slow_client_with_a_full_snapshot(monkeypatch):
    monkeypatch.setattr(stream, "QUEUE_SIZE", 1)
    hub = StreamHub()
    payload = _payload()
    subscriber, _ = _subscribe(hub, payload)
    first = deepcopy(payload)
    first["settings"]["brightness"] = 80
    second = deepcopy(payload)
    second["settings"]["brightness"] = 60
    hub.publish("ticker-1", Projection.of(first))
    hub.publish("ticker-1", Projection.of(second))
    reset = json.loads(subscriber.queue.get_nowait().text)
    assert subscriber.queue.empty()
    assert reset["type"] == "snapshot"
    assert reset["seq"] == 3
    assert reset["payload"]["settings"]["brightness"] == 60


def test_hub_detaches_input_and_shares_an_immutable_wire_message():
    hub = StreamHub()
    payload = _payload()
    first, initial = _subscribe(hub, payload)
    second, _ = _subscribe(hub, payload)
    projection = Projection.of({**payload, "settings": {**payload["settings"], "brightness": 80}})
    with pytest.raises(TypeError):
        projection.sections["settings"] = "{}"
    payload["content"]["sports"][0]["data"]["away_score"] = "999"
    hub.publish("ticker-1", projection)
    left, right = first.queue.get_nowait(), second.queue.get_nowait()
    assert left is right
    assert json.loads(left.text)["changes"]["settings"]["brightness"] == 80
    assert json.loads(initial[0].text)["payload"]["content"]["sports"][0]["data"]["away_score"] == "17"


def test_hub_tracks_removed_and_null_sections_and_ignores_object_key_order():
    hub = StreamHub()
    payload = {"settings": {"brightness": 80, "name": "é雪\"\n"}, "obsolete": {"value": 1}}
    subscriber, _ = _subscribe(hub, payload)
    hub.publish("ticker-1", Projection.of({"obsolete": {"value": 1}, "settings": {"name": "é雪\"\n", "brightness": 80}}))
    assert subscriber.queue.empty()
    hub.publish("ticker-1", Projection.of({"settings": payload["settings"], "nullable": None}))
    value = json.loads(subscriber.queue.get_nowait().text)
    assert value["removed"] == ["obsolete"]
    assert value["changes"] == {"nullable": None}


def test_hub_ignores_a_timing_only_change():
    hub = StreamHub()
    payload = {"snapshot": {"ticker_id": "ticker-1", "timing": {"published_at_ms": 1.0}}, "settings": {}}
    subscriber, _ = _subscribe(hub, payload)
    hub.publish("ticker-1", Projection.of({**payload, "snapshot": {"ticker_id": "ticker-1", "timing": {"published_at_ms": 2.0}}}))
    assert subscriber.queue.empty()


def test_projection_runs_outside_the_event_loop_and_stops_at_once():
    import asyncio
    from threading import get_ident

    async def run():
        main_thread = get_ident()
        threads = []
        changed = deepcopy(_payload())
        changed["settings"]["brightness"] = 80

        def projector(ticker_id):
            threads.append(get_ident())
            return changed

        hub = StreamHub()
        subscriber, _ = _subscribe(hub, _payload())
        stop = asyncio.Event()
        runner = asyncio.create_task(hub.run(projector, stop))
        await asyncio.sleep(0)
        hub.changed("ticker-1")
        message = json.loads((await asyncio.wait_for(subscriber.queue.get(), 5)).text)
        assert message["changes"]["settings"]["brightness"] == 80
        assert threads and all(thread != main_thread for thread in threads)
        stop.set()
        await asyncio.wait_for(runner, 0.5)

    asyncio.run(run())
