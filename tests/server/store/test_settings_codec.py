"""Verify canonical settings survive JSON and durable storage boundaries."""
import json

import pytest

from ticker.shared.domain import DisplaySettings
from ticker.shared.domain.settings import settings_from_mapping, settings_to_mapping
from ticker.server.store import TickerRepository
from ticker.server.providers.normalization import normalize_settings

pytestmark = pytest.mark.critical


def test_settings_survive_json_and_repository_reopen(tmp_path):
    settings = DisplaySettings(
        mode="sports", sports_presentation="pinned", pinned_content_id="nfl:123",
        active_sports={"nfl": True, "nba": False}, my_teams=("nfl:NYG",),
        custom_stock_symbols=("NVDA", "BRK.B"), brightness=37,
        timezone="America/New_York", inverted=True,
        weather_city="Boston", weather_lat=42.36, weather_lon=-71.06,
        airport_code_iata="BOS", airport_code_icao="KBOS", airport_name="Logan",
        track_flight_id="UA123", track_guest_name="Guest", live_delay_mode=True,
        live_delay_seconds=90, scroll_speed=0.04, scroll_seamless=False, score_alerts=False,
    )
    payload = json.loads(json.dumps(settings_to_mapping(settings)))
    assert payload["custom_stock_symbols"] == ["NVDA", "BRK.B"]
    assert payload["active_sports"] == {"nfl": True, "nba": False}
    assert settings_from_mapping(payload) == settings
    assert normalize_settings(payload) == settings
    database = tmp_path / "settings.sqlite3"
    with TickerRepository(database) as repository:
        repository.create_ticker("codec-ticker", display_settings=settings)
    with TickerRepository(database) as repository:
        assert repository.get_ticker("codec-ticker").display_settings == settings


def test_missing_settings_use_domain_defaults_without_mutable_aliases():
    assert settings_from_mapping({"future_setting": True}) == DisplaySettings()
    assert settings_from_mapping(None) == DisplaySettings()
    settings = settings_from_mapping({"active_sports": {"nfl": True}, "my_teams": ["nfl:NYG"]})
    payload = settings_to_mapping(settings)
    payload["active_sports"]["nfl"] = False
    payload["my_teams"].append("nfl:DAL")
    assert settings.active_sports["nfl"] is True
    assert "nfl:DAL" not in settings.my_teams


def test_settings_codec_preserves_validation_and_provider_mode_coercion():
    with pytest.raises(ValueError):
        settings_from_mapping({"custom_stock_symbols": ["INVALID!"]})
    with pytest.raises(TypeError):
        settings_from_mapping([])
    assert settings_from_mapping({"mode": ""}).mode == "sports"
    with pytest.raises(ValueError):
        settings_from_mapping({"mode": None})
    with pytest.raises(ValueError):
        normalize_settings({"mode": None})
