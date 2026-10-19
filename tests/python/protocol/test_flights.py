"""Exercise the production flight contract through projection and rendering."""

from datetime import datetime, timezone

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.providers.flights import FlightsProvider
from sports_ticker.providers.live_sources import FlightRadarSource
from sports_ticker.providers.contracts import ProviderHealth
from sports_ticker.projections import project_data_v2
from ticker_core.context import RenderContext
from ticker_core.features.flight import FlightRenderer
from ticker_core.rendering import ContentScene, load_default_font_set


NOW = 1_800_000_000.0


class FlightRadarFixture:
    """Return real-shaped FlightRadar24 search and airport responses."""

    def search(self, query: str) -> dict[str, object]:
        assert query == "UA123"
        return {
            "stats": {"total": 1},
            "live": [
                {
                    "id": "fr24-ua1230",
                    "detail": {"flight": "UA1230", "callsign": "UAL1230"},
                },
                {
                    "id": "fr24-ua123",
                    "detail": {
                        "flight": "UA123",
                        "callsign": "UAL123",
                        "status": {"text": "En route", "live": True},
                        "schd_from": "EWR",
                        "schd_to": "LAX",
                        "lat": 37.0,
                        "lon": -90.0,
                        "alt": 36_000,
                        "spd": 430,
                    },
                }
            ],
        }

    def get_flight_details(self, entry: object) -> dict[str, object]:
        assert isinstance(entry, dict)
        return {
            "identification": {
                "number": {"default": "UA123", "alternative": "UAL123"},
                "callsign": "UAL123",
            },
            "airline": {
                "name": "United Airlines",
                "code": {"iata": "UA", "icao": "UAL"},
            },
            "aircraft": {
                "model": {"text": "Boeing 737-8 MAX", "code": "B38M"},
                "registration": "N123UA",
            },
            "airport": {
                "origin": {
                    "name": "Newark Liberty",
                    "code": {"iata": "EWR", "icao": "KEWR"},
                    "position": {
                        "latitude": 40.6895,
                        "longitude": -74.1745,
                        "region": {"city": "Newark"},
                    },
                },
                "destination": {
                    "name": "Los Angeles International",
                    "code": {"iata": "LAX", "icao": "KLAX"},
                    "position": {
                        "latitude": 33.9416,
                        "longitude": -118.4085,
                        "region": {"city": "Los Angeles"},
                    },
                },
            },
            "time": {
                "scheduled": {
                    "departure": NOW - 4_800,
                    "arrival": NOW + 7_200,
                },
                "estimated": {
                    "arrival": NOW + 8_400,
                },
            },
            "trail": [{"lat": 37.0, "lng": -90.0, "alt": 36_000, "spd": 430, "ts": NOW}],
        }

    def get_airport_details(self, code: str, *, flight_limit: int) -> dict[str, object]:
        assert code == "EWR"
        assert flight_limit == 4
        return {
            "airport": {
                "pluginData": {
                    "details": {
                        "name": "Newark Liberty International",
                        "code": {"iata": "EWR", "icao": "KEWR"},
                        "position": {"region": {"city": "Newark"}},
                    },
                    "weather": {
                        "temp": {"fahrenheit": 72, "celsius": 22.2},
                        "sky": {"condition": {"text": "Clear"}},
                        "wind": {"speed": {"mph": 8, "kts": 7}},
                        "time": NOW,
                        "cached": NOW,
                    },
                    "schedule": {
                        "arrivals": {
                            "data": [
                                {
                                    "flight": {
                                        "identification": {"number": {"default": "DL456"}},
                                        "airline": {
                                            "name": "Delta Air Lines",
                                            "code": {"iata": "DL", "icao": "DAL"},
                                        },
                                        "airport": {
                                            "origin": {
                                                "code": {"iata": "ATL"},
                                                "position": {"region": {"city": "Atlanta"}},
                                            },
                                            "destination": {
                                                "code": {"iata": "EWR"},
                                                "position": {"region": {"city": "Newark"}},
                                            },
                                        },
                                        "time": {
                                            "scheduled": {"arrival": NOW + 1_200},
                                            "estimated": {"arrival": NOW + 2_100},
                                        },
                                    }
                                }
                            ]
                        },
                        "departures": {
                            "data": [
                                {
                                    "flight": {
                                        "identification": {"number": {"default": "UA789"}},
                                        "airport": {
                                            "origin": {
                                                "code": {"iata": "EWR"},
                                                "position": {"region": {"city": "Newark"}},
                                            },
                                            "destination": {
                                                "code": {"iata": "ORD"},
                                                "position": {"region": {"city": "Chicago"}},
                                            },
                                        },
                                        "status": {"text": "Boarding"},
                                        "time": {
                                            "scheduled": {"departure": NOW + 1_800},
                                            "estimated": {"departure": NOW + 3_600},
                                        },
                                    }
                                }
                            ]
                        },
                    },
                },
            }
        }


