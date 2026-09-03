import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.live_sources import EspnNewsSource

pytestmark = pytest.mark.critical


class SequenceClient:
    def __init__(self, values):
        self.values = iter(values)

    def get_json(self, url, *, timeout):
        del timeout
        if "/summary" in url:
            return {}
        return next(self.values)


def _scoreboard(score):
    return {
        "events": [
            {
                "id": "game-1",
                "status": {"type": {"state": "in", "shortDetail": "Q3 08:12"}},
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "score": str(score), "team": {"id": "1", "abbreviation": "NYG", "color": "0B2265", "alternateColor": "A71930"}},
                            {"homeAway": "away", "score": "7", "team": {"id": "2", "abbreviation": "DAL", "color": "041E42", "alternateColor": "869397"}},
                        ]
                    }
                ],
            }
        ]
    }


def test_espn_score_change_enters_the_v2_alert_channel():
    provider = EspnScoreboardProvider(
        {"nfl": "https://example.test/nfl"},
        client=SequenceClient([_scoreboard(7), _scoreboard(14)]),
    )
    settings = DisplaySettings(my_teams=("nfl:NYG",))

    assert provider.fetch(settings).alerts == ()
    alerts = provider.fetch(settings).alerts

    assert len(alerts) == 1
    assert alerts[0]["team_abbr"] == "NYG"
    assert alerts[0]["headline"] == "TOUCHDOWN"
    assert alerts[0]["home_score"] == 14


class NewsClient:
    def get_json(self, url, *, timeout):
        del url, timeout
        return {
            "articles": [
                {
                    "id": "article-1",
                    "type": "HeadlineNews",
                    "headline": "New Jersey Devils trade for Predators forward Evangelista",
                    "categories": [
                        {"type": "team", "team": {"abbreviation": "NJD", "displayName": "New Jersey Devils"}},
                        {"type": "team", "team": {"abbreviation": "NSH", "displayName": "Nashville Predators"}},
                        {"type": "athlete", "description": "Luke Evangelista"},
                    ],
                },
                {
                    "id": "article-2",
                    "type": "HeadlineNews",
                    "headline": "Sources: Rockets' Amen Thompson agrees to 5-year extension",
                    "categories": [
                        {"type": "team", "team": {"abbreviation": "HOU", "displayName": "Houston Rockets"}},
                        {"type": "athlete", "description": "Amen Thompson"},
                    ],
                },
                {
                    "id": "article-3",
                    "type": "HeadlineNews",
                    "headline": "Pirates rookie Konnor Griffin eyes Friday return from 60-day IL",
                    "categories": [
                        {"type": "team", "team": {"abbreviation": "PIT", "displayName": "Pittsburgh Pirates"}},
                        {"type": "athlete", "description": "Konnor Griffin"},
                    ],
                },
                {
                    "id": "article-4",
                    "type": "HeadlineNews",
                    "headline": "Blues name Thomas captain despite last season's trade rumors",
                    "categories": [
                        {"type": "team", "team": {"abbreviation": "STL", "displayName": "St. Louis Blues"}},
                        {"type": "athlete", "description": "Robert Thomas"},
                    ],
                },
                {
                    "id": "article-5",
                    "type": "Story",
                    "headline": "Fantasy football trade updates and rankings",
                    "categories": [
                        {"type": "team", "team": {"abbreviation": "NYG", "displayName": "New York Giants"}},
                        {"type": "athlete", "description": "Cam Skattebo"},
                    ],
                },
                {
                    "id": "article-6",
                    "type": "HeadlineNews",
                    "headline": "Giants' Cam Skattebo says he mulled retiring after 2025 injury",
                    "categories": [
                        {"type": "team", "team": {"abbreviation": "NYG", "displayName": "New York Giants"}},
                        {"type": "athlete", "description": "Cam Skattebo"},
                    ],
                },
            ]
        }


def test_espn_news_source_produces_half_panel_payload_for_followed_team():
    source = EspnNewsSource(
        {"nhl": "https://example.test/nhl/news"},
        client=NewsClient(),
        background=False,
    )
    records = source.fetch(
        DisplaySettings(my_teams=("nhl:NJD", "nhl:HOU", "nhl:PIT", "nhl:STL"))
    )

    assert [record["kind"] for record in records["news"]] == ["TRADE", "EXTENSION", "INJURY"]
    assert records["news"][0]["domain"] == "sports"
    assert records["news"][0]["from_abbr"] == "NSH"
    assert records["news"][0]["to_abbr"] == "NJD"
    assert records["news"][0]["text"] == "ACQUIRE Luke Evangelista"
    assert records["news"][1]["to_abbr"] == "HOU"
    assert records["news"][1]["text"] == "EXTENSION Amen Thompson"
    assert records["news"][2]["kind"] == "INJURY"
