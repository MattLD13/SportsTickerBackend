from datetime import datetime, timezone

from ticker.shared.domain import DisplaySettings
from ticker.server.providers.racing import RacingProvider
from ticker.server.providers.racing_live import LiveRacingSource, _indycar_driver, _indycar_short_event



class JsonFixture:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values
        self.urls: list[str] = []

    def get_json(self, url: str, *, timeout: float) -> object:
        del timeout
        self.urls.append(url)
        for prefix, value in self.values.items():
            if url.startswith(prefix):
                return value
        raise AssertionError(f"unexpected URL: {url}")


class TextFixture:
    def __init__(self, value: str) -> None:
        self.value = value
        self.urls: list[str] = []

    def get_text(self, url: str, *, timeout: float) -> str:
        del timeout
        self.urls.append(url)
        return self.value


def _settings(**active_sports: bool) -> DisplaySettings:
    return DisplaySettings(active_sports={**dict.fromkeys(("f1", "indycar", "nascar", "wec", "imsa"), False), **active_sports}, timezone="America/New_York")


class NoCircuitWeather:
    def fetch(self, track, country=""):
        return {"available": False}


def _source(client, *args, **kwargs):
    return LiveRacingSource(client, *args, weather_source=NoCircuitWeather(), **kwargs)


def test_indycar_polls_the_official_timing_blob_and_driver_feed() -> None:
    now = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    client = JsonFixture(
        {
            "https://indycar.blob.core.windows.net/racecontrol/timingscoring-ris.json": {
                "timing_results": {
                    "heartbeat": {
                        "Series": "I",
                        "EventID": "indy-event",
                        "eventName": "Test Grand Prix at Road America",
                        "trackName": "Road America",
                        "SessionType": "R",
                        "SessionName": "Race",
                        "SessionStatus": "LIVE",
                        "currentFlag": "GREEN",
                        "startTimeUTC": "2026-08-15T14:00:00Z",
                        "totalLaps": 55,
                    },
                    "Item": [
                        {"no": "1", "firstName": "One", "lastName": "Driver", "team": "Penske", "rank": 1, "laps": 12, "diff": "0.000.00"},
                        {"no": "2", "firstName": "Two", "lastName": "Driver", "team": "Ganassi", "rank": 2, "laps": 12, "diff": "+1.2"},
                    ],
                }
            },
            "https://indycar.blob.core.windows.net/racecontrol/driversfeed.json": {
                "drivers": {"driver": [{"number": "1", "carillustration": "car-1", "endplatesmall": "plate-1"}]}
            },
            "https://api.open-meteo.com/v1/forecast": {"current": {"temperature_2m": 72, "wind_speed_10m": 4, "wind_direction_10m": 180}},
        }
    )
    source = _source(client, now=lambda: now, clock=lambda: now.timestamp())

    result = source.fetch(_settings(f1=False, indycar=True))

    game = result["content"][0]
    assert game["sport"] == "indycar"
    assert game["state"] == "in"
    assert game["indycar"]["event_name"] == "Road America GP"
    assert game["indycar"]["drivers"][0]["team_logo"] == "plate-1"
    assert game["indycar"]["drivers"][0]["gap"] == "Leader"
    assert game["indycar"]["drivers"][1]["gap"] == "+1.2"

    normalized = RacingProvider(source).fetch(_settings(f1=False, indycar=True))
    assert normalized.content[0].family == "racing"
    assert normalized.content[0].kind == "indycar"
    assert normalized.content[0].data["sport"] == "indycar"


def test_indycar_race_leader_sets_leader_gap_when_diff_is_present() -> None:
    item = {
        "rank": 1,
        "no": "1",
        "firstName": "Alex",
        "lastName": "Palou",
        "diff": "0.000.00",
    }
    driver = _indycar_driver(item, {}, "R", "RC")
    assert driver is not None
    assert driver["gap"] == "Leader"


