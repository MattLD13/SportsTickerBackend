"""Keep generated filtering and device projection under one field owner."""
import pytest
from tools.mini.generate_mini_fields import header, TARGET
from sports_ticker.projections.device_data import project_device_data

pytestmark = pytest.mark.critical


def test_mini_fields_preserve_display_facts_and_match_generated_filter():
    assert TARGET.read_text(encoding="utf-8") == header()
    game = {"sport": "nhl", "away_seed": "1", "home_rank": "3", "unused": "large source data",
            "away_logo_asset": {"state": "ready", "asset_id": "identity", "sha256": "digest", "url": "unused"},
            "situation": {"manpower": {"scrollLabel": "PP", "penalties": [{"timeRemaining": "0:45", "jerseyNumber": "88", "unused": 1}]}}}
    source = {"content": {"sports": [{"id": "visible", "is_shown": True, "data": game}, {"id": "hidden", "is_shown": False, "data": game}]}, "settings": {"mode": "sports"}}
    actual = project_device_data(source, mini=True)
    assert len(actual["content"]["sports"]) == 1
    data = actual["content"]["sports"][0]["data"]
    assert data["away_seed"] == "1" and data["home_rank"] == "3"
    assert data["away_logo_asset"] == {"state": "ready", "asset_id": "identity", "sha256": "digest"}
    assert data["situation"]["manpower"]["penalties"] == [{"timeRemaining": "0:45", "jerseyNumber": "88"}]
    assert "unused" not in data
    assert source["content"]["sports"][0]["data"]["unused"] == "large source data"
