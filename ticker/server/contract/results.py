"""Encode a ProviderResult as JSON in a worker and decode it in the core."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

RESULT_FIELDS = {"content", "alerts", "news", "observed_at", "health"}


def encode(value: Any) -> Any:
    """Return a JSON-ready copy of a dataclass, mapping, sequence, or datetime value."""
    if is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [encode(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def decode_result(value: Any, *, receipt: Mapping[str, Any] | None = None):
    """Rebuild one ProviderResult. A receipt adds latency timing to each content item."""
    from ticker.shared.domain import ContentItem
    from ticker.server.providers.contracts import ProviderHealth, ProviderResult

    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise ValueError("worker result does not match the provider contract")
    prefix = uuid4().hex
    content = []
    for item in value["content"]:
        if receipt is not None:
            timing = item["data"].get("_source_timing")
            timing = dict(timing) if isinstance(timing, Mapping) else {
                "trace_id": f"worker:{prefix}:{item['id']}", "source": receipt["source"],
                "ingested_at_ms": receipt["core_received_at_ms"], "input_boundary": "core_worker_result_received"}
            timing.update(core_received_at_ms=receipt["core_received_at_ms"], request_started_ms=receipt["request_started_ms"])
            item = {**item, "data": {**item["data"], "_source_timing": timing}}
        content.append(ContentItem(**item))
    return ProviderResult(content=tuple(content), alerts=tuple(value["alerts"]), news=tuple(value["news"]),
                          observed_at=datetime.fromisoformat(value["observed_at"]), health=ProviderHealth(**value["health"]))
