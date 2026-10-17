"""Build stable sport display facts from ESPN scoreboard records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from hashlib import sha1
import unicodedata
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
        if league == "nhl":
            shootout = _nhl_has_shootout_marker(event, competition)
            completed = state in {"post", "final"}
            situation["shootout_state"] = (
                "completed" if shootout and completed else "active" if shootout else "none"
            )
            situation["shootout_winner"] = next(
                (
                    str(competitor.get("homeAway") or "").lower()
                    for competitor in _sequence(competition.get("competitors"))
                    if isinstance(competitor, Mapping) and competitor.get("winner") is True
                ),
                "",
            ) if shootout and completed else ""
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
    raw_clock = status.get("displayClock")
    if raw_clock is None or not str(raw_clock).strip():
        raw_clock = status.get("clock")
    clock = str(raw_clock if raw_clock is not None else "").strip()
    period = _integer(status.get("period"), _integer(kind.get("period"), 0))
    if not clock:
        clock = str(_mapping(competition.get("situation")).get("clock") or "").strip()
    upper = detail.upper()

    if state == "pre":
        return str(data.get("status") or detail or "TBD")
    if "POSTPON" in upper or "CANCEL" in upper or "SUSPEND" in upper or "DELAY" in upper:
        return detail.split(",", 1)[0].title()
    if league == "nhl" and state in {"in", "half", "crit"} and _nhl_has_shootout_marker(
        event, competition
    ):
        return "S/O"
    if league == "nhl" and upper.startswith("END OF"):
        return _period_status("P", period, "END", overtime_base=3)
    if state == "half" or "HALFTIME" in upper or upper in {"HT", "HALF"}:
        return "Half" if league.startswith("soccer") else "Halftime"
    if "FINAL" in upper or state in {"post", "final"}:
        return _final_status(league, upper, period)
    if league in _COLLEGE_FOOTBALL and period > 4:
        return _period_status("Q", period, "", overtime_base=4)
    if league in _FOOTBALL and period > 0 and _is_zero_clock(clock):
        return _period_status("Q", period, "END", overtime_base=4)
    if league == "nhl" and period > 0 and _is_zero_clock(clock):
        return _period_status("P", period, "END", overtime_base=3)
    if league in _BASKETBALL and period > 0 and _is_zero_clock(clock):
        if league == "march_madness" and period in {1, 2}:
            return f"H{period} END"
        overtime_base = 2 if league == "march_madness" else 4
        return _period_status("Q", period, "END", overtime_base=overtime_base)
    if league in _FOOTBALL:
        return _period_status("Q", period, clock, overtime_base=4)
    if league in _BASKETBALL:
        if league == "march_madness" and period in {1, 2}:
            return f"H{period} {clock}".strip()
        overtime_base = 2 if league == "march_madness" else 4
        return _period_status("Q", period, clock, overtime_base=overtime_base)
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
        result = {
            "balls": _integer(source.get("balls")),
            "strikes": _integer(source.get("strikes")),
            "outs": _integer(source.get("outs")),
            "onFirst": bool(source.get("onFirst")),
            "onSecond": bool(source.get("onSecond")),
            "onThird": bool(source.get("onThird")),
            "possession": possession,
        }
        batter = source.get("batter") or _first_mapping(source.get("dueUp"))
        batter_stats = baseball_player_stats(batter)
        for key, target in (
            ("hits", "batter_h"),
            ("atBats", "batter_ab"),
            ("avg", "batter_avg"),
        ):
            if batter_stats.get(key) not in (None, ""):
                result[target] = batter_stats[key]
        pitcher_stats = baseball_player_stats(source.get("pitcher"))
        for key, target in (("pitches", "pitcher_pitches"), ("era", "pitcher_era")):
            if pitcher_stats.get(key) not in (None, ""):
                result[target] = pitcher_stats[key]
        for role in ("batter", "pitcher"):
            name = _baseball_player_name(source.get(role))
            if role == "batter" and not name:
                name = _baseball_player_name(_first_mapping(source.get("dueUp")))
            if name:
                result[f"{role}_name"] = name
        return result
    if league == "nhl":
        return _nhl_situation(source, possession, home_abbr, away_abbr)
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
    if league == "nhl":
        active_team = str(
            result.get("emptyNetSide") or result.get("powerPlayTeam") or ""
        ).strip()
    else:
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
        "batter_name",
        "batter_h",
        "batter_ab",
        "batter_avg",
        "pitcher_name",
        "pitcher_pitches",
        "pitcher_era",
        "home_challenges",
        "home_challenges_used",
        "away_challenges",
        "away_challenges_used",
        "last_pitch_speed",
        "last_pitch_type",
        "powerPlay",
        "powerPlayTeam",
        "manpower",
        "hockeyGoals",
        "emptyNet",
        "emptyNetSide",
    }
)


def _baseball_batting_team(status: str, home_abbr: str, away_abbr: str) -> str:
    """Resolve batting ownership from the provider-normalized inning status."""

    half = baseball_inning_display({"state": "in", "status": status})["half"]
    return away_abbr if half == "top" else home_abbr if half == "bottom" else ""


def _baseball_player_name(value: Any) -> str:
    """Read one live MLB player name from the scoreboard situation."""

    player = _mapping(value)
    athlete = _mapping(player.get("athlete"))
    return str(
        athlete.get("displayName")
        or athlete.get("fullName")
        or player.get("displayName")
        or player.get("fullName")
        or ""
    ).strip()


def baseball_player_stats(value: Any) -> dict[str, str]:
    """Read available MLB player stats from scoreboard situation data."""

    player = _mapping(value)
    stats: dict[str, str] = {}
    sources = [
        player,
        _mapping(player.get("stats")),
        _mapping(player.get("statistics")),
        _mapping(player.get("batting")),
        _mapping(player.get("pitching")),
    ]
    aliases = {
        "hits": ("hits", "H"),
        "atBats": ("atBats", "AB", "at_bats"),
        "avg": ("avg", "AVG", "average"),
        "pitches": ("pitches", "pitchCount", "pitch_count"),
        "era": ("era", "ERA"),
    }
    for target, keys in aliases.items():
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    stats[target] = str(value).strip()
                    break
            if target in stats:
                break
    summary = str(player.get("summary") or "").strip()
    match = re.match(r"^(\d+)\s*-\s*(\d+)\b", summary)
    if match:
        stats.setdefault("hits", match.group(1))
        stats.setdefault("atBats", match.group(2))
    return stats


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
    red_zone = bool(source.get("isRedZone"))
    if possession and to_goal is not None:
        red_zone = to_goal <= 20
    return {
        "possession": possession,
        "downDist": short,
        "downDistFull": full,
        "ballOn": ball_on,
        "down": down,
        "yardsToGo": distance,
        "yardLine": yard_line,
        "isGoalToGo": goal_to_go,
        "isRedZone": red_zone,
    }


def _final_status(league: str, detail: str, period: int) -> str:
    """Keep final overtime and shootout labels visible on compact cards."""

    if league == "nhl":
        if re.search(r"\bS/?O\b|SHOOTOUT", detail):
            return "FINAL S/O"
        if period >= 4:
            return f"FINAL OT{period - 3 if period > 4 else ''}"
    if league == "march_madness" and period > 2:
        return f"FINAL OT{period - 2 if period > 3 else ''}"
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


def _is_zero_clock(value: str) -> bool:
    """Return whether one provider value represents zero seconds remaining."""

    return re.fullmatch(r"0+(?::0+)?(?:\.0+)?", value.strip()) is not None


def _nhl_has_shootout_marker(
    event: Mapping[str, Any], competition: Mapping[str, Any]
) -> bool:
    """Detect explicit NHL shootout markers without treating overtime as a shootout."""

    status = _mapping(event.get("status"))
    status_type = _mapping(status.get("type"))
    competition_situation = _mapping(competition.get("situation"))
    event_situation = _mapping(event.get("situation"))
    sources = (
        status_type,
        event_situation,
        competition_situation,
        _mapping(event_situation.get("lastPlay")),
        _mapping(competition_situation.get("lastPlay")),
        _mapping(event.get("lastPlay")),
    )
    for source in sources:
        for key in ("shootout", "isShootout", "inShootout", "shootoutActive"):
            value = source.get(key)
            if value is True or str(value or "").strip().lower() in {"true", "yes", "active"}:
                return True
        for key in ("shortDetail", "detail", "altDetail", "displayValue", "text"):
            value = str(source.get(key) or "").strip().upper()
            if re.search(r"\bS/?O\b|SHOOTOUT", value):
                return True
        period = _mapping(source.get("period"))
        if str(period.get("displayValue") or "").strip().upper() == "SO":
            return True
        shot_info = _mapping(source.get("shotInfo"))
        if "SHOOTOUT" in str(shot_info.get("text") or "").upper():
            return True
    return False


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
        .replace("ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢", "'")
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
    """Project NCAA college football rankings into the shared display contract."""

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
    """Return one NCAA ranking, excluding the provider's unranked sentinel."""

    team = _mapping(competitor.get("team"))
    team_id = str(team.get("id") or competitor.get("id") or "").strip()
    return normalize_rank((football_rankings or {}).get(team_id))


