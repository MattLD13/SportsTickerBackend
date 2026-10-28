"""Verify recorded football player identities through the V2 alert boundary."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.domain import ContentItem, DisplaySettings, TickerSnapshot
from sports_ticker.projections.data_api import project_data_v2
from sports_ticker.providers.espn_details import _event_scoring_details, _event_football_details
from sports_ticker.providers.score_alerts import ScoreAlertTracker, alerts_for_settings
from ticker_core.protocol import TickerResponse


pytestmark = pytest.mark.critical


def test_recorded_turnover_players_keep_their_names_and_teams_in_v2_alerts() -> None:
    path = Path(__file__).parents[2] / "fixtures/display" / "football_turnover_names.json"
    for case in json.loads(path.read_text(encoding="utf-8")):
        payload = case["payload"]
        competitors = payload["header"]["competitions"][0]["competitors"]
        abbreviations = {c["homeAway"]: c["team"]["abbreviation"] for c in competitors}
        raw = next(iter(payload.get("plays") or payload["scoringPlays"]))
        data = {
            "sport": case["sport"], "state": "in",
            "home_abbr": abbreviations["home"], "away_abbr": abbreviations["away"],
            "home_score": raw["homeScore"], "away_score": raw["awayScore"],
            "status": f"Q{raw['period']['number']} {raw['clock']['displayValue']}",
        }
        details = _event_scoring_details(payload, data)
        details.update(_event_football_details(payload, data))
        turnover = details["football_plays"][0]
        assert turnover["scorer_full"] == case["player"]
        assert turnover["team"] == case["team"]
        game = {"kind": "scoreboard", "id": case["event_id"], **data, "situation": details}
        baseline = {**game, "situation": {"football_plays": []}}
        if turnover["is_scoring"]:
            side = "home" if case["team"] == data["home_abbr"] else "away"
            points = 6 + int(raw.get("pointAfterAttempt", {}).get("value") or 0)
            baseline[f"{side}_score"] -= points
        tracker = ScoreAlertTracker(clock=lambda: 100.0)
        tracker.ingest([baseline])
        tracker.ingest([game])
        tracker.ingest([game])
        settings = DisplaySettings(mode="sports", score_alerts=True, my_teams=(f"{case['sport']}:{case['team']}",))
        alerts = alerts_for_settings(tracker.recent(), settings)
        assert len(alerts) == 1, case["play_id"]
        snapshot = TickerSnapshot(
            "name-review", 1, datetime.now(timezone.utc),
            (ContentItem(case["event_id"], "sports", "scoreboard", True, data),),
            alerts, (), settings,
        )
        response = TickerResponse.from_payload(project_data_v2(snapshot, {}, {}))
        alert = response.alerts[0].data
        assert alert["kind"] == turnover["football_kind"] + ("_td" if turnover["is_scoring"] else "")
        assert alert["player"] == case["player"]
        assert alert["team_abbr"] == case["team"]
