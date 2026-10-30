"""Merge MLB StatsAPI live details into ESPN baseball events."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from datetime import date, datetime
import re
from types import MappingProxyType
from typing import Any

from ticker.shared.payloads import as_mapping as _mapping, as_sequence as _sequence, first_mapping as _first_mapping
from ticker.shared.sports_display import (
    baseball_player_stats,
    baseball_player_name,
)
from ticker.server.providers.espn_events import _event_competition, _mlb_person_id


_MLB_PITCH_LABELS = {
    "four seam fastball": "4S Fastball",
    "two seam fastball": "2S Fastball",
    "cutter": "Cutter",
    "changeup": "Changeup",
    "curveball": "Curveball",
    "knuckle curve": "Knuckle Curve",
    "knuckleball": "Knuckleball",
    "sinker": "Sinker",
    "slider": "Slider",
    "splitter": "Splitter",
    "sweeper": "Sweeper",
}


_MLB_PITCH_ABBREVIATIONS = {
    "2SFB": "2S Fastball",
    "4SFB": "4S Fastball",
    "CH": "Changeup",
    "CU": "Curveball",
    "FC": "Cutter",
    "FF": "4S Fastball",
    "FS": "Splitter",
    "KC": "Knuckle Curve",
    "KN": "Knuckleball",
    "SI": "Sinker",
    "SL": "Slider",
    "ST": "Sweeper",
    "SV": "Sweeper",
}


_MLB_TEAM_ABBREVIATION_ALIASES = MappingProxyType(
    {
        "ARI": "AZ",
        "AZ": "ARI",
        "CHW": "CWS",
        "CWS": "CHW",
    }
)


@dataclass(frozen=True, slots=True)
class _MlbLiveDetailCache:
    """Keep one last-known live MLB detail set for one active event."""

    values: Mapping[str, Any]
    batter_id: str = ""
    pitcher_id: str = ""


@dataclass(frozen=True, slots=True)
class _MlbEventKey:
    """Keep the MLB teams and complete ESPN start time for one event."""

    away_abbr: str
    home_abbr: str
    event_date: date
    event_start: datetime | None = None


@dataclass(frozen=True, slots=True)
class _MlbScheduleGame:
    """Keep one MLB schedule candidate without collapsing doubleheaders."""

    game_pk: str
    away_abbr: str
    home_abbr: str
    game_start: datetime | None = None


def _mlb_api_summary_url(request_url: str) -> str:
    """Return ESPN's API-host equivalent for one MLB summary URL."""

    return request_url.replace(
        "site.web.api.espn.com",
        "site.api.espn.com",
    )


def _mlb_has_boxscore(payload: Mapping[str, Any]) -> bool:
    """Return whether an MLB summary has complete active-player display facts."""

    details = _mlb_event_details(payload)
    required = {
        "batter_name",
        "batter_h",
        "batter_ab",
        "batter_avg",
        "pitcher_name",
        "pitcher_pitches",
    }
    if not required.issubset(details):
        return False
    return bool(
        details.get("pitcher_era")
        or details.get("last_pitch_type")
        or details.get("last_pitch_speed")
    )