def normalize_rank(value: object) -> str:
    """Normalize one ranking value and discard its unranked sentinel."""

    try:
        number = int(float(str(value or "").strip().lstrip("Tt")))
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
    assist: object = "",
    goal_type: object = "",
    shot_type: object = "",
    expected_goals: object = "",
) -> dict[str, Any]:
    """Project soccer player, assist, clock, and goal facts."""

    name = str(player or "").strip()
    surname = name.split()[-1].upper()[:8] if name else ""
    clock = str(minute or "").strip()
    result = {
        "is_home": bool(is_home),
        "player": surname,
        "time": clock,
        "own_goal": bool(own_goal),
    }
    if name:
        result["alert_player"] = name
    if str(assist or "").strip():
        full_assist = str(assist).strip()
        result["assist"] = full_assist.split()[-1].upper()[:12]
        result["alert_assist"] = full_assist
    if str(goal_type or "").strip():
        result["goal_type"] = str(goal_type).strip().upper()[:12]
    if str(shot_type or "").strip():
        result["shot_type"] = str(shot_type).strip().upper()[:12]
    if expected_goals not in (None, ""):
        result["expected_goals"] = expected_goals
    return result


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


def baseball_inning_display(data: Mapping[str, Any]) -> dict[str, Any]:
    """Own inning number, half, and phase for every display target."""
    state = str(data.get("state") or "pre").lower()
    result = {"number": 0, "half": "none", "phase": "inactive"}
    if state not in {"in", "crit"}:
        return result
    match = re.match(r"^(TOP|BOTTOM|BOT|MID|MIDDLE|END)(?:\s+OF)?\s*(\d+)", str(data.get("status") or "").strip().upper())
    if match is None or int(match[2]) < 1:
        return {**result, "phase": "paused"}
    half = "top" if match[1] == "TOP" else "bottom" if match[1] in {"BOTTOM", "BOT"} else "break"
    return {"number": int(match[2]), "half": half, "phase": "break" if half == "break" else "playing"}


