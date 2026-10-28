"""Extract football, soccer, and hockey play details from ESPN summaries."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .payloads import as_mapping as _mapping, as_sequence as _sequence
from .sports_display import (
    display_situation,
    football_red_zone_for_play,
    football_name_matches,
    normalize_football_turnover_play,
    soccer_event,
)
from .espn_events import _competitors, _event_competition, _mlb_person_id
from .espn_mlb import _mlb_number, _mlb_play_metrics, _mlb_players


def _nhl_event_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Read ESPN NHL context before the league source supplies live display facts."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    source = _mapping(summary.get("situation")) or _mapping(competition.get("situation"))
    if not source and not competition:
        return {}
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    projected_competition = dict(competition)
    projected_competition["situation"] = source
    details = display_situation(
        "nhl", projected_competition, home_abbr=home_abbr, away_abbr=away_abbr
    )
    return details


def _soccer_event_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Read goal, red-card, and penalty facts from a live soccer event."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    source = _mapping(summary.get("situation")) or _mapping(competition.get("situation"))
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    details = display_situation("soccer", competition, home_abbr=home_abbr, away_abbr=away_abbr)
    goals: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for play in _event_plays(summary):
        text = " ".join(
            str(value or "")
            for value in (
                play.get("type"), play.get("text"), play.get("shortText"), play.get("description")
            )
        ).lower()
        if "goal" not in text and "red" not in text:
            continue
        team = _event_team_abbr(play, competition, home_abbr, away_abbr)
        participants = _event_participant_names(play, summary)
        event = soccer_event(
            is_home=team == home_abbr,
            player=participants[0] if participants else _event_player_full(play, summary, sport="soccer"),
            minute=_event_clock(play),
            own_goal="own goal" in text,
            assist=participants[1] if len(participants) > 1 else "",
            goal_type=_soccer_goal_type(text),
        )
        if "goal" in text:
            goals.append(event)
        if "red" in text:
            cards.append(event)
    if goals:
        details["goal_events"] = goals
    if cards:
        details["red_cards"] = cards
    shootout = _shootout_details(summary)
    if shootout is not None:
        details["shootout"] = shootout
    if source.get("possession"):
        details["possession"] = _event_team_abbr(source, competition, home_abbr, away_abbr)
    return details


def _event_plays(summary: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return event-like records without depending on one ESPN shape."""

    records: list[Mapping[str, Any]] = []
    for key in ("scoringPlays", "plays", "events", "keyEvents"):
        records.extend(_mapping(value) for value in _sequence(summary.get(key)))
    return tuple(record for record in records if record)