def _mlb_event_details(payload: Any) -> dict[str, Any]:
    """Extract the small live MLB detail set used by the full panel."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    situation = _mapping(summary.get("situation")) or _mapping(
        competition.get("situation")
    )
    if not situation:
        return {}
    batter_ref = situation.get("batter")
    if not _mlb_person_id(batter_ref) and not baseball_player_name(batter_ref):
        batter_ref = _first_mapping(situation.get("dueUp"))
    pitcher_ref = situation.get("pitcher")
    if not _mlb_person_id(pitcher_ref) and not baseball_player_name(pitcher_ref):
        pitcher_ref = _mlb_latest_play_participant(summary, "pitcher")
    batter_id = _mlb_person_id(batter_ref)
    pitcher_id = _mlb_person_id(pitcher_ref)
    players = _mlb_players(_mapping(summary.get("boxscore")))
    batter = players.get(batter_id, {})
    pitcher = players.get(pitcher_id, {})
    scoreboard_batter_stats = baseball_player_stats(batter_ref)
    scoreboard_pitcher_stats = baseball_player_stats(pitcher_ref)
    pitch_count = (
        _mlb_value(pitcher.get("pitching"), "pitches")
        or scoreboard_pitcher_stats.get("pitches", "")
        or _mlb_pitcher_pitches(summary, pitcher_id)
    )
    pitcher_era = (
        _mlb_first_value(pitcher.get("pitching"), "era", "ERA")
        or scoreboard_pitcher_stats.get("era", "")
    )
    if pitcher_era in {"-", "-.--", "N/A", "n/a"}:
        pitcher_era = ""
    batter_name = str(
        batter.get("name") or baseball_player_name(batter_ref)
    ).strip()
    pitcher_name = str(
        pitcher.get("name") or baseball_player_name(pitcher_ref)
    ).strip()
    result: dict[str, Any] = {
        "balls": _mlb_number(situation.get("balls")),
        "strikes": _mlb_number(situation.get("strikes")),
        "outs": _mlb_number(situation.get("outs")),
        "onFirst": bool(situation.get("onFirst")),
        "onSecond": bool(situation.get("onSecond")),
        "onThird": bool(situation.get("onThird")),
        "batter_name": batter_name,
        "batter_h": (
            _mlb_value(batter.get("batting"), "hits")
            or scoreboard_batter_stats.get("hits", "")
        ),
        "batter_ab": (
            _mlb_value(batter.get("batting"), "atBats")
            or scoreboard_batter_stats.get("atBats", "")
        ),
        "batter_avg": (
            _mlb_value(batter.get("batting"), "avg")
            or scoreboard_batter_stats.get("avg", "")
        ),
        "pitcher_name": pitcher_name,
        "pitcher_pitches": pitch_count,
        "pitcher_era": pitcher_era,
    }
    result.update(_mlb_last_pitch(summary, situation))
    result.update(_mlb_abs_challenge_fields(summary))
    return {key: value for key, value in result.items() if value not in (None, "")}


def _mlb_live_player_ids(payload: Any) -> tuple[str, str]:
    """Read the active MLB batter and pitcher identifiers from one detail payload."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    situation = _mapping(summary.get("situation")) or _mapping(
        competition.get("situation")
    )
    batter_ref = situation.get("batter")
    if not _mlb_person_id(batter_ref) and not baseball_player_name(batter_ref):
        batter_ref = _first_mapping(situation.get("dueUp"))
    pitcher_ref = situation.get("pitcher")
    if not _mlb_person_id(pitcher_ref) and not baseball_player_name(pitcher_ref):
        pitcher_ref = _mlb_latest_play_participant(summary, "pitcher")
    return _mlb_person_id(batter_ref), _mlb_person_id(pitcher_ref)


def _mlb_live_detail_cache_matches(
    cached: _MlbLiveDetailCache,
    *,
    batter_id: str,
    pitcher_id: str,
    details: Mapping[str, Any],
) -> bool:
    """Reject cached player facts after the active MLB batter or pitcher changes."""

    for role, current_id, name_key in (
        ("batter", batter_id, "batter_name"),
        ("pitcher", pitcher_id, "pitcher_name"),
    ):
        prior_id = cached.batter_id if role == "batter" else cached.pitcher_id
        if current_id and prior_id:
            if current_id != prior_id:
                return False
            continue
        current_name = str(details.get(name_key) or "").strip()
        prior_name = str(cached.values.get(name_key) or "").strip()
        if current_name and prior_name and current_name != prior_name:
            return False
    return True


def _mlb_abs_challenge_fields(payload: Any) -> dict[str, int]:
    """Normalize MLB automated ball-strike challenge counts for the display contract."""

    source = _mapping(payload)
    raw = _mapping(source.get("absChallenges"))
    if not raw:
        raw = _mapping(_mapping(source.get("gameData")).get("absChallenges"))
    if not raw and ("home" in source or "away" in source):
        raw = source
    result: dict[str, int] = {}
    for side in ("home", "away"):
        challenge = _mapping(raw.get(side))
        remaining = _optional_mlb_number(challenge.get("remaining"))
        failed = _optional_mlb_number(challenge.get("usedFailed"))
        if remaining is not None:
            result[f"{side}_challenges"] = remaining
        if failed is not None:
            result[f"{side}_challenges_used"] = failed
    for key in (
        "home_challenges",
        "home_challenges_used",
        "away_challenges",
        "away_challenges_used",
    ):
        value = _optional_mlb_number(source.get(key))
        if value is not None:
            result[key] = value
    return result


