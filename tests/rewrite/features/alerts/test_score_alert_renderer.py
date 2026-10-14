"""Verify score-alert facts, down colors, and baseball inning markers."""

from PIL import Image

from ticker_core.features.alerts.score_alert_port import (
    PreparedScoreAlertRenderer,
    _score_alert_fact_layout,
    score_alert_duration,
)
from ticker_core.features.alerts.news_banner_port import PreparedNewsBannerRenderer
from ticker_core.rendering import load_default_font_set


def test_news_banner_cache_reuses_pixels_and_keeps_animation_output() -> None:
    renderer = PreparedNewsBannerRenderer()
    item = {
        "kind": "TRADE",
        "from_abbr": "VAN",
        "to_abbr": "NYR",
        "from_color": "#00843D",
        "to_color": "#C8102E",
        "text": "Miller for Kakko",
    }
    base = Image.new("RGB", (384, 32), (12, 20, 28))
    banner = renderer.draw_news_banner(item)

    assert renderer.draw_news_banner(dict(item)) is banner
    for elapsed in (0.0, 0.15, 0.30, 2.0, 6.7):
        actual = renderer.apply_news_banner(base, item, elapsed)
        expected = PreparedNewsBannerRenderer().apply_news_banner(base, item, elapsed)
        assert actual.tobytes() == expected.tobytes()

    changed = {**item, "to_color": "#00A3E0"}
    changed_banner = renderer.draw_news_banner(changed)
    assert changed_banner is not banner
    assert changed_banner.tobytes() != banner.tobytes()


class EmptyLogos:
    """Provide deterministic missing logos."""

    def get(self, url, size):
        del url, size
        return None


def test_baseball_alert_shows_top_bottom_and_mid_inning_markers() -> None:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())

    assert renderer._alert_status_label({"sport": "mlb", "status": "Top 7th"}) == ("▲", "7")
    assert renderer._alert_status_label({"sport": "mlb", "status": "Bottom 7th"}) == ("▼", "7")
    assert renderer._alert_status_label({"sport": "mlb", "status": "Mid 7th"}) == ("-", "7")


def test_baseball_alert_keeps_final_status_without_an_inning_marker() -> None:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())

    assert renderer._alert_status_label({"sport": "mlb", "status": "Final"}) == ("", "FINAL")


def test_score_alert_render_duration_matches_runtime_residence() -> None:
    assert score_alert_duration({"big": False}) == 8.0
    assert score_alert_duration({"big": True}) == 8.0


def test_score_alert_groups_labeled_hockey_assists_in_a_separate_box() -> None:
    alert = {
        "player": "Artemi Panarin",
        "primary_assist": "Adam Fox",
        "secondary_assist": "Mika Zibanejad",
    }

    layout = _score_alert_fact_layout(alert, 42, 283)

    assert [kind for kind, _, _, _ in layout] == [
        "player", "assists",
    ]
    assert [value for _, value, _, _ in layout] == [
        "ARTEMI PANARIN", "ASSISTS: FOX, ZIBANEJAD",
    ]
    assert all(x + width <= 283 for _, _, x, width in layout)
    assert all(
        current[2] >= previous[2] + previous[3]
        for previous, current in zip(layout, layout[1:])
    )
    single = _score_alert_fact_layout({"primary_assist": "Adam Fox"}, 42, 283)
    assert single[0][1] == "ASSIST: FOX"


def test_score_alert_places_football_down_distance_in_its_own_chip() -> None:
    layout = _score_alert_fact_layout({
        "headline": "FIELD GOAL",
        "player": "Daniel Jones",
        "data": "50YD FIELD GOAL",
        "down_distance": "4&7",
    }, 42, 283)

    assert [kind for kind, _, _, _ in layout] == ["player", "data"]
    assert [value for _, value, _, _ in layout] == ["DANIEL JONES", "50YD"]
    assert layout[-1][2] + layout[-1][3] <= 283