def test_indycar_qualifying_uses_speed_on_ovals_and_time_on_street_courses() -> None:
    item = {
        "rank": 1,
        "no": "1",
        "firstName": "One",
        "lastName": "Driver",
        "qualSpeed": "220.123",
        "qualTime": "1:14.2024",
    }

    oval = _indycar_driver(item, {}, "Q", "O")
    street = _indycar_driver(item, {}, "Q", "SC")

    assert oval is not None and oval["qualifying_value"] == "220.123"
    assert street is not None and street["qualifying_value"] == "1:14.2024"


def test_indycar_short_event_names_keep_city_or_race_distance() -> None:
    examples = {
        "Indianapolis 500": "Indy 500",
        "Bitnile.com Grand Prix of Portland": "Portland GP",
        "Portland GP": "Portland GP",
        "Freedom 250 presented by Sponsor": "Freedom 250",
        "Ontario Honda Dealers Indy at Markham": "Markham GP",
        "Big Machine Music City Grand Prix": "Music City GP",
        "Snap-on 250": "Snap On 250",
    }

    for event_name, expected in examples.items():
        assert _indycar_short_event(event_name, "") == expected


def test_indycar_expired_post_session_clears_after_3am() -> None:
    # Race was Sunday Aug 16 at 12:00 PM EDT (16:00 UTC)
    # Now is Tuesday Aug 18 at 13:00 EDT (past 3 AM Monday reset)
    now = datetime(2026, 8, 18, 17, 0, tzinfo=timezone.utc)
    client = JsonFixture(
        {
            "https://indycar.blob.core.windows.net/racecontrol/timingscoring-ris.json": {
                "timing_results": {
                    "heartbeat": {
                        "Series": "I",
                        "EventID": "5520",
                        "eventName": "Ontario Honda Dealers Indy at Markham",
                        "trackName": "Streets of Markham",
                        "SessionType": "R",
                        "SessionName": "Race",
                        "SessionStatus": "COLD",
                        "currentFlag": "COLD",
                        "flagCounts": {
                            "green": ["2026-08-16T12:22:47.8738-04:00"],
                        },
                        "totalLaps": "90",
                    },
                    "Item": [
                        {"no": "1", "firstName": "Marcus", "lastName": "Ericsson", "team": "Andretti", "rank": 1, "laps": 90, "diff": "0.000.00"},
                    ],
                }
            },
            "https://indycar.blob.core.windows.net/racecontrol/driversfeed.json": {
                "drivers": {"driver": [{"number": "1", "carillustration": "car-1", "endplatesmall": "plate-1"}]}
            },
            "https://site.web.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard": {
                "events": [
                    {"name": "Grand Prix of Ontario", "date": "2026-08-16T16:00Z"},
                    {"name": "Grand Prix of Washington, D.C.", "date": "2026-08-23T17:00Z"},
                ]
            },
            "https://api.open-meteo.com/v1/forecast": {"current": {"temperature_2m": 72, "wind_speed_10m": 4, "wind_direction_10m": 180}},
        }
    )
    source = _source(client, now=lambda: now, clock=lambda: now.timestamp())

    result = source.fetch(_settings(f1=False, indycar=True))

    assert len(result["content"]) == 0