def _mlb_team_abbreviations_match(left: str, right: str) -> bool:
    """Match the small set of ESPN and StatsAPI MLB abbreviation differences."""

    first = str(left or "").strip().upper()
    second = str(right or "").strip().upper()
    return first == second or _MLB_TEAM_ABBREVIATION_ALIASES.get(first) == second


def _mlb_statsapi_summary(payload: Any, event_id: str) -> dict[str, Any]:
    """Adapt one MLB StatsAPI live feed to the ESPN summary shape used downstream."""

    source = _mapping(payload)
    live = _mapping(source.get("liveData"))
    game_data = _mapping(source.get("gameData"))
    plays_data = _mapping(live.get("plays"))
    all_plays = _sequence(plays_data.get("allPlays"))
    current = _mapping(plays_data.get("currentPlay"))
    matchup = _mapping(current.get("matchup"))
    if not matchup:
        matchup = next(
            (
                _mapping(_mapping(play).get("matchup"))
                for play in reversed(all_plays)
                if _mapping(_mapping(play).get("matchup"))
            ),
            {},
        )
    linescore = _mapping(live.get("linescore"))
    count = _mapping(current.get("count"))
    offense = _mapping(linescore.get("offense"))
    batter = _statsapi_player_ref(matchup.get("batter"))
    pitcher = _statsapi_player_ref(matchup.get("pitcher"))
    current_about = _mapping(current.get("about"))
    at_bat_id = (
        str(current_about.get("atBatIndex")).strip()
        if current_about.get("atBatIndex") is not None
        else ""
    )
    situation = {
        "balls": count.get("balls", 0),
        "strikes": count.get("strikes", 0),
        "outs": linescore.get("outs", count.get("outs", 0)),
        "onFirst": bool(offense.get("first")),
        "onSecond": bool(offense.get("second")),
        "onThird": bool(offense.get("third")),
        "batter": batter,
        "pitcher": pitcher,
    }
    plays: list[dict[str, Any]] = []
    for index, event in enumerate(_sequence(current.get("playEvents"))):
        normalized = _statsapi_pitch_play(
            event,
            at_bat_id=at_bat_id,
            batter=batter,
            pitcher=pitcher,
            fallback_index=index,
        )
        if normalized:
            plays.append(normalized)
    if current and not plays:
        normalized = _statsapi_pitch_play(
            {
                "playId": at_bat_id,
                "isPitch": bool(_mapping(current.get("pitchData"))),
                "pitchNumber": current.get("pitchIndex"),
                "pitchData": current.get("pitchData"),
                "details": current.get("details"),
            },
            at_bat_id=at_bat_id,
            batter=batter,
            pitcher=pitcher,
            fallback_index=0,
        )
        if normalized:
            plays.append(normalized)
    if not plays:
        for raw_play in reversed(all_plays):
            play = _mapping(raw_play)
            play_about = _mapping(play.get("about"))
            play_matchup = _mapping(play.get("matchup"))
            play_batter = _statsapi_player_ref(play_matchup.get("batter"))
            play_pitcher = _statsapi_player_ref(play_matchup.get("pitcher"))
            play_at_bat_id = (
                str(play_about.get("atBatIndex")).strip()
                if play_about.get("atBatIndex") is not None
                else ""
            )
            for index, event in reversed(tuple(enumerate(_sequence(play.get("playEvents"))))):
                normalized = _statsapi_pitch_play(
                    event,
                    at_bat_id=play_at_bat_id,
                    batter=play_batter,
                    pitcher=play_pitcher,
                    fallback_index=index,
                )
                if normalized:
                    plays.append(normalized)
                    break
            if plays:
                break
    latest_pitch_id = str(_mapping(plays[-1]).get("id") or "").strip() if plays else ""
    if latest_pitch_id:
        situation["lastPlay"] = {"id": latest_pitch_id}
    elif at_bat_id:
        situation["lastPlay"] = {"id": at_bat_id}
    game_teams = _mapping(game_data.get("teams"))
    away_abbr = str(_mapping(game_teams.get("away")).get("abbreviation") or "").strip().upper()
    home_abbr = str(_mapping(game_teams.get("home")).get("abbreviation") or "").strip().upper()
    scoring_plays = _statsapi_scoring_plays(
        all_plays,
        away_abbr=away_abbr,
        home_abbr=home_abbr,
    )
    result = {
        "id": event_id,
        "situation": situation,
        "plays": plays,
        "scoringPlays": scoring_plays,
        "boxscore": _statsapi_boxscore(_mapping(live.get("boxscore"))),
    }
    result.update(_mlb_abs_challenge_fields(game_data.get("absChallenges")))
    return result


