"""Build stable sport display facts from ESPN scoreboard records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any

from sports_ticker.domain import ContentItem


_FOOTBALL = frozenset(("nfl", "ncf_fbs", "ncf_fcs"))
_COLLEGE_FOOTBALL = frozenset(("ncf_fbs", "ncf_fcs"))
_BASKETBALL = frozenset(("nba", "march_madness"))
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


@dataclass(slots=True)
class SportsDisplayProjector:
    """Own sport status, facts, and short-lived live state for one provider."""

    _football: dict[str, dict[str, Any]] = field(default_factory=dict)
    _possession: dict[str, str] = field(default_factory=dict)

    def project(
        self,
        item: ContentItem,
        event: Mapping[str, Any],
        *,
        football_rankings: Mapping[str, str] | None = None,
    ) -> ContentItem:
        """Return one renderer-ready item without exposing ESPN display quirks."""

        data = dict(item.data)
        competition = _first_mapping(event.get("competitions"))
        league = str(data.get("sport") or "").lower()
        state = str(data.get("state") or "pre").lower()
        prior = _mapping(data.get("situation"))
        situation = display_situation(
            league,
            competition,
            home_abbr=str(data.get("home_abbr") or ""),
            away_abbr=str(data.get("away_abbr") or ""),
        )
        if prior.get("clock"):
            situation["clock"] = prior["clock"]
        data["status"] = _status(league, state, event, competition, data)
        situation = self._stable_situation(
            item.id, league, state, str(data["status"]), situation
        )
        data["situation"] = assign_active_team(
            league,
            state,
            str(data["status"]),
            situation,
            home_abbr=str(data.get("home_abbr") or ""),
            away_abbr=str(data.get("away_abbr") or ""),
        )
        if league == "march_madness":
            data.update(_seeds(competition))
        elif league in _COLLEGE_FOOTBALL:
            data.update(_football_ranks(competition, football_rankings))
        return ContentItem(
            id=item.id,
            family=item.family,
            kind=item.kind,
            is_shown=item.is_shown,
            data=data,
        )

    def _stable_situation(
        self,
        identifier: str,
        league: str,
        state: str,
        status: str,
        situation: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep possession and football down data through ESPN's empty polls."""

        live = state in {"in", "half", "crit"}
        if not live:
            self._possession.pop(identifier, None)
            self._football.pop(identifier, None)
            return situation
        halftime = "half" in status.lower()
        possession = str(situation.get("possession") or "")
        if possession:
            self._possession[identifier] = possession
        elif live and not halftime:
            situation["possession"] = self._possession.get(identifier, "")
        else:
            self._possession.pop(identifier, None)

        if league not in _FOOTBALL:
            return situation
        if not live or halftime:
            self._football.pop(identifier, None)
            return situation
        if situation.get("downDist"):
            self._football[identifier] = dict(situation)
        elif identifier in self._football:
            cached = dict(self._football[identifier])
            cached["possession"] = situation.get("possession") or cached.get("possession", "")
            return cached
        return situation


def sports_content_sort_key(item: ContentItem) -> tuple[int, str, str, str, str]:
    """Order scoreboard items consistently after ESPN and FotMob content merge."""

    data = item.data
    state = str(data.get("state") or "pre").lower()
    status = str(data.get("status") or "").upper()
    priority = 3 if state == "post" or "FINAL" in status else 2
    return (
        priority,
        str(data.get("startTimeUTC") or "9999"),
        str(data.get("sport") or ""),
        str(data.get("home_abbr") or ""),
        str(data.get("away_abbr") or ""),
    )


def _status(
    league: str,
    state: str,
    event: Mapping[str, Any],
    competition: Mapping[str, Any],
    data: Mapping[str, Any],
) -> str:
    """Return the exact concise status language used by the ticker layouts."""

    status = _mapping(event.get("status"))
    kind = _mapping(status.get("type"))
    detail = str(
        kind.get("shortDetail") or kind.get("detail") or data.get("status") or ""
    ).strip()
    clock = str(status.get("displayClock") or status.get("clock") or "").strip()
    period = _integer(status.get("period"), _integer(kind.get("period"), 0))
    if not clock:
        clock = str(_mapping(competition.get("situation")).get("clock") or "").strip()
    upper = detail.upper()

    if state == "pre":
        return str(data.get("status") or detail or "TBD")
    if "POSTPON" in upper or "CANCEL" in upper or "SUSPEND" in upper or "DELAY" in upper:
        return detail.split(",", 1)[0].title()
    if state == "half" or "HALFTIME" in upper or upper in {"HT", "HALF"}:
        return "Half" if league.startswith("soccer") else "Halftime"
    if "FINAL" in upper or state in {"post", "final"}:
        return _final_status(league, upper, period)
    if league in _FOOTBALL:
        return _period_status("Q", period, clock, overtime_base=4)
    if league in _BASKETBALL:
        if league == "march_madness" and period in {1, 2}:
            return f"H{period} {clock}".strip()
        return _period_status("Q", period, clock, overtime_base=4)
    if league == "nhl":
        return _period_status("P", period, clock, overtime_base=3)
    if league.startswith("soccer"):
        label = normalize_soccer_clock(clock, period=period) or normalize_soccer_clock(detail, period=period)
        if label:
            return f"ET {label}" if period >= 3 or "ET" in upper else label
        return "ET" if period >= 3 or "ET" in upper else detail
    if league == "mlb":
        return _baseball_status(detail)
    return detail or str(data.get("status") or state)