def test_indycar_session_lifecycle_and_3am_rollover() -> None:
    # Race was Sunday Aug 16 at 12:00 PM EDT (16:00 UTC)
    # 1. Sunday Aug 16 at 18:00 EDT (same evening, before 3 AM Monday reset) -> visible as post
    now_same_day = datetime(2026, 8, 16, 22, 0, tzinfo=timezone.utc)
    client_post = JsonFixture(
        {
            "https://indycar.blob.core.windows.net/racecontrol/timingscoring-ris.json": {
                "timing_results": {
                    "heartbeat": {
                        "Series": "I",
                        "EventID": "5520",
                        "eventName": "Ontario Honda Dealers Indy at Markham",
                        "trackName": "Streets of Markham",
                        "SessionType": "R",
                        "SessionName": "Race",
                        "SessionStatus": "COLD",
                        "currentFlag": "COLD",
                        "flagCounts": {
                            "green": ["2026-08-16T12:22:47.8738-04:00"],
                        },
                        "totalLaps": "90",
                    },
                    "Item": [
                        {"no": "1", "firstName": "Marcus", "lastName": "Ericsson", "team": "Andretti", "rank": 1, "laps": 90, "diff": "0.000.00"},
                    ],
                }
            },
            "https://indycar.blob.core.windows.net/racecontrol/driversfeed.json": {
                "drivers": {"driver": [{"number": "1", "carillustration": "car-1", "endplatesmall": "plate-1"}]}
            },
            "https://site.web.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard": {
                "events": [
                    {"name": "Grand Prix of Ontario", "date": "2026-08-16T16:00Z"},
                ]
            },
            "https://api.open-meteo.com/v1/forecast": {"current": {"temperature_2m": 72, "wind_speed_10m": 4, "wind_direction_10m": 180}},
        }
    )
    source_post = _source(client_post, now=lambda: now_same_day, clock=lambda: now_same_day.timestamp())
    result_post = source_post.fetch(_settings(f1=False, indycar=True))
    assert len(result_post["content"]) >= 1
    race_game = next(g for g in result_post["content"] if g["home_abbr"] == "Race")
    assert race_game["sport"] == "indycar"
    assert race_game["state"] == "post"
    assert race_game["status"] == "FINAL"
    assert race_game["indycar"]["drivers"][0]["name"] == "Marcus Ericsson"

    # 2. Upcoming weekend: Hidden on Wednesday Aug 19, shown on Saturday Aug 22
    now_early = datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc)
    now_sat = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    data_upcoming = {
        "https://indycar.blob.core.windows.net/racecontrol/timingscoring-ris.json": {
            "timing_results": {}
        },
        "https://site.web.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard": {
            "events": [
                {"name": "Grand Prix of Washington, D.C.", "date": "2026-08-23T17:00Z"},
            ]
        },
        "https://indycar.blob.core.windows.net/racecontrol/driversfeed.json": {"drivers": {"driver": []}},
        "https://api.open-meteo.com/v1/forecast": {"current": {}},
    }
    source_early = _source(JsonFixture(data_upcoming), now=lambda: now_early, clock=lambda: now_early.timestamp())
    assert len(source_early.fetch(_settings(f1=False, indycar=True))["content"]) == 0

    weekend_page = """
    <h3>Saturday, Aug 22</h3>
    <div class="schedule-entry">
        <div class="schedule-time">9:00AM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Practice 1</div>
    </div>
    <div class="schedule-entry">
        <div class="schedule-time">5:00PM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Qualifying</div>
    </div>
    """
    source_sat = _source(
        JsonFixture(data_upcoming),
        text_client=TextFixture(weekend_page),
        now=lambda: now_sat,
        clock=lambda: now_sat.timestamp(),
    )
    result_sat = source_sat.fetch(_settings(f1=False, indycar=True))
    sessions = [g["home_abbr"] for g in result_sat["content"]]
    assert "Practice 1" in sessions
    assert "Qualifying" in sessions


def test_indycar_weekend_session_html_parser() -> None:
    html = """
    <h3>Saturday, Aug 22</h3>
    <div class="schedule-entry">
        <div class="schedule-time">9:00AM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Practice 1</div>
    </div>
    <div class="schedule-entry">
        <div class="schedule-time">1:00PM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Practice 2</div>
    </div>
    <div class="schedule-entry">
        <div class="schedule-time">5:00PM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Qualifying</div>
    </div>
    <h3>Sunday, Aug 23</h3>
    <div class="schedule-entry">
        <div class="schedule-time">9:00AM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Warmup</div>
    </div>
    <div class="schedule-entry">
        <div class="schedule-time">1:00PM ET</div>
        <div class="schedule-description">NTT INDYCAR SERIES - Race</div>
    </div>
    """
    from ticker.server.providers.racing_live import _parse_indycar_weekend_html

    sessions = _parse_indycar_weekend_html(html, 2026)
    assert len(sessions) == 5
    assert "Practice1" in sessions
    assert "Practice2" in sessions
    assert "Qualifying" in sessions
    assert "Warmup" in sessions
    assert "Race" in sessions

    p1_start, p1_dur, p1_name, p1_practice = sessions["Practice1"]
    assert p1_name == "Practice 1"
    assert p1_dur == 90
    assert p1_practice is True
    assert p1_start == datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc)