def _event_drive_plays(summary: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return the complete football play stream, including non-scoring plays."""

    drives = _mapping(summary.get("drives"))
    records: list[Mapping[str, Any]] = []
    for key in ("previous", "current"):
        source = drives.get(key)
        drive_values = (source,) if isinstance(source, Mapping) else _sequence(source)
        for drive in drive_values:
            records.extend(_mapping(value) for value in _sequence(_mapping(drive).get("plays")))
    if not records:
        records.extend(_mapping(value) for value in _sequence(summary.get("plays")))
    if not records:
        records.extend(_mapping(value) for value in _sequence(summary.get("scoringPlays")))

    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not record:
            continue
        identifier = str(record.get("id") or record.get("sequenceNumber") or "").strip()
        if identifier and identifier in seen:
            continue
        if identifier:
            seen.add(identifier)
        result.append(record)
    return tuple(result)


def _event_scoring_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize ESPN scoring plays for score-alert detail rendering."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    league = str(item.get("sport") or "").strip().lower()
    raw_scoring = _sequence(summary.get("scoringPlays"))
    records = raw_scoring or _event_plays(summary)
    football = league in {"nfl", "ncf_fbs", "ncf_fcs"}
    drive_plays = {
        str(play.get("id") or ""): play for play in _event_drive_plays(summary)
    } if football else {}
    scoring_plays: list[dict[str, Any]] = []
    for raw_play in records:
        play = _mapping(raw_play)
        if football:
            play = {**drive_plays.get(str(play.get("id") or ""), {}), **play}
        text = str(
            play.get("text")
            or play.get("shortText")
            or play.get("description")
            or ""
        ).strip()
        score_value = play.get("scoreValue")
        is_scoring = bool(
            raw_scoring
            or play.get("scoringPlay")
            or play.get("isScoringPlay")
            or score_value not in (None, "", 0, "0")
            or re.search(r"\b(score|goal|touchdown|field goal|home run|homer|three.?pointer|free throw)\b", text, re.IGNORECASE)
        )
        if not is_scoring:
            continue
        if football and (
            re.search(r"\b(?:no play|overturned|reversed)\b", text, re.IGNORECASE)
            or re.search(r"\b(?:no good|missed|failed)\b", text.split("(", 1)[0], re.IGNORECASE)
        ):
            continue
        team = _event_team_abbr(play, competition, home_abbr, away_abbr)
        football_play = None
        if league in {"nfl", "ncf_fbs", "ncf_fcs"}:
            football_play = _normalize_football_play(
                play, competition, home_abbr, away_abbr, summary, force_scoring=bool(raw_scoring),
            )
            if football_play and football_play.get("team"):
                team = football_play["team"]
        if not team:
            continue
        play_type = play.get("type")
        play_type_text = _mapping(play_type).get("text")
        if not play_type_text and isinstance(play_type, str):
            play_type_text = play_type
        athlete_full = _event_player_full(play, summary, sport=league) or _event_text_player_full(text, sport=league)
        athlete = _compact_event_name(athlete_full)
        scoring_type = str(
            _mapping(play.get("scoringType")).get("displayName")
            or (
                _mapping(play.get("alternativeType")).get("text")
                if league == "mlb"
                else ""
            )
            or play_type_text
            or play.get("scoringType")
            or ""
        ).strip()
        alternative_type = _mapping(play.get("alternativeType"))
        event_type = str(
            play.get("event_type")
            or play.get("eventType")
            or alternative_type.get("type")
            or (scoring_type if league == "mlb" else play_type_text)
            or scoring_type
            or ""
        ).strip()
        rbi = play.get("rbi")
        rbi_value = _mlb_number(rbi) if league == "mlb" and rbi not in (None, "") else 0
        scorer_id = str(play.get("player_id") or "").strip() or _mlb_person_id(play)
        if league == "mlb" and not scorer_id:
            scorer_id = next(
                (
                    _mlb_person_id(_mapping(_mapping(participant).get("athlete")))
                    for participant in _sequence(play.get("participants"))
                    if str(_mapping(participant).get("type") or "").strip().lower() == "batter"
                ),
                "",
            )
        normalized = {
            "team": team,
            "scorer": athlete,
            "player": athlete,
            "type": scoring_type,
            "event_type": event_type,
            "text": text[:180],
        }
        identifier = str(play.get("id") or play.get("sequenceNumber") or "").strip()
        if identifier:
            normalized["play_id"] = identifier
        for source_key, target_key in (
            ("homeScore", "home_score"), ("awayScore", "away_score"),
            ("home_score", "home_score"), ("away_score", "away_score"),
        ):
            if play.get(source_key) is not None:
                normalized[target_key] = play[source_key]
        if athlete_full:
            normalized["scorer_full"] = athlete_full
        if league in {"nfl", "ncf_fbs", "ncf_fcs"}:
            normalized["passer_full"] = _event_football_full_name(_event_passer_full(text), summary, team)
            conversion = re.search(r"\(([^()]+)\)", text)
            if conversion:
                conversion_text = conversion[1].strip()
                if re.search(r"\b(?:kick|extra point)\b", conversion_text, re.IGNORECASE) and not re.search(
                    r"\b(?:no good|missed|failed|blocked)\b", conversion_text, re.IGNORECASE
                ):
                    kicker = re.split(r"\s+(?:kick|extra point)\b", conversion_text, flags=re.IGNORECASE)[0]
                    normalized["conversion_type"] = "extra_point"
                    normalized["conversion_player_full"] = _event_football_full_name(kicker, summary, team)
                elif re.search(r"two[- ]point conversion", conversion_text, re.IGNORECASE) and not re.search(
                    r"\b(?:failed|no good)\b", conversion_text, re.IGNORECASE
                ):
                    normalized["conversion_type"] = "two_point"
                    normalized["conversion_player_full"] = _event_football_full_name(
                        _event_text_player_full(conversion_text, sport="nfl"), summary, team
                    )
        raw_score_value = play.get("scoreValue", play.get("score_value"))
        if raw_score_value not in (None, ""):
            normalized["score_value"] = raw_score_value
            if league == "mlb":
                rbi_value = max(rbi_value, _mlb_number(raw_score_value))
        participant_names = _event_participant_names(play, summary)
        if participant_names and not athlete:
            normalized["scorer"] = _compact_event_name(participant_names[0])
            normalized["player"] = normalized["scorer"]
        if not athlete and not participant_names:
            text_player = _event_text_player(text)
            if text_player:
                normalized["scorer"] = text_player
                normalized["player"] = text_player
        if league in {"nba", "march_madness"} and len(participant_names) > 1:
            normalized["assists_full"] = participant_names[1:]
            normalized["assists"] = tuple(
                _compact_event_name(name) for name in participant_names[1:]
            )
        if league == "nhl":
            if team.upper() in {home_abbr.upper(), away_abbr.upper()}:
                normalized["is_home"] = team.upper() == home_abbr.upper()
            assists = _event_assist_names(play, summary, athlete)
            if assists:
                normalized["assists_full"] = assists
                normalized["assists"] = tuple(_compact_event_name(name) for name in assists)
            strength = _mapping(play.get("strength"))
            strength_text = str(
                strength.get("abbreviation") or strength.get("text") or ""
            ).strip()
            if strength_text:
                normalized["strength"] = strength_text
            shot_info = _mapping(play.get("shotInfo"))
            shot_type = str(shot_info.get("text") or "").strip()
            if shot_type and shot_type.lower() != "none":
                normalized["shot_type"] = shot_type
        if league in {"nfl", "ncf_fbs", "ncf_fcs"}:
            yards = _event_yards(text)
            if yards is not None:
                normalized["yards"] = yards
            passer = _event_passer(text)
            if passer:
                normalized["passer"] = passer
            if football_play:
                normalized.update(
                    {
                        key: value
                        for key, value in football_play.items()
                        if key not in {"team", "scorer", "player", "text"}
                    }
                )
                if football_play.get("team"):
                    normalized["team"] = football_play["team"]
                if football_play.get("scorer"):
                    normalized["scorer"] = football_play["scorer"]
                    normalized["player"] = football_play["scorer"]
        clock = _event_clock(play)
        if league == "nhl" or league in {"nfl", "ncf_fbs", "ncf_fcs"}:
            clock = clock.rstrip("'")
        period = _mapping(play.get("period"))
        period_text = str(period.get("displayValue") or period.get("number") or "").strip()
        if league in {"nfl", "ncf_fbs", "ncf_fcs"} and period_text.isdigit():
            period_text = f"Q{period_text}"
        if clock:
            normalized["clock"] = clock
        if period_text:
            normalized["period"] = period_text
        if league == "mlb":
            normalized.update(_mlb_play_metrics(play))
            if scorer_id:
                normalized["player_id"] = scorer_id
                batter_stats = _mlb_players(_mapping(summary.get("boxscore"))).get(scorer_id, {}).get("batting", {})
                for source_key, target_key in (("hits", "player_h"), ("atBats", "player_ab"), ("avg", "player_avg")):
                    value = batter_stats.get(source_key)
                    if value not in (None, ""):
                        normalized[target_key] = value
            if rbi_value or re.search(r"\b(single|double)\w*\b.*\bscored\b", text, re.IGNORECASE):
                normalized["rbi"] = rbi_value or 1
            normalized["walk_off"] = bool(
                play.get("walk_off")
                or play.get("walkOff")
                or re.search(r"\bwalk[- ]off\b", text, re.IGNORECASE)
            )
        scoring_plays.append(normalized)
    return {"scoring_plays": scoring_plays} if scoring_plays else {}


def _event_football_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize football turnovers and player context from ESPN drive plays."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    plays: list[dict[str, Any]] = []
    scoring_ids = {str(_mapping(play).get("id") or "") for play in _sequence(summary.get("scoringPlays"))}
    for raw_play in _event_drive_plays(summary):
        normalized = _normalize_football_play(
            raw_play,
            competition,
            home_abbr,
            away_abbr,
            summary,
            force_scoring=str(raw_play.get("id") or "") in scoring_ids,
        )
        if normalized and normalized.get("football_kind"):
            plays.append(normalized)
    return {"football_plays": plays}


def _normalize_football_play(
    play: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
    summary: Mapping[str, Any],
    *,
    force_scoring: bool = False,
) -> dict[str, Any] | None:
    """Normalize one authoritative ESPN football play without text-only scoring guesses."""

    text = str(
        play.get("shortText")
        or play.get("text")
        or play.get("description")
        or ""
    ).strip()
    play_type = _mapping(play.get("type"))
    type_text = str(
        play_type.get("text")
        or play.get("event_type")
        or play.get("eventType")
        or ""
    ).strip()
    lower = f"{type_text} {text}".lower()
    review = _mapping(play.get("review"))
    if review.get("upheld") is False and "revers" in lower:
        return None

    is_scoring = force_scoring or _event_boolean(play.get("scoringPlay")) or _event_boolean(play.get("isScoringPlay"))
    kind = "interception" if "intercept" in lower else "fumble" if "fumble" in lower else ""
    if not kind and not is_scoring:
        return None

    event_id = str(play.get("id") or play.get("sequenceNumber") or "").strip()
    offense = _event_participant_team(play, competition, home_abbr, away_abbr, "offense")
    defense = _event_participant_team(play, competition, home_abbr, away_abbr, "defense")
    start = _event_team_abbr(_mapping(play.get("start")), competition, home_abbr, away_abbr)
    end = _event_team_abbr(_mapping(play.get("end")), competition, home_abbr, away_abbr)
    explicit = _event_team_abbr(play, competition, home_abbr, away_abbr)
    if kind == "interception":
        team = explicit or defense or end or start or offense
    elif kind == "fumble":
        team = end if _event_boolean(play.get("isTurnover")) and end and end != start else offense or start or explicit or end
    else:
        team = explicit or offense or start or end

    interceptor = _event_interceptor(text) if kind == "interception" else ""
    if kind == "interception" and not interceptor:
        interceptor = _event_interception_returner(text)
    fumbler = _event_fumbler(text) if kind == "fumble" else ""
    recoverer = _event_recoverer(text) if kind == "fumble" else ""
    forced_by = _event_forced_by(text) if kind == "fumble" else ""
    if kind == "fumble" and not recoverer:
        recoverer = _event_fumble_returner(text)
    if kind == "fumble" and not recoverer and "recovers" in lower:
        recoverer = fumbler
    passer = _event_passer(text) if kind == "interception" else ""
    return_yards = _event_return_yards(text, kind)
    if return_yards is None and kind in {"interception", "fumble"}:
        return_yards = _event_yards(text)
    scorer = _event_player(play, summary)
    if kind == "interception" and interceptor:
        scorer = interceptor
    elif kind == "fumble" and is_scoring and recoverer:
        scorer = recoverer
    if not scorer:
        scorer = _event_text_player(text)
    full_player = _event_player_full(play, summary, sport="nfl") or _event_text_player_full(text, sport="nfl")
    full_player = _event_football_full_name(full_player, summary, team)
    if full_player and not kind:
        scorer = _compact_event_name(full_player)
    if kind:
        identity = normalize_football_turnover_play(
            play, situation={}, competition=competition, home_abbr=home_abbr, away_abbr=away_abbr,
            player_catalog=_event_boxscore_players(summary),
        )
        if identity.get("player"):
            full_player = identity["player"]
            scorer = _compact_event_name(full_player)
        if identity.get("team"):
            team = identity["team"]

    period = _mapping(play.get("period"))
    period_text = str(period.get("displayValue") or period.get("number") or "").strip()
    if period_text.isdigit():
        period_text = f"Q{period_text}"
    clock = _event_clock(play).rstrip("'")
    start_state = _mapping(play.get("start"))
    result: dict[str, Any] = {
        "event_id": event_id,
        "football_kind": kind,
        "team": team,
        "scorer": scorer,
        "player": scorer,
        "scorer_full": full_player,
        "player_full": full_player,
        "event_type": type_text,
        "text": text[:180],
        "is_scoring": is_scoring,
        "is_turnover": _event_boolean(play.get("isTurnover")) or kind == "interception",
    }
    for key, value in (
        ("interceptor", interceptor),
        ("fumbler", fumbler),
        ("recoverer", recoverer),
        ("forced_by", forced_by),
        ("passer", passer),
        ("return_yards", return_yards),
        ("period", period_text),
        ("clock", clock),
    ):
        if value not in (None, ""):
            result[key] = value
    for source_key, target_key in (("down", "down"), ("distance", "distance")):
        value = start_state.get(source_key)
        if value not in (None, ""):
            result[target_key] = value
    if start_state.get("shortDownDistanceText"):
        result["downDist"] = str(start_state["shortDownDistanceText"])
    stat_yardage = play.get("statYardage")
    if stat_yardage not in (None, ""):
        try:
            result["yards"] = int(stat_yardage)
        except (TypeError, ValueError):
            pass
    if return_yards is not None:
        result["yards"] = return_yards
    result["is_red_zone"] = football_red_zone_for_play(
        play, situation={}, competition=competition, home_abbr=home_abbr, away_abbr=away_abbr,
    )
    return result


def _event_boolean(value: Any) -> bool:
    """Read ESPN boolean fields without treating the string false as true."""

    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def _event_participant_team(
    play: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
    role: str,
) -> str:
    """Resolve one offense or defense team from ESPN play participants."""

    for participant in _sequence(play.get("teamParticipants")):
        record = _mapping(participant)
        if str(record.get("type") or "").strip().lower() != role:
            continue
        identifier = record.get("id") or _mapping(record.get("team")).get("id")
        return _event_team_abbr(
            {"teamId": identifier},
            competition,
            home_abbr,
            away_abbr,
        )
    return ""


def _event_interceptor(text: str) -> str:
    """Read the defender named after ESPN's interception marker."""

    match = re.search(r"\bINTERCEPTED\s+by\s+(?:[A-Z]{2,4}-)?([A-Z][A-Za-z.'-]*)", text, re.IGNORECASE)
    return _compact_event_name(match.group(1)) if match else ""


def _event_interception_returner(text: str) -> str:
    """Read an interception-return scorer when ESPN omits the interception clause."""

    match = re.search(
        r"^\s*(.+?)\s+\d+\s+Yd\s+Interception\s+Return\b",
        text,
        re.IGNORECASE,
    )
    return _compact_event_name(match.group(1)) if match else ""


def _event_fumbler(text: str) -> str:
    """Read the ball carrier named before ESPN's fumble marker."""

    prefix = re.split(r"FUMBLES", text, maxsplit=1, flags=re.IGNORECASE)[0]
    prefix = re.sub(r"^\s*(?:\([^)]*\)\s*)+", "", prefix)
    match = re.match(
        r"\s*([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]+)?)\b",
        prefix,
    )
    if match and match.group(1).strip().upper() in {"PUNT", "KICKOFF", "SNAP"}:
        return ""
    return _compact_event_name(match.group(1)) if match else ""


def _event_recoverer(text: str) -> str:
    """Read the player named after ESPN's fumble recovery marker."""

    match = re.search(r"\bRECOVERED\s+by\s+(?:[A-Z]{2,4}-)?([A-Z][A-Za-z.'-]*)", text, re.IGNORECASE)
    return _compact_event_name(match.group(1)) if match else ""


def _event_fumble_returner(text: str) -> str:
    """Read a fumble-return scorer when ESPN omits the recovery clause."""

    match = re.search(
        r"^\s*(.+?)\s+\d+\s+Yd\s+Fumble\s+Return\b",
        text,
        re.IGNORECASE,
    )
    return _compact_event_name(match.group(1)) if match else ""


def _event_forced_by(text: str) -> str:
    """Read the first forced-fumble defender from ESPN's parenthetical text."""

    match = re.search(r"FUMBLES\s*\(([^)]+)\)", text, re.IGNORECASE)
    return _compact_event_name(match.group(1)) if match else ""


def _event_return_yards(text: str, kind: str) -> int | None:
    """Read return yardage only from the interception or fumble return segment."""

    marker = "INTERCEPTED" if kind == "interception" else "FUMBLES"
    tail = text[text.upper().find(marker):] if marker in text.upper() else text
    values = re.findall(r"\bfor\s+(\d+)\s+yards?\b", tail, re.IGNORECASE)
    return int(values[-1]) if values else None


def _event_team_abbr(
    value: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
) -> str:
    """Resolve an ESPN team identifier to the compact display abbreviation."""

    raw = value.get("team") or value.get("teamId") or value.get("team_id") or value.get("possession")
    team = _mapping(raw)
    candidate = str(team.get("abbreviation") or team.get("id") or raw or "").strip()
    if candidate.upper() in {home_abbr.upper(), away_abbr.upper()}:
        return candidate.upper()
    for competitor in _competitors(competition.get("competitors")):
        source = _mapping(competitor.get("team"))
        if candidate and candidate == str(source.get("id") or ""):
            return home_abbr if str(competitor.get("homeAway") or "").lower() == "home" else away_abbr
    return ""


def _event_player(
    play: Mapping[str, Any], summary: Mapping[str, Any] | None = None
) -> str:
    """Return the scorer or carded player's compact surname."""

    return _compact_event_name(_event_player_full(play, summary))


def _event_boxscore_athletes(
    summary: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Index ESPN boxscore athlete names for play participant IDs."""

    result: dict[str, str] = {}
    for record in _event_boxscore_players(summary):
        athlete = _mapping(record.get("athlete"))
        identifier = str(athlete.get("id") or "").strip()
        name = _event_person_name(athlete, {})
        if identifier and name:
            result[identifier] = name
    return result


def _event_person_name(
    athlete: Mapping[str, Any],
    boxscore_athletes: Mapping[str, str],
) -> str:
    """Return one full play participant name from inline or boxscore data."""

    return str(
        athlete.get("displayName")
        or athlete.get("fullName")
        or athlete.get("shortName")
        or boxscore_athletes.get(str(athlete.get("id") or "").strip())
        or ""
    ).strip()


def _event_participant_names(
    play: Mapping[str, Any],
    summary: Mapping[str, Any] | None,
    *,
    sport: str = "",
) -> tuple[str, ...]:
    """Return role-ordered full participant names from one ESPN play."""

    athletes = _event_boxscore_athletes(summary)
    records = tuple(_mapping(value) for value in _sequence(play.get("participants")))
    ordered = sorted(
        enumerate(records),
        key=lambda pair: (_event_role_priority(pair[1], sport), pair[0]),
    )
    result: list[str] = []
    for _, participant in ordered:
        name = _event_person_name(_mapping(_mapping(participant).get("athlete")), athletes)
        if name and name not in result:
            result.append(name)
    return tuple(result)


def _event_assist_names(
    play: Mapping[str, Any],
    summary: Mapping[str, Any] | None,
    scorer: str,
) -> tuple[str, ...]:
    """Read hockey assists by participant role, then use ESPN text as a fallback."""

    athletes = _event_boxscore_athletes(summary)
    tagged: list[str] = []
    participants = tuple(_mapping(value) for value in _sequence(play.get("participants")))
    has_roles = False
    for participant in participants:
        raw_role = participant.get("type")
        role = str(_mapping(raw_role).get("text") or raw_role or "").strip().lower()
        has_roles = has_roles or bool(role)
        if not re.search(r"\bassist(?:er)?\b", role):
            continue
        name = _event_person_name(_mapping(participant.get("athlete")), athletes)
        compact = name.strip()
        if compact and compact not in tagged:
            tagged.append(compact)
    if tagged:
        return tuple(tagged)

    text = str(play.get("text") or play.get("shortText") or play.get("description") or "")
    match = re.search(r"\bassists?:\s*(.+)$", text, re.IGNORECASE)
    if match:
        scorer_name = _compact_event_name(scorer)
        names: list[str] = []
        for value in match.group(1).split(","):
            name = re.sub(r"\s*\([^)]*\)", "", value).strip(" .;:")
            compact = name.strip()
            if compact and _compact_event_name(compact) != scorer_name and compact not in names:
                names.append(compact)
        return tuple(names)
    if has_roles:
        return ()
    scorer_name = _compact_event_name(scorer)
    return tuple(dict.fromkeys(
        compact
        for name in _event_participant_names(play, summary)
        if (compact := name.strip()) and _compact_event_name(compact) != scorer_name
    ))


def _compact_event_name(value: object) -> str:
    """Return one participant surname for a narrow alert detail line."""

    raw = str(value or "").strip().strip(".,;:()")
    text = raw
    if not text:
        return ""
    parts = text.replace(".", "").split()
    if len(parts) == 1 and "." in raw:
        return raw.rsplit(".", 1)[-1].upper()[:12]
    if len(parts) > 1 and parts[-1].upper() in {"JR", "SR", "II", "III", "IV", "V"}:
        return f"{parts[-2]} {parts[-1]}".upper()[:12]
    return parts[-1].upper()[:12]


def _event_yards(text: str) -> int | None:
    """Read a scoring-play yard count from ESPN text."""

    match = re.search(r"(?<!\w)(-?\d+)\s+yds?\b", text.split("(", 1)[0], re.IGNORECASE)
    return int(match.group(1)) if match else None


def _event_passer(text: str) -> str:
    """Read a quarterback name from one ESPN passing touchdown description."""

    return _compact_event_name(_event_passer_full(text))


def _event_text_player(text: str) -> str:
    """Read the compact scorer name from ESPN scoring text."""

    return _compact_event_name(_event_text_player_full(text))


def _soccer_goal_type(text: str) -> str:
    """Read a compact soccer goal type from event text."""

    lower = text.lower()
    for label, needle in (
        ("PENALTY", "penalty"),
        ("HEADER", "header"),
        ("FREE KICK", "free kick"),
        ("VOLLEY", "volley"),
    ):
        if needle in lower:
            return label
    return ""


def _event_clock(play: Mapping[str, Any]) -> str:
    """Return one compact event time for soccer side-lane labels."""

    clock = _mapping(play.get("clock"))
    value = clock.get("displayValue") or clock.get("value") or play.get("time") or ""
    text = str(value).strip()
    return text if not text or text.endswith("'") else f"{text}'"


def _shootout_details(summary: Mapping[str, Any]) -> dict[str, list[str]] | None:
    """Normalize penalty attempts when ESPN exposes them in one event."""

    raw = summary.get("shootout") or summary.get("shootoutDetails") or summary.get("penaltyShootout")
    source = _mapping(raw)
    if not source:
        return None

    def side(name: str) -> list[str]:
        values = _sequence(source.get(name) or source.get(f"{name}Results"))
        outcome: list[str] = []
        for value in values:
            item = _mapping(value)
            text = str(item.get("result") or item.get("outcome") or value).lower()
            outcome.append(
                "goal" if text in {"goal", "score", "scored", "made"}
                else "miss" if text in {"miss", "missed", "save", "saved", "failed"}
                else "pending"
            )
        return outcome

    home = side("home")
    away = side("away")
    return {"home": home, "away": away} if home or away else None


def _event_player_full(
    play: Mapping[str, Any],
    summary: Mapping[str, Any] | None = None,
    *,
    sport: str = "",
) -> str:
    """Return the full name of the primary participant in one play."""

    athlete = _mapping(play.get("athlete") or play.get("player"))
    text = str(
        athlete.get("displayName")
        or athlete.get("fullName")
        or athlete.get("shortName")
        or play.get("athleteName")
        or play.get("playerName")
        or ""
    ).strip()
    if not text:
        names = _event_participant_names(play, summary, sport=sport)
        if names:
            text = names[0]
    return text.strip()


def _event_boxscore_players(summary: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    """Index boxscore names and teams for turnover identity resolution."""

    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    boxscore = _mapping(_mapping(summary).get("boxscore"))
    for group in _sequence(boxscore.get("players")):
        team = _mapping(_mapping(group).get("team"))
        for statistics in _sequence(_mapping(group).get("statistics")):
            for record in _sequence(_mapping(statistics).get("athletes")):
                athlete = _mapping(_mapping(record).get("athlete"))
                identifier = str(athlete.get("id") or "").strip()
                if identifier:
                    result[(str(team.get("id") or ""), identifier)] = {"athlete": athlete, "team": team}
    return tuple(result.values())


def _event_role_priority(participant: Mapping[str, Any], sport: str) -> int:
    """Sort scorers before helpers, and helpers before unrelated participants."""

    del sport
    role = " ".join(
        str(participant.get(key) or "")
        for key in ("type", "role", "displayRole", "description")
    ).casefold().replace("_", " ")
    primary = (
        "scorer", "goal scorer", "goalscorer", "batter", "shooter",
        "receiver", "rusher", "runner", "interceptor", "recoverer",
    )
    if any(value in role for value in primary):
        return 0
    if any(value in role for value in ("assist", "passer", "goalkeeper")):
        return 2
    return 1


def _event_football_full_name(token: str, summary: Mapping[str, Any], team: str) -> str:
    """Resolve one unambiguous football name from the same summary and team."""
    matches = set()
    for record in _event_boxscore_players(summary):
        if str(_mapping(record.get("team")).get("abbreviation") or "").upper() != team.upper():
            continue
        athlete = _mapping(record.get("athlete"))
        name = str(athlete.get("displayName") or athlete.get("fullName") or "").strip()
        if name and (football_name_matches(token, name) or token.casefold() == str(athlete.get("shortName") or "").casefold()):
            matches.add(name)
    return next(iter(matches)) if len(matches) == 1 else token


def _event_text_player_full(text: str, *, sport: str = "") -> str:
    """Read a full primary scorer name from common ESPN play descriptions."""

    prefix = text.split("(", 1)[0].strip()
    if sport in {"nfl", "ncf_fbs", "ncf_fcs"}:
        for pattern in (
            r"(?:^|,\s*)([^,]+?)\s+returns?(?:\s+for)?\s+\d+\s+yds?\b",
            r"\bpass(?:es)?(?: complete)? to\s+(.+?)\s+for\s+-?\d+\s+yds?\b",
            r"\bpass(?:es)? to\s+(.+?)\s+for\s+(?:two|2)[- ]point conversion\b",
            r"^(.+?)\s+(?:run|runs|rush|rushed)(?:\s+for)?\s+-?\d+\s+yds?\b",
            r"^(.+?)\s+(?:run|rush)(?:\s+for)?\s+(?:two|2)[- ]point conversion\b",
        ):
            match = re.search(pattern, prefix, re.IGNORECASE)
            if match:
                return match[1].strip()
    match = re.match(r"(.+?)\s+\d+\s+Yd\b", prefix, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    if sport in {"nfl", "ncf_fbs", "ncf_fcs"}:
        match = re.match(r"^(.+?)\s+(?:field goal|extra point|kick)\b", prefix, re.IGNORECASE)
        if match:
            return match[1].strip()
    if sport in {"mlb", "baseball"}:
        match = re.match(
            r"(.+?)\s+(?:singled|doubled|tripled|homers?|homered|walked|walks?|"
            r"strikes? out|grounds? out|flies? out|lines? out|hits? a home run)\b",
            prefix,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        match = re.search(
            r"\b(?:single|double|triple|home run) by\s+([^,.;()]+)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    if sport in {"nba", "march_madness", "basketball"}:
        match = re.match(r"(.+?)\s+(?:makes?|made|hits?)\b", prefix, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    if sport == "nhl":
        match = re.search(r"\bgoal\s+by\s+([^,.;()]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.match(r"(.+?)\s+(?:scores?|scored)\b", prefix, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    if sport.startswith("soccer"):
        match = re.search(r"\bscorer\s*[:=]\s*([^,.;()]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _event_passer_full(text: str) -> str:
    """Read a quarterback's full name from one ESPN passing-play description."""

    text = text.split("(", 1)[0].strip()
    match = re.search(r"\bpass from\s+([^()]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.match(r"(.+?)\s+pass(?:es)?\s+(?:to|complete|incomplete)\b", text, re.IGNORECASE)
    if match:
        return match[1].strip()
    match = re.search(r"\b([A-Z][A-Za-z.'-]*)\s+pass\b", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""