def _statsapi_pitch_play(
    value: Any,
    *,
    at_bat_id: str,
    batter: Mapping[str, Any],
    pitcher: Mapping[str, Any],
    fallback_index: int,
) -> dict[str, Any]:
    """Convert one StatsAPI pitch event into the shared pitch-play shape."""

    source = _mapping(value)
    pitch_data = _mapping(source.get("pitchData"))
    details = _mapping(source.get("details"))
    pitch_type = _mapping(details.get("type"))
    if not (
        source.get("isPitch")
        or str(source.get("type") or "").strip().lower() == "pitch"
        or pitch_data
        or pitch_type
    ):
        return {}
    pitch_number = source.get("pitchNumber")
    identifier = str(source.get("playId") or "").strip()
    if not identifier:
        suffix = str(pitch_number) if pitch_number is not None else str(fallback_index)
        identifier = f"{at_bat_id}:{suffix}" if at_bat_id else f"pitch:{suffix}"
    participants = []
    for role, reference in (("pitcher", pitcher), ("batter", batter)):
        player_id = _mlb_person_id(reference)
        if player_id:
            participants.append({"type": role, "athlete": {"id": player_id}})
    return {
        "id": identifier,
        "atBatId": at_bat_id,
        "atBatPitchNumber": pitch_number,
        "participants": participants,
        "pitchVelocity": pitch_data.get("startSpeed"),
        "pitchType": {
            "abbreviation": pitch_type.get("code"),
            "text": pitch_type.get("description") or pitch_type.get("shortDescription"),
        },
    }


def _statsapi_scoring_plays(
    plays: Sequence[Any],
    *,
    away_abbr: str,
    home_abbr: str,
) -> list[dict[str, Any]]:
    """Convert StatsAPI scoring at-bats into the shared alert fact shape."""

    previous_away = 0
    previous_home = 0
    result: list[dict[str, Any]] = []
    for raw_play in plays:
        play = _mapping(raw_play)
        about = _mapping(play.get("about"))
        outcome = _mapping(play.get("result"))
        away_score = _optional_mlb_number(outcome.get("awayScore"))
        home_score = _optional_mlb_number(outcome.get("homeScore"))
        delta = 0
        if away_score is not None:
            delta = max(delta, away_score - previous_away)
        if home_score is not None:
            delta = max(delta, home_score - previous_home)
        rbi = _optional_mlb_number(outcome.get("rbi")) or 0
        is_scoring = bool(about.get("isScoringPlay") or delta > 0 or rbi > 0)
        if is_scoring:
            half = str(about.get("halfInning") or "").strip().lower()
            team = home_abbr if half == "bottom" else away_abbr
            batter = _mapping(_mapping(play.get("matchup")).get("batter"))
            batter_id = str(batter.get("id") or "").strip()
            batter_name = str(batter.get("fullName") or "").strip()
            event_type = str(
                outcome.get("event") or outcome.get("eventType") or ""
            ).strip()
            walk_off = bool(
                about.get("isWalkOff")
                or outcome.get("isWalkOff")
                or re.search(r"\bwalk[- ]off\b", str(outcome.get("description") or ""), re.IGNORECASE)
                or (
                    half == "bottom"
                    and _mlb_number(about.get("inning")) >= 9
                    and home_score is not None
                    and home_score > away_score
                    and previous_home <= previous_away
                )
            )
            result.append({
                "team": team,
                "player_id": batter_id,
                "scorer": batter_name,
                "player": batter_name,
                "athlete": {"id": batter_id, "displayName": batter_name},
                "type": event_type[:18],
                "event_type": str(outcome.get("eventType") or event_type)[:18],
                "text": str(outcome.get("description") or "")[:48],
                "rbi": rbi or delta or 1,
                "score_value": delta or rbi or 1,
                "walk_off": walk_off,
                "inning": about.get("inning"),
                "half_inning": half,
            })
            result[-1].update(_mlb_play_metrics(play))
        if away_score is not None:
            previous_away = away_score
        if home_score is not None:
            previous_home = home_score
    return result


