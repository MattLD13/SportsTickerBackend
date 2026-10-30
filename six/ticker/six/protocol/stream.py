"""Validate and apply sequenced device stream messages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any

from ticker.six.protocol.model import PayloadValidationError, TickerResponse


@dataclass(frozen=True, slots=True)
class StreamMessage:
    """Hold one validated server envelope."""

    kind: str
    stream_id: str
    sequence: int
    base_sequence: int
    payload: Mapping[str, Any] | None = None
    changes: Mapping[str, Any] | None = None
    removed: tuple[str, ...] = ()
    server_time: str = ""
    projected_at_ms: float | None = None

    @classmethod
    def from_payload(cls, value: object) -> "StreamMessage":
        """Validate the envelope before it changes controller state."""
        if not isinstance(value, Mapping):
            raise PayloadValidationError("stream message must be an object")
        kind = value.get("type")
        if kind not in {"snapshot", "delta", "ready"}:
            raise PayloadValidationError("stream message type is invalid")
        stream_id = value.get("stream_id")
        if not isinstance(stream_id, str) or not stream_id.strip():
            raise PayloadValidationError("stream_id must be a non-empty string")
        sequence = _sequence(value.get("seq"), "seq")
        base_sequence = _sequence(value.get("base_seq"), "base_seq")
        if kind in {"snapshot", "ready"} and base_sequence != sequence:
            raise PayloadValidationError("snapshot and ready base_seq must match seq")
        if kind == "delta" and sequence != base_sequence + 1:
            raise PayloadValidationError("delta seq must follow base_seq")
        if not isinstance(value.get("server_time"), str):
            raise PayloadValidationError("server_time must be a string")
        timing = value.get("timing", {})
        if not isinstance(timing, Mapping):
            raise PayloadValidationError("stream timing must be an object")
        projected = timing.get("projected_at_ms")
        if projected is not None and (isinstance(projected, bool) or not isinstance(projected, (int, float)) or not math.isfinite(projected) or projected < 0):
            raise PayloadValidationError("projected_at_ms must be a number")
        payload = value.get("payload")
        changes = value.get("changes")
        removed = value.get("removed", ())
        if kind == "snapshot" and not isinstance(payload, Mapping):
            raise PayloadValidationError("snapshot payload must be an object")
        if kind == "delta" and not isinstance(changes, Mapping):
            raise PayloadValidationError("delta changes must be an object")
        if not isinstance(removed, (list, tuple)) or any(not isinstance(item, str) for item in removed):
            raise PayloadValidationError("delta removed must contain strings")
        return cls(
            kind,
            stream_id.strip(),
            sequence,
            base_sequence,
            dict(payload) if isinstance(payload, Mapping) else None,
            dict(changes) if isinstance(changes, Mapping) else None,
            tuple(removed),
            value["server_time"],
            float(projected) if projected is not None else None,
        )


class DeviceStreamState:
    """Apply snapshots and contiguous deltas while rejecting sequence gaps."""

    def __init__(self) -> None:
        self.stream_id: str | None = None
        self.sequence: int | None = None
        self._response: TickerResponse | None = None

    @property
    def cursor(self) -> tuple[str, int] | None:
        """Return a reconnect cursor after receiving a full snapshot."""
        if self.stream_id is None or self.sequence is None or self._response is None:
            return None
        return self.stream_id, self.sequence

    def apply(self, message: StreamMessage) -> TickerResponse | None:
        """Apply a new message and return changed effective display data."""
        if message.kind == "ready":
            if self.cursor != (message.stream_id, message.sequence):
                raise PayloadValidationError("ready cursor does not match local stream state")
            return None
        if message.kind == "snapshot":
            if (
                self.stream_id == message.stream_id
                and self.sequence is not None
                and message.sequence < self.sequence
            ):
                return None
            response = TickerResponse.from_payload(message.payload)
        else:
            if self.stream_id != message.stream_id or self.sequence is None or self._response is None:
                raise PayloadValidationError("delta arrived without its matching snapshot")
            if message.sequence <= self.sequence:
                return None
            if message.base_sequence != self.sequence or message.sequence != self.sequence + 1:
                raise PayloadValidationError("delta sequence is stale or has a gap")
            response = self._response.apply_projection_delta(message.changes or {}, message.removed)
        self.stream_id = message.stream_id
        self.sequence = message.sequence
        self._response = response
        return response


def _sequence(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PayloadValidationError(f"{name} must be a non-negative integer")
    return value
