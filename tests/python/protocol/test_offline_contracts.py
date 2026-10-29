"""Validate saved V2 contracts without network calls or new dependencies."""

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from sports_ticker.application.schedule import block_to_mapping, condition_to_mapping
from sports_ticker.domain import ScheduleBlock, ScheduleCondition
from sports_ticker.firmware import FirmwareManifest
from sports_ticker.fleet.profiles import TickerProfile
from ticker3.offline import create_offline_application

pytestmark = pytest.mark.critical


def device_token(ticker_id: str) -> str:
    """Return the device token of one test device. The token alone names the ticker."""
    return hashlib.sha256(ticker_id.encode()).hexdigest()
CONTRACTS = Path(__file__).resolve().parents[3] / "docs" / "contracts"
FIXTURES = CONTRACTS / "fixtures"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value, schema):
    """Evaluate the schema keywords used by this offline contract collection."""
    supported = {
        "$schema", "$id", "$ref", "title", "description", "default", "type",
        "properties", "required", "additionalProperties", "items", "minItems",
        "maxItems", "uniqueItems", "enum", "const", "pattern", "minLength",
        "minimum", "maximum", "anyOf",
    }
    assert not set(schema).difference(supported), "unsupported schema keyword"
    if "$ref" in schema:
        reference = schema["$ref"]
        assert "/" not in reference and reference.endswith(".json")
        _validate(value, _read(CONTRACTS / reference))
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                _validate(value, branch)
                break
            except AssertionError:
                pass
        else:
            raise AssertionError("no anyOf branch matches")
    kinds = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if "type" in schema:
        accepted = schema["type"]
        assert any(kinds[kind] for kind in ([accepted] if isinstance(accepted, str) else accepted))
    if "enum" in schema:
        assert any(type(value) is type(item) and value == item for item in schema["enum"])
    if "const" in schema:
        assert type(value) is type(schema["const"]) and value == schema["const"]
    if isinstance(value, dict):
        assert set(schema.get("required", ())).issubset(value)
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, child in value.items():
            if key in properties:
                _validate(child, properties[key])
            elif isinstance(extra, dict):
                _validate(child, extra)
            else:
                assert extra is not False, f"unknown field: {key}"
    if isinstance(value, list):
        assert len(value) >= schema.get("minItems", 0)
        assert len(value) <= schema.get("maxItems", len(value))
        if schema.get("uniqueItems"):
            assert len({json.dumps(item, sort_keys=True) for item in value}) == len(value)
        for child in value:
            _validate(child, schema.get("items", {}))
    if isinstance(value, str):
        assert len(value) >= schema.get("minLength", 0)
        if "pattern" in schema:
            assert re.search(schema["pattern"], value)
    if kinds["number"]:
        assert value >= schema.get("minimum", value)
        assert value <= schema.get("maximum", value)


def validate(name, value):
    _validate(value, _read(CONTRACTS / f"{name}.json"))


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda path: path.stem)
def test_saved_positive_contract(path):
    validate(path.stem, _read(path))


def test_sports_projection_fixture_contains_content_and_overlays():
    document = _read(FIXTURES / "display" / "sports.json")
    validate("display-response", document)
    assert document["content"]["sports"][0]["data"]["state"] == "in"
    assert document["events"]["alerts"][0]["kind"] == "score_alert"
    assert document["events"]["news"][0]["kind"] == "news"
    invalid = deepcopy(document)
    invalid["content"]["sports"][0]["data"] = []
    with pytest.raises(AssertionError):
        validate("display-response", invalid)


@pytest.mark.parametrize("name,path,value", [
    ("device-registration-request", "device_id", "   "),
    ("device-registration-request", "name", None),
    ("device-registration-request", "metadata", []),
    ("device-registration-request", "pairing_code", 123456),
    ("hardware-profile-response", "product_family", "normal"),
    ("hardware-profile-response", "display.width", 0),
    ("hardware-profile-response", "capabilities.modes", []),
    ("schedule-block-request", "days_of_week", [True]),
    ("schedule-block-request", "mode", "pairing"),
    ("schedule-block-response", "days_of_week", [0, 0]),
    ("schedule-condition-request", "threshold", 0),
    ("schedule-condition-response", "ignore_pinned", False),
    ("schedule-response", "days", []),
    ("firmware-manifest-response", "size", 65535),
    ("firmware-manifest-response", "size", 2093057),
    ("firmware-manifest-response", "binary_url", "http://example.com/image.bin"),
    ("firmware-manifest-response", "sha256", "g" * 64),
    ("display-response", "settings.mode", "pinned"),
    ("display-response", "events.news", [{}]),
])
def test_saved_negative_contract(name, path, value):
    document = deepcopy(_read(FIXTURES / f"{name}.json"))
    target = document
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    with pytest.raises(AssertionError):
        validate(name, document)


