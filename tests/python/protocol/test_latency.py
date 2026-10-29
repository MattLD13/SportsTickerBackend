"""Verify correlated input-to-visible-frame timing without changing display facts."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import pickle

import pytest

from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.projections.data_api import project_data_v2
from sports_ticker.providers.espn_fastcast import EspnFastcastSource, fastcast_published_at_ms
from ticker_core.app.latency import DisplayLatencyTracker, received_timing
from ticker3.api.stream import Projection, StreamHub
from ticker_core.protocol import StreamMessage, TickerResponse

pytestmark = pytest.mark.critical
BASE = 1792979000000


def test_fastcast_timestamp_comes_from_the_wrapper_and_not_the_message_id():
    message = {"op": "P", "mid": BASE + 100, "pl": json.dumps({"ts": BASE, "~c": 1, "pl": "compressed"})}
    assert fastcast_published_at_ms(message) == BASE
    assert fastcast_published_at_ms({"mid": BASE, "pl": "[]"}) is None
    for value in (True, float("nan"), BASE / 1000, "not-a-time"):
        assert fastcast_published_at_ms({"ts": value}) is None


def test_event_timing_stays_with_the_retained_snapshot_and_http_replaces_its_origin():
    wall = [BASE / 1000 + 0.2]
    source = EspnFastcastSource({"nfl": "topic"}, wall_clock=lambda: wall[0], monotonic=lambda: 10)
    event = {"id": "game", "uid": "event:game", "status": {"state": "pre"}}
    source.prime("nfl", {"events": [event]})
    source._handle_wire_message(json.dumps({"op": "P", "tc": "topic", "mid": 1, "pl": json.dumps({
        "ts": BASE, "pl": [{"op": "replace", "path": "/events/0/status/state", "value": "in"}],
    })}))
    snapshot, timings = source.timed_snapshot("nfl")
    assert snapshot["events"][0]["status"]["state"] == "in"
    assert timings["game"]["source_published_at_ms"] == BASE
    assert timings["game"]["ingested_at_ms"] == pytest.approx(BASE + 200)
    assert timings["game"]["source_timestamp_kind"] == "publisher_envelope"
    wall[0] += 1
    source.prime_event("nfl", {**event, "status": {"state": "post"}})
    _, newer = source.timed_snapshot("nfl")
    assert newer["game"]["source"] == "espn_http"
    assert "source_published_at_ms" not in newer["game"]
    assert timings["game"]["source"] == "espn_fastcast"


def traced_payload():
    trace = {"trace_id": "topic:1:game", "source": "espn_fastcast", "ingested_at_ms": BASE,
             "source_published_at_ms": BASE - 100, "source_timestamp_kind": "publisher_envelope"}
    snapshot = TickerSnapshot("ticker", 0, datetime.now(timezone.utc), (
        ContentItem(id="game", data={"sport": "nfl", "home_score": "7", "_source_timing": trace}),
    ), (), (), DisplaySettings())
    store = SnapshotStore(clock=lambda: (BASE + 100) / 1000)
    return project_data_v2(store.replace(snapshot), {}, {})


def test_timing_survives_projection_but_does_not_enter_the_scene_or_display_fingerprint():
    payload = traced_payload()
    assert payload["snapshot"]["timing"]["snapshot_ready_ms"] == BASE + 100
    assert "_source_timing" not in payload["content"]["sports"][0]["data"]
    before = TickerResponse.from_payload(payload)
    changed = deepcopy(payload)
    changed["snapshot"]["timing"]["snapshot_ready_ms"] += 100
    after = TickerResponse.from_payload(changed)
    assert before.payload_key == after.payload_key
    assert before.content == after.content
    hub = StreamHub()
    subscriber, _ = hub.subscribe("ticker", Projection.of(payload), stream_id=None, after_seq=None)
    hub.publish("ticker", Projection.of(changed))
    assert subscriber.queue.empty()
    _, current = hub.subscribe("ticker", Projection.of(changed), stream_id=hub.stream_id, after_seq=1)
    assert json.loads(current[0].text)["type"] == "ready"


def test_input_timing_alone_does_not_create_a_new_delayed_source_frame():
    now = [1000.0]
    store = SnapshotStore(clock=lambda: now[0])

    def snapshot(trace_id):
        return TickerSnapshot("ticker", 0, datetime.now(timezone.utc), (
            ContentItem(id="game", data={"home_score": "7", "_source_timing": {"trace_id": trace_id}}),
        ), (), (), DisplaySettings())

    first = store.replace(snapshot("one"))
    now[0] += 1
    latest = store.replace(snapshot("two"))
    assert latest.revision == 2
    assert store.get_delayed("ticker", 0) is first


def timing():
    return {"received_at_ms": 1160, "received_mono": 2, "decoded_mono": 2.01, "queued_mono": 2.015,
            "server_published_at_ms": 1130, "snapshot_ready_ms": 1100, "projected_at_ms": 1120,
            "items": {"game": {"trace_id": "one", "source": "espn_fastcast", "ingested_at_ms": 1000,
                               "source_published_at_ms": 900, "source_timestamp_kind": "publisher_envelope"}}}


def test_latency_records_the_complete_path_only_after_matching_pixels_are_presented():
    rows = []
    tracker = DisplayLatencyTracker(rows.append)
    tracker.accept(timing(), event_mono=2.02, accepted_mono=2.03, delay_seconds=0)
    tracker.presented({"other": {"changed_visible": True}}, at_ms=1200, at_mono=2.04, present_started=2.035)
    assert rows == []
    tracker.presented({"game": {"changed_visible": True, "installed_mono": 2.05}}, at_ms=1240, at_mono=2.08, present_started=2.07)
    row = rows[0]
    assert row["source_to_present_ms"] == 240
    assert row["publisher_to_present_ms"] == 340
    assert row["publisher_to_ingress_ms"] == 100
    assert row["decode_ms"] == row["accept_ms"] == row["present_ms"] == 10
    assert row["client_prepare_ms"] == row["queue_ms"] == 5
    assert row["pane_prepare_ms"] == row["visibility_wait_ms"] == 20
    assert row["device_to_present_ms"] == 80
    assert row["clock_order_valid"]
    assert tracker.pending_ids == ()


def test_visibility_at_accept_and_ready_time_survive_offscreen_supersession():
    rows = []
    tracker = DisplayLatencyTracker(rows.append)
    tracker.accept(timing(), event_mono=2.02, accepted_mono=2.03, delay_seconds=0,
                   visible_ids=frozenset({"other"}))
    tracker.ready({"game": {"installed_mono": 2.08, "worker_wait_ms": 10, "worker_render_ms": 30}})
    tracker.accept(timing(), event_mono=2.10, accepted_mono=2.11, delay_seconds=0,
                   visible_ids=frozenset({"game"}))
    assert rows[0]["outcome"] == "superseded"
    assert rows[0]["visible_at_accept"] is False
    assert rows[0]["pane_prepare_ms"] == 50
    assert rows[0]["worker_wait_ms"] == 10 and rows[0]["worker_render_ms"] == 30
    assert rows[0]["visibility_wait_ms"] is None
    tracker.presented({"game": {"changed_visible": True, "installed_mono": 2.15}},
                      at_ms=1300, at_mono=2.2, present_started=2.19)
    assert rows[1]["visible_at_accept"] is True
    assert rows[1]["pane_prepare_ms"] == 40
    assert rows[1]["visibility_wait_ms"] == 40


def test_visibility_classification_uses_presented_geometry_and_marks_overlays_unknown():
    from ticker_core.app.application import TickerApplication
    from ticker_core.runtime import Content, FrameDecision, FrameKind

    class Viewport:
        def visible_ids(self, offset, width):
            assert (offset, width) == (12, 384)
            return frozenset({"game"})

    class Sink:
        width = 384

    app = object.__new__(TickerApplication)
    app._viewport, app._sink = Viewport(), Sink()
    frame = FrameDecision(FrameKind.SCROLL, .03, 100, False, datetime.now(timezone.utc), "sports", scroll_offset=12)
    assert app._visible_ids_for_decision(frame) == frozenset({"game"})
    from dataclasses import replace
    assert app._visible_ids_for_decision(replace(frame, connection_lost=True)) is None
    assert app._visible_ids_for_decision(replace(frame, news={"id": "news"})) is None
    assert app._visible_ids_for_decision(replace(frame, kind=FrameKind.SCORE_ALERT)) is None
    assert app._visible_ids_for_decision(replace(frame, kind=FrameKind.STATIC,
                                                 content=Content("pinned", "scoreboard", "nfl", {}))) == frozenset({"pinned"})


def test_reused_card_does_not_attribute_an_earlier_worker_run_to_a_new_update():
    rows = []
    tracker = DisplayLatencyTracker(rows.append)
    tracker.accept(timing(), event_mono=2.02, accepted_mono=2.03, delay_seconds=0, visible_ids=frozenset({"game"}))
    tracker.ready({"game": {"installed_mono": 2.0, "worker_wait_ms": 100, "worker_render_ms": 50}})
    tracker.presented({"game": {"changed_visible": True, "installed_mono": 2.0}},
                      at_ms=1240, at_mono=2.08, present_started=2.07)
    assert rows[0]["pane_ready_during_accept"] is True
    assert rows[0]["pane_prepare_ms"] == 0
    assert rows[0]["worker_wait_ms"] is None and rows[0]["worker_render_ms"] is None


def test_superseded_and_unchanged_pixels_do_not_claim_a_display_latency():
    rows = []
    tracker = DisplayLatencyTracker(rows.append)
    for _ in range(2):
        tracker.accept(timing(), event_mono=2.02, accepted_mono=2.03, delay_seconds=120)
    assert rows[0]["outcome"] == "superseded"
    assert rows[0]["source_to_present_ms"] is None
    tracker.presented({"game": {"changed_visible": False}}, at_ms=1240, at_mono=2.08, present_started=2.07)
    assert rows[1]["outcome"] == "unchanged_pixels"
    assert rows[1]["source_to_present_ms"] is None
    assert rows[1]["configured_delay_ms"] == 120000


def test_bad_clock_order_remains_visible_in_the_record():
    rows = []
    value = timing()
    value["items"]["game"]["source_published_at_ms"] = 2000
    tracker = DisplayLatencyTracker(rows.append)
    tracker.accept(value, event_mono=2.02, accepted_mono=2.03, delay_seconds=0)
    tracker.presented({"game": {"changed_visible": True}}, at_ms=1240, at_mono=2.08, present_started=2.07)
    assert not rows[0]["clock_order_valid"]
    assert rows[0]["publisher_to_ingress_ms"] == -1000


def test_the_same_input_trace_is_measured_only_at_its_first_presentation():
    rows = []
    tracker = DisplayLatencyTracker(rows.append)
    tracker.accept(timing(), event_mono=2.02, accepted_mono=2.03, delay_seconds=0)
    tracker.presented({"game": {"changed_visible": True}}, at_ms=1240, at_mono=2.08, present_started=2.07)
    tracker.accept(timing(), event_mono=3.02, accepted_mono=3.03, delay_seconds=0)
    assert tracker.pending_ids == ()
    assert [row["outcome"] for row in rows] == ["presented", "trace_already_presented"]
    assert rows[1]["source_to_present_ms"] is None


def test_receive_timing_is_serializable_across_the_polling_process_boundary():
    payload = traced_payload()
    response = TickerResponse.from_payload(payload)
    message = StreamMessage.from_payload({"type": "snapshot", "stream_id": "one", "seq": 1,
                                         "base_seq": 1, "server_time": "2026-10-25T22:00:00+00:00", "payload": payload})
    value = received_timing(response, message, received_ms=BASE + 200, received_mono=2, decoded_mono=2.01, queued_mono=2.015, item_ids=["game"])
    assert pickle.loads(pickle.dumps(value)) == value
    assert json.loads(json.dumps(value)) == value


def test_timing_tracks_all_150_games_and_prunes_games_that_leave_the_rotation():
    payload = traced_payload()
    original = payload["content"]["sports"][0]
    payload["content"]["sports"] = [{**deepcopy(original), "id": f"game-{index}"} for index in range(150)]
    response = TickerResponse.from_payload(payload)
    identifiers = [item.id for item in response.content]
    value = received_timing(response, None, received_ms=BASE + 200, received_mono=2,
                            decoded_mono=2.01, queued_mono=2.015, item_ids=identifiers)
    rows = []
    tracker = DisplayLatencyTracker(rows.append)
    tracker.accept(value, event_mono=2.02, accepted_mono=2.03, delay_seconds=0)
    assert len(tracker.pending_ids) == 150
    assert tracker.pending_ids[-1] == "game-149"
    tracker.presented({"game-149": {"changed_visible": True, "installed_mono": 2.05}},
                      at_ms=BASE + 240, at_mono=2.08, present_started=2.07)
    assert rows[-1]["item_id"] == "game-149"
    assert rows[-1]["outcome"] == "presented"
    tracker.accept({**value, "active_items": ["game-0"], "items": {}},
                   event_mono=3, accepted_mono=3.01, delay_seconds=0)
    assert tracker.pending_ids == ("game-0",)
    assert sum(row["outcome"] == "removed_before_present" for row in rows) == 148


def test_polling_process_bridge_retains_timing_on_success_events():
    from queue import Queue
    from ticker_core.app.application import _ProcessPollEvents
    from ticker_core.app.poller import PollSucceeded

    target = Queue()
    source = PollSucceeded(TickerResponse.from_payload(traced_payload()), 12.0, 123, timing())
    _ProcessPollEvents(target).put(source)
    restored = pickle.loads(pickle.dumps(target.get_nowait()))
    assert restored.timing == source.timing
    assert restored.payload.payload_key == source.payload.payload_key


def test_worker_receipt_starts_generic_timing_and_preserves_earlier_fastcast_timing():
    from ticker3.contract.results import decode_result, encode
    from sports_ticker.providers.contracts import ProviderResult

    result = ProviderResult(content=(ContentItem(id="weather", family="weather", kind="weather", data={"temperature": 75}),))
    receipt = {"source": "weather", "request_started_ms": 1000, "core_received_at_ms": 1200}
    traced = decode_result(encode(result), receipt=receipt)
    value = traced.content[0].data["_source_timing"]
    assert value["ingested_at_ms"] == value["core_received_at_ms"] == 1200
    assert value["input_boundary"] == "core_worker_result_received"
    source = ContentItem(id="game", data={"_source_timing": {"trace_id": "one", "source": "espn_fastcast", "ingested_at_ms": 900}})
    traced = decode_result(encode(ProviderResult(content=(source,))), receipt={**receipt, "source": "espn"})
    assert traced.content[0].data["_source_timing"]["ingested_at_ms"] == 900
    assert traced.content[0].data["_source_timing"]["core_received_at_ms"] == 1200


def test_report_counts_first_presentation_per_device_and_omits_small_sample_tail_estimates():
    from tools.diagnostics.latency_report import summarize

    row = {"kind": "latency", "source": "espn_fastcast", "outcome": "presented", "device_id": "a",
           "item_id": "game", "trace_id": "one", "source_to_present_ms": 10, "clock_order_valid": True}
    result = summarize([row, {**row, "source_to_present_ms": 20}, {**row, "device_id": "b", "source_to_present_ms": 30}])
    assert result["unique_presentations"] == 2
    assert result["duplicate_presentations_excluded"] == 1
    metric = result["sources"]["espn_fastcast"]["metrics"]["source_to_present_ms"]
    assert metric["p50_ms"] == 20
    assert metric["p95_ms"] is None
