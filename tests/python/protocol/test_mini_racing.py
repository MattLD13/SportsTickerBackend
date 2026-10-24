"""Keep the reviewed Mini class layout under the V2 racing contract."""
from copy import deepcopy

import pytest

from sports_ticker.projections.racing_display import racing_cards
from sports_ticker.providers.sports_display import racing_number_style
from tools.mini.racing_vectors import game, mini_payload

pytestmark = pytest.mark.critical


@pytest.mark.parametrize("sport,classes", [("f1", ["F1"]), ("indycar", ["INDY"]), ("nascar", ["CUP"]),
                                           ("wec", ["HY", "LMGT3"]), ("imsa", ["GTP", "LMP2", "GTD PRO", "GTD"])])
def test_mini_has_one_top_three_page_per_class(sport, classes):
    source = game(sport)
    before = deepcopy(source)
    payload = mini_payload(source)
    cards = [item["data"]["racing_display"] for item in payload["content"]["racing"]]
    assert [c["class_label"] for c in cards] == classes
    assert all([row["position"] for row in card["rows"]] == [1, 2, 3] for card in cards)
    assert all([row["position_rgb"] for row in card["rows"]] == [[255, 215, 0], [192, 192, 192], [205, 127, 50]] for card in cards)
    assert source == before
    assert all("drivers" not in item["data"] and "car_illustration" not in item["data"] for item in payload["content"]["racing"])


def test_metric_values_and_colors_do_not_change_with_number_colors():
    source = game("nascar")
    rows = racing_cards(source)[0]["rows"]
    assert [row["metric"] for row in rows] == ["Leader", "+0.801s", "+2.924s"]
    assert [row["compact_metric"] for row in rows] == ["LEAD", "+0.801s", "+2.924s"]
    assert [row["metric_rgb"] for row in rows] == [[255, 215, 0], [180, 210, 255], [180, 210, 255]]
    assert [row["number_style"]["color_rgb"] for row in rows] == [[255, 255, 255], [245, 219, 27], [36, 109, 217]]
    assert rows[2]["number_style"]["outline_rgb"] == [255, 210, 80]


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
