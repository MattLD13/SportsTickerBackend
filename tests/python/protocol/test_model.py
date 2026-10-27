"""Validate the version two display payload boundary."""

from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
import pickle
from types import MappingProxyType

import pytest

from ticker_core.protocol import DeviceState, PayloadValidationError, TickerResponse, apply_display_delta, canonical_payload_hash, display_delta

pytestmark = pytest.mark.critical


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


def test_payload_hashing_and_snapshot_stability() -> None:
    assert canonical_payload_hash({"a": True, "b": [1]}) == canonical_payload_hash({"b": [1], "a": True})

    before = _payload()
    after = _payload()
    after["snapshot"]["observed_at"] = "2026-08-11T00:00:01+00:00"
    after["snapshot"]["revision"] = 2

    assert TickerResponse.from_payload(before).payload_key == TickerResponse.from_payload(after).payload_key


def test_payload_hash_matches_canonical_wire_data_and_rejects_nonfinite_values() -> None:
    payload = _payload()
    expected = deepcopy(payload)
    del expected["snapshot"]["observed_at"]
    del expected["snapshot"]["revision"]
    encoded = json.dumps(expected, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    assert TickerResponse.from_payload(payload).payload_key == hashlib.sha256(encoded).hexdigest()
    for value in (float("nan"), float("inf"), float("-inf")):
        payload["health"]["invalid"] = value
        with pytest.raises(PayloadValidationError, match="canonical JSON"):
            TickerResponse.from_payload(payload)


def test_frozen_hashing_matches_wire_bytes_without_thawing_the_tree(monkeypatch) -> None:
    import ticker_core.protocol.model as model

    payload = _payload()
    payload["extra"] = {"unicode": "é雪", "escaped": "line\n\"", "values": [None, False, 0, -0.0, 1.25, {"z": []}]}
    expected = deepcopy(payload)
    expected["snapshot"].pop("revision")
    expected["snapshot"].pop("observed_at")
    digest = hashlib.sha256(json.dumps(expected, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()

    def forbidden(value):
        raise AssertionError("Fingerprinting rebuilt the complete payload")

    monkeypatch.setattr(model, "_thaw", forbidden)
    assert TickerResponse.from_payload(payload).payload_key == digest
    assert canonical_payload_hash(payload) == hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def test_payload_boundary_detaches_nested_values_inside_external_mapping_proxies() -> None:
    payload = _payload()
    values = ["nba:NY"]
    payload["settings"] = MappingProxyType({**payload["settings"], "my_teams": values})
    response = TickerResponse.from_payload(payload)
    values.append("nhl:NYR")
    assert response.settings.data["my_teams"] == ("nba:NY",)


def test_response_can_cross_the_poll_process_without_mapping_proxy_errors() -> None:
    response = TickerResponse.from_payload(_payload())
    restored = pickle.loads(pickle.dumps(response))

    assert restored.payload_key == response.payload_key
    assert restored.content[0].data == response.content[0].data


def test_display_delta_behavior() -> None:
    before_payload = _payload()
    before_payload["settings"]["my_teams"] = ["nba:NY"]
    before = TickerResponse.from_payload(before_payload)

    # Content change only
    after_content_payload = _payload()
    after_content_payload["settings"]["my_teams"] = ["nba:NY"]
    after_content_payload["content"]["sports"][0]["data"]["state"] = "post"
    after_content = TickerResponse.from_payload(after_content_payload)

    delta_content = display_delta(before, after_content)
    restored = apply_display_delta(before, delta_content)

    assert len(delta_content.changed) == 1
    assert not delta_content.settings_changed
    assert restored.content[0].data["state"] == "post"
    assert restored.payload_key == after_content.payload_key

    # Settings change
    after_settings_payload = _payload("clock")
    after_settings_payload["settings"]["my_teams"] = ["nba:NY"]
    delta_settings = display_delta(before, TickerResponse.from_payload(after_settings_payload))

    assert delta_settings.settings_changed
