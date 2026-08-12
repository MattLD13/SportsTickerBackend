from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ticker_core.protocol import DeviceState, PayloadValidationError, TickerResponse, canonical_payload_hash
from ticker_core.runtime import TickerRuntime


def _payload() -> dict:
    return {
        "status": "ok",
        "ticker_id": "pi-1",
        "global_config": {"update": True, "update_version": "r99", "reboot": False, "other": {"x": 1}},
        "local_config": {"mode": "sports", "brightness": 85, "scroll_speed": 0.04, "inverted": True, "extra": [1]},
        "content": {"sports": [{"id": "game-1", "type": "game", "home": {"name": "Cats"}}]},
        "alerts": [{"id": "alert-1", "headline": "Goal"}],
        "news": [{"id": "news-1", "text": "Trade"}],
    }


def test_response_validates_runtime_fields_and_keeps_unknown_fields() -> None:
    response = TickerResponse.from_payload(_payload())

    assert response.status is DeviceState.ACTIVE
    assert response.local_config.mode == "sports"
    assert response.local_config.brightness == 85.0
    assert response.content[0].id == "game-1"
    assert response.content[0]["home"]["name"] == "Cats"
    assert response.global_config.data["other"]["x"] == 1
    with pytest.raises(TypeError):
        response.content[0].data["id"] = "changed"  # type: ignore[index]


def test_pairing_response_has_defaults() -> None:
    response = TickerResponse.from_payload({"status": "pairing", "code": "123456", "ticker_id": "pi-1"})

    assert response.status is DeviceState.PAIRING
    assert response.pairing_code == "123456"
    assert response.content == ()
    assert response.local_config.mode == "sports"


@pytest.mark.parametrize(
    ("legacy_mode", "canonical_mode"),
    [
        ("flight_tracker", "flights"),
        ("soccer_full", "sports_full"),
        ("f1", "sports"),
    ],
)
def test_response_translates_retired_server_modes(legacy_mode: str, canonical_mode: str) -> None:
    response = TickerResponse.from_payload({"local_config": {"mode": legacy_mode}})

    assert response.local_config.mode == canonical_mode


def test_translated_server_mode_reaches_the_runtime() -> None:
    response = TickerResponse.from_payload({"local_config": {"mode": "flight_tracker"}})
    runtime = TickerRuntime(
        monotonic=lambda: 0.0,
        wall_clock=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
    )

    runtime.accept_response(response)

    assert runtime.mode == "flights"


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"status": "broken"}, "response.status"),
        ({"content": {"sports": [{}]}}, r"response\.content\.sports\[0\]\.id"),
        ({"alerts": {"id": "a"}}, "response.alerts must be a list"),
        ({"local_config": {"brightness": "bright"}}, "local_config.brightness"),
    ],
)
def test_response_rejects_invalid_boundary_data(payload: dict, message: str) -> None:
    with pytest.raises(PayloadValidationError, match=message):
        TickerResponse.from_payload(payload)


def test_canonical_hash_ignores_mapping_order_and_detects_changes() -> None:
    first = {"b": [1, {"x": "y"}], "a": True}
    second = {"a": True, "b": [1, {"x": "y"}]}

    assert canonical_payload_hash(first) == canonical_payload_hash(second)
    assert canonical_payload_hash(first) != canonical_payload_hash({"a": False, "b": [1, {"x": "y"}]})
