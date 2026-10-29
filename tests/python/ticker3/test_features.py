import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ticker3.contract.manifest import validate_manifest
from ticker3.contract.records import references, validate_record
from ticker3.contract.settings import normalize_config, subscription_key
from ticker3.features import racing, sports, weather

pytestmark = pytest.mark.critical

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ticker3"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_each_feature_manifest_is_valid_and_imports_no_core_module():
    for module in (weather, sports, racing):
        validate_manifest(module.MANIFEST)
    root = Path(weather.__file__).resolve().parents[1]
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not [name for name in names if name.startswith(("ticker3.core", "sports_ticker", "backend_ops"))], path


def test_weather_record_from_a_real_open_meteo_payload():
    [record] = weather.records(fixture("openmeteo_nyc_2026-10-29.json"), {"units": "f"})
    validate_record(record)
    values = record["values"]
    assert (values["temp"], values["icon"], values["condition"], values["hi"], values["lo"], values["wind"]) == (
        "61°", "sun", "Clear", "67°", "47°", "6 mph")
    assert [values[f"day{index}.name"] for index in (1, 2, 3)] == ["FRI", "SAT", "SUN"]
    night = fixture("openmeteo_nyc_2026-10-29.json")
    night["current"]["is_day"] = 0
    assert weather.records(night, {"units": "f"})[0]["values"]["icon"] == "moon"


def test_sports_cards_from_real_scoreboards():
    nfl = sports.records(fixture("espn_nfl_2026-10-29.json"), "nfl")
    nba = sports.records(fixture("espn_nba_2026-10-29.json"), "nba")
    for record in nfl + nba:
        validate_record(record)
    first = nfl[0]
    assert first["id"] == "nfl-401873023" and first["tags"] == ["nfl:car", "nfl:gb"]
    assert first["values"]["state"] == "pre" and first["values"]["starts"] == 1793319300
    assert "status" not in first["values"] and first["values"]["away.score"] == ""
    final = nba[0]["values"]
    assert (final["away.abbr"], final["away.score"], final["home.abbr"], final["home.score"], final["status"], final["winner"]) == (
        "MIA", "129", "ATL", "117", "FINAL", "away")


@pytest.mark.parametrize("league,status,state,text", [
    ("nfl", {"period": 3, "displayClock": "8:12", "type": {"shortDetail": "8:12 - 3rd"}}, "in", "Q3 8:12"),
    ("nfl", {"period": 2, "displayClock": "0:00", "type": {"name": "STATUS_HALFTIME", "shortDetail": "Halftime"}}, "in", "HALF"),
    ("nba", {"period": 1, "displayClock": "0.0", "type": {"shortDetail": "End of 1st"}}, "in", "END Q1"),
    ("nba", {"period": 5, "displayClock": "2:01", "type": {"shortDetail": "2:01 - OT"}}, "in", "OT 2:01"),
    ("nba", {"period": 6, "type": {"shortDetail": "Final/2OT"}}, "post", "FINAL OT2"),
    ("ncaab", {"period": 2, "displayClock": "11:40", "type": {"shortDetail": "11:40 - 2nd Half"}}, "in", "H2 11:40"),
    ("nhl", {"period": 2, "displayClock": "0:00", "type": {"shortDetail": "End of 2nd"}}, "in", "END P2"),
    ("nhl", {"period": 5, "type": {"shortDetail": "Final/SO"}}, "post", "FINAL S/O"),
    ("nhl", {"period": 4, "type": {"shortDetail": "Final/OT"}}, "post", "FINAL OT"),
    ("mlb", {"period": 7, "type": {"shortDetail": "Bot 7th"}}, "in", "BOT 7"),
    ("mlb", {"period": 10, "type": {"shortDetail": "Final/10"}}, "post", "FINAL"),
    ("nfl", {"period": 0, "type": {"shortDetail": "Postponed, weather"}}, "in", "POSTPONED"),
])
def test_status_text_follows_the_ticker_rules(league, status, state, text):
    assert sports.status_text(sports.LEAGUES[league], status, state) == text


def test_live_situation_values_for_football_and_baseball():
    payload = fixture("espn_mlb_2026-10-29.json")
    event = payload["events"][0]
    event["status"] = {"period": 5, "type": {"state": "in", "shortDetail": "Top 5th"}}
    competition = event["competitions"][0]
    competition["situation"] = {"onFirst": True, "onSecond": False, "onThird": True, "outs": 2}
    [record] = sports.records(payload, "mlb")
    assert (record["values"]["status"], record["values"]["bases"], record["values"]["outs"]) == ("TOP 5", "101", 2)
    football = fixture("espn_nfl_2026-10-29.json")
    event = football["events"][0]
    event["status"] = {"period": 1, "displayClock": "9:00", "type": {"state": "in"}}
    home = next(team for team in event["competitions"][0]["competitors"] if team["homeAway"] == "home")
    event["competitions"][0]["situation"] = {"possession": home["id"], "shortDownDistanceText": "3rd & 4", "isRedZone": True}
    values = sports.records(football, "nfl")[0]["values"]
    assert (values["possession"], values["down"], values["redzone"], values["status"]) == ("home", "3RD & 4", True, "Q1 9:00")


def test_racing_session_refers_to_track_weather():
    season = fixture("jolpica_f1_2026.json")
    [record] = racing.records(season, datetime(2026, 10, 29, 15, tzinfo=timezone.utc))
    validate_record(record)
    assert (record["values"]["event"], record["values"]["session"], record["values"]["state"]) == ("MEXICO CITY GP", "PRACTICE 1", "pre")
    [(key, target)] = references(record)
    config = normalize_config(weather.MANIFEST["settings"], target.config)
    assert key == "weather" and config == {"latitude": 19.4042, "longitude": -99.0907, "units": "f"}
    assert len(subscription_key(config)) == 16
    assert racing.records(season, datetime(2026, 10, 30, 19, tzinfo=timezone.utc))[0]["values"]["state"] == "in"
    assert racing.records(season, datetime(2026, 12, 31, tzinfo=timezone.utc)) == []
