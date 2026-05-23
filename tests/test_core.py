import os
import json
import time
import pytest
from sports_ticker.core import (
    normalize_mode,
    is_mode_enabled,
    first_enabled_mode,
    normalize_enabled_mode,
    _normalize_single_pin,
    _game_sort_key,
    save_json_atomically,
    purge_stale_tickers,
    generate_pairing_code,
    safe_get,
    parse_iso,
    create_ticker_record,
    tickers,
    state,
)

def test_normalize_mode():
    assert normalize_mode("sports") == "sports"
    assert normalize_mode("nonexistent") == "sports"
    # Test migrations if they exist in MODE_MIGRATIONS
    from sports_ticker.leagues import MODE_MIGRATIONS
    for k, v in MODE_MIGRATIONS.items():
        assert normalize_mode(k) == v


def test_is_mode_enabled(clean_state):
    # Default behavior (sports should be enabled)
    assert is_mode_enabled("sports") is True

    # Explicitly disable
    clean_state["active_modes"]["sports"] = False
    assert is_mode_enabled("sports") is False

    # Explicitly enable
    clean_state["active_modes"]["sports"] = True
    assert is_mode_enabled("sports") is True


def test_first_enabled_mode(clean_state):
    # Disable sports, see if it finds another enabled one or fallback
    clean_state["active_modes"]["sports"] = False
    # Set at least one mode to true
    clean_state["active_modes"]["clock"] = True
    
    first = first_enabled_mode()
    assert first != "sports"
    assert is_mode_enabled(first) is True


def test_normalize_enabled_mode(clean_state):
    # When target is enabled
    clean_state["active_modes"]["clock"] = True
    assert normalize_enabled_mode("clock") == "clock"


def test_normalize_single_pin():
    # Test list vs single pinned game
    single, lst = _normalize_single_pin(pinned_game="nhl:123", pinned_games=[])
    assert single == "nhl:123"
    assert lst == ["nhl:123"]

    single, lst = _normalize_single_pin(pinned_game=None, pinned_games=["nba:456", "nfl:789"])
    assert single == "nfl:789"
    assert lst == ["nfl:789"]

    single, lst = _normalize_single_pin(pinned_game="nhl:123", pinned_games=["nba:456"])
    assert single == "nba:456"
    assert lst == ["nba:456"]


def test_game_sort_key():
    # Clock gets priority 0, Weather 1, Active 2, Final 3, Hidden 4
    clock = {"type": "clock", "startTimeUTC": "2026-01-01T00:00:00Z"}
    weather = {"type": "weather", "startTimeUTC": "2026-01-01T00:00:00Z"}
    active_game = {"type": "game", "status": "In Progress", "startTimeUTC": "2026-01-01T12:00:00Z"}
    final_game = {"type": "game", "status": "FINAL", "startTimeUTC": "2026-01-01T10:00:00Z"}
    canceled_game = {"type": "game", "status": "canceled", "startTimeUTC": "2026-01-01T08:00:00Z"}

    games = [canceled_game, final_game, active_game, weather, clock]
    sorted_games = sorted(games, key=_game_sort_key)
    
    assert sorted_games[0]["type"] == "clock"
    assert sorted_games[1]["type"] == "weather"
    assert sorted_games[2]["status"] == "In Progress"
    assert sorted_games[3]["status"] == "FINAL"
    assert sorted_games[4]["status"] == "canceled"


def test_save_json_atomically(tmp_path):
    filepath = tmp_path / "test_config.json"
    data = {"hello": "world"}
    save_json_atomically(str(filepath), data)
    
    assert filepath.exists()
    with open(filepath, "r") as f:
        loaded = json.load(f)
    assert loaded == data


def test_purge_stale_tickers(clean_state):
    # Add some active and inactive/junk tickers
    # tickers is a global dict in core.py
    now = time.time()
    
    # 1. Valid active ticker
    tickers["ticker_valid"] = create_ticker_record("Valid Ticker", paired=True)
    tickers["ticker_valid"]["last_seen"] = now
    
    # 2. Junk ID ticker
    tickers["ticker_poop"] = create_ticker_record("Junk Ticker", paired=True)
    tickers["ticker_poop"]["last_seen"] = now
    
    # 3. Stale ticker (8 days ago)
    tickers["ticker_stale"] = create_ticker_record("Stale Ticker", paired=True)
    tickers["ticker_stale"]["last_seen"] = now - (9 * 24 * 3600)
    
    # 4. Unnamed ticker (2 hours ago)
    tickers["ticker_unnamed"] = create_ticker_record("", paired=True)
    tickers["ticker_unnamed"]["name"] = ""
    tickers["ticker_unnamed"]["last_seen"] = now - (2 * 3600)

    # Perform purge
    purged = purge_stale_tickers()
    
    assert "ticker_valid" in tickers
    assert "ticker_poop" not in tickers
    assert "ticker_stale" not in tickers
    assert "ticker_unnamed" not in tickers
    assert len(purged) == 3


def test_generate_pairing_code(clean_state):
    code = generate_pairing_code()
    assert len(code) == 6
    assert code.isdigit()


def test_safe_get():
    data = {"a": {"b": {"c": 42}}}
    assert safe_get(data, "a", "b", "c") == 42
    assert safe_get(data, "a", "x", default="fallback") == "fallback"
    assert safe_get(None, "a") is None


def test_parse_iso():
    from datetime import datetime, timezone
    dt = parse_iso("2026-05-23T04:00:00Z")
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 23
    assert dt.hour == 4
    assert dt.tzinfo == timezone.utc

    with pytest.raises(ValueError):
        parse_iso("")