def _mlb_play_metrics(play: Mapping[str, Any]) -> dict[str, Any]:
    """Read Statcast hit and pitch metrics from one MLB play or pitch event."""

    direct = {
        key: play.get(key)
        for key in (
            "home_run_distance",
            "exit_velocity",
            "launch_angle",
            "pitch_speed",
            "pitch_type",
            "spin_rate",
            "release_extension",
        )
        if play.get(key) not in (None, "")
    }
    for event in reversed(_sequence(play.get("playEvents"))):
        source = _mapping(event)
        hit = _mapping(source.get("hitData"))
        pitch = _mapping(source.get("pitchData"))
        details = _mapping(source.get("details"))
        pitch_type = _mapping(details.get("type"))
        values = {
            "home_run_distance": hit.get("totalDistance"),
            "exit_velocity": hit.get("launchSpeed"),
            "launch_angle": hit.get("launchAngle"),
            "pitch_speed": pitch.get("startSpeed"),
            "pitch_type": pitch_type.get("description") or pitch_type.get("code"),
            "spin_rate": _mapping(pitch.get("breaks")).get("spinRate"),
            "release_extension": pitch.get("extension"),
        }
        for key, value in values.items():
            if key not in direct and value not in (None, ""):
                direct[key] = value
    return direct


def _optional_mlb_number(value: Any) -> int | None:
    """Read an optional StatsAPI score without turning missing values into zero."""

    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _statsapi_player_ref(value: Any) -> dict[str, Any]:
    """Convert one StatsAPI matchup player into an ESPN-compatible reference."""

    player = _mapping(value)
    identifier = str(player.get("id") or "").strip()
    name = str(player.get("fullName") or "").strip()
    return {
        "playerId": identifier,
        "athlete": {"id": identifier, "displayName": name},
    } if identifier or name else {}


