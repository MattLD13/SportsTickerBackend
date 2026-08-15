"""Validate the version two display payload boundary."""

from datetime import datetime, timezone
import pickle

import pytest

from ticker_core.protocol import DeviceState, PayloadValidationError, TickerResponse, canonical_payload_hash


def _payload(mode: str = "sports") -> dict:
    return {
        "api_version": "v2",
        "snapshot": {"ticker_id": "pi-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
        "settings": {"mode": mode, "sports_presentation": "rotation", "pinned_content_id": "", "brightness": 85, "scroll_speed": 0.04, "inverted": True},
        "content": {"sports": [{"id": "game-1", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nfl", "state": "in"}}]},
        "events": {"alerts": [], "news": []}, "health": {"provider": "refresh", "healthy": True, "error": None},
        "meta": {"pairing": {"paired": mode != "pairing", "code": "123456" if mode == "pairing" else None}},
    }


def test_response_validates_the_v2_display_contract() -> None:
    response = TickerResponse.from_payload(_payload())

    assert response.status is DeviceState.ACTIVE
    assert response.settings.mode == "sports"
    assert response.content[0]["sport"] == "nfl"
    with pytest.raises(TypeError):
        response.content[0].data["sport"] = "mlb"  # type: ignore[index]


def test_pairing_response_exposes_the_pairing_code() -> None:
    response = TickerResponse.from_payload(_payload("pairing"))

    assert response.status is DeviceState.PAIRING
    assert response.pairing_code == "123456"


def test_payload_boundary_rejects_a_non_v2_response() -> None:
    with pytest.raises(PayloadValidationError, match="api_version"):
        TickerResponse.from_payload({"api_version": "v1"})


def test_canonical_hash_ignores_mapping_order() -> None:
    assert canonical_payload_hash({"a": True, "b": [1]}) == canonical_payload_hash({"b": [1], "a": True})


def test_snapshot_observation_does_not_restart_the_display_pipeline() -> None:
    before = _payload()
    after = _payload()
    after["snapshot"]["observed_at"] = "2026-08-11T00:00:01+00:00"
    after["snapshot"]["revision"] = 2

    assert TickerResponse.from_payload(before).payload_key == TickerResponse.from_payload(after).payload_key


def test_response_can_cross_the_poll_process_without_mapping_proxy_errors() -> None:
    response = TickerResponse.from_payload(_payload())
    restored = pickle.loads(pickle.dumps(response))

    assert restored.payload_key == response.payload_key
    assert restored.content[0].data == response.content[0].data
