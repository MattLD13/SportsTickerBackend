"""Verify NHL live situation acquisition."""

import pytest

from sports_ticker.domain import ContentItem
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.nhl_live import NhlLiveSituationSource


class NhlClient:
    def __init__(self) -> None:
        self.live_games = [
            {
                "id": 2026010001,
                "gameState": "LIVE",
                "awayTeam": {"abbrev": "NYR"},
                "homeTeam": {"abbrev": "NYI"},
            },
            {
                "id": 2026010002,
                "gameState": "FUT",
                "awayTeam": {"abbrev": "BOS"},
                "homeTeam": {"abbrev": "TOR"},
            },
        ]

    def get_json(self, url: str, *, timeout: float):
        del timeout
        if url.endswith("/score/now"):
            return {"games": self.live_games}
        assert url.endswith("/2026010001/play-by-play")
        return {
            "plays": [
                {"sortOrder": 10, "situationCode": "1551"},
                {"sortOrder": 20, "situationCode": "1451"},
            ],
            "summary": {
                "iceSurface": {
                    "awayTeam": {"penaltyBox": [{"playerId": 1}]},
                    "homeTeam": {"penaltyBox": []},
                }
            },
        }


def test_live_nhl_feed_reads_latest_situation_and_penalty_box() -> None:
    source = NhlLiveSituationSource(client=NhlClient(), background=False)

    assert source.snapshot() == {
        ("NYR", "NYI"): {
            "situationCode": "1451",
            "awayPenaltyBoxCount": 1,
            "homePenaltyBoxCount": 0,
        }
    }


def test_live_nhl_feed_drops_games_that_are_no_longer_live() -> None:
    client = NhlClient()
    source = NhlLiveSituationSource(client=client, background=False)

    assert ("NYR", "NYI") in source.snapshot()
    client.live_games = []

    assert source.snapshot() == {}


@pytest.mark.critical
def test_live_situation_enrichment_supplies_renderer_team_without_possession() -> None:
    class SituationSource:
        def snapshot(self):
            return {
                ("NYR", "NYI"): {
                    "situationCode": "1541",
                    "awayPenaltyBoxCount": 0,
                    "homePenaltyBoxCount": 1,
                }
            }

    provider = EspnScoreboardProvider(
        {"nhl": "https://example.test/hockey/nhl/scoreboard"},
        nhl_situation_source=SituationSource(),
    )
    item = ContentItem(
        "hockey-live",
        "sports",
        "scoreboard",
        True,
        {
            "sport": "nhl",
            "state": "in",
            "status": "P2 8:00",
            "away_abbr": "NYR",
            "home_abbr": "NYI",
            "situation": {"powerPlay": False, "powerPlayTeam": "NYI"},
        },
    )

    enriched = provider._enrich_live_items((item,), suppressed_update_ids={("nhl", item.id)})[0]

    assert enriched.data["situation"]["powerPlay"] is True
    assert enriched.data["situation"]["powerPlayTeam"] == "NYR"
    assert "possession" not in enriched.data["situation"]
