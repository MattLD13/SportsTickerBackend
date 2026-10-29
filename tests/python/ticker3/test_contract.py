import pytest

from ticker3.contract import ContractError
from ticker3.contract.manifest import validate_manifest
from ticker3.contract.messages import device_message, worker_message
from ticker3.contract.records import references, validate_record
from ticker3.contract.settings import expand, normalize, normalize_config, subscription_key, validate_schema
from ticker3.contract.templates import bundle, fill, shown, validate_template
from ticker3.contract.wire import decode, encode

pytestmark = pytest.mark.critical

SPORTS = validate_schema({"fields": {
    "leagues": {"type": "list", "items": {"type": "enum", "values": ["nfl", "nba", "nhl"]}, "default": ["nfl"],
                "role": "fanout", "as": "league", "min_items": 1},
    "teams": {"type": "list", "items": {"type": "string", "lower": True, "pattern": "[a-z_]+:[a-z]+"}, "default": [], "role": "filter"},
    "dwell": {"type": "int", "min": 3, "max": 60, "default": 8, "role": "view"},
}})
WEATHER = validate_schema({"fields": {
    "latitude": {"type": "float", "min": -90, "max": 90, "required": True},
    "longitude": {"type": "float", "min": -180, "max": 180, "required": True},
    "units": {"type": "enum", "values": ["f", "c"], "default": "f"},
}})
CARD = {"id": "sports.card", "version": 1, "panels": {"w64h32": {"box": [64, 32], "flow": "page", "parts": [
    {"part": "text", "at": [32, 1], "font": "tiny", "align": "center", "value": "{status}"},
    {"part": "text", "at": [32, 12], "font": "big", "align": "center", "value": "{away.score}-{home.score}"},
    {"part": "bases", "at": [26, 22], "value": "{bases}", "show_when": "sport == baseball"},
]}}}


def test_fanout_gives_one_shared_subscription_for_each_league():
    first = expand(SPORTS, normalize(SPORTS, {"leagues": ["nfl", "nba", "nfl"], "teams": ["NFL:nyg"]}))
    second = expand(SPORTS, normalize(SPORTS, {"leagues": ["nba"]}))

    assert first.configs == ({"league": "nfl"}, {"league": "nba"})
    assert first.filters == {"teams": ("nfl:nyg",)}
    assert first.view == {"dwell": 8}
    assert subscription_key(first.configs[1]) == subscription_key(second.configs[0])
    assert second.filters == {}


def test_settings_reject_unknown_invalid_and_missing_values():
    with pytest.raises(ContractError, match="unknown settings"):
        normalize(SPORTS, {"colour": "red"})
    with pytest.raises(ContractError, match="at least 1"):
        normalize(SPORTS, {"leagues": []})
    with pytest.raises(ContractError, match="one of"):
        normalize(SPORTS, {"leagues": ["cricket"]})
    with pytest.raises(ContractError, match="required"):
        normalize(WEATHER, {"latitude": 40.7})
    with pytest.raises(ContractError, match="at most 90"):
        normalize(WEATHER, {"latitude": 91, "longitude": 0})


def test_reference_configs_normalize_to_the_same_key_as_an_app():
    app = expand(WEATHER, normalize(WEATHER, {"latitude": 19, "longitude": -99.0})).configs[0]
    reference = normalize_config(WEATHER, {"latitude": 19.0, "longitude": -99})

    assert subscription_key(app) == subscription_key(reference)
    assert normalize_config(SPORTS, {"league": "nhl"}) == {"league": "nhl"}
    with pytest.raises(ContractError, match="required"):
        normalize_config(SPORTS, {})


def test_records_validate_values_and_find_references():
    record = validate_record({"id": "f1-19", "template": "racing.session", "values": {
        "name": "Mexico City", "lap": 3, "weather": {"$ref": {"feature": "weather", "config": {"latitude": 19.4}, "record": "now"}}}})

    assert record["tags"] == [] and record["order"] == 0
    [(key, target)] = references(record)
    assert key == "weather" and target.feature == "weather" and target.record == "now"
    for bad in ({"id": "x y", "template": "a.b"}, {"id": "x", "template": "nodot"},
                {"id": "x", "template": "a.b", "values": {"k": [1]}},
                {"id": "x", "template": "a.b", "values": {"k": float("nan")}},
                {"id": "x", "template": "a.b", "values": {"k": {"$ref": {"feature": "w"}}}},
                {"id": "x", "template": "a.b", "extra": 1}):
        with pytest.raises(ContractError):
            validate_record(bad)


def test_templates_validate_parts_and_evaluate_rules():
    validate_template(CARD)
    values = {"status": "Q3 08:12", "away.score": "17", "home.score": "14", "sport": "football"}

    assert fill("{away.score}-{home.score}", values) == "17-14"
    assert fill("{down}", values) is None
    assert shown("sport == baseball", values) is False
    assert shown("sport != baseball", values) is True
    assert shown("!down", values) is True
    assert shown("status", values) is True
    digest, blocks = bundle({"sports.card": CARD}, "w64h32")
    assert len(digest) == 16 and blocks["sports.card"]["version"] == 1
    assert bundle({"sports.card": CARD}, "w384h32")[1] == {}
    for broken in ({**CARD, "panels": {"w64h32": {"box": [65, 32], "flow": "page", "parts": CARD["panels"]["w64h32"]["parts"]}}},
                   {**CARD, "panels": {"w64h32": {"box": [64, 32], "flow": "page", "parts": [{"part": "laser", "at": [0, 0]}]}}},
                   {**CARD, "panels": {"w64h32": {"box": [64, 32], "flow": "page", "parts": [{"part": "text", "at": [70, 0], "font": "tiny", "value": "x"}]}}},
                   {**CARD, "panels": {"w64h32": {"box": [64, 32], "flow": "page", "parts": [{"part": "text", "at": [0, 0], "font": "tiny", "value": "x", "show_when": "a ==="}]}}}):
        with pytest.raises(ContractError):
            validate_template(broken)


def test_manifest_templates_must_belong_to_the_feature():
    manifest = {"feature": "sports", "title": "Sports", "version": "1", "settings": SPORTS, "templates": [CARD]}
    assert set(validate_manifest(manifest)["templates"]) == {"sports.card"}
    with pytest.raises(ContractError, match="must start with weather."):
        validate_manifest({**manifest, "feature": "weather"})


def test_messages_and_wire_round_trip():
    manifest = {"feature": "sports", "title": "Sports", "version": "1", "settings": SPORTS, "templates": [CARD]}
    hello = worker_message(decode(encode({"t": "hello", "protocol": 1, "feature": "sports", "release": "abc123",
                                          "pid": 42, "manifest": manifest})))
    assert hello["manifest"]["templates"]["sports.card"] == CARD
    delta = worker_message({"t": "delta", "sub": "0123456789abcdef", "upsert": [{"id": "a", "template": "sports.card"}], "remove": ["b"]})
    assert delta["upsert"][0]["values"] == {}
    with pytest.raises(ContractError, match="twice"):
        worker_message({"t": "sync", "sub": "0123456789abcdef", "records": [{"id": "a", "template": "a.b"}] * 2})
    with pytest.raises(ContractError):
        decode(b'{"t": "sync", "x": NaN}\n')
    assert device_message({"t": "hello", "protocol": 1, "token": "t" * 32, "panel": "w64h32"})["panel"] == "w64h32"
    with pytest.raises(ContractError):
        device_message({"t": "hello", "protocol": 1, "token": "t" * 32, "panel": "big"})
