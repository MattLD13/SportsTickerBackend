"""Define every selectable scoreboard league in one place."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class League:
    """Describe one ESPN scoreboard league and its selectable teams."""

    id: str
    label: str
    scoreboard_path: str
    scoreboard_query: tuple[tuple[str, str], ...] = ()
    team_abbreviations: frozenset[str] | None = None

    def allows_team(self, abbreviation: str) -> bool:
        """Return true when this league exposes the team in My Teams."""

        if self.team_abbreviations is None:
            return True
        return abbreviation.strip().upper() in self.team_abbreviations


# Set team_abbreviations to frozenset(("PIT", "NYG")) to limit My Teams for a league.
# Keep None to expose every current team returned by ESPN.
LEAGUES: Final[tuple[League, ...]] = (
    League("nfl", "NFL", "football/nfl"),
    League("mlb", "MLB", "baseball/mlb"),
    League("nhl", "NHL", "hockey/nhl"),
    League("nba", "NBA", "basketball/nba"),
    League("ncf_fbs", "NCAA (FBS)", "football/college-football", (("groups", "80"),)),
    League("ncf_fcs", "NCAA (FCS)", "football/college-football", (("groups", "81"),)),
    League(
        "march_madness",
        "March Madness",
        "basketball/mens-college-basketball",
        (("groups", "100"), ("limit", "100")),
    ),
    League("soccer_epl", "Premier League", "soccer/eng.1"),
    League("soccer_fa_cup", "FA Cup", "soccer/eng.fa"),
    League("soccer_champ", "Championship", "soccer/eng.2"),
    League("soccer_champions_league", "Champions League", "soccer/uefa.champions"),
    League("soccer_mls", "MLS", "soccer/usa.1"),
)

LEAGUE_BY_ID: Final = MappingProxyType({league.id: league for league in LEAGUES})
SCOREBOARD_PATHS: Final = MappingProxyType(
    {league.id: league.scoreboard_path for league in LEAGUES}
)


def league_for(identifier: str) -> League:
    """Return one configured league by its stable identifier."""

    return LEAGUE_BY_ID[str(identifier).strip().lower()]


__all__ = ["LEAGUES", "LEAGUE_BY_ID", "SCOREBOARD_PATHS", "League", "league_for"]
