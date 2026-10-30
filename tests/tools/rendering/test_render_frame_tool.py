import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "rendering"))

import render_frame  # noqa: E402

pytestmark = pytest.mark.critical


def airport_payload():
    item = json.loads((ROOT / "tests/fixtures/engine/flights_result.json").read_text(encoding="utf-8"))["result"]["content"][0]
    return {"content": {"airports": [
        {"id": item["id"], "family": item["family"], "kind": item["kind"], "is_shown": True, "data": item["data"]}]}}


def test_tool_prepares_items_like_the_six_protocol_model():
    [item] = render_frame.normalize_snapshot(airport_payload(), "airports")["content"]["items"]

    assert item["type"] == "flight_airport_hud"
    assert isinstance(item["arrivals"], list) and len(item["arrivals"]) == 4


def test_airport_board_draws_its_recorded_rows():
    snapshot = render_frame.normalize_snapshot(airport_payload(), "airports")
    empty = json.loads(json.dumps(snapshot))
    empty["content"]["items"][0].update(arrivals=[], departures=[])

    board = render_frame.render_snapshot(snapshot, "airports", prefetch=False)
    blank = render_frame.render_snapshot(empty, "airports", prefetch=False)

    assert board.size == (384, 32)
    lit = sum(1 for pixel in board.getdata() if pixel != (0, 0, 0))
    assert lit > sum(1 for pixel in blank.getdata() if pixel != (0, 0, 0)) + 500
