"""Verify league-wide blockbuster news and followed-team news routing."""

import pytest

from sports_ticker.domain import DisplaySettings
from sports_ticker.providers.news_transactions import ConfirmedTrade
from sports_ticker.providers.live_sources import (
    EspnNewsSource,
    _classify_espn_news_article,
    _filter_news_for_ticker,
)

pytestmark = pytest.mark.critical


def _article(article_id, headline, description, teams, athlete):
    return {
        "id": article_id,
        "type": "HeadlineNews",
        "headline": headline,
        "description": description,
        "categories": [
            {"type": "team", "team": {"abbreviation": team}}
            for team in teams
        ] + [{"type": "athlete", "description": athlete}],
    }


_FIXTURES = {
    "nfl": [
        _article(
            "parsons",
            "Cowboys trading Micah Parsons to Packers for two first-round picks, DL Kenny Clark",
            "All-Pro edge rusher Micah Parsons joins Green Bay in a stunning blockbuster trade and highest-paid non-quarterback deal.",
            ("DAL", "GB"),
            "Micah Parsons",
        ),
        _article(
            "gardner",
            "Jets trade CB Sauce Gardner to Colts for two first-round picks, WR Adonai Mitchell",
            "The two-time All-Pro cornerback is headed to Indianapolis in a blockbuster trade.",
            ("NYJ", "IND"),
            "Sauce Gardner",
        ),
        _article(
            "quinnen",
            "Jets trade DT Quinnen Williams to Cowboys for draft picks and Mazi Smith",
            "The 2022 All-Pro defensive tackle is headed to Dallas for a first-round pick.",
            ("NYJ", "DAL"),
            "Quinnen Williams",
        ),
    ],
    "nba": [
        _article(
            "davis",
            "Anthony Davis traded to Wizards in 9-player, 3-team deal",
            "Ten-time All-Star Anthony Davis is headed to Washington along with four players and five picks.",
            ("DAL", "WAS", "CHA"),
            "Anthony Davis",
        ),
        _article(
            "morant",
            "Trail Blazers add Ja Morant in trade with Grizzlies",
            "The former two-time All-Star guard is headed to Portland in a major trade.",
            ("POR", "MEM"),
            "Ja Morant",
        ),
    ],
    "mlb": [
        _article(
            "skubal",
            "Dodgers deliver blockbuster, acquire Tarik Skubal from Tigers",
            "Two-time AL Cy Young Award winner Tarik Skubal moves in a blockbuster for top prospects.",
            ("LAD", "DET"),
            "Tarik Skubal",
        ),
        _article(
            "rutschman",
            "Adley Rutschman traded to Red Sox for big prospect haul",
            "The Orioles traded the 2019 No. 1 overall Draft pick and franchise cornerstone in a massive haul.",
            ("BAL", "BOS"),
            "Adley Rutschman",
        ),
    ],
    "nhl": [
        _article(
            "tkachuk",
            "Panthers trade for Brady Tkachuk in blockbuster deal",
            "Former Senators captain Brady Tkachuk arrives for three first-round selections.",
            ("FLA", "OTT"),
            "Brady Tkachuk",
        ),
        _article(
            "kyrou",
            "Kyrou traded to Capitals by Blues for McMichael, 1st-round pick",
            "Jordan Kyrou scored 46 points and has five seasons remaining on an eight-year, $65 million contract.",
            ("STL", "WSH"),
            "Jordan Kyrou",
        ),
        _article(
            "hughes",
            "Hughes traded to Wild by Canucks in blockbuster deal",
            "The 2023-24 Norris winner and Vancouver captain moves for three players and a first-round pick.",
            ("VAN", "MIN"),
            "Quinn Hughes",
        ),
    ],
}


class FixtureClient:
    """Return the real-shaped article set for each league endpoint."""

    def get_json(self, url, *, timeout):
        del timeout
        league = url.rstrip("/").split("/")[-2]
        return {"articles": _FIXTURES[league]}


def _source():
    return EspnNewsSource(
        {league: f"https://example.test/{league}/news" for league in _FIXTURES},
        client=FixtureClient(),
        trade_confirmation_source=FixtureTradeVerifier(),
        background=False,
    )


class FixtureTradeVerifier:
    """Confirm transaction fixtures through an injected trusted source."""

    def confirm_trade(self, league, athlete_names, team_abbreviations, *, now):
        if len(team_abbreviations) < 2 or not athlete_names:
            return None
        return ConfirmedTrade(
            from_abbr=team_abbreviations[0],
            to_abbr=team_abbreviations[1],
            occurred_at=now.date(),
            source_url="https://example.test/transactions/confirmed",
            headline="Confirmed transaction",
            details="Confirmed completed trade",
        )


def test_ten_recent_real_transaction_shapes_get_impact_tiers():
    records = _source()._fetch_news()

    assert len(records) == 10
    assert sum(record["impact_tier"] == "BLOCKBUSTER" for record in records) == 5
    assert sum(record["impact_tier"] == "MAJOR" for record in records) == 5
    assert all(record["distribution"] == "global" for record in records if record["impact_tier"] == "BLOCKBUSTER")
    assert all(record["distribution"] == "global" for record in records if record["impact_tier"] == "MAJOR")


