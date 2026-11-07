"""Keep the reviewed Mini class layout under the V2 racing contract."""
from copy import deepcopy

import pytest

from sports_ticker.projections.racing_display import racing_cards
from sports_ticker.providers.sports_display import racing_number_style
from tools.mini.racing_vectors import game, mini_payload

pytestmark = pytest.mark.critical


@pytest.mark.parametrize("sport,classes", [("f1", ["Race"]), ("indycar", ["Race"]), ("nascar", ["Race"]),
                                           ("wec", ["HY", "LMGT3"]), ("imsa", ["GTP", "LMP2", "GTD PRO", "GTD"])])
def test_mini_has_one_top_three_page_per_class(sport, classes):
    source = game(sport)
    before = deepcopy(source)
    payload = mini_payload(source)
    cards = [item["data"]["racing_display"] for item in payload["content"]["racing"]]
    assert [c["class_label"] for c in cards] == classes
    assert all(c["session_label"] == ("Race" if sport in {"wec", "imsa"} else "") for c in cards)
    assert all([row["position"] for row in card["rows"]] == [1, 2, 3] for card in cards)
    assert all([row["position_rgb"] for row in card["rows"]] == [[255, 215, 0], [192, 192, 192], [205, 127, 50]] for card in cards)
    assert source == before
    assert all("drivers" not in item["data"] and "car_illustration" not in item["data"] for item in payload["content"]["racing"])


def test_metric_values_and_colors_do_not_change_with_number_colors():
    source = game("nascar")
    for driver, speed in zip(source["nascar"]["drivers"], ("126.123", "125.456", "")):
        driver["speed"] = speed
    rows = racing_cards(source)[0]["rows"]
    assert [row["metric"] for row in rows] == ["126.123", "125.456", "--"]
    assert [row["compact_metric"] for row in rows] == ["126.123", "125.456", "--"]
    assert [row["metric_rgb"] for row in rows] == [[255, 215, 0], [180, 210, 255], [180, 210, 255]]
    assert [row["number_style"]["color_rgb"] for row in rows] == [[255, 255, 255], [245, 219, 27], [36, 109, 217]]
    assert rows[2]["number_style"]["outline_rgb"] == [255, 210, 80]


@pytest.mark.parametrize("sport", ["indycar", "nascar"])
@pytest.mark.parametrize("session,field", [("Qualifying", "best_time"), ("Race", "last_time")])
def test_track_shape_selects_reported_speed_or_lap_time(sport, session, field):
    source = game(sport)
    payload = source[sport]
    payload["session_name"] = session
    payload["drivers"][0].update(speed="120.123", best_time="1:10.100", last_time="1:12.300")
    payload["track_type"] = "OVAL"
    card = racing_cards(source)[0]
    assert card["metric_type"] == "mph" and card["rows"][0]["metric"] == "120.123"
    payload["track_type"] = "RC"
    card = racing_cards(source)[0]
    assert card["metric_type"] == "lap_time" and card["rows"][0]["metric"] == payload["drivers"][0][field]
    del payload["drivers"][0][field]
    assert racing_cards(source)[0]["rows"][0]["metric"] == "--"
    payload["track_type"] = ""
    assert racing_cards(source)[0]["metric_type"] == "unknown"
    assert racing_cards(source)[0]["rows"][0]["metric"] == "--"


def test_number_styles_preserve_season_class_and_leading_zero_identity():
    for sport, group, car in (("wec", "HYPERCAR", "8"), ("imsa", "LMP2", "04"), ("nascar", "", "45")):
        style = racing_number_style(sport, {"class": group, "car": car}, 2026)
        assert style["source"] != "unavailable"
        assert racing_number_style(sport, {"class": group, "car": car}, 2027)["source"] == "unavailable"
    assert racing_number_style("imsa", {"class": "LMP2", "car": "04"}, 2026) != racing_number_style("imsa", {"class": "LMP2", "car": "4"}, 2026)