def test_score_alert_long_facts_keep_every_box_inside_the_center_panel() -> None:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())
    cases = (
        {
            "player": "Ryan Nugent-Hopkins",
            "primary_assist": "Leon Draisaitl",
            "secondary_assist": "Connor McDavid",
        },
        {
            "player": "Alexandra Verylonghyphenatedsurname",
            "data": "468FT 115EV 30LA",
            "primary_assist": "Christopher Anotherlonghyphenatedsurname",
            "secondary_assist": "Alexander Thirdlonghyphenatedsurname",
        },
    )
    for facts in cases:
        alert = {
            "headline": "GOAL", "sport": "nhl", "status": "P3 02:00",
            "team_abbr": "EDM", "team_color": "#041E42", "team_alt_color": "#FF4C00",
            "home_abbr": "EDM", "away_abbr": "VAN", "home_score": 3, "away_score": 2,
            **facts,
        }
        layout = _score_alert_fact_layout(alert, 42, 283)
        assert [kind for kind, _, _, _ in layout] == [
            "player", *(["data"] if facts.get("data") else []), "assists",
        ]
        assert layout[-1][1].startswith("ASSISTS: ")
        assert ", " in layout[-1][1]
        assert all(value and x >= 42 and x + width <= 283 for _, value, x, width in layout)
        assert all(
            current[2] >= previous[2] + previous[3] + 2
            for previous, current in zip(layout, layout[1:])
        )
        frame = renderer.draw_score_alert(alert, 2.0)
        empty = renderer.draw_score_alert({**alert, **dict.fromkeys(facts, "")}, 2.0)
        for bounds in ((0, 0, 38, 32), (286, 0, 384, 32)):
            assert frame.crop(bounds).tobytes() == empty.crop(bounds).tobytes()


def test_score_alert_colors_down_distance_red_inside_the_red_zone() -> None:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())
    alert = {
        "headline": "RUSH TD",
        "sport": "ncf_fcs",
        "status": "Q1 08:29",
        "player": "Luke Yoder",
        "data": "RUSH 1YD",
        "down_distance": "2&1",
        "is_red_zone": True,
        "team_abbr": "LEH",
        "team_color": "#4B2E83",
        "home_abbr": "LEH",
        "away_abbr": "DAR",
        "home_score": 7,
        "away_score": 0,
    }

    frame = renderer.draw_score_alert(alert, 2.0)

    assert frame.size == (384, 32)
    assert frame.getbbox() == (0, 0, 384, 32)
    corner = frame.crop((350, 23, 384, 32))
    colors = {color for _, color in corner.convert("RGB").getcolors(34 * 9)}
    assert (255, 91, 104) in colors
    assert (69, 220, 120) not in colors


def test_score_alert_colors_down_distance_green_outside_the_red_zone() -> None:
    renderer = PreparedScoreAlertRenderer(load_default_font_set(), EmptyLogos())
    alert = {
        "headline": "RUSH TD",
        "sport": "ncf_fcs",
        "status": "Q1 08:29",
        "player": "Luke Yoder",
        "data": "RUSH 1YD",
        "down_distance": "2&1",
        "is_red_zone": False,
        "team_abbr": "LEH",
        "team_color": "#4B2E83",
        "team_alt_color": "#D3D3D3",
        "home_abbr": "LEH",
        "away_abbr": "DAR",
        "home_score": 7,
        "away_score": 0,
    }

    frame = renderer.draw_score_alert(alert, 2.0)
    corner = frame.crop((350, 23, 384, 32))
    colors = {color for _, color in corner.convert("RGB").getcolors(34 * 9)}

    assert (69, 220, 120) in colors
    assert (255, 91, 104) not in colors


def test_score_alert_fact_boxes_keep_one_assist_label_without_repeating_the_headline() -> None:
    alert = {
        "headline": "FUMBLE TD",
        "player": "Tae Crowder",
        "data": "FUMBLE 43YD RET",
        "primary_assist": "Sam Carrick",
        "secondary_assist": "Adam Fox",
    }

    layout = _score_alert_fact_layout(alert, 42, 283)

    assert [kind for kind, _, _, _ in layout] == [
        "player", "data", "assists",
    ]
    assert [value for _, value, _, _ in layout] == [
        "TAE CROWDER", "43YD RET", "ASSISTS: CARRICK, FOX",
    ]


def test_sports_news_kinds_use_distinct_banner_accents() -> None:
    renderer = PreparedNewsBannerRenderer()
    colors = [
        renderer.draw_news_banner({
            "kind": kind,
            "from_abbr": "VAN",
            "to_abbr": "NYR",
            "text": "ACQUIRE PLAYER",
        }).getpixel((0, 0))
        for kind in ("TRADE", "SIGNING", "EXTENSION", "INJURY")
    ]

    assert len(set(colors)) == 4
