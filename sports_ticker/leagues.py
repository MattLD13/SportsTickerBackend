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
    scoreboard_path: str = ""
    scoreboard_query: tuple[tuple[str, str], ...] = ()
    my_teams_enabled: bool = True
    team_abbreviations: frozenset[str] | None = None
    fotmob_league_id: int | None = None

    def allows_team(self, abbreviation: str) -> bool:
        """Return true when this league exposes the team in My Teams."""

        if self.team_abbreviations is None:
            return True
        return abbreviation.strip().upper() in self.team_abbreviations


# Set my_teams_enabled to False to remove a league from My Teams.
# Set team_abbreviations to frozenset(("PIT", "NYG")) to limit its teams.
# Keep team_abbreviations as None to expose every current ESPN team.
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
        my_teams_enabled=False,
    ),
    League("golf", "Golf (PGA)", my_teams_enabled=False),
    League("f1", "Formula 1", my_teams_enabled=False),
    League("indycar", "IndyCar", my_teams_enabled=False),
    League("nascar", "NASCAR", my_teams_enabled=False),
    League("soccer_epl", "Premier League", "soccer/eng.1", fotmob_league_id=47),
    League("soccer_fa_cup", "FA Cup", "soccer/eng.fa", fotmob_league_id=132),
    League("soccer_champ", "Championship", "soccer/eng.2", fotmob_league_id=48),
    League("soccer_champions_league", "Champions League", "soccer/uefa.champions", fotmob_league_id=42),
    League("soccer_mls", "MLS", "soccer/usa.1", fotmob_league_id=130),
)

LEAGUE_BY_ID: Final = MappingProxyType({league.id: league for league in LEAGUES})
TEAM_CATALOG_PATHS: Final = MappingProxyType(
    {league.id: league.scoreboard_path for league in LEAGUES if league.scoreboard_path}
)
ESPN_SCOREBOARD_PATHS: Final = MappingProxyType(
    {
        league.id: league.scoreboard_path
        for league in LEAGUES
        if league.scoreboard_path and league.fotmob_league_id is None
    }
)
FOTMOB_LEAGUES: Final = MappingProxyType(
    {league.id: league.fotmob_league_id for league in LEAGUES if league.fotmob_league_id is not None}
)


def league_for(identifier: str) -> League:
    """Return one configured league by its stable identifier."""

    return LEAGUE_BY_ID[str(identifier).strip().lower()]


def allows_my_team_selection(identifier: str) -> bool:
    """Return true when one scoped team ID remains selectable."""

    league_id, separator, abbreviation = str(identifier).strip().lower().partition(":")
    if not separator or not abbreviation:
        return False
    definition = LEAGUE_BY_ID.get(league_id)
    return bool(definition and definition.my_teams_enabled and definition.allows_team(abbreviation))


__all__ = [
    "LEAGUES",
    "LEAGUE_BY_ID",
    "ESPN_SCOREBOARD_PATHS",
    "FOTMOB_LEAGUES",
    "TEAM_CATALOG_PATHS",
    "League",
    "allows_my_team_selection",
    "league_for",
]