class NearMissFlightRadarFixture(FlightRadarFixture):
    """Return only a nearby flight number that must not satisfy the request."""

    def search(self, query: str) -> dict[str, object]:
        assert query == "UA123"
        return {
            "live": [{"id": "fr24-ua1230", "detail": {"flight": "UA1230"}}],
        }


def _settings() -> DisplaySettings:
    return DisplaySettings(
        mode="flights",
        track_flight_id="UA123",
        track_guest_name="VISITOR",
        airport_code_iata="EWR",
        airport_code_icao="KEWR",
        airport_name="Newark Liberty International",
    )


def test_flight_source_supplies_live_and_airport_contract_facts() -> None:
    source = FlightRadarSource(FlightRadarFixture(), clock=lambda: NOW)
    payload = source.fetch(_settings())

    visitor, airport = payload["content"]
    assert visitor["route"] == "EWR > LAX"
    assert visitor["origin_city"] == "Newark"
    assert visitor["dest_city"] == "Los Angeles"
    assert visitor["altitude_ft"] == 36_000
    assert visitor["distance_miles"] > 0
    assert visitor["speed_mph"] == 495
    assert visitor["eta_str"] == "2H 20M"
    assert 0 < visitor["progress_pct"] < 100
    assert visitor["delay_min"] == 20
    assert visitor["is_delayed"] is True
    assert visitor["airline_iata"] == "UA"
    assert visitor["aircraft_model"] == "Boeing 737-8 MAX"
    assert visitor["aircraft_registration"] == "N123UA"
    assert airport["weather"]["away_abbr"] == "72F"
    assert airport["weather"]["status"] == "CLEAR"
    assert airport["weather"]["city"] == "Newark"
    assert airport["weather"]["airport_name"] == "Newark Liberty International"
    assert airport["weather"]["wind_mph"] == 8
    assert airport["arrivals"][0]["status"] == "ARRIVING"
    assert airport["arrivals"][0]["state"] == "arriving"
    assert airport["arrivals"][0]["delay_min"] == 15
    assert airport["departures"][0]["status"] == "BOARDING"
    assert airport["departures"][0]["state"] == "boarding"
    assert airport["departures"][0]["delay_min"] == 30


def test_flight_search_does_not_select_a_nearby_flight_number() -> None:
    source = FlightRadarSource(NearMissFlightRadarFixture(), clock=lambda: NOW)
    visitor = source.fetch(_settings())["content"][0]
    assert visitor["id"] == "UA123"
    assert visitor["status"] == "pending"


def test_flight_provider_projection_and_render_keep_contract_shape() -> None:
    settings = _settings()
    provider = FlightsProvider(FlightRadarSource(FlightRadarFixture(), clock=lambda: NOW))
    result = provider.fetch(settings)
    assert result.health == ProviderHealth(provider="flights")
    snapshot = TickerSnapshot(
        ticker_id="ticker-1",
        revision=1,
        observed_at=datetime.fromtimestamp(NOW, tz=timezone.utc),
        content=result.content,
        alerts=(),
        news=(),
        effective_settings=settings,
    )
    projected = project_data_v2(snapshot, result.health, {"stale": False})
    visitor_envelope = projected["content"]["flights"][0]
    airport_envelope = projected["content"]["airports"][0]
    visitor = {**visitor_envelope["data"], "type": visitor_envelope["kind"]}
    airport = {**airport_envelope["data"], "type": airport_envelope["kind"]}
    renderer = FlightRenderer(load_default_font_set())
    context = RenderContext(datetime.fromtimestamp(NOW, tz=timezone.utc))
    visitor_frame = renderer.render(context, ContentScene(visitor, "flights")).image
    airport_frame = renderer.render(context, ContentScene(airport, "airports")).image
    assert visitor_frame.size == (384, 32)
    assert airport_frame.size == (384, 32)
