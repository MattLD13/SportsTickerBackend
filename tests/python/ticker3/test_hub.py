import pytest

from ticker3.contract import ContractError
from ticker3.contract.records import validate_record
from ticker3.contract.settings import subscription_key
from ticker3.core.builtin import BUILTINS
from ticker3.core.hub import App, Hub

pytestmark = pytest.mark.critical


def template(identifier):
    return {"id": identifier, "version": 1, "panels": {"w64h32": {"box": [64, 32], "flow": "page", "parts": [
        {"part": "text", "at": [0, 0], "font": "tiny", "value": "{name}"}]}}}


SPORTS = {"feature": "sports", "title": "Sports", "version": "1", "templates": [template("sports.card")], "settings": {"fields": {
    "leagues": {"type": "list", "items": {"type": "enum", "values": ["nfl", "nba"]}, "default": ["nfl"], "role": "fanout", "as": "league"},
    "teams": {"type": "list", "items": {"type": "string"}, "default": [], "role": "filter"},
    "dwell": {"type": "int", "default": 8, "role": "view"}}}}
WEATHER = {"feature": "weather", "title": "Weather", "version": "1", "templates": [template("weather.now")], "settings": {"fields": {
    "latitude": {"type": "float", "required": True}, "longitude": {"type": "float", "required": True},
    "units": {"type": "enum", "values": ["f", "c"], "default": "f"}}}}
RACING = {"feature": "racing", "title": "Racing", "version": "1", "templates": [template("racing.session")],
          "settings": {"fields": {"series": {"type": "enum", "values": ["f1"], "default": "f1"}}}}


class Recorder:
    def __init__(self):
        self.wanted, self.screens, self.now = {}, [], 1000.0

    def hub(self):
        hub = Hub(clock=lambda: self.now, on_wanted=lambda feature, subs: self.wanted.__setitem__(feature, subs),
                  on_screens=lambda ticker, composition: self.screens.append((ticker, composition)))
        for manifest in (SPORTS, WEATHER, RACING):
            hub.register(manifest)
        hub.register(BUILTINS["clock"].manifest, builtin=BUILTINS["clock"])
        return hub


def game(identifier, name, tags=(), **extra):
    return {"id": identifier, "template": "sports.card", "values": {"name": name}, "tags": list(tags), "order": 0,
            "expires_at": None, "overlay": None, **extra}


def key(config):
    return subscription_key(config)


def test_tickers_with_one_league_share_one_subscription_and_get_only_their_changes():
    recorder = Recorder()
    hub = recorder.hub()
    hub.set_playlist("a", [App("s", "sports", {"leagues": ["nfl", "nba"]})])
    hub.set_playlist("b", [App("s", "sports", {"leagues": ["nba"]})])
    nfl, nba = key({"league": "nfl"}), key({"league": "nba"})

    assert recorder.wanted["sports"] == {nfl: {"league": "nfl"}, nba: {"league": "nba"}}
    recorder.screens.clear()
    assert hub.apply("sports", {"t": "sync", "sub": nfl, "records": [game("g1", "GB-CAR")]})
    assert [ticker for ticker, _ in recorder.screens] == ["a"]
    hub.apply("sports", {"t": "sync", "sub": nba, "records": [game("g2", "ATL-MIA")]})
    assert [screen["id"] for screen in hub.composition("a").screens] == ["s/g1", "s/g2"]
    assert [screen["values"] for screen in hub.composition("b").screens] == [{"name": "ATL-MIA", "app.dwell": 8}]
    assert not hub.apply("sports", {"t": "sync", "sub": key({"league": "nhl"}), "records": []})


def test_filters_keep_tagged_records_and_deltas_replace_records():
    recorder = Recorder()
    hub = recorder.hub()
    hub.set_playlist("a", [App("s", "sports", {"leagues": ["nfl"], "teams": ["nfl:gb"]})])
    nfl = key({"league": "nfl"})
    hub.apply("sports", {"t": "sync", "sub": nfl, "records": [game("g1", "GB-CAR", ["nfl:gb"]), game("g2", "BUF-BAL", ["nfl:buf"])]})
    assert [screen["id"] for screen in hub.composition("a").screens] == ["s/g1"]
    hub.apply("sports", {"t": "delta", "sub": nfl, "upsert": [game("g1", "GB 7-0 CAR", ["nfl:gb"])], "remove": ["g2"]})
    assert hub.composition("a").screens[0]["values"]["name"] == "GB 7-0 CAR"


