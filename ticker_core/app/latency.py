"""Track provider input through reception, pane preparation, and successful presentation."""

from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime
import math
from typing import Any


def timestamp(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def received_timing(response, message, *, received_ms: float, received_mono: float, decoded_mono: float, queued_mono: float, item_ids) -> dict:
    """Detach optional V2 timing metadata for the polling process boundary."""
    snapshot = response.data.get("snapshot", {})
    source = snapshot.get("timing", {}) if isinstance(snapshot, Mapping) else {}
    items = source.get("items", {}) if isinstance(source, Mapping) else {}
    active_items = [item.id for item in response.content if item.is_shown]
    visible_ids = set(active_items)
    selected_ids = tuple(identifier for identifier in item_ids if identifier in visible_ids)
    try:
        published = datetime.fromisoformat(message.server_time.replace("Z", "+00:00")) if message is not None else None
        server_ms = published.timestamp() * 1000 if published is not None and published.tzinfo is not None else None
    except (ValueError, TypeError):
        server_ms = None
    return {
        "received_at_ms": received_ms, "received_mono": received_mono, "decoded_mono": decoded_mono,
        "queued_mono": queued_mono, "response_key": response.payload_key,
        "transport": "websocket" if message is not None else "http_bootstrap",
        "server_published_at_ms": server_ms,
        "snapshot_ready_ms": source.get("snapshot_ready_ms") if isinstance(source, Mapping) else None,
        "projected_at_ms": message.projected_at_ms if message is not None else None,
        "active_items": active_items,
        "items": {
            identifier: dict(items[identifier]) if isinstance(items, Mapping) and isinstance(items.get(identifier), Mapping)
            else {"trace_id": f"{message.stream_id if message is not None else response.payload_key}:{message.sequence if message is not None else 0}:{identifier}",
                  "source": "backend_stream" if message is not None else "backend_http"}
            for identifier in selected_ids
        },
    }


class DisplayLatencyTracker:
    """Keep at most one pending visual update per item without retaining image data."""

    def __init__(self, record):
        self._record = record
        self._pending: OrderedDict[str, dict] = OrderedDict()
        self._presented: OrderedDict[tuple[str, str], None] = OrderedDict()

    @property
    def pending_ids(self) -> tuple[str, ...]:
        return tuple(self._pending)

    def accept(self, timing: Mapping[str, Any] | None, *, event_mono: float, accepted_mono: float, delay_seconds: float) -> None:
        if not timing:
            return
        removed = set(timing.get("removed_items", ()))
        if timing.get("active_items") is not None:
            removed.update(self._pending.keys() - set(timing["active_items"]))
        for identifier in removed:
            previous = self._pending.pop(identifier, None)
            if previous is not None:
                self._finish(identifier, previous, "removed_before_present")
        for identifier, source in timing.get("items", {}).items():
            if not isinstance(source, Mapping):
                continue
            previous = self._pending.pop(identifier, None)
            if previous is not None:
                self._finish(identifier, previous, "superseded")
            self._pending[identifier] = {
                "trace_id": str(source.get("trace_id", ""))[:200], "source": str(source.get("source", ""))[:64],
                "source_timestamp_kind": str(source.get("source_timestamp_kind", ""))[:64],
                "input_boundary": str(source.get("input_boundary", ""))[:64],
                "response_key": str(timing.get("response_key", "")), "transport": str(timing.get("transport", "")),
                "ingested_at_ms": timestamp(source.get("ingested_at_ms")),
                "source_published_at_ms": timestamp(source.get("source_published_at_ms")),
                "core_received_at_ms": timestamp(source.get("core_received_at_ms")),
                "request_started_ms": timestamp(source.get("request_started_ms")),
                **{key: timestamp(timing.get(key)) for key in (
                    "received_at_ms", "received_mono", "decoded_mono", "queued_mono", "server_published_at_ms", "snapshot_ready_ms", "projected_at_ms")},
                "event_mono": event_mono, "accepted_mono": accepted_mono,
                "configured_delay_ms": delay_seconds * 1000.0,
            }
            current = self._pending.get(identifier)
            if current is not None and (identifier, current["trace_id"]) in self._presented:
                self._pending.pop(identifier)
                self._finish(identifier, current, "trace_already_presented")

    def presented(self, visible: Mapping[str, Mapping[str, Any]], *, at_ms: float, at_mono: float, present_started: float) -> None:
        for identifier, state in visible.items():
            value = self._pending.pop(identifier, None)
            if value is None:
                continue
            outcome = "presented" if state.get("changed_visible") else "unchanged_pixels"
            if outcome == "presented" and value["trace_id"]:
                self._presented[(identifier, value["trace_id"])] = None
                while len(self._presented) > 4096:
                    self._presented.popitem(last=False)
            installed = state.get("installed_mono", present_started)
            value.update(presented_at_ms=at_ms, presented_mono=at_mono, present_started_mono=present_started,
                         pane_installed_mono=max(installed, value["accepted_mono"]),
                         pane_ready_during_accept=installed < value["accepted_mono"])
            self._finish(identifier, value, outcome)

    def _finish(self, identifier: str, value: dict, outcome: str) -> None:
        if outcome != "presented":
            value.pop("presented_at_ms", None)
            value.pop("presented_mono", None)
        record = {key: item for key, item in value.items() if not key.endswith("mono") and key != "received_mono"}
        record.update(item_id=identifier, outcome=outcome, clock_basis="utc_unix_ms", presentation_boundary="frame_sink_return")

        def span(name, start, end, scale=1.0):
            a, b = timestamp(value.get(start)), timestamp(value.get(end))
            record[name] = round((b - a) * scale, 3) if a is not None and b is not None else None

        span("source_to_present_ms", "ingested_at_ms", "presented_at_ms")
        span("snapshot_to_present_ms", "snapshot_ready_ms", "presented_at_ms")
        span("core_to_present_ms", "core_received_at_ms", "presented_at_ms")
        span("request_to_present_ms", "request_started_ms", "presented_at_ms")
        span("publisher_to_present_ms", "source_published_at_ms", "presented_at_ms")
        span("publisher_to_ingress_ms", "source_published_at_ms", "ingested_at_ms")
        span("ingress_to_snapshot_ms", "ingested_at_ms", "snapshot_ready_ms")
        span("ingress_to_core_ms", "ingested_at_ms", "core_received_at_ms")
        span("core_to_snapshot_ms", "core_received_at_ms", "snapshot_ready_ms")
        span("snapshot_to_projection_ms", "snapshot_ready_ms", "projected_at_ms")
        span("projection_to_publication_ms", "projected_at_ms", "server_published_at_ms")
        span("publication_to_receive_ms", "server_published_at_ms", "received_at_ms")
        span("decode_ms", "received_mono", "decoded_mono", 1000)
        if value.get("transport") == "http_bootstrap":
            record["decode_ms"] = None
            record["receive_boundary"] = "http_fetch_complete"
        elif value.get("transport") == "websocket":
            record["receive_boundary"] = "websocket_recv_return"
        else:
            record["receive_boundary"] = value.get("transport") or "unavailable"
        span("client_prepare_ms", "decoded_mono", "queued_mono", 1000)
        span("queue_ms", "queued_mono", "event_mono", 1000)
        span("accept_ms", "event_mono", "accepted_mono", 1000)
        span("pane_prepare_ms", "accepted_mono", "pane_installed_mono", 1000)
        if record["pane_prepare_ms"] is not None and record["pane_prepare_ms"] < 0:
            record["pane_ready_during_accept"] = True
            record["pane_prepare_ms"] = 0.0
        span("visibility_wait_ms", "pane_installed_mono", "present_started_mono", 1000)
        span("present_ms", "present_started_mono", "presented_mono", 1000)
        span("device_to_present_ms", "received_mono", "presented_mono", 1000)
        spans = (record.get(key) for key in ("publisher_to_ingress_ms", "ingress_to_snapshot_ms", "snapshot_to_projection_ms", "projection_to_publication_ms", "publication_to_receive_ms"))
        record["clock_order_valid"] = all(item is None or item >= 0 for item in spans)
        self._record(record)