def test_racing_standardized_flags() -> None:
    from ticker.server.providers.racing_live import _normalize_racing_flag, _CAUTION_FLAGS

    cases = {
        "VIRTUAL SAFETY CAR DEPLOYED": ("VSC", True),
        "SAFETY CAR DEPLOYED": ("SAFETY CAR", True),
        "VSC ENDING": ("VSC ENDING", True),
        "SC ENDING": ("SC ENDING", True),
        "DOUBLE YELLOW": ("DOUBLE YELLOW", True),
        "YELLOW FLAG": ("YELLOW", True),
        "RED FLAG IN SECTOR 1": ("RED FLAG", True),
        "FULL COURSE YELLOW": ("FCY", True),
        "CHKD": ("CHECKERED", False),
        "CHECKERED FLAG": ("CHECKERED", False),
        "BLACK AND ORANGE": ("MEATBALL", False),
        "BLACK AND WHITE": ("BLACK AND WHITE", False),
        "GWC": ("GWC", False),
        "GREEN": ("GREEN", False),
        "CLEAR": ("GREEN", False),
        "1": ("UNKNOWN", False),
    }

    for input_flag, (expected_token, is_caution) in cases.items():
        token = _normalize_racing_flag(input_flag)
        assert token == expected_token, f"Failed for {input_flag}: expected {expected_token}, got {token}"
        assert (token in _CAUTION_FLAGS) == is_caution, f"Caution mismatch for {token}"


def test_series_fetch_at_the_same_time_and_keep_the_fixed_order() -> None:
    from threading import Barrier

    source = _source(JsonFixture({}), TextFixture(""))
    barrier = Barrier(5, timeout=5)

    def series(name, fail=False):
        def fetch(settings):
            # Each fetch waits here until all five run, so a sequential fetch fails.
            barrier.wait()
            if fail:
                raise RuntimeError("feed down")
            return [{"id": name}]
        return fetch

    source._fetch_f1 = series("f1")
    source._fetch_indycar = series("indycar", fail=True)
    source._cup_source.fetch = series("nascar")
    source._endurance_source.fetch = lambda sport, settings: series(sport)(settings)
    try:
        result = source.fetch(_settings(f1=True, indycar=True, nascar=True, wec=True, imsa=True))
    finally:
        source.close()

    assert [record["id"] for record in result["content"]] == ["f1", "nascar", "wec", "imsa"]
    assert result["health"] == {"provider": "racing", "healthy": False, "error": "indycar: feed down"}


def test_circuit_weather_location_lookups_stay_one_per_second_across_series() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from ticker.server.providers.racing_weather import CircuitWeatherSource

    class Client:
        def __init__(self):
            self.lookups = 0

        def get_json(self, url, *, timeout):
            if "nominatim" in url:
                self.lookups += 1
                return [{"type": "raceway", "lat": "33.1", "lon": "-83.8"}]
            return {"current": {"time": "2026-10-29T12:00", "temperature_2m": 70, "wind_speed_10m": 5, "wind_direction_10m": 90}}

    client = Client()
    weather = CircuitWeatherSource(client, clock=lambda: 1000.0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda track: weather.fetch(track), [f"TRACK {index}" for index in range(8)]))

    assert client.lookups == 1
    assert sum(result.get("available", False) for result in results) == 1
