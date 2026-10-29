import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ticker3.contract.records import validate_record
from ticker3.contract.templates import shown
from ticker3.core.builtin import BUILTINS
from ticker3.features import racing, sports, weather
from ticker3.player import draw_frame, draw_screen, fonts, text_extent, text_width

pytestmark = pytest.mark.critical

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ticker3"
NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc).timestamp()
PANELS = {"w384h32": (384, 32), "w64h32": (64, 32)}


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def sample_screens():
    """Return (template, values) for every record that the features make from the recorded payloads."""
    found = []
    templates = {template["id"]: template for module in (weather, sports, racing) for template in module.MANIFEST["templates"]}
    templates.update({template["id"]: template for template in BUILTINS["clock"].manifest["templates"]})
    records = weather.records(fixture("openmeteo_nyc_2026-10-29.json"), {"units": "f"})
    for league in ("nfl", "nba", "mlb"):
        records += sports.records(fixture(f"espn_{league}_2026-10-29.json"), league)
    session = racing.records(fixture("jolpica_f1_2026.json"), datetime.fromtimestamp(NOW, timezone.utc))
    session[0]["values"].pop("weather")
    session[0]["values"].update({f"weather.{key}": value for key, value in records[0]["values"].items()})
    records += session
    live = fixture("espn_nfl_2026-10-29.json")
    live["events"][0]["status"] = {"period": 3, "displayClock": "8:12", "type": {"state": "in"}}
    live["events"][0]["competitions"][0]["situation"] = {"possession": live["events"][0]["competitions"][0]["competitors"][1]["id"],
                                                        "shortDownDistanceText": "3rd & 10"}
    records += sports.records(live, "nfl")[:1]
    records += BUILTINS["clock"].records({"timezone": "America/New_York", "format": "12h"})
    for record in records:
        validate_record(record)
        values = {key: value for key, value in record["values"].items() if not isinstance(value, dict)}
        values.update({"ticker.tz": "America/New_York", "app.color": "#ffffff", "app.label": "NEW YORK"})
        found.append((templates[record["template"]], values))
    return found


def test_glyphs_draw_their_bits_and_alignment_moves_text():
    block = {"box": [64, 32], "flow": "page", "parts": [{"part": "text", "at": [0, 0], "font": "tiny", "value": "8"}]}
    image = draw_screen(block, {}, now=NOW)
    lit = sum(1 for x in range(64) for y in range(32) if image.getpixel((x, y)) != (0, 0, 0))
    assert lit == sum(bin(row).count("1") for row in fonts()["tiny"]["glyphs"]["8"]["bits"]) > 0
    right = draw_screen({**block, "parts": [{**block["parts"][0], "at": [63, 0], "align": "right"}]}, {}, now=NOW)
    columns = [x for x in range(64) for y in range(32) if right.getpixel((x, y)) != (0, 0, 0)]
    assert max(columns) <= 63 and min(columns) >= 63 - text_width("tiny", "8")


def test_show_rules_hide_parts_and_missing_values_draw_nothing():
    block = {"box": [64, 32], "flow": "page", "parts": [
        {"part": "text", "at": [0, 0], "font": "tiny", "value": "{down}", "show_when": "down"},
        {"part": "rect", "at": [0, 20], "size": [4, 4], "color": "#ff0000", "show_when": "sport == baseball"}]}
    assert draw_screen(block, {"sport": "football"}, now=NOW).getbbox() is None
    assert draw_screen(block, {"sport": "baseball"}, now=NOW).getbbox() == (0, 20, 4, 24)


def test_scroll_screens_join_into_one_strip():
    block = {"box": [96, 32], "flow": "scroll", "parts": [{"part": "rect", "at": [0, 0], "size": [1, 32], "color": "#ffffff"}]}
    frame = draw_frame("w384h32", [(block, {})] * 5, now=NOW, offset=10)
    lit = [x for x in range(384) if frame.getpixel((x, 0)) != (0, 0, 0)]
    assert lit == [86, 182, 278, 374]


def test_time_and_clock_use_the_ticker_zone():
    starts = int(datetime(2026, 10, 30, 0, 15, tzinfo=timezone.utc).timestamp())
    part = {"part": "time", "at": [0, 0], "font": "tiny", "value": "{starts}", "tz": "{ticker.tz}", "format": "weekday_time"}
    left, right = text_extent(part, {"starts": starts, "ticker.tz": "America/New_York"}, now=NOW)
    assert right - left == text_width("tiny", "THU 8:15P")
    left, right = text_extent({**part, "format": "date"}, {"starts": starts, "ticker.tz": "Asia/Tokyo"}, now=NOW)
    assert right - left == text_width("tiny", "OCT 30")


@pytest.mark.parametrize("panel", PANELS)
def test_text_stays_inside_each_box_for_every_recorded_screen(panel):
    for template, values in sample_screens():
        block = template["panels"].get(panel)
        if block is None:
            continue
        for part in block["parts"]:
            if not shown(part.get("show_when"), values):
                continue
            extent = text_extent(part, values, now=NOW)
            if extent is not None:
                assert 0 <= extent[0] and extent[1] <= block["box"][0], (template["id"], panel, part["value"], extent)


@pytest.mark.parametrize("panel", PANELS)
def test_sports_text_never_covers_a_logo(panel):
    for template, values in sample_screens():
        if template["id"] != "sports.card":
            continue
        block = template["panels"][panel]
        image = draw_screen(block, values, now=NOW)
        for part in block["parts"]:
            if part["part"] == "logo":
                (x, y), size = part["at"], part["size"]
                assert image.crop((x, y, x + size, y + size)).getbbox() is None, (panel, values.get("status"), part["value"])
