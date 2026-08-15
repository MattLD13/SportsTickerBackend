from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.espn import EspnScoreboardProvider
from sports_ticker.providers.live_sources import EspnNewsSource


class SequenceClient:
    def __init__(self, values):
        self.values = iter(values)

    def get_json(self, url, *, timeout):
        del url, timeout
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
                    "headline": "Giants prepare for Sunday matchup",
                    "categories": [{"team": {"abbreviation": "NYG"}}],
                }
            ]
        }


def test_espn_news_source_produces_half_panel_payload_for_followed_team():
    source = EspnNewsSource({"nfl": "https://example.test/nfl/news"}, client=NewsClient())
    records = source.fetch(DisplaySettings(my_teams=("nfl:NYG",)))

    assert records["news"][0]["domain"] == "sports"
    assert records["news"][0]["from_abbr"] == "NYG"
    assert records["news"][0]["text"] == "Giants prepare for Sunday matchup"
