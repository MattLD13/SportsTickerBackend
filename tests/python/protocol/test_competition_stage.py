"""Keep tournament rounds explicit across provider and device boundaries."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.projections import project_data_v2
from sports_ticker.projections.device_data import project_device_data
from sports_ticker.providers.espn import _content_item
from sports_ticker.providers.fotmob import _content_item as soccer_item
from sports_ticker.providers.sports_display import SportsDisplayProjector, espn_competition_stage
from ticker_core.protocol import PayloadValidationError, TickerResponse


ROUNDS = json.loads((Path(__file__).parents[2] / "fixtures/providers/postseason_rounds.json").read_text(encoding="utf-8"))
pytestmark = pytest.mark.critical


@pytest.mark.parametrize("case", ROUNDS, ids=lambda case: case["name"])
@pytest.mark.parametrize("state", ("pre", "in", "post"))
def test_recorded_round_survives_snapshot_and_both_device_projections(case, state):
    event = deepcopy(case["event"])
    event["status"]["type"]["state"] = state
    item = SportsDisplayProjector().project(_content_item(case["sport"], event), event)
    snapshot = TickerSnapshot("rounds", 1, datetime(2026, 10, 23, tzinfo=timezone.utc),
                              (item,), (), (), DisplaySettings())
    payload = project_data_v2(snapshot, {}, {})
    for mini in (False, True):
        device = project_device_data(payload, mini=mini)
        parsed = TickerResponse.from_payload(device)
        assert parsed.content[0].data["competition_stage"] == case["expected"]
        assert type(parsed.content[0].data["competition_stage"]) is int


@pytest.mark.parametrize("headline", (
    "East Finals - Game 1", "Western Conference Finals - Game 7", "AFC Championship",
    "National Championship - Semifinal", "Men's Basketball Championship - Final Four",
    "Men's Basketball Championship - Midwest Region - 1st Round",
))
def test_earlier_rounds_override_a_generic_final_type(headline):
    event = {"competitions": [{"type": {"abbreviation": "FINAL"}, "notes": [{"headline": headline}]}]}
    assert espn_competition_stage(event) == 1


def test_final_result_and_recap_do_not_change_a_regular_season_round():
    event = {"season": {"type": 2}, "status": {"type": {"state": "post", "description": "Final"}},
             "competitions": [{"headlines": [{"description": "A rematch of the NBA Finals"}]}]}
    assert espn_competition_stage(event) == 0


@pytest.mark.parametrize("stage,expected", (("final", 2), ("1/2", 1),
    ("1/4", 1), ("round of 16", 1), ("38", 0)))
def test_soccer_uses_tournament_metadata_instead_of_full_time(stage, expected):
    match = {"id": 1, "tournamentStage": stage, "status": {"finished": True, "reason": {"short": "FT"}}}
    item = soccer_item("soccer_champions_league", match, None, timezone_name="UTC")
    assert item.data["competition_stage"] == expected


def test_soccer_detail_round_is_available_when_the_match_omits_it():
    item = soccer_item("soccer_fa_cup", {"id": 1}, {"general": {"matchRound": "final"}}, timezone_name="UTC")
    assert item.data["competition_stage"] == 2


@pytest.mark.parametrize("stage", ("playoff", "1", True, False, 1.0, -1, 3))
def test_pi_rejects_noncontract_competition_stages(stage):
    from sports_ticker.domain import ContentItem

    snapshot = TickerSnapshot("rounds", 1, datetime(2026, 10, 23, tzinfo=timezone.utc),
                              (ContentItem("game", "sports", "scoreboard", True, {"sport": "nhl"}),),
                              (), (), DisplaySettings())
    payload = project_data_v2(snapshot, {}, {})
    payload["content"]["sports"][0]["data"]["competition_stage"] = stage
    with pytest.raises(PayloadValidationError, match="competition_stage"):
        TickerResponse.from_payload(payload)
