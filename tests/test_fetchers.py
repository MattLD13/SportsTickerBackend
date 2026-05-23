import time
import responses
import pytest
from sports_ticker.fetchers.test_mode import TestMode
from sports_ticker.fetchers.weather import WeatherFetcher
from sports_ticker.fetchers.stocks import StockFetcher

def test_test_mode_configuration():
    # Reset
    TestMode.configure(enabled=False)
    assert TestMode.is_enabled("spotify") is False
    assert TestMode.is_enabled("stocks") is False

    # Enable all
    TestMode.configure(enabled=True)
    assert TestMode.is_enabled("spotify") is True
    assert TestMode.is_enabled("stocks") is True

    # Per subsystem
    TestMode.configure(enabled=False, spotify=True)
    assert TestMode.is_enabled("spotify") is True
    assert TestMode.is_enabled("stocks") is False

    # Custom date override
    TestMode.configure(custom_date="2026-12-25", sports_date=True)
    assert TestMode.get_custom_date() == "20261225"
    
    TestMode.configure(sports_date=False)
    assert TestMode.get_custom_date() is None


def test_weather_fetcher_helpers():
    fetcher = WeatherFetcher(city="Seattle", initial_lat=47.6, initial_lon=-122.3)
    
    assert fetcher.city_name == "Seattle"
    assert fetcher.lat == 47.6
    assert fetcher.lon == -122.3

    # Update config
    fetcher.update_config(city="Portland", lat=45.5, lon=-122.6)
    assert fetcher.city_name == "Portland"
    assert fetcher.lat == 45.5
    assert fetcher.lon == -122.6

    # Icons mapping
    assert fetcher.get_weather_icon(0) == "sun"
    assert fetcher.get_weather_icon(3) == "cloud"
    assert fetcher.get_weather_icon(61) == "rain"
    assert fetcher.get_weather_icon(73) == "snow"
    assert fetcher.get_weather_icon(95) == "storm"
    assert fetcher.get_weather_icon("unknown") == "cloud"

    # Day name conversion
    # Assume 2026-05-25 is a Monday
    assert fetcher.get_day_name("2026-05-25") == "MON"


@responses.activate
def test_weather_fetcher_get_weather():
    fetcher = WeatherFetcher(city="Miami", initial_lat=25.76, initial_lon=-80.19)
    
    # Mock Open-Meteo Weather API
    responses.add(
        responses.GET,
        "https://api.open-meteo.com/v1/forecast",
        json={
            "current": {
                "temperature_2m": 78.4,
                "apparent_temperature": 82.1,
                "weather_code": 0,
                "wind_speed_10m": 12.5,
                "relative_humidity_2m": 68
            },
            "daily": {
                "time": ["2026-05-23", "2026-05-24"],
                "weather_code": [0, 3],
                "temperature_2m_max": [85.0, 82.0],
                "temperature_2m_min": [74.0, 72.0],
                "uv_index_max": [9.5, 6.0]
            }
        },
        status=200
    )

    # Mock Open-Meteo AQI API
    responses.add(
        responses.GET,
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        json={
            "current": {
                "us_aqi": 42
            }
        },
        status=200
    )

    data = fetcher.get_weather()
    
    assert data is not None
    assert data["type"] == "weather"
    assert data["away_abbr"] == "MIAMI"
    assert data["home_score"] == "78"
    assert data["situation"]["icon"] == "sun"
    assert data["situation"]["stats"]["aqi"] == "42"
    assert data["situation"]["stats"]["uv"] == "9.5"
    assert data["situation"]["stats"]["feels"] == "82"
    assert data["situation"]["stats"]["wind"] == "12"
    assert data["situation"]["stats"]["humidity"] == "68"
    assert len(data["situation"]["forecast"]) == 2
    assert data["situation"]["forecast"][0]["high"] == 85
    assert data["situation"]["forecast"][0]["low"] == 74
    assert data["situation"]["forecast"][1]["icon"] == "cloud"


def test_stock_fetcher_helpers(clean_state):
    # Stock fetcher works either in simulation mode (no API keys) or using keys.
    # In both cases we can test core helper methods.
    fetcher = StockFetcher()
    
    # Clear ETF vs financial company logo builders
    assert "clearbit" in fetcher.get_logo_url("SPY")
    assert "financialmodelingprep" in fetcher.get_logo_url("AAPL")

    # Maker helper
    res = fetcher._make_stock_result("MSFT", 420.50, 5.25, 1.25)
    assert res["symbol"] == "MSFT"
    assert res["price"] == "420.50"
    assert res["change_amt"] == "+5.25"
    assert res["change_pct"] == "+1.25%"

    res_neg = fetcher._make_stock_result("TSLA", 175.20, -3.40, -1.90)
    assert res_neg["change_amt"] == "-3.40"
    assert res_neg["change_pct"] == "-1.90%"


def test_stock_fetcher_simulation(clean_state):
    # Force simulation mode
    fetcher = StockFetcher()
    fetcher.simulated = True

    # Seed mock cache
    fetcher.market_cache["AAPL"] = {
        "price": "180.50",
        "change_amt": "+2.40",
        "change_pct": "+1.35%"
    }

    # Test obj retrieval
    obj = fetcher.get_stock_obj("AAPL", "AI STOCKS")
    assert obj is not None
    assert obj["home_abbr"] == "AAPL"
    assert obj["home_score"] == "180.50"
    assert obj["away_score"] == "+1.35%"
    assert obj["situation"]["change"] == "+2.40"
    assert obj["status"] == "AI STOCKS"

    # Test list retrieval
    fetcher.lists = {"tech": ["AAPL"]}
    tech_list = fetcher.get_list("tech")
    assert len(tech_list) == 1
    assert tech_list[0]["home_abbr"] == "AAPL"
