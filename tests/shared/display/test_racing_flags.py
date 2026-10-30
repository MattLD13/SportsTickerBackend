"""Audit the flag vocabulary, series meanings, and native flag vectors."""
import json

import pytest

from ticker.shared.sports_display import RACING_FLAGS, racing_flag_code, racing_signal, racing_flag_pixel
from tools.mini.racing_vectors import TARGET, vectors, game, mini_payload

pytestmark = pytest.mark.critical


@pytest.mark.parametrize("raw,expected", [
    ("green", "GREEN"), ("GF", "GREEN"), ("YF", "YELLOW"), ("RF", "RED FLAG"),
    ("FF", "CHECKERED"), ("SC", "SAFETY CAR"), ("FCY", "FCY"), ("C60", "CODE60"),
    ("DoubleWavedYellow", "DOUBLE YELLOW"), ("BLUE_WITH_YELLOW_STRIPE", "BLUE YELLOW"),
    ("BlackWithOrangeDisk", "MEATBALL"), ("BlackWithWhiteCross", "BLACK WHITE CROSS"),
    ("BlackAndWhite", "BLACK AND WHITE"), ("WhiteWithRedCross", "WHITE RED CROSS"),
    ("RedWithYellowCross", "RED YELLOW CROSS"), ("YellowWithRedStripes", "SURFACE"),
    ("BlackAndRedCombined", "RED BLACK"), ("FurledBlack", "BLACK FURLED"),
    ("WavedBlue", "BLUE"), ("MotionlessSingleYellow", "YELLOW"), ("WAVED WHITE FLAG", "WHITE"),
    ("Chequered", "CHECKERED"), ("ChequeredYellow", "CHECKERED YELLOW"),
    ("ChequeredSafetyCar", "CHECKERED SC"), ("ChequeredVirtualSafetyCar", "CHECKERED VSC"),
    ("LastLap", "LAST LAP"), ("LastLapYellow", "LAST LAP YELLOW"),
    ("LastLapSafetyCar", "LAST LAP SC"), ("LastLapVirtualSafetyCar", "LAST LAP VSC"),
    ("WhiteYellow", "WHITE YELLOW"), ("WhiteSafetyCar", "WHITE SC"),
    ("TemporaryChequered", "CHECKERED"), ("VirtualSafetyCar", "VSC"),
    ("SAFETY CAR DEPLOYED", "SAFETY CAR"), ("VIRTUAL SAFETY CAR DEPLOYED", "VSC"),
])
def test_published_timing_vocabularies_keep_their_identity(raw, expected):
    assert racing_flag_code(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "1", 7, "Other", "NOT GREEN", "UNKNOWN FUTURE FLAG", "GREENISH"])
def test_absent_or_unrecognized_values_never_become_green(raw):
    assert racing_flag_code(raw) == "UNKNOWN"
    signal = racing_signal(raw, "f1")
    assert not signal["known"]
    assert signal["color_rgb"] != RACING_FLAGS["GREEN"][3]


@pytest.mark.parametrize("series", ["f1", "wec"])
def test_fia_white_flag_means_slow_vehicle(series):
    assert racing_signal("WHITE", series)["meaning"] == "Slow vehicle ahead"


@pytest.mark.parametrize("series", ["indycar", "nascar", "imsa"])
def test_white_flag_keeps_starter_and_corner_post_meanings_separate(series):
    assert racing_signal("WHITE", series)["meaning"] == "Last lap"
    assert racing_signal("WHITE", series, scope="sector", sector="3")["meaning"] == "Slow vehicle ahead"


def test_safety_boards_are_distinct_and_car_flags_keep_their_target():
    assert racing_signal("SC", "wec")["code"] != racing_signal("VSC", "wec")["code"]
    assert racing_signal("BLACK", "f1", car="16")["scope"] == "car"
    assert racing_signal("RED WITH YELLOW CROSS", "nascar")["scope"] == "pit"
    signal = racing_signal("RED FLAG IN SECTOR 1", "f1")
    assert signal["scope"] == "sector" and signal["sector"] == "1"
    assert racing_signal("BLACK AND RED COMBINED", "imsa")["meaning"] == "Stop beside the track"
    assert racing_signal("BLUE", "nascar")["scope"] == "sector"
    assert racing_signal("BLUE", "nascar")["meaning"] != racing_signal("BLUE YELLOW", "nascar")["meaning"]
    assert racing_signal("BLACK", "f1")["label"] == "DSQ"
    assert racing_signal("BLACK", "nascar")["label"] == "PIT"


@pytest.mark.parametrize("code", list(RACING_FLAGS))
def test_every_signal_has_valid_pixels_at_all_three_native_sizes(code):
    signal = racing_signal(code, "imsa")
    assert signal["known"] is (code != "UNKNOWN")
    for width, height in ((5, 5), (9, 6), (15, 10)):
        pixels = [racing_flag_pixel(signal, x, y, width, height) for y in range(height) for x in range(width)]
        assert all(len(pixel) == 3 and all(0 <= channel <= 255 for channel in pixel) for pixel in pixels)
        assert len(pixels) == width * height


def test_patterned_signals_remain_distinct_from_plain_flags():
    def raster(code):
        signal = racing_signal(code, "imsa")
        return [racing_flag_pixel(signal, x, y, 5, 5) for y in range(5) for x in range(5)]
    assert raster("BLUE") != raster("BLUE YELLOW")
    assert raster("YELLOW") != raster("DOUBLE YELLOW")
    assert raster("CHECKERED") != raster("BLACK AND WHITE")
    assert raster("MEATBALL") != raster("BLACK")
    assert raster("WHITE RED CROSS") != raster("WHITE")
    assert raster("CHECKERED YELLOW") != raster("CHECKERED")


def test_native_fixture_matches_the_contract_generator():
    assert json.loads(TARGET.read_text(encoding="utf-8")) == vectors()


def test_reported_motion_survives_normalization_and_mini_projection():
    source = game("nascar", "YELLOW")
    source["nascar"]["flag_raw"] = "WAVED YELLOW"
    signals = mini_payload(source)["content"]["racing"][0]["data"]["racing_display"]["signals"]
    assert signals[0]["flashing"] is True


def test_car_and_sector_signals_survive_mini_projection_without_changing_the_track_signal():
    source = game("wec")
    source["wec"]["signals"] = [
        {"active": True, "code": "MEATBALL", "scope": "car", "car": "45"},
        {"active": True, "code": "DOUBLE YELLOW", "scope": "sector", "sector": "2"},
        {"active": False, "code": "RED FLAG", "scope": "track"},
    ]
    payload = mini_payload(source)
    signals = payload["content"]["racing"][0]["data"]["racing_display"]["signals"]
    assert signals[0]["code"] == "GREEN"
    assert [s["code"] for s in signals] == ["GREEN", "MEATBALL", "DOUBLE YELLOW"]
    assert signals[1]["label"] == "ME45"
    assert signals[2]["label"] == "2 S2"
    assert all(len(s["pixels"]) == 25 for s in signals)