def sport_family(sport: object) -> str:
    """Return the broad sport category for one league identifier."""
    value = str(sport or "").strip().lower()
    if value in {"mlb", "wbc"} or "baseball" in value:
        return "baseball"
    if value in {"nfl"} or value.startswith("ncf") or "football" in value:
        return "football"
    if value in {"nhl"} or "hockey" in value:
        return "hockey"
    if value in {"nba", "wnba", "march_madness"} or value.startswith(("ncb", "ncw")) or "basketball" in value:
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


def _nhl_situation(
    source: Mapping[str, Any],
    possession: str,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Project manpower, power-play ownership, empty-net, and shootout facts."""

    result = nhl_manpower_situation(source, home_abbr=home_abbr, away_abbr=away_abbr)
    result["possession"] = possession
    result["shootout"] = nhl_shootout_display(source)
    return result


def nhl_manpower_situation(
    source: Mapping[str, Any],
    *,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Own current NHL counts, badge ownership, and count-label visibility."""

    phase = str(source.get("phase") or "unavailable")
    manpower: dict[str, Any] = {
        "phase": phase,
        "state": "unavailable" if phase == "unavailable" else "inactive",
        "awaySkaters": None,
        "homeSkaters": None,
        "label": "",
        "scrollLabel": "",
        "powerPlayTimeRemaining": "",
        "powerPlayLabel": "",
        "penaltyNumbers": [],
        "penalties": [],
    }
    result: dict[str, Any] = {
        "powerPlay": False,
        "powerPlayTeam": "",
        "emptyNet": False,
        "emptyNetSide": "",
        "manpower": manpower,
    }
    if phase not in {"regulation", "overtime"}:
        return result
    manpower["state"] = "unavailable"
    code = str(source.get("situationCode") or "").strip()
    if not re.fullmatch(r"[01][3-6][3-6][01]", code):
        return result
    away_goalie, away_skaters, home_skaters, home_goalie = map(int, code)
    manpower.update(awaySkaters=away_skaters, homeSkaters=home_skaters)
    away_pp = source.get("awayPowerPlay") is True
    home_pp = source.get("homePowerPlay") is True
    result["powerPlay"] = away_pp != home_pp
    if result["powerPlay"]:
        result["powerPlayTeam"] = away_abbr if away_pp else home_abbr
        advantage = away_skaters if away_pp else home_skaters
        opponent = home_skaters if away_pp else away_skaters
        manpower["powerPlayLabel"] = "PP" if (advantage, opponent) in {(5, 4), (4, 3)} else f"{advantage}v{opponent}"
    result["emptyNet"] = not away_goalie or not home_goalie
    if away_goalie != home_goalie:
        result["emptyNetSide"] = away_abbr if not away_goalie else home_abbr
    if result["emptyNet"]:
        manpower["state"] = "empty_net"
    elif result["powerPlay"]:
        manpower["state"] = "power_play"
    elif away_skaters != home_skaters:
        manpower["state"] = "unequal_strength"
    elif phase == "regulation" and away_skaters < 5:
        manpower["state"] = "reduced_strength"
    else:
        manpower["state"] = "even_strength"
    if manpower["state"] in {"empty_net", "power_play", "unequal_strength", "reduced_strength"}:
        manpower["label"] = f"{away_skaters}v{home_skaters}"
    remaining = source.get("powerPlaySecondsRemaining")
    if result["powerPlay"]:
        if isinstance(remaining, int) and not isinstance(remaining, bool) and 0 <= remaining <= 1200:
            manpower["powerPlayTimeRemaining"] = f"{remaining // 60}:{remaining % 60:02d}"
        short_side = "home" if away_pp else "away"
        advantage_count = (away_skaters - (not away_goalie)) if away_pp else (home_skaters - (not home_goalie))
        short_count = (home_skaters - (not home_goalie)) if away_pp else (away_skaters - (not away_goalie))
        penalty_count = max(0, min(2, advantage_count - short_count))
        candidates = []
        for entry in _sequence(_mapping(source.get("penaltyBox")).get(short_side)):
            penalty = _mapping(entry)
            jersey = _integer_or_none(penalty.get("jerseyNumber"))
            seconds = penalty.get("secondsRemaining")
            kind = str(penalty.get("kind") or "").upper()
            if jersey is None or not 0 <= jersey <= 99:
                continue
            if not isinstance(seconds, int) or isinstance(seconds, bool) or not 0 < seconds <= 1200:
                continue
            if kind not in {"MIN", "MAJ"}:
                continue
            candidates.append({"jerseyNumber": jersey, "secondsRemaining": seconds, "timeRemaining": f"{seconds // 60}:{seconds % 60:02d}"})
        candidates.sort(key=lambda penalty: (penalty["secondsRemaining"] != remaining, penalty["secondsRemaining"], penalty["jerseyNumber"]))
        selected = []
        seen = set()
        for penalty in candidates:
            if penalty["jerseyNumber"] not in seen and len(selected) < penalty_count:
                selected.append(penalty)
                seen.add(penalty["jerseyNumber"])
        selected.sort(key=lambda penalty: (penalty["secondsRemaining"], penalty["jerseyNumber"]))
        manpower["penalties"] = selected
        manpower["penaltyNumbers"] = [penalty["jerseyNumber"] for penalty in selected]
        groups: dict[str, list[str]] = {}
        for penalty in selected:
            groups.setdefault(penalty["timeRemaining"], []).append(f"#{penalty['jerseyNumber']}")
        manpower["scrollLabel"] = " | ".join(f"{clock} {'/'.join(numbers)}" for clock, numbers in groups.items())
        if not groups:
            manpower["scrollLabel"] = manpower["powerPlayTimeRemaining"]
    else:
        manpower["scrollLabel"] = manpower["label"]
    return result


def nhl_goal_display(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build complete goal labels with three surname letters and jersey numbers."""

    goals = []
    for goal in _sequence(source.get("goals")):
        record = _mapping(goal)
        if record.get("side") not in {"away", "home"}:
            continue
        name = unicodedata.normalize("NFKD", str(record.get("lastName") or ""))
        letters = "".join(character for character in name.upper() if character.isascii() and character.isalpha())[:3]
        jersey = _integer_or_none(record.get("jerseyNumber"))
        player_label = letters or "---"
        if jersey is not None:
            player_label = f"{letters}#{jersey}"
        period = _integer(record.get("period"))
        clock = str(record.get("clock") or "")
        goals.append({
            "id": str(record.get("id") or ""),
            "side": record["side"],
            "playerLabel": player_label,
            "label": f"{player_label} {period} {clock}".strip(),
        })
    return goals


def nhl_shootout_display(source: Mapping[str, Any]) -> dict[str, Any] | None:
    """Own NHL shootout lifecycle and one aligned three-round display window."""

    raw = _mapping(source.get("shootout"))
    state = str(raw.get("state") or "")
    if state not in {"active", "complete"}:
        return None
    attempts = {side: _results(raw.get(side)) for side in ("away", "home")}
    current_round = max(1, len(attempts["away"]), len(attempts["home"]))
    first_side = str(raw.get("firstSide") or "")
    next_side = ""
    if state == "active" and first_side in attempts:
        second_side = "home" if first_side == "away" else "away"
        first_count = len(attempts[first_side])
        second_count = len(attempts[second_side])
        if first_count == second_count:
            next_side = first_side
            current_round = first_count + 1
        elif first_count == second_count + 1:
            next_side = second_side
            current_round = first_count
    last_round = max(3, current_round)
    first_round = last_round - 2
    rounds = []
    for number in range(first_round, last_round + 1):
        row: dict[str, Any] = {"round": number, "nextSide": next_side if number == current_round else ""}
        for side, results in attempts.items():
            row[side] = results[number - 1] if number <= len(results) else "pending" if state == "active" else "not_taken"
        rounds.append(row)
    return {
        **attempts,
        "state": state,
        "round": current_round,
        "stage": "sudden_death" if current_round > 3 else "initial",
        "nextSide": next_side,
        "awayGoals": attempts["away"].count("goal"),
        "homeGoals": attempts["home"].count("goal"),
        "roundLabel": f"R{first_round}-{last_round}",
        "displayRounds": rounds,
    }


__all__ = [
    "SportsDisplayProjector",
    "nhl_manpower_situation",
    "nhl_goal_display",
    "nhl_shootout_display",
    "assign_active_team",
    "display_situation",
    "matches_followed_team",
    "normalize_rank",
    "normalize_soccer_clock",
    "soccer_event",
    "sport_family",
    "sports_content_sort_key",
]


def _football_name_matches(token: str, name: str) -> bool:
    """Match a full name or ESPN initials without losing the surname."""

    def without_suffix(value):
        return re.sub(r"\s+(?:JR|SR|II|III|IV|V)\.?$", "", value, flags=re.IGNORECASE)

    def key(value):
        return re.sub(r"[\W_]+", "", without_suffix(value).casefold())

    if key(token) == key(name):
        return True
    parts = without_suffix(name).split()
    if not parts:
        return False
    initial = re.fullmatch(r"([A-Za-z.]+)\.\s*(.+)", token)
    if initial:
        return key(initial[2]) == key(parts[-1]) and key(" ".join(parts[:-1])).startswith(key(initial[1]))
    return key(token) == key(parts[-1])


def normalize_football_turnover_play(
    play: Mapping[str, Any],
    *,
    situation: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
    player_catalog: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Normalize one ESPN interception or fumble play for score alerts."""

    play_type = _mapping(play.get("type"))
    text = str(play.get("text") or play.get("shortText") or play.get("description") or "").strip()
    folded = f"{play_type.get('text') or ''} {text}".casefold()
    name_end = r"(?=(?<=[a-z])\.\s+|\s+(?:at|to|for|return(?:ed)?|ran|runs?)\b|[,;()]|$)"
    if re.search(r"\bintercept(?:ion|ed)\b", folded):
        kind = "interception"
        role_words = ("interceptor", "interception", "defender", "returner")
        name_match = re.search(
            r"\b(?:intercepted(?:\s+by)?|interception by)\s+([^,;()]+?)" + name_end,
            text,
            re.IGNORECASE,
        )
    elif re.search(r"\bfumbl(?:e|es|ed|ing)\b", folded):
        kind = "fumble"
        role_words = ("recoverer", "recovery", "fumbler", "rusher", "runner")
        name_match = re.search(
            r"\b(?:recovered by|fumbled by|fumble by)\s+([^,;()]+?)" + name_end,
            text,
            re.IGNORECASE,
        )
    else:
        return {}

    score_value = play.get("scoreValue", play.get("score_value"))
    is_scoring = bool(
        score_value not in (None, "", 0, "0")
        or re.search(r"\b(touchdown|for a td|safety)\b", folded)
    )
    home = home_abbr.upper()
    away = away_abbr.upper()
    play_team = _possession(
        play.get("team") or play.get("teamId") or play.get("possession"),
        competition,
        home_abbr,
        away_abbr,
    )
    role_teams = {
        str(record.get("type") or "").casefold(): _possession(
            record.get("id") or record.get("team"), competition, home_abbr, away_abbr,
        )
        for record in (_mapping(value) for value in _sequence(play.get("teamParticipants")))
    }
    start_team = _possession(_mapping(play.get("start")).get("team"), competition, home_abbr, away_abbr)
    end_team = _possession(_mapping(play.get("end")).get("team"), competition, home_abbr, away_abbr)
    offense = role_teams.get("offense") or start_team or play_team or _possession(
        situation.get("possession"), competition, home_abbr, away_abbr
    )
    active_possession = _possession(
        situation.get("possession"), competition, home_abbr, away_abbr
    )
    athletes = tuple(
        _mapping(value)
        for value in _sequence(play.get("athletesInvolved") or play.get("participants"))
    )
    catalog = {
        str(_mapping(record.get("athlete")).get("id") or ""): record
        for record in player_catalog
    }
    candidates: list[tuple[str, str, str]] = []
    for record in athletes:
        athlete = _mapping(record.get("athlete") or record.get("player") or record)
        catalog_record = _mapping(catalog.get(str(athlete.get("id") or "")))
        athlete = {**_mapping(catalog_record.get("athlete")), **athlete}
        name = str(
            athlete.get("displayName")
            or athlete.get("fullName")
            or athlete.get("shortName")
            or ""
        ).strip()
        team = _possession(
            athlete.get("team") or record.get("team") or catalog_record.get("team"),
            competition,
            home_abbr,
            away_abbr,
        )
        role = " ".join(
            str(record.get(key) or "")
            for key in ("role", "type", "displayRole", "description")
        ).casefold()
        if name:
            candidates.append((name, team, role))

    named_player = name_match.group(1).strip() if name_match else ""
    if not named_player:
        text_prefix = text.split("(", 1)[0].strip()
        player_match = re.match(r"(.+?)\s+\d+\s+(?:yd|yards?)\b", text_prefix, re.IGNORECASE)
        if player_match:
            named_player = player_match.group(1).strip()
    named_player = re.sub(r"^#\d+\s*", "", named_player).strip(" ,.;")
    named_team = ""
    for abbreviation in (home, away):
        for alias in _TEAM_ALIASES.get(abbreviation, (abbreviation,)):
            if named_player.startswith(alias + "-"):
                named_team = abbreviation
                named_player = named_player[len(alias) + 1:]
                break
    catalog_candidates = []
    for record in player_catalog:
        athlete = _mapping(record.get("athlete"))
        name = str(athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "").strip()
        team = _possession(record.get("team") or athlete.get("team"), competition, home_abbr, away_abbr)
        if name:
            catalog_candidates.append((name, team, ""))
    preferred_team = named_team or (role_teams.get("defense") if kind == "interception" else "") or end_team or (play_team if is_scoring else "")
    matches = {
        candidate for candidate in (*candidates, *catalog_candidates)
        if named_player and _football_name_matches(named_player, candidate[0])
        and (not preferred_team or not candidate[1] or candidate[1] == preferred_team)
    }
    identities = {(candidate[0], candidate[1]) for candidate in matches}
    actor = next(iter(matches)) if len(identities) == 1 else None
    if actor is None:
        actor = next(
            (
                candidate
                for candidate in candidates
                if any(word in candidate[2] for word in role_words)
            ),
            None,
        )
    if actor is None and kind == "interception":
        actor = next(
            (
                candidate
                for candidate in candidates
                if candidate[1] and candidate[1] != offense
            ),
            None,
        )
    if actor is None and kind == "fumble":
        actor = next(
            (
                candidate
                for candidate in candidates
                if candidate[1] == offense
            ),
            None,
        )

    player = actor[0] if actor else named_player
    actor_team = actor[1] if actor else ""
    if kind == "interception":
        team = actor_team or named_team or role_teams.get("defense") or end_team or (
            play_team if is_scoring else ""
        ) or (active_possession if active_possession and active_possession != offense else "")
        if not team and offense in {home, away}:
            team = away if offense == home else home
    else:
        team = actor_team or named_team or end_team or (play_team if is_scoring else "") or offense or active_possession

    period = _mapping(play.get("period"))
    clock = _mapping(play.get("clock"))
    period_text = str(
        period.get("displayValue") or period.get("number") or ""
    ).strip()
    clock_text = str(
        clock.get("displayValue") or clock.get("value") or ""
    ).strip()
    return_match = re.search(
        r"\b(\d+)\s*(?:yd|yard)s?\s*(?:interception\s*)?return\b|"
        r"\breturn(?:ed)?\s+for\s+(\d+)\s+yards?\b",
        text,
        re.IGNORECASE,
    )
    return_yards = next(
        (int(value) for value in return_match.groups() if value),
        None,
    ) if return_match else None
    source_id = str(play.get("id") or "").strip()
    if not source_id:
        fingerprint = "|".join((period_text, clock_text, text.casefold()))
        source_id = sha1(fingerprint.encode("utf-8")).hexdigest()[:16]

    result: dict[str, Any] = {
        "id": source_id,
        "kind": kind,
        "team": team,
        "player": player,
        "text": text[:180],
        "is_scoring": is_scoring,
    }
    if return_yards is not None:
        result["return_yards"] = return_yards
    if period_text:
        result["period"] = period_text
    if clock_text:
        result["clock"] = clock_text
    if score_value not in (None, ""):
        result["score_value"] = score_value
    down = _integer_or_none(play.get("down") or _mapping(play.get("start")).get("down"))
    distance = _integer_or_none(
        play.get("distance") or _mapping(play.get("start")).get("distance")
    )
    if down is None:
        down = _integer_or_none(situation.get("down"))
    if distance is None:
        distance = _integer_or_none(situation.get("distance"))
    if down is not None:
        result["down"] = down
    if distance is not None:
        result["distance"] = distance
    red_zone = football_red_zone_for_play(
        play,
        situation=situation,
        competition=competition,
        home_abbr=home_abbr,
        away_abbr=away_abbr,
    )
    if red_zone is not None:
        result["is_red_zone"] = red_zone
    return result


def football_red_zone_for_play(
    play: Mapping[str, Any],
    *,
    situation: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
) -> bool | None:
    """Resolve red-zone state from one play before using live situation state."""

    contexts = (
        play,
        _mapping(play.get("situation")),
        _mapping(play.get("start")),
    )
    for context in contexts:
        for key in ("isRedZone", "is_red_zone", "redZone"):
            if key in context and context[key] is not None:
                value = context[key]
                if isinstance(value, str):
                    return value.strip().casefold() in {"true", "1", "yes"}
                return bool(value)

    start = _mapping(play.get("start"))
    yards_to_goal = _integer_or_none(start.get("yardsToEndzone"))
    if yards_to_goal is not None:
        return yards_to_goal <= 20
    raw_line = next(
        (
            value for value in (
                start.get("yardLine"),
                start.get("yardLineText"),
                play.get("yardLine"),
                play.get("yardLineText"),
            )
            if value not in (None, "")
        ),
        None,
    )
    if isinstance(raw_line, Mapping):
        raw_line = raw_line.get("text") or raw_line.get("displayValue") or raw_line.get("value")
    if isinstance(raw_line, str) and re.search(r"[A-Z]{2,4}", raw_line, re.IGNORECASE):
        text = raw_line if " at " in raw_line.casefold() else f"at {raw_line}"
        yard_line = _yard_line(text, home_abbr, away_abbr)
    else:
        yard_line = _integer_or_none(raw_line)

    possession = _possession(
        play.get("possession") or play.get("team") or situation.get("possession"),
        competition,
        home_abbr,
        away_abbr,
    )
    if yard_line is not None and possession in {home_abbr, away_abbr}:
        yards_to_goal = yard_line if possession == away_abbr else 100 - yard_line
        return yards_to_goal <= 20

    current = situation.get("isRedZone")
    return bool(current) if current is not None else None