def test_espn_team_catalog_primary_and_alternate_colors_reach_news_records():
    colors = {
        "DAL": {"color": "003594", "alt_color": "869397"},
        "GB": {"color": "203731", "alt_color": "FFB612"},
    }
    source = EspnNewsSource(
        {"nfl": "https://example.test/nfl/news"},
        client=FixtureClient(),
        team_color_lookup=lambda league: colors,
        trade_confirmation_source=FixtureTradeVerifier(),
        background=False,
    )

    records = source._fetch_news()
    parsons = next(record for record in records if record["athletes"] == ["Micah Parsons"])

    assert parsons["from_color"] == "#003594"
    assert parsons["from_alt_color"] == "#869397"
    assert parsons["to_color"] == "#203731"
    assert parsons["to_alt_color"] == "#FFB612"


def test_unverified_trade_language_stays_followed_team_news():
    class UnverifiedClient:
        def get_json(self, url, *, timeout):
            del url, timeout
            return {
                "articles": [
                    _article(
                        "larkin",
                        "Amid trade request, Red Wings move Larkin to injured reserve",
                        "Detroit places captain Dylan Larkin on injured reserve.",
                        ("DET", "NYR"),
                        "Dylan Larkin",
                    )
                ]
            }

    source = EspnNewsSource(
        {"nhl": "https://example.test/nhl/news"},
        client=UnverifiedClient(),
        background=False,
    )

    records = source._fetch_news()

    assert len(records) == 1
    assert records[0]["kind"] == "INJURY"
    assert records[0]["distribution"] == "followed_teams"


def test_unverified_trade_recap_stays_a_headline_news_item():
    headline = "Tatum 'comfortable' leading new-look Celtics post-Brown trade"
    article = _article(
        "brown-recap",
        headline,
        "Boston traded Jaylen Brown to Philadelphia earlier this offseason.",
        ("BOS", "PHI"),
        "Jayson Tatum",
    )

    record = _classify_espn_news_article(article, "nba", set())

    assert record["kind"] == "NEWS"
    assert record["text"] == headline
    assert record["distribution"] == "followed_teams"
    assert record["verification"] == "source_report"


def test_record_breaking_does_not_create_an_injury_alert():
    article = _article(
        "record-broken",
        "Harvey Elliott's record as youngest player in EFL Cup broken by 15-year-old",
        "A youth player set a new age record in the EFL Cup.",
        ("LIV",),
        "Harvey Elliott",
    )

    assert _classify_espn_news_article(article, "soccer_epl", set()) is None


def test_blockbuster_and_major_trades_broadcast_without_followed_teams():
    records = _source().fetch(DisplaySettings())

    assert {record["impact_tier"] for record in records["news"]} == {"BLOCKBUSTER", "MAJOR"}
    assert {record["athletes"][0] for record in records["news"]} == {
        "Micah Parsons",
        "Sauce Gardner",
        "Quinnen Williams",
        "Anthony Davis",
        "Ja Morant",
        "Tarik Skubal",
        "Adley Rutschman",
        "Brady Tkachuk",
        "Jordan Kyrou",
        "Quinn Hughes",
    }


def test_followed_team_receives_its_major_trade_and_all_blockbusters():
    records = _source().fetch(DisplaySettings(my_teams=("mlb:BOS",)))

    assert "Adley Rutschman" in {record["athletes"][0] for record in records["news"]}
    assert "Quinnen Williams" in {record["athletes"][0] for record in records["news"]}
    assert sum(record["impact_tier"] == "BLOCKBUSTER" for record in records["news"]) == 5


@pytest.mark.parametrize(
    ("headline", "expected_kind"),
    (
        ("Pirates place Konnor Griffin on waivers", "WAIVER"),
        ("Pirates designate Konnor Griffin for assignment", "DFA"),
        ("Pirates outright release Konnor Griffin", "RELEASE"),
        ("Pirates option Konnor Griffin to Triple-A", "OPTION"),
        ("Pirates recall Konnor Griffin from Triple-A", "RECALL"),
        ("Pirates activate Konnor Griffin from the 10-day IL", "ACTIVATED"),
        ("Pirates suspend Konnor Griffin", "SUSPENSION"),
        ("Konnor Griffin announces retirement", "RETIREMENT"),
        ("Pirates non-tender Konnor Griffin", "NO_TENDER"),
    ),
)
def test_roster_transaction_kinds_are_followed_team_only(headline, expected_kind):
    record = _classify_espn_news_article(
        _article("roster", headline, "", ("PIT",), "Konnor Griffin"),
        "mlb",
        set(),
    )

    assert record["kind"] == expected_kind
    assert record["distribution"] == "followed_teams"
    assert _filter_news_for_ticker((record,), set()) == ()
    assert _filter_news_for_ticker((record,), {"mlb:pit"}) == (record,)
