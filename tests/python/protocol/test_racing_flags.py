"""Audit the flag vocabulary, series meanings, and native flag vectors."""
from pathlib import Path
import json

import pytest

from sports_ticker.providers.sports_display import RACING_FLAGS, racing_flag_code, racing_signal, racing_flag_pixel, RACING_COMBINED_SIGNALS
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
    assert signals[0]["alternate_ms"] == 0
    assert racing_signal("WAVED YELLOW", "nascar")["motion"] == "waved"


def test_car_and_pit_signals_are_filtered_but_sector_signals_remain():
    source = game("wec")
    source["wec"]["signals"] = [
        {"active": True, "code": "MEATBALL", "scope": "car", "car": "45"},
        {"active": True, "code": "DOUBLE YELLOW", "scope": "sector", "sector": "2"},
        {"active": True, "code": "RED YELLOW CROSS", "scope": "pit"},
        {"active": False, "code": "RED FLAG", "scope": "track"},
    ]
    payload = mini_payload(source)
    signals = payload["content"]["racing"][0]["data"]["racing_display"]["signals"]
    assert signals[0]["code"] == "GREEN"
    assert [s["code"] for s in signals] == ["GREEN", "DOUBLE YELLOW"]
    assert all("label" not in signal and "show_label" not in signal for signal in signals)
    assert all(len(s["pixels"]) == 66 for s in signals)


def test_checkered_yellow_alternates_full_flags_on_six_and_mini():
    from ticker_core.features.racing.renderer import _pulse_flag
    signal = racing_signal("CHECKERED YELLOW", "wec")
    first, second = _pulse_flag(signal, 0), _pulse_flag(signal, 1)
    assert first["code"] == "CHECKERED" and second["code"] == "YELLOW"
    payload = mini_payload(game("imsa", "CHECKERED YELLOW"))
    signals = payload["content"]["racing"][0]["data"]["racing_display"]["signals"]
    combined = next(s for s in signals if s["code"] == "CHECKERED YELLOW")
    assert len(combined["pixels"]) == len(combined["alternate_pixels"]) == 66
    assert len(set(combined["pixels"])) == 2
    assert len(set(combined["alternate_pixels"])) == 1


def test_driver_flags_do_not_appear_and_car_only_track_flag_is_neutral():
    source = game("wec", "BLACK")
    source["wec"]["drivers"][0]["flag"] = "MEATBALL"
    signals = mini_payload(source)["content"]["racing"][0]["data"]["racing_display"]["signals"]
    assert [signal["code"] for signal in signals] == ["NONE"]


@pytest.mark.parametrize("flag", ["GREEN", "YELLOW", "RED FLAG", "CHECKERED", "SURFACE", "VSC", "FCY", "SLOW ZONE", "CODE60"])
def test_other_track_flags_remain_static(flag):
    from ticker_core.features.racing.renderer import _pulse_flag
    signal = racing_signal(flag, "wec")
    assert _pulse_flag(signal, 0) == _pulse_flag(signal, 1)
    mini = mini_payload(game("wec", flag))["content"]["racing"][0]["data"]["racing_display"]["signals"][0]
    assert mini["alternate_ms"] == 0


@pytest.mark.parametrize("code", ["VSC", "FCY", "CODE60", "SLOW ZONE", "NEXT SLOW"])
def test_fia_boards_use_a_readable_symbol_and_stay_static(code):
    from ticker_core.features.racing.renderer import _pulse_flag
    signal = racing_signal(code, "wec")
    assert _pulse_flag(signal, 0) == _pulse_flag(signal, 1)
    board = [racing_flag_pixel(signal, x, y, 11, 6) for y in range(6) for x in range(11)]
    assert (235, 235, 235) in board
    mini = mini_payload(game("wec", code))["content"]["racing"][0]["data"]["racing_display"]["signals"][0]
    assert (mini["width"], mini["height"], mini["alternate_ms"]) == (11, 6, 0)
    assert len(set(mini["pixels"])) >= 2


def test_double_yellow_has_two_opposed_diagonal_panels():
    signal = racing_signal("DOUBLE YELLOW", "wec")
    assert racing_flag_pixel(signal, 0, 0, 11, 6) == racing_flag_pixel(signal, 10, 5, 11, 6)
    assert racing_flag_pixel(signal, 0, 5, 11, 6) == racing_flag_pixel(signal, 10, 0, 11, 6)
    assert racing_flag_pixel(signal, 0, 0, 11, 6) != racing_flag_pixel(signal, 0, 5, 11, 6)


@pytest.mark.parametrize("code,pair", list(RACING_COMBINED_SIGNALS.items()))
def test_combined_signals_alternate_complete_indicators(code, pair):
    from ticker_core.features.racing.renderer import _pulse_flag
    signal = racing_signal(code, "wec")
    assert _pulse_flag(signal, 0)["code"] == pair[0]
    assert _pulse_flag(signal, 1)["code"] == pair[1]
    mini = mini_payload(game("wec", code))["content"]["racing"][0]["data"]["racing_display"]["signals"][0]
    assert mini["alternate_ms"] == 1000
    assert len(mini["pixels"]) == len(mini["alternate_pixels"]) == mini["width"] * mini["height"]
    assert mini["pixels"] != mini["alternate_pixels"]
    if pair[1] == "SAFETY CAR":
        assert len(mini["alternate_board_off_pixels"]) == mini["width"] * mini["height"]
        assert mini["alternate_board_off_pixels"] != mini["alternate_pixels"]
    if pair[1] == "VSC":
        assert mini["width"] == 11


@pytest.mark.parametrize("flag", ["GREEN", "YELLOW", "SURFACE", "CHECKERED", "VSC", "SAFETY CAR", "CHECKERED VSC"])
def test_mini_flag_matches_six_indicator_shape_and_pixels(flag):
    source = game("wec", flag)
    card = mini_payload(source)["content"]["racing"][0]["data"]["racing_display"]["signals"][0]
    component = RACING_COMBINED_SIGNALS.get(flag, (flag,))[0]
    signal = racing_signal(component, "wec")
    expected = []
    for y in range(6):
        for x in range(11):
            r, g, b = racing_flag_pixel(signal, x, y, 11, 6)
            expected.append(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    assert (card["width"], card["height"]) == (11, 6)
    assert card["pixels"] == expected


def test_fia_safety_car_board_flashes_only_the_letters():
    from ticker_core.features.racing.renderer import _pulse_flag
    signal = racing_signal("SAFETY CAR", "wec")
    on, off = _pulse_flag(signal, 0), _pulse_flag(signal, .5)
    first = [racing_flag_pixel(on, x, y, 11, 6) for y in range(6) for x in range(11)]
    second = [racing_flag_pixel(off, x, y, 11, 6) for y in range(6) for x in range(11)]
    assert (235, 235, 235) in first and (235, 235, 235) not in second
    assert first[0] == second[0] == (255, 215, 0)
    mini = mini_payload(game("wec", "SAFETY CAR"))["content"]["racing"][0]["data"]["racing_display"]["signals"][0]
    assert mini["alternate_ms"] == 500 and mini["pixels"] != mini["alternate_pixels"]