def display_situation(
    league: str,
    competition: Mapping[str, Any],
    *,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Return all facts consumed by compact and pinned renderer ports."""

    source = _mapping(competition.get("situation"))
    possession = _possession(source.get("possession"), competition, home_abbr, away_abbr)
    if league in _FOOTBALL:
        return _football_situation(source, possession, home_abbr, away_abbr)
    if league == "mlb":
        return {
            "balls": _integer(source.get("balls")),
            "strikes": _integer(source.get("strikes")),
            "outs": _integer(source.get("outs")),
            "onFirst": bool(source.get("onFirst")),
            "onSecond": bool(source.get("onSecond")),
            "onThird": bool(source.get("onThird")),
            "possession": possession,
        }
    if league == "nhl":
        return {
            "possession": possession,
            "powerPlay": _boolean_any(source, "powerPlay", "isPowerPlay", "hasPowerPlay"),
            "emptyNet": _boolean_any(source, "emptyNet", "isEmptyNet"),
            "emptyNetSide": _possession(
                source.get("emptyNetSide") or source.get("emptyNetTeam"),
                competition,
                home_abbr,
                away_abbr,
            ),
            "shootout": _shootout(source.get("shootout") or source.get("shootoutDetails")),
        }
    if league.startswith("soccer"):
        return {
            "possession": possession,
            "shootout": _shootout(source.get("shootout") or source.get("shootoutDetails")),
            "goal_events": _events(source.get("goalEvents") or source.get("goals"), home_abbr, away_abbr),
            "red_cards": _events(source.get("redCards") or source.get("cards"), home_abbr, away_abbr),
        }
    return {"possession": possession}


def assign_active_team(
    league: str,
    state: str,
    status: str,
    situation: Mapping[str, Any],
    *,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Set live-play ownership only while the game remains active."""

    result = dict(situation)
    if state not in {"in", "half", "crit"}:
        for key in _LIVE_PLAY_KEYS:
            result.pop(key, None)
        return result
    active_team = str(result.get("possession") or "").strip()
    if league == "mlb" and not active_team:
        active_team = _baseball_batting_team(status, home_abbr, away_abbr)
    if active_team:
        result["activeTeam"] = active_team
    else:
        result.pop("activeTeam", None)
    return result


_LIVE_PLAY_KEYS = frozenset(
    {
        "activeTeam",
        "possession",
        "downDist",
        "downDistFull",
        "down",
        "ballOn",
        "yardLine",
        "yardsToGo",
        "yardsToGoal",
        "isGoalToGo",
        "goalToGo",
        "isRedZone",
        "balls",
        "strikes",
        "outs",
        "onFirst",
        "onSecond",
        "onThird",
        "powerPlay",
        "emptyNet",
        "emptyNetSide",
    }
)


def _baseball_batting_team(status: str, home_abbr: str, away_abbr: str) -> str:
    """Resolve batting ownership from the provider-normalized inning status."""

    normalized = status.strip().casefold()
    if normalized.startswith("top"):
        return away_abbr
    if normalized.startswith("bottom") or normalized.startswith("bot"):
        return home_abbr
    return ""


def _football_situation(
    source: Mapping[str, Any], possession: str, home_abbr: str, away_abbr: str
) -> dict[str, Any]:
    """Normalize football down, spot, first-down, and red-zone facts."""

    full = str(source.get("downDistanceText") or "").strip()
    short = str(source.get("shortDownDistanceText") or "").strip()
    down = _integer_or_none(source.get("down"))
    distance = _integer_or_none(source.get("distance"))
    yard_line = _integer_or_none(source.get("yardLine"))
    if yard_line is None:
        yard_line = _yard_line(full, home_abbr, away_abbr)
    if yard_line is not None:
        yard_line = max(0, min(100, yard_line))
    if not short:
        short = full.split(" at ", 1)[0].strip()
    if not short and down in _ORDINALS and distance is not None:
        short = f"{_ORDINALS[down]} & {distance}"
    ball_on = str(source.get("possessionText") or "").strip()
    if not ball_on and " at " in full:
        ball_on = full.split(" at ", 1)[1].strip()
    to_goal = None
    if possession.upper() == away_abbr.upper():
        to_goal = yard_line
    elif possession.upper() == home_abbr.upper() and yard_line is not None:
        to_goal = 100 - yard_line
    goal_to_go = "goal" in short.lower() or "goal" in full.lower()
    if to_goal is not None and distance is not None and distance >= to_goal:
        goal_to_go = True
    return {
        "possession": possession,
        "downDist": short,
        "downDistFull": full,
        "ballOn": ball_on,
        "down": down,
        "yardsToGo": distance,
        "yardLine": yard_line,
        "isGoalToGo": goal_to_go,
        "isRedZone": bool(source.get("isRedZone")) or bool(to_goal is not None and to_goal <= 20),
    }


def _final_status(league: str, detail: str, period: int) -> str:
    """Keep final overtime and shootout labels visible on compact cards."""

    if league == "nhl":
        if "SO" in detail or "SHOOTOUT" in detail or period >= 5:
            return "FINAL S/O"
        if period >= 4:
            return f"FINAL OT{period - 3 if period > 4 else ''}"
    if league in _FOOTBALL | _BASKETBALL and period > 4:
        return f"FINAL OT{period - 4 if period > 5 else ''}"
    return "FINAL"


def _period_status(prefix: str, period: int, clock: str, *, overtime_base: int) -> str:
    if period > overtime_base:
        extra = period - overtime_base
        label = f"OT{extra if extra > 1 else ''}"
    else:
        label = f"{prefix}{period}" if period else prefix
    return f"{label} {clock}".strip()


def _baseball_status(value: str) -> str:
    text = value.replace("Inning", "").replace("inning", "").strip()
    text = re.sub(r"^TOP\s+", "Top ", text, flags=re.IGNORECASE)
    text = re.sub(r"^BOTTOM\s+", "Bottom ", text, flags=re.IGNORECASE)
    return text or "In Progress"


def normalize_soccer_clock(value: object, *, period: int | None = None) -> str:
    """Return one canonical soccer clock label."""

    text = (
        str(value or "")
        .replace("\u200e", "")
        .replace("\u200f", "")
        .replace("\ufffd", "")
        .replace("’", "'")
    )
    text = re.sub(r"\s+", "", text).replace("'", "")
    match = re.fullmatch(
        r"(?P<minute>\d+)(?::(?P<seconds>\d{1,2}))?"
        r"(?:\+(?P<added_minute>\d+)(?::(?P<added_seconds>\d{1,2}))?)?",
        text,
    )
    if match is None:
        return ""
    if any(
        int(val) >= 60
        for val in (match.group("seconds"), match.group("added_seconds"))
        if val is not None
    ):
        return ""
    minute = match.group("minute")
    added_minute = match.group("added_minute")
    if added_minute is not None:
        added_seconds = match.group("added_seconds")
        added = added_minute if added_seconds is None else f"{added_minute}:{added_seconds.zfill(2)}"
        return f"{minute}'+{added}'"

    minute_value = int(minute)
    seconds = match.group("seconds")
    if period == 1 and minute_value > 45:
        extra = minute_value - 45
        added = str(extra) if seconds is None else f"{extra}:{seconds.zfill(2)}"
        return f"45'+{added}'"
    if minute_value > 120 or (period is not None and period >= 3 and minute_value > 15):
        extra = minute_value - 120 if minute_value > 120 else minute_value - 15
        added = str(extra) if seconds is None else f"{extra}:{seconds.zfill(2)}"
        return f"120'+{added}'"
    if minute_value > 90:
        extra = minute_value - 90
        added = str(extra) if seconds is None else f"{extra}:{seconds.zfill(2)}"
        return f"90'+{added}'"
    return f"{minute}'"



def _seeds(competition: Mapping[str, Any]) -> dict[str, str]:
    competitors = _competitors(competition.get("competitors"))
    home = _find_side(competitors, "home")
    away = _find_side(competitors, "away")
    return {
        "home_seed": _seed(home),
        "away_seed": _seed(away),
    }


def _football_ranks(
    competition: Mapping[str, Any],
    football_rankings: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Project ESPN college football rankings into the shared display contract."""

    competitors = _competitors(competition.get("competitors"))
    home = _find_side(competitors, "home")
    away = _find_side(competitors, "away")
    return {
        "home_rank": _rank(home, football_rankings),
        "away_rank": _rank(away, football_rankings),
    }


def _seed(competitor: Mapping[str, Any]) -> str:
    value = _mapping(competitor.get("curatedRank")).get("current")
    return "" if value in (None, "", 99, "99") else str(value)


def _rank(
    competitor: Mapping[str, Any],
    football_rankings: Mapping[str, str] | None = None,
) -> str:
    """Return one ESPN ranking, excluding the provider's unranked sentinel."""

    value = _mapping(competitor.get("curatedRank")).get("current")
    rank = normalize_rank(value)
    if rank:
        return rank
    team = _mapping(competitor.get("team"))
    team_id = str(competitor.get("id") or team.get("id") or "").strip()
    return normalize_rank((football_rankings or {}).get(team_id))


def normalize_rank(value: object) -> str:
    """Normalize one ranking value and discard ESPN's unranked sentinel."""

    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return ""
    return str(number) if 0 < number < 99 else ""


def _possession(value: object, competition: Mapping[str, Any], home_abbr: str, away_abbr: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    folded = text.casefold()
    if folded in {"home", "home_team"}:
        return home_abbr
    if folded in {"away", "away_team"}:
        return away_abbr
    for competitor, abbreviation in ((_find_side(_competitors(competition.get("competitors")), "home"), home_abbr), (_find_side(_competitors(competition.get("competitors")), "away"), away_abbr)):
        team = _mapping(competitor.get("team"))
        if text == str(team.get("id") or "") or folded == abbreviation.casefold():
            return abbreviation
    return ""


def _yard_line(text: str, home_abbr: str, away_abbr: str) -> int | None:
    if " at " not in text:
        return None
    parts = text.split(" at ", 1)[1].strip().split()
    if len(parts) == 1:
        return 50 if _integer_or_none(parts[0]) == 50 else None
    if len(parts) < 2:
        return None
    yard = _integer_or_none(parts[1])
    if yard is None:
        return None
    return yard if parts[0].upper() == home_abbr.upper() else 100 - yard if parts[0].upper() == away_abbr.upper() else None


def _shootout(value: object) -> dict[str, list[str]] | None:
    source = _mapping(value)
    if not source:
        return None
    return {
        "away": _results(source.get("away") or source.get("awayResults")),
        "home": _results(source.get("home") or source.get("homeResults")),
    }


def _results(value: object) -> list[str]:
    result: list[str] = []
    for entry in _sequence(value):
        text = str(_mapping(entry).get("result") or entry).lower()
        result.append("goal" if text in {"goal", "made", "score"} else "miss" if text in {"miss", "failed", "save"} else "pending")
    return result


def _events(value: object, home_abbr: str, away_abbr: str) -> list[dict[str, Any]]:
    """Project provider event records into the soccer renderer contract."""

    result: list[dict[str, Any]] = []
    for entry in _sequence(value):
        source = _mapping(entry)
        team = str(source.get("team") or source.get("teamAbbreviation") or "")
        result.append(soccer_event(
            is_home=team.upper() == home_abbr.upper(),
            player=source.get("displayName") or source.get("athlete") or source.get("name"),
            minute=source.get("clock") or source.get("time"),
            own_goal=bool(source.get("ownGoal") or source.get("isOwnGoal")),
        ))
    return result


def soccer_event(
    *,
    is_home: bool,
    player: object,
    minute: object,
    own_goal: bool = False,
) -> dict[str, Any]:
    """Return the V1-equivalent goal or card event consumed by both panel layouts."""

    name = str(player or "").strip()
    surname = name.split()[-1].upper()[:8] if name else ""
    clock = str(minute or "").strip()
    return {
        "is_home": bool(is_home),
        "player": surname,
        "time": clock,
        "own_goal": bool(own_goal),
    }


def _boolean_any(source: Mapping[str, Any], *keys: str) -> bool:
    return any(bool(source.get(key)) for key in keys)


def _integer(value: object, default: int = 0) -> int:
    result = _integer_or_none(value)
    return default if result is None else result


def _integer_or_none(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _competitors(value: object) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in _sequence(value) if isinstance(item, Mapping))


def _find_side(competitors: Sequence[Mapping[str, Any]], side: str) -> Mapping[str, Any]:
    return next((item for item in competitors if str(item.get("homeAway") or "").lower() == side), {})


def _first_mapping(value: object) -> Mapping[str, Any]:
    return _mapping(_sequence(value)[0]) if _sequence(value) else {}


_TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    # NBA
    "NY": ("NY", "NYK", "NYC", "RBNY"),
    "NYK": ("NY", "NYK"),
    "GS": ("GS", "GSW"),
    "GSW": ("GS", "GSW"),
    "NO": ("NO", "NOP"),
    "NOP": ("NO", "NOP"),
    "SA": ("SA", "SAS"),
    "SAS": ("SA", "SAS"),
    "PHX": ("PHX", "PHO"),
    "PHO": ("PHX", "PHO"),
    "UTA": ("UTA", "UTAH"),
    "UTAH": ("UTA", "UTAH"),
    # NFL
    "WAS": ("WAS", "WSH"),
    "WSH": ("WAS", "WSH"),
    "JAC": ("JAC", "JAX"),
    "JAX": ("JAC", "JAX"),
    "TB": ("TB", "TAM"),
    "TAM": ("TB", "TAM"),
    # MLS / Soccer
    "RBNY": ("RBNY", "NYR", "NY"),
    "NYR": ("NYR", "RBNY", "NY"),
    "LAFC": ("LAFC", "LAF"),
    "LAF": ("LAFC", "LAF"),
    "LA": ("LA", "LAG", "LAD", "LAC", "LAR"),
    "LAG": ("LAG", "LA"),
    "SJ": ("SJ", "SJE"),
    "SJE": ("SJ", "SJE"),
    "NE": ("NE", "NER"),
    "NER": ("NE", "NER"),
    "DC": ("DC", "DCU"),
    "DCU": ("DC", "DCU"),
    "WXM": ("WXM", "WRE", "WREXHAM"),
    "WRE": ("WXM", "WRE", "WREXHAM"),
    "ATX": ("ATX", "AUS"),
    "AUS": ("ATX", "AUS"),
    "SKC": ("SKC", "KC"),
    "KC": ("SKC", "KC"),
    "SEA": ("SEA", "SEATTLE"),
    "VAN": ("VAN", "VANCOUVER"),
    "NYC": ("NYC", "NYCF"),
    "BHA": ("BHA", "BRI"),
    "BRI": ("BHA", "BRI"),
    "NFO": ("NFO", "NOT"),
    "NOT": ("NFO", "NOT"),
    "MCI": ("MCI", "MNC"),
    "MNC": ("MCI", "MNC"),
    "MUN": ("MUN", "MAN"),
    "MAN": ("MUN", "MAN"),
}


def sport_family(sport: object) -> str:
    """Return the broad sport category for one league identifier."""
    value = str(sport or "").strip().lower()
    if value in {"mlb", "wbc"} or "baseball" in value:
        return "baseball"
    if value in {"nfl"} or value.startswith("ncf") or "football" in value:
        return "football"
    if value in {"nhl"} or "hockey" in value:
        return "hockey"
    if value in {"nba", "wnba"} or value.startswith(("ncb", "ncw")) or "basketball" in value:
        return "basketball"
    if value.startswith("soccer") or value in {"mls", "epl", "championship", "champions_league"}:
        return "soccer"
    return value or "other"


def matches_followed_team(sport: str, team_abbr: str, followed_entries: set[str] | frozenset[str] | Sequence[str]) -> bool:
    """Return whether one team in a sport matches any followed team identifier."""
    sport_str = str(sport or "").strip().lower()
    team_str = str(team_abbr or "").strip().lower()
    if not sport_str or not team_str:
        return False
    followed_set = {str(item).strip().lower() for item in followed_entries if str(item).strip()}
    if not followed_set:
        return False
    family = sport_family(sport_str)
    sport_variants = {sport_str, family}
    if "_" in sport_str:
        sport_variants.add(sport_str.split("_", 1)[1])
        sport_variants.add(sport_str.replace("_", ""))
    team_aliases = _TEAM_ALIASES.get(team_str.upper(), (team_str.upper(),))
    team_variants = {t.lower() for t in team_aliases} | {team_str}
    for s in sport_variants:
        for t in team_variants:
            if f"{s}:{t}" in followed_set or t in followed_set:
                return True
    return False


__all__ = [
    "SportsDisplayProjector",
    "assign_active_team",
    "display_situation",
    "matches_followed_team",
    "normalize_rank",
    "normalize_soccer_clock",
    "soccer_event",
    "sport_family",
    "sports_content_sort_key",
]
