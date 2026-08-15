from datetime import datetime, timezone

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.racing import RacingProvider
from sports_ticker.providers.racing_live import LiveRacingSource, _indycar_driver


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


def _settings(**active_sports: bool) -> DisplaySettings:
    return DisplaySettings(active_sports=active_sports, timezone="America/New_York")


def test_f1_polls_openf1_positions_for_the_current_session() -> None:
    now = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    client = JsonFixture(
        {
            "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard": {
                "events": [
                    {
                        "id": "f1-event",
                        "name": "Sponsor Canadian Grand Prix",
                        "circuit": {"fullName": "Test Circuit", "address": {"city": "Montreal"}},
                        "competitions": [
                            {
                                "type": {"abbreviation": "Race"},
                                "startDate": "2026-08-15T14:00:00Z",
                            }
                        ],
                    }
                ]
            },
            "https://api.openf1.org/v1/sessions?session_key=latest": [
                {
                    "session_key": 99,
                    "session_name": "Race",
                    "date_start": "2026-08-15T14:00:00Z",
                    "date_end": "2026-08-15T17:00:00Z",
                }
            ],
            "https://api.openf1.org/v1/drivers?session_key=99": [
                {"driver_number": 1, "full_name": "Leader Driver", "name_acronym": "LED", "team_name": "Test Team"},
                {"driver_number": 2, "full_name": "Second Driver", "name_acronym": "SEC", "team_name": "Test Team"},
            ],
            "https://api.openf1.org/v1/position?session_key=99": [
                {"driver_number": 1, "position": 1, "date": "2026-08-15T15:00:00Z"},
                {"driver_number": 2, "position": 2, "date": "2026-08-15T15:00:00Z"},
            ],
            "https://api.openf1.org/v1/laps?session_key=99": [
                {"driver_number": 1, "lap_number": 12, "lap_duration": 80.0},
                {"driver_number": 2, "lap_number": 12, "lap_duration": 81.0},
            ],
            "https://api.openf1.org/v1/intervals?session_key=99": [
                {"driver_number": 1, "gap_to_leader": 0.0, "date": "2026-08-15T15:00:00Z"},
                {"driver_number": 2, "gap_to_leader": 1.234, "date": "2026-08-15T15:00:00Z"},
            ],
            "https://api.openf1.org/v1/race_control?session_key=99": [],
        }
    )
    source = LiveRacingSource(client, now=lambda: now, clock=lambda: now.timestamp())

    result = source.fetch(_settings(f1=True, indycar=False))

    game = result["content"][0]
    assert game["sport"] == "f1"
    assert game["state"] == "in"
    assert game["f1"]["lap"] == 12
    assert game["f1"]["drivers"][1]["gap"] == "+1.234s"
    assert any("api.openf1.org/v1/position" in url for url in client.urls)


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
                        {"no": "1", "firstName": "One", "lastName": "Driver", "team": "Penske", "rank": 1, "laps": 12},
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
    source = LiveRacingSource(client, now=lambda: now, clock=lambda: now.timestamp())

    result = source.fetch(_settings(f1=False, indycar=True))

    game = result["content"][0]
    assert game["sport"] == "indycar"
    assert game["state"] == "in"
    assert game["indycar"]["event_name"] == "Road America"
    assert game["indycar"]["drivers"][0]["team_logo"] == "plate-1"
    assert game["indycar"]["drivers"][1]["gap"] == "+1.2"

    normalized = RacingProvider(source).fetch(_settings(f1=False, indycar=True))
    assert normalized.content[0].family == "racing"
    assert normalized.content[0].kind == "indycar"
    assert normalized.content[0].data["sport"] == "indycar"


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