def test_reference_subscribes_the_target_feature_and_joins_its_values():
    recorder = Recorder()
    hub = recorder.hub()
    hub.set_playlist("a", [App("r", "racing", {})])
    hub.set_playlist("b", [App("w", "weather", {"latitude": 19.4, "longitude": -99.09})])
    racing, place = key({"series": "f1"}), key({"latitude": 19.4, "longitude": -99.09, "units": "f"})
    session = {"id": "mex", "template": "racing.session", "values": {
        "name": "Mexico City", "weather": {"$ref": {"feature": "weather", "config": {"latitude": 19.4, "longitude": -99.09}, "record": "now"}}}}

    hub.apply("racing", {"t": "sync", "sub": racing, "records": [validate_record(session)]})
    assert recorder.wanted["weather"] == {place: {"latitude": 19.4, "longitude": -99.09, "units": "f"}}
    assert hub.composition("a").screens[0]["values"] == {"name": "Mexico City"}
    recorder.screens.clear()
    hub.apply("weather", {"t": "sync", "sub": place, "records": [
        validate_record({"id": "now", "template": "weather.now", "values": {"name": "Mexico City", "temp": "68"}})]})
    assert sorted(ticker for ticker, _ in recorder.screens) == ["a", "b"]
    assert hub.composition("a").screens[0]["values"] == {"name": "Mexico City", "weather.name": "Mexico City", "weather.temp": "68"}
    hub.apply("racing", {"t": "sync", "sub": racing, "records": []})
    assert recorder.wanted["weather"] == {place: {"latitude": 19.4, "longitude": -99.09, "units": "f"}}
    hub.remove_ticker("b")
    assert recorder.wanted["weather"] == {}


def test_clock_runs_in_the_core_without_a_worker():
    recorder = Recorder()
    hub = recorder.hub()
    hub.set_playlist("a", [App("c", "clock", {"timezone": "Europe/London", "format": "24h"})])

    assert "clock" not in recorder.wanted
    [screen] = hub.composition("a").screens
    assert screen == {"id": "c/clock", "template": "clock.face",
                      "values": {"tz": "Europe/London", "format": "24h", "app.color": "#ffffff"}}


def test_expired_records_and_overlays_leave_on_tick():
    recorder = Recorder()
    hub = recorder.hub()
    hub.set_playlist("a", [App("s", "sports", {})])
    nfl = key({"league": "nfl"})
    hub.apply("sports", {"t": "sync", "sub": nfl, "records": [
        game("g1", "old", expires_at=1010.0), game("alert", "TOUCHDOWN", overlay={"ttl": 5})]})
    composition = hub.composition("a")
    assert [screen["id"] for screen in composition.screens] == ["s/g1"]
    assert [screen["id"] for screen in composition.overlays] == ["s/alert"]
    assert composition.next_change == 1005.0
    recorder.now = 1006
    hub.tick()
    assert hub.composition("a").overlays == () and len(hub.composition("a").screens) == 1
    recorder.now = 1011
    hub.tick()
    assert hub.composition("a").screens == ()


def test_invalid_playlists_fail_and_a_new_schema_reports_app_errors():
    recorder = Recorder()
    hub = recorder.hub()
    with pytest.raises(ContractError, match="unknown feature"):
        hub.set_playlist("a", [App("x", "cricket", {})])
    with pytest.raises(ContractError):
        hub.set_playlist("a", [App("s", "sports", {"leagues": ["mls"]})])
    hub.set_playlist("a", [App("s", "sports", {"leagues": ["nba"]})])
    stricter = {**SPORTS, "version": "2", "settings": {"fields": {**SPORTS["settings"]["fields"],
        "leagues": {**SPORTS["settings"]["fields"]["leagues"], "items": {"type": "enum", "values": ["nfl"]}}}}}
    hub.register(stricter)
    assert hub.composition("a").errors == ("s: setting leagues must be one of nfl",)
    assert recorder.wanted["sports"] == {}