def test_registration_contract_matches_route_defaults_and_normalization():
    app = create_offline_application(":memory:", [], clock=lambda: 1786752000.0)
    backend = app.extensions["ticker.application"]
    try:
        client = app.test_client()
        requests = [
            {"device_id": " default-contract "},
            {"device_id": "null-contract", "name": "", "profile": None, "pairing_code": None},
            {"device_id": "alias-contract", "profile": {"product_family": " NORMAL "}},
            {"device_id": "mini-contract", "metadata": {"build": "esp32-dev"}},
        ]
        for request in requests:
            validate("device-registration-request", request)
            headers = {"X-Device-Token": device_token(request["device_id"])}
            response = client.post("/register", json=request, headers=headers)
            assert response.status_code == 201
            document = response.get_json()
            validate("device-registration-response", document)
            assert document["ticker_id"] == request["device_id"].strip()
            assert document["ticker"]["name"] == "Ticker"
            assert document["ticker"]["profile"]["product_family"] == (
                "mini" if request["device_id"] == "mini-contract" else "full"
            )
            validate("display-response", client.get("/data", headers=headers).get_json())
        repeat = client.post("/register", json=requests[0], headers={"X-Device-Token": device_token(requests[0]["device_id"])})
        assert repeat.status_code == 200
        validate("device-registration-response", repeat.get_json())
        for invalid in ({"device_id": " "}, {"device_id": "x", "unknown": True}, {"device_id": "x", "metadata": []}):
            assert client.post("/register", json=invalid, headers={"X-Device-Token": device_token(" default-contract ")}).status_code == 400
            with pytest.raises(AssertionError):
                validate("device-registration-request", invalid)
    finally:
        backend.close()


def test_profile_fixture_preserves_input_coercion():
    source = _read(FIXTURES / "hardware-profile-request.json")
    validate("hardware-profile-request", source)
    profile = TickerProfile.from_mapping(source).to_mapping()
    validate("hardware-profile-response", profile)
    assert profile["product_family"] == "full"
    assert profile["display"]["width"] == 384
    assert profile["display"]["orientation"] == "landscape"


def test_manifest_fixture_preserves_input_normalization():
    source = _read(FIXTURES / "firmware-manifest-input.json")
    validate("firmware-manifest-input", source)
    manifest = FirmwareManifest.from_mapping(source).to_mapping()
    validate("firmware-manifest-response", manifest)
    assert manifest == _read(FIXTURES / "firmware-manifest-response.json")


def test_schedule_fixtures_match_domain_normalization():
    source = _read(FIXTURES / "schedule-block-request.json")
    block = ScheduleBlock(id="block-contract", ticker_id="mini-contract", **source)
    projected = block_to_mapping(block)
    validate("schedule-block-response", projected)
    assert projected["mode"] == "sports"
    assert projected["days_of_week"] == [0, 2]
    assert projected["sports_filter"] is None
    condition = ScheduleCondition(
        id="condition-contract", ticker_id="mini-contract",
        **_read(FIXTURES / "schedule-condition-request.json"),
    )
    validate("schedule-condition-response", condition_to_mapping(condition))
    assert condition.operator == "gt"
    assert condition.action_sports_filter == "live"
    with pytest.raises(ValueError, match="after start_minute"):
        ScheduleBlock(id="invalid", ticker_id="mini-contract", **{**source, "end_minute": 30})


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda path: path.stem)
def test_contract_required_fields_reject_missing_values(path):
    schema = _read(CONTRACTS / path.name)
    document = _read(path)
    for field in schema.get("required", ()):
        invalid = {key: value for key, value in document.items() if key != field}
        with pytest.raises(AssertionError):
            validate(path.stem, invalid)