def _statsapi_first_value(values: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _statsapi_boxscore(boxscore: Mapping[str, Any]) -> dict[str, Any]:
    """Convert StatsAPI game player rows into the compact ESPN stat blocks."""

    teams: list[dict[str, Any]] = []
    for side in ("away", "home"):
        team = _mapping(_mapping(boxscore.get("teams")).get(side))
        batting_rows: list[dict[str, Any]] = []
        pitching_rows: list[dict[str, Any]] = []
        for player in _mapping(team.get("players")).values():
            record = _mapping(player)
            person = _mapping(record.get("person"))
            identifier = str(person.get("id") or "").strip()
            athlete = {
                "id": identifier,
                "displayName": person.get("fullName"),
            }
            stats = _mapping(record.get("stats"))
            batting = _mapping(stats.get("batting"))
            season_stats = _mapping(record.get("seasonStats"))
            season_batting = _mapping(season_stats.get("batting"))
            if identifier and (batting or season_batting):
                batting_rows.append({
                    "athlete": athlete,
                    "stats": [
                        batting.get("hits"),
                        batting.get("atBats"),
                        batting.get("avg") or season_batting.get("avg"),
                    ],
                })
            pitching = _mapping(stats.get("pitching"))
            season_pitching = _mapping(season_stats.get("pitching"))
            position = _mapping(record.get("position"))
            season_era = _statsapi_first_value(season_pitching, "era", "ERA")
            is_pitcher = bool(pitching) or str(
                position.get("abbreviation") or ""
            ).upper() == "P"
            is_pitcher = is_pitcher or str(position.get("code") or "") == "1"
            is_pitcher = is_pitcher or (
                season_era not in (None, "", "-", "-.--")
            )
            if identifier and is_pitcher:
                pitch_count = _statsapi_first_value(
                    pitching, "numberOfPitches", "pitchesThrown", "pitches"
                )
                if pitch_count is None:
                    pitch_count = 0
                pitching_rows.append({
                    "athlete": athlete,
                    "stats": [
                        pitch_count,
                        season_era,
                    ],
                })
        statistics: list[dict[str, Any]] = []
        if batting_rows:
            statistics.append({
                "keys": ["hits", "atBats", "avg"],
                "athletes": batting_rows,
            })
        if pitching_rows:
            statistics.append({
                "keys": ["pitches", "era"],
                "athletes": pitching_rows,
            })
        if statistics:
            teams.append({"statistics": statistics})
    return {"players": teams}


def _mlb_latest_play_participant(
    summary: Mapping[str, Any], role: str
) -> Mapping[str, Any]:
    """Return the latest MLB play participant for one player role."""

    wanted = str(role).strip().lower()
    for play in reversed(_sequence(summary.get("plays"))):
        for participant in _sequence(_mapping(play).get("participants")):
            if str(_mapping(participant).get("type") or "").strip().lower() == wanted:
                return _mapping(participant)
    return {}


def _mlb_players(boxscore: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index summary player names and boxscore columns by ESPN athlete ID."""

    players: dict[str, dict[str, Any]] = {}
    for team in _sequence(boxscore.get("players")):
        for block in _sequence(_mapping(team).get("statistics")):
            values = _mapping(block)
            keys = tuple(str(value) for value in _sequence(values.get("keys")))
            category = "batting" if "atBats" in keys else "pitching" if "pitches" in keys else ""
            if not category:
                continue
            for row in _sequence(values.get("athletes")):
                record = _mapping(row)
                athlete = _mapping(record.get("athlete"))
                identifier = str(athlete.get("id") or "").strip()
                if not identifier:
                    continue
                stats = {
                    key: value
                    for key, value in zip(keys, _sequence(record.get("stats")))
                }
                entry = players.setdefault(identifier, {})
                entry["name"] = str(athlete.get("displayName") or entry.get("name") or "")
                entry[category] = stats
    return players


def _mlb_last_pitch(summary: Mapping[str, Any], situation: Mapping[str, Any]) -> dict[str, Any]:
    """Read the latest real pitch, including one before a new at-bat marker."""

    last = _mapping(situation.get("lastPlay"))
    identifier = str(last.get("id") or "")
    plays = _sequence(summary.get("plays"))
    candidates = [
        item for item in plays
        if identifier and str(_mapping(item).get("id") or "") == identifier
    ]
    candidates.extend(reversed(plays))
    seen: set[str] = set()
    for candidate in candidates:
        data = _mapping(candidate)
        candidate_id = str(data.get("id") or "")
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        raw_speed = data.get("pitchVelocity")
        if raw_speed in (None, ""):
            raw_speed = data.get("velocity") or data.get("speed")
        pitch = _mapping(data.get("pitchType"))
        abbreviation = str(
            pitch.get("abbreviation") or data.get("pitchTypeAbbreviation") or ""
        ).strip()
        full = str(pitch.get("text") or data.get("pitchTypeText") or "").strip()
        label = _mlb_pitch_label(full, abbreviation)
        if raw_speed in (None, "") and not label:
            continue
        result: dict[str, Any] = {}
        speed = _mlb_number(raw_speed)
        if speed:
            result["last_pitch_speed"] = speed
        if label:
            result["last_pitch_type"] = label
        if result:
            return result
    return {}


def _mlb_pitcher_pitches(summary: Mapping[str, Any], pitcher_id: str) -> str:
    """Count completed pitches for the active pitcher from summary play records."""

    if not pitcher_id:
        return ""
    pitches_by_at_bat: dict[str, int] = {}
    for play in _sequence(summary.get("plays")):
        record = _mapping(play)
        participants = _sequence(record.get("participants"))
        participant_ids = {
            _mlb_person_id(participant)
            for participant in participants
            if str(_mapping(participant).get("type") or "").strip().lower() == "pitcher"
        }
        if pitcher_id not in participant_ids:
            continue
        try:
            pitch_number = int(record.get("atBatPitchNumber"))
        except (TypeError, ValueError):
            continue
        at_bat_id = str(record.get("atBatId") or record.get("id") or "").strip()
        if at_bat_id:
            pitches_by_at_bat[at_bat_id] = max(
                pitches_by_at_bat.get(at_bat_id, 0), pitch_number
            )
    total = sum(pitches_by_at_bat.values())
    return str(total) if total else ""


def _mlb_pitch_label(full: str, abbreviation: str) -> str:
    """Return the short fixed MLB pitch label for a 384-pixel panel."""

    normalized = re.sub(r"[^a-z0-9]+", " ", full.lower()).strip()
    if normalized in _MLB_PITCH_LABELS:
        return _MLB_PITCH_LABELS[normalized]
    normalized_abbreviation = abbreviation.upper().replace("-", "").replace(" ", "")
    if normalized_abbreviation in _MLB_PITCH_ABBREVIATIONS:
        return _MLB_PITCH_ABBREVIATIONS[normalized_abbreviation]
    return full.title()[:12] if full else normalized_abbreviation[:12]


def _mlb_value(values: Any, key: str) -> str:
    value = _mapping(values).get(key)
    return "" if value is None else str(value).strip()


def _mlb_first_value(values: Any, *keys: str) -> str:
    for key in keys:
        value = _mlb_value(values, key)
        if value:
            return value
    return ""


def _mlb_number(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
