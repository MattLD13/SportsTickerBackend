"""Verify shootout wins from ESPN records through the V2 alert contract."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.projections.data_api import project_data_v2
from sports_ticker.providers.espn import _content_item
from sports_ticker.providers.score_alerts import ScoreAlertTracker, alerts_for_settings
from sports_ticker.providers.sports_display import SportsDisplayProjector
from ticker_core.protocol import TickerResponse


pytestmark = pytest.mark.critical


def test_hockey_shootout_winner_reaches_the_v2_alert_contract_once() -> None:
    # ESPN event 401802398 records Minnesota's 4-3 shootout win on October 13, 2025.
    path = Path(__file__).parents[1] / "debug" / "nhl_shootout_final.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))
    cases = (
        ("home", False, False, "Final/SO", 1),
        ("away", False, False, "Final/SO", 1),
        ("home", True, False, "Final/SO", 1),
        ("home", False, True, "Final/SO", 0),
        ("home", False, False, "Final/OT", 0),
        ("home", False, False, "Final", 0),
    )
    for winner, score_before_final, cold_start, detail, expected_count in cases:
        event = deepcopy(recorded)
        event["status"]["type"].update(shortDetail=detail, detail=detail, altDetail=detail)
        for competitor in event["competitions"][0]["competitors"]:
            won = competitor["homeAway"] == winner
            competitor.update(winner=won, score="4" if won else "3")
        projector = SportsDisplayProjector()
        final = projector.project(_content_item("nhl", event), event)
        tracker = ScoreAlertTracker(clock=lambda: 100.0)
        if not cold_start:
            live_event = deepcopy(event)
            live_event["status"]["type"].update(
                state="in", completed=False, shortDetail="Shootout", detail="Shootout", altDetail="SO"
            )
            for competitor in live_event["competitions"][0]["competitors"]:
                competitor.update(winner=False, score="3")
            live = projector.project(_content_item("nhl", live_event), live_event)
            tracker.ingest([{"kind": live.kind, "id": live.id, **live.data}])
            if score_before_final:
                for competitor in live_event["competitions"][0]["competitors"]:
                    competitor["score"] = "4" if competitor["homeAway"] == winner else "3"
                live = projector.project(_content_item("nhl", live_event), live_event)
                tracker.ingest([{"kind": live.kind, "id": live.id, **live.data}])
                assert tracker.recent() == ()
        game = {"kind": final.kind, "id": final.id, **final.data}
        tracker.ingest([game])
        tracker.ingest([game])
        alerts = tracker.recent()
        assert len(alerts) == expected_count
        if detail != "Final/SO":
            assert final.data["situation"]["shootout_state"] == "none"
            assert final.data["status"] != "FINAL S/O"
        if not expected_count:
            continue
        team = final.data[f"{winner}_abbr"]
        opponent = final.data["away_abbr" if winner == "home" else "home_abbr"]
        settings = DisplaySettings(mode="sports", score_alerts=True, my_teams=(f"nhl:{team}",))
        assert alerts_for_settings(alerts, settings) == alerts
        assert alerts_for_settings(alerts, DisplaySettings(my_teams=(f"nhl:{opponent}",))) == ()
        assert alerts_for_settings(alerts, DisplaySettings(score_alerts=False, my_teams=(f"nhl:{team}",))) == ()
        snapshot = TickerSnapshot(
            ticker_id="shootout-preview", revision=1, observed_at=datetime.now(timezone.utc),
            content=(final,), alerts=alerts, news=(), effective_settings=settings,
        )
        response = TickerResponse.from_payload(project_data_v2(snapshot, {}, {}))
        alert = response.alerts[0].data
        assert alert["kind"] == "shootout_winner"
        assert alert["headline"] == "SHOOTOUT WINNER"
        assert alert["side"] == winner
        assert alert["team_abbr"] == team
        assert alert["status"] == "FINAL S/O"
        assert alert["points"] == 1
        assert alert["big"] is True
        assert all(alert[key] == "" for key in ("player", "data", "primary_assist", "secondary_assist"))
        assert sorted((alert["home_score"], alert["away_score"])) == [3, 4]
