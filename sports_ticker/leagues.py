"""Define every selectable scoreboard league in one place."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
    conference_filter_enabled: bool = False

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
    League(
        "ncf_fbs",
        "NCAA (FBS)",
        "football/college-football",
        (("groups", "80"),),
        conference_filter_enabled=True,
    ),
    League(
        "ncf_fcs",
        "NCAA (FCS)",
        "football/college-football",
        (("groups", "81"),),
        conference_filter_enabled=True,
    ),
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
    League("imsa", "IMSA", my_teams_enabled=False),
    League("wec", "FIA WEC", my_teams_enabled=False),
    # League("nascar", "NASCAR", my_teams_enabled=False),
    League("soccer_epl", "Premier League", "soccer/eng.1", fotmob_league_id=47),
    League("soccer_fa_cup", "FA Cup", "soccer/eng.fa", my_teams_enabled=False, fotmob_league_id=132),
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
COLLEGE_FOOTBALL_LEAGUES: Final = frozenset(
    league.id for league in LEAGUES if league.conference_filter_enabled
)


def college_conference_key(league: str, conference_id: object) -> str:
    """Return one stable settings key for a college conference."""

    return f"{str(league).strip().lower()}:{str(conference_id).strip().lower()}"


def college_conference_settings(
    active_sports: Mapping[str, bool] | None,
) -> dict[str, bool]:
    """Extract conference controls encoded in the existing sports settings map."""

    if not isinstance(active_sports, Mapping):
        return {}
    result: dict[str, bool] = {}
    for raw_key, enabled in active_sports.items():
        league, separator, conference_id = str(raw_key).strip().lower().partition(":")
        if separator and conference_id and league in COLLEGE_FOOTBALL_LEAGUES:
            result[college_conference_key(league, conference_id)] = bool(enabled)
    return result


def allows_college_conferences(
    league: str,
    conference_ids: Iterable[object],
    active_conferences: Mapping[str, bool] | None,
) -> bool:
    """Return true when one event belongs to an enabled college conference."""

    identifier = str(league).strip().lower()
    if identifier not in COLLEGE_FOOTBALL_LEAGUES:
        return True
    configured = active_conferences if isinstance(active_conferences, Mapping) else {}
    disabled = {
        str(key).strip().lower()
        for key, enabled in configured.items()
        if str(key).strip() and not bool(enabled)
    }
    if not disabled:
        return True
    normalized_ids = tuple(
        str(value).strip().lower()
        for value in conference_ids
        if str(value).strip()
    )
    if not normalized_ids:
        return True
    return any(
        college_conference_key(identifier, value) not in disabled
        for value in normalized_ids
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
    "COLLEGE_FOOTBALL_LEAGUES",
    "TEAM_CATALOG_PATHS",
    "League",
    "allows_college_conferences",
    "allows_my_team_selection",
    "college_conference_settings",
    "college_conference_key",
    "league_for",
]
