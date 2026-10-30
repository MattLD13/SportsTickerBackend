"""Keep device polling limited to content selected by the V2 projection."""
from collections.abc import Mapping
from typing import Any
from ticker.server.projections.mini_fields import SPORTS_FIELDS
from ticker.server.projections.racing_display import mini_racing_cards


def project_device_data(payload: Mapping[str, Any], *, mini: bool = False) -> dict[str, Any]:
    """Omit hidden records without changing selected display facts or controller data."""
    visible = {**payload, "content": {
        family: [item for item in items if item["is_shown"]]
        for family, items in payload["content"].items()
    }}
    return compact_mini_data(visible) if mini else visible


def compact_mini_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the Mini wire fields after asset facts have been projected."""
    result = {**payload, "content": {
        family: [{**item, "data": select_fields(item["data"], SPORTS_FIELDS)} for item in items]
                if family == "sports" else [card for item in items for card in mini_racing_cards(item)] if family == "racing" else items
        for family, items in payload["content"].items()
    }}
    if isinstance(payload.get("snapshot"), Mapping):
        result["snapshot"] = {key: value for key, value in payload["snapshot"].items() if key != "timing"}
    return result


def select_fields(value, specification):
    """Copy only declared fields while retaining source values and types."""
    if specification is True:
        return value
    if isinstance(specification, list) and isinstance(value, (list, tuple)):
        return [select_fields(item, specification[0]) for item in value]
    if isinstance(specification, dict) and isinstance(value, Mapping):
        return {key: select_fields(value[key], child) for key, child in specification.items() if key in value}
    return value