def test_upcoming_session_has_no_white_or_green_flag():
    source = game("f1")
    source.update(state="pre", status="14:00")
    source["f1"]["drivers"] = []
    card = racing_cards(source)[0]
    assert not card["rows"]
    assert card["signals"][0]["code"] == "NONE"
    assert card["status"] == "14:00"


def test_le_mans_lmp2_card_sits_between_hypercar_and_lmgt3():
    source = game("wec")
    extra = deepcopy(source["wec"]["drivers"][:3])
    for driver in extra:
        driver["class"] = "LMP2"
        driver["pos"] += 6
    source["wec"]["drivers"].extend(extra)
    assert [card["class_label"] for card in racing_cards(source)] == ["HY", "LMP2", "LMGT3"]


def test_compact_status_preserves_the_lap_and_start_time_without_clipping_a_leading_digit():
    source = game("nascar")
    source["nascar"].update(lap=158, total_laps=312)
    assert racing_cards(source)[0]["status"] == "L158"
    source.update(state="pre", status="12:00 PM")
    assert racing_cards(source)[0]["status"] == "12:00P"


@pytest.mark.parametrize("sport", ["f1", "indycar", "nascar", "wec", "imsa"])
def test_mini_replaces_duplicate_session_status_with_live(sport):
    source = game(sport)
    source[sport].update(lap=0, total_laps=0, time_to_go="", session_name="Race")
    cards = [item["data"]["racing_display"] for item in mini_payload(source)["content"]["racing"]]
    assert all(card["status"] == "LIVE" for card in cards)
    source[sport].update(lap=65, total_laps=200)
    cards = [item["data"]["racing_display"] for item in mini_payload(source)["content"]["racing"]]
    assert all(card["status"] == "65/200" for card in cards)


def test_mini_keeps_remaining_time_and_final_status():
    source = game("wec")
    source["wec"].update(lap=0, total_laps=0, time_to_go="45:00")
    cards = [item["data"]["racing_display"] for item in mini_payload(source)["content"]["racing"]]
    assert all(card["status"] == "45:00" for card in cards)
    source["state"] = "post"
    cards = [item["data"]["racing_display"] for item in mini_payload(source)["content"]["racing"]]
    assert all(card["status"] == "FINAL" for card in cards)


@pytest.mark.parametrize("label", ["Q1", "Q2", "Q3", "SQ1", "SQ2", "SQ3"])
def test_qualifying_rounds_keep_the_session_label_and_timed_state(label):
    source = game("f1")
    source["f1"].update(session_name=label, session_type=label, lap=0, total_laps=0, time_to_go="9:42")
    card = racing_cards(source)[0]
    assert card["class_label"] == label
    assert card["timed"] is True
    mini = mini_payload(source)["content"]["racing"][0]["data"]["racing_display"]
    assert mini["class_label"] == label and mini["status"] == "9:42"


def test_nascar_track_classification_and_recorded_race_lap_time():
    from sports_ticker.providers.racing_cup import _track_type
    from sports_ticker.providers.racing_live import _nascar_driver
    assert _track_type({'track_id': 214}) == 'ROAD'
    assert _track_type({'track_id': 84}) == 'OVAL'
    assert _track_type({'track_id': 162, 'race_name': 'Bank of America Roval 400'}) == 'ROAD'
    assert _track_type({'track_id': 162}) == ''
    assert _track_type({'track_id': 999}) == ''
    driver = _nascar_driver({'running_position': 1, 'last_lap_time': 103.425})
    assert driver['last_time'] == '1:43.425'


def test_indycar_keeps_last_lap_time_for_road_races():
    from sports_ticker.providers.racing_live import _indycar_driver
    driver = _indycar_driver({'rank': 1, 'no': '10', 'lastLapTime': '1:14.2024'}, {}, 'Race', 'RC')
    assert driver['last_time'] == '1:14.2024'
