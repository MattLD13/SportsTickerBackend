"""Detect live score changes and project V2 alert facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from threading import Lock
from time import time
from typing import Any, Callable

from sports_ticker.leagues import allows_college_conferences

from .sports_display import matches_followed_team, sport_family


_LIVE_STATES = frozenset(("in", "half", "crit"))
_BIG_KINDS = frozenset(
    (
        "walk_off",
        "walk_off_rbi_single",
        "walk_off_rbi_double",
        "grand_slam",
        "three_run_hr",
        "hat_trick",
        "interception_td",
        "fumble_td",
        "kick_return_td",
        "punt_return_td",
        "blocked_fg_td",
        "interception",
        "fumble",
        "shorthanded",
        "empty_net",
        "penalty_shot",
        "power_play_goal",
        "safety",
        "shootout_winner",
    )
)
_MAX_ALERTS = 64
_MAX_AGE = 45.0
_FOOTBALL_PLAY_KINDS = frozenset(("interception", "fumble"))


def _number(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _describe(
    sport: object,
    delta: int,
    scoring_play: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    family = sport_family(sport)
    if family == "football":
        play_text = " ".join(
            str(scoring_play.get(key) or "")
            for key in ("type", "event_type", "scoring_type", "text")
        ).lower() if scoring_play else ""
        successful_two_point = (
            (re.search(r"\b(?:two|2)[- ]point conversion\b", play_text) is not None
             or bool(scoring_play and scoring_play.get("conversion_type") == "two_point"))
            and re.search(r"\b(?:failed|no good|unsuccessful)\b", play_text) is None
        )
        if scoring_play and scoring_play.get("conversion_type") == "extra_point" and delta == 1:
            return "extra_point", "EXTRA POINT"
        if scoring_play and scoring_play.get("conversion_type") == "two_point" and delta == 2:
            return "two_point", "2-POINT CONV"
        if "interception" in play_text and "touchdown" in play_text:
            return "interception_td", "INTERCEPTION TD"
        if "fumble return touchdown" in play_text or "fumble recovery" in play_text:
            return "fumble_td", "FUMBLE TD"
        if "kickoff return touchdown" in play_text or (
            "kickoff" in play_text and "touchdown" in play_text and re.search(r"\breturns?\b", play_text)
        ):
            return "kick_return_td", "KICK RETURN TD"
        if "punt return touchdown" in play_text or (
            "punt" in play_text and "touchdown" in play_text
        ):
            return "punt_return_td", "PUNT RETURN TD"
        if "blocked field goal" in play_text and "touchdown" in play_text:
            return "blocked_fg_td", "BLOCKED FG TD"
        if "passing touchdown" in play_text or ("touchdown" in play_text and "pass" in play_text.split("(", 1)[0]):
            return "passing_td", "PASS TD +2PT" if successful_two_point else "PASS TD"
        if "rushing touchdown" in play_text or ("touchdown" in play_text and re.search(r"\b(?:run|rush)\b", play_text)):
            return "rushing_td", "RUSH TD +2PT" if successful_two_point else "RUSH TD"
        if successful_two_point and delta == 2:
            return "two_point", "2-POINT CONV"
        if "field goal" in play_text:
            return "field_goal", "FIELD GOAL"
        if "safety" in play_text:
            return "safety", "SAFETY"
        if "extra point" in play_text or re.search(r"\bpat\b", play_text):
            return "extra_point", "EXTRA POINT"
        if delta in {6, 7, 8}:
            return "touchdown", "TOUCHDOWN"
        if delta == 3:
            return "field_goal", "FIELD GOAL"
        if delta == 1:
            return "extra_point", "EXTRA POINT"
        return "score", f"+{delta} POINTS"
    if family == "baseball":
        play_text = " ".join(
            str(scoring_play.get(key) or "")
            for key in ("type", "kind", "scoring_type", "event_type", "text")
        ).lower() if scoring_play else ""
        home_run = bool(
            re.search(r"\b(home run|homer|homered|homers)\b", play_text)
        )
        if home_run:
            runs = _number(scoring_play.get("score_value")) if scoring_play else None
            runs = runs if runs is not None else delta
            if runs >= 4 or "grand slam" in play_text:
                return "grand_slam", "GRAND SLAM"
            if runs == 3:
                return "three_run_hr", "3-RUN HOME RUN"
            if runs == 2:
                return "two_run_hr", "2-RUN HOME RUN"
            return "home_run", "HOME RUN"
        scoring_type = re.sub(
            r"[^a-z0-9]+",
            " ",
            str(
                scoring_play.get("type")
                or scoring_play.get("kind")
                or scoring_play.get("event_type")
                or ""
            ).lower(),
        ).strip() if scoring_play else ""
        if scoring_type in {"sac fly", "sacrifice fly"}:
            scoring_type = "sacrifice fly"
        if scoring_type in {"sac bunt", "sacrifice bunt"}:
            scoring_type = "sacrifice bunt"
        if scoring_type == "sacrifice":
            if "sacrifice fly" in play_text:
                scoring_type = "sacrifice fly"
            elif "sacrifice bunt" in play_text:
                scoring_type = "sacrifice bunt"
        baseball_types = {
            "single": ("single", "SINGLE"),
            "double": ("double", "DOUBLE"),
            "triple": ("triple", "TRIPLE"),
            "sacrifice fly": ("sacrifice_fly", "SAC FLY"),
            "sacrifice bunt": ("sacrifice_bunt", "SAC BUNT"),
            "walk": ("walk", "WALK"),
            "intentional walk": ("intentional_walk", "INTENTIONAL WALK"),
            "hit by pitch": ("hit_by_pitch", "HIT BY PITCH"),
        }
        if scoring_type in {"single", "double"} and scoring_play:
            runs = _number(scoring_play.get("score_value")) or 0
            is_rbi = bool(scoring_play.get("rbi")) or runs > 0
            if is_rbi:
                if scoring_play.get("walk_off"):
                    return (
                        "walk_off_rbi_single" if scoring_type == "single" else "walk_off_rbi_double",
                        "WALK OFF RBI SINGLE" if scoring_type == "single" else "WALK OFF RBI DOUBLE",
                    )
                return (
                    "rbi_single" if scoring_type == "single" else "rbi_double",
                    "RBI SINGLE" if scoring_type == "single" else "RBI DOUBLE",
                )
        if scoring_type in baseball_types:
            return baseball_types[scoring_type]
        return "run", "RUN SCORES"
    if family == "hockey":
        play_text = " ".join(
            str(scoring_play.get(key) or "")
            for key in ("type", "event_type", "strength", "text")
        ).lower().replace("-", " ") if scoring_play else ""
        if "empty net" in play_text or str(scoring_play.get("strength") if scoring_play else "").upper() in {"ENG", "EMPTY NET"}:
            return "empty_net", "EMPTY NET GOAL"
        if "shorthanded" in play_text or str(scoring_play.get("strength") if scoring_play else "").upper() in {"SHG", "SHORT-HANDED"}:
            return "shorthanded", "SHORTHANDED GOAL"
        if "power play" in play_text or str(scoring_play.get("strength") if scoring_play else "").upper() in {"PPG", "POWER PLAY"}:
            return "power_play_goal", "POWER PLAY GOAL"
        if "penalty shot" in play_text:
            return "penalty_shot", "PENALTY SHOT"
        return "goal", "GOAL"
    if family == "soccer":
        play_text = " ".join(
            str(scoring_play.get(key) or "")
            for key in ("type", "event_type", "goal_type", "text")
        ).lower() if scoring_play else ""
        if "own goal" in play_text:
            return "own_goal", "OWN GOAL"
        if "penalty" in play_text:
            return "penalty_goal", "PENALTY GOAL"
        if "header" in play_text:
            return "header_goal", "HEADER GOAL"
        return "goal", "GOAL"
    return "score", f"+{delta}"






def _football_event_identity(play: Mapping[str, Any]) -> str:
    """Return a stable ESPN play identity for poll-to-poll deduplication."""

    identifier = str(
        play.get("event_id")
        or play.get("play_id")
        or play.get("id")
        or play.get("sequence")
        or play.get("sequenceNumber")
        or ""
    ).strip()
    if identifier:
        return identifier
    return "|".join(
        str(play.get(key) or "").strip()
        for key in ("football_kind", "team", "text", "period", "clock")
    )


def _football_events(
    situation: Mapping[str, Any], game: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    """Read normalized football turnover plays from the shared game projection."""

    values = situation.get("football_plays") or game.get("football_plays")
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(value for value in values if isinstance(value, Mapping) and value.get("football_kind"))


def _has_football_projection(situation: Mapping[str, Any], game: Mapping[str, Any]) -> bool:
    """Return whether the provider supplied a complete football play projection."""

    return "football_plays" in situation or "football_plays" in game


def _football_event_side(game: Mapping[str, Any], play: Mapping[str, Any]) -> str:
    """Resolve the team that owns one normalized football event."""

    team = str(play.get("team") or "").strip().lower()
    for side in ("home", "away"):
        if team and team == str(game.get(f"{side}_abbr") or "").strip().lower():
            return side
    return ""




def _compact_metric(value: object) -> str:
    """Round one Statcast metric for the narrow LED detail line."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(round(number))) if number.is_integer() or abs(number) >= 10 else f"{number:.1f}".rstrip("0").rstrip(".")


def _latest_scoring_play(
    game: Mapping[str, Any], situation: Mapping[str, Any], side: str,
    *, previous_score: int | None = None,
) -> Mapping[str, Any] | None:
    """Return the latest normalized scoring play for one team."""

    scoring_plays = situation.get("scoring_plays") or game.get("scoring_plays")
    if not isinstance(scoring_plays, (list, tuple)):
        return None
    team = str(game.get(f"{side}_abbr") or side).lower()
    matching = [
        play for play in scoring_plays
        if isinstance(play, Mapping)
        and str(play.get("team") or play.get("side") or "").lower() in {team, side}
    ]
    if sport_family(game.get("sport")) == "hockey":
        return _hockey_scoring_play_for_score(game, matching, side)
    if sport_family(game.get("sport")) == "football":
        return _football_scoring_play_for_score(game, matching, side, previous_score)
    if matching:
        return matching[-1]
    if sport_family(game.get("sport")) == "soccer":
        goal_events = situation.get("goal_events") or game.get("goal_events")
        if isinstance(goal_events, (list, tuple)):
            is_home = side == "home"
            for event in reversed(goal_events):
                if not isinstance(event, Mapping) or bool(event.get("is_home")) != is_home:
                    continue
                return {
                    "team": game.get(f"{side}_abbr") or side,
                    "scorer": event.get("player") or "",
                    "type": event.get("goal_type") or "Goal",
                    "goal_type": event.get("goal_type") or "",
                    "text": event.get("goal_type") or "Goal",
                    "assist": event.get("assist") or "",
                }
    return None


def _football_scoring_play_for_score(
    game: Mapping[str, Any], plays: Sequence[Mapping[str, Any]], side: str, previous_score: int | None,
) -> Mapping[str, Any] | None:
    """Bind football detail to the scoring team's observed score increase."""
    target = _number(game.get(f"{side}_score"))
    if target is None:
        return None
    candidates = [play for play in plays if _number(play.get(f"{side}_score")) == target]
    if previous_score is not None:
        interval = [play for play in plays if previous_score < (_number(play.get(f"{side}_score")) or 0) <= target]
        if target - previous_score >= 6:
            touchdowns = [play for play in interval if "touchdown" in str(play.get("type") or "").lower()]
            if touchdowns:
                return touchdowns[-1]
        if not candidates and target - previous_score == 6:
            candidates = [play for play in plays if
                _number(play.get(f"{side}_score")) in {target + 1, target + 2}
                and "touchdown" in str(play.get("type") or "").lower()
                and play.get("conversion_type")]
    return candidates[-1] if candidates else None


def _hockey_scoring_play_for_score(
    game: Mapping[str, Any], plays: Sequence[Mapping[str, Any]], side: str
) -> Mapping[str, Any] | None:
    """Match one hockey goal to its scoreboard state instead of taking the latest team goal."""

    if not plays:
        return None
    target_home = _number(game.get("home_score"))
    target_away = _number(game.get("away_score"))
    if target_home is None or target_away is None:
        return plays[-1]
    score_aware = any(
        _number(play.get("home_score")) is not None
        and _number(play.get("away_score")) is not None
        for play in plays
    )
    if score_aware:
        for play in reversed(plays):
            if (
                _number(play.get("home_score")) == target_home
                and _number(play.get("away_score")) == target_away
            ):
                return play
        return None
    target_team_score = _number(game.get(f"{side}_score"))
    if target_team_score is None or target_team_score <= 0 or len(plays) < target_team_score:
        return None
    return plays[target_team_score - 1]




class ScoreAlertTracker:
    """Keep score memory across scoreboard polls and release recent alerts."""

    def __init__(self, *, clock: Callable[[], float] = time) -> None:
        self._clock = clock
        self._lock = Lock()
        self._scores: dict[str, tuple[int, int, str, str]] = {}
        self._football_events: dict[str, set[str]] = {}
        self._football_projection_ready: dict[str, bool] = {}
        self._alerts: list[dict[str, Any]] = []

    def prime(self, games: Sequence[Mapping[str, Any]]) -> None:
        """Set a complete source baseline without creating score alerts."""

        scores: dict[str, tuple[int, int, str, str]] = {}
        football_events: dict[str, set[str]] = {}
        projection_ready: dict[str, bool] = {}
        for game in games:
            if str(game.get("kind") or game.get("type") or "") != "scoreboard":
                continue
            game_id = str(game.get("id") or "").strip()
            home = _number(game.get("home_score"))
            away = _number(game.get("away_score"))
            if not game_id or home is None or away is None:
                continue
            scores[game_id] = (
                home,
                away,
                str(game.get("status") or ""),
                str(game.get("state") or "").lower(),
            )
            sit = game.get("situation")
            situation = sit if isinstance(sit, Mapping) else {}
            projection_ready[game_id] = _has_football_projection(situation, game)
            football_events[game_id] = {
                _football_event_identity(play)
                for play in _football_events(situation, game)
                if _football_event_identity(play)
            }
        with self._lock:
            self._scores = scores
            self._football_events = football_events
            self._football_projection_ready = projection_ready

    def ingest(self, games: Sequence[Mapping[str, Any]]) -> None:
        """Compare one complete scoreboard observation with the prior poll."""

        now = float(self._clock())
        current_ids: set[str] = set()
        with self._lock:
            for game in games:
                if str(game.get("kind") or game.get("type") or "") != "scoreboard":
                    continue
                game_id = str(game.get("id") or "").strip()
                home = _number(game.get("home_score"))
                away = _number(game.get("away_score"))
                if not game_id or home is None or away is None:
                    continue
                current_ids.add(game_id)
                status = str(game.get("status") or "")
                previous = self._scores.get(game_id)
                sport = str(game.get("sport") or "").lower()
                family = sport_family(sport)
                state = str(game.get("state") or "").lower()
                self._scores[game_id] = (home, away, status, state)
                if family == "basketball":
                    continue
                sit = game.get("situation")
                situation = sit if isinstance(sit, Mapping) else {}
                football_events = _football_events(situation, game)
                seen_football_events = self._football_events.setdefault(game_id, set())
                projection_ready = _has_football_projection(situation, game)
                seed_football_events = False
                if previous is None:
                    seen_football_events.update(
                        _football_event_identity(play)
                        for play in football_events
                        if _football_event_identity(play)
                    )
                    self._football_projection_ready[game_id] = projection_ready
                    continue
                if family == "football" and projection_ready and not self._football_projection_ready.get(game_id, False):
                    seen_football_events.update(
                        _football_event_identity(play)
                        for play in football_events
                        if _football_event_identity(play)
                    )
                    self._football_projection_ready[game_id] = True
                    seed_football_events = True
                elif projection_ready:
                    self._football_projection_ready[game_id] = True
                shootout_winner = str(situation.get("shootout_winner") or "")
                shootout_completed = (
                    family == "hockey"
                    and situation.get("shootout_state") == "completed"
                    and shootout_winner in {"home", "away"}
                    and previous[3] in _LIVE_STATES
                    and state in {"post", "final"}
                )
                if family == "hockey" and situation.get("shootout_state") == "active":
                    continue
                if family == "hockey":
                    self._hydrate_hockey_alerts(game)
                elif family == "football":
                    self._hydrate_football_alerts(game)
                final_score = state in {"post", "final"} and previous[3] in _LIVE_STATES and (
                    home > previous[0] or away > previous[1]
                ) and not (family == "hockey" and previous[2] == "S/O")
                if state not in _LIVE_STATES and not shootout_completed and not final_score:
                    seen_football_events.update(
                        _football_event_identity(play)
                        for play in football_events
                        if _football_event_identity(play)
                    )
                    continue

                def append_alert(
                    side: str,
                    kind: str,
                    headline: str,
                    facts: Mapping[str, Any],
                    points: int,
                    *,
                    event_id: str = "",
                    scoring_play_id: str = "",
                ) -> None:
                    other = "away" if side == "home" else "home"
                    identifier = event_id or f"{game_id}:{home}-{away}:{side}"
                    if any(alert.get("id") == identifier for alert in self._alerts):
                        return
                    self._alerts.append(
                        {
                            "id": identifier,
                            "game_id": game_id,
                            "event_id": event_id,
                            "sport": sport,
                            "ts": now,
                            "side": side,
                            "kind": kind,
                            "headline": headline,
                            **facts,
                            "points": points,
                            "big": kind in _BIG_KINDS,
                            "team_abbr": str(game.get(f"{side}_abbr") or "").upper(),
                            "team_logo": game.get(f"{side}_logo", ""),
                            "team_color": game.get(f"{side}_color", ""),
                            "team_alt_color": game.get(f"{side}_alt_color", ""),
                            "opp_abbr": str(game.get(f"{other}_abbr") or "").upper(),
                            "opp_logo": game.get(f"{other}_logo", ""),
                            "opp_color": game.get(f"{other}_color", ""),
                            "home_abbr": str(game.get("home_abbr") or "").upper(),
                            "away_abbr": str(game.get("away_abbr") or "").upper(),
                            "home_score": home,
                            "away_score": away,
                            "status": facts.get("status", status),
                            "home_conference_id": game.get("home_conference_id", ""),
                            "away_conference_id": game.get("away_conference_id", ""),
                            **({"scoring_play_id": scoring_play_id} if scoring_play_id else {}),
                        }
                    )

                if shootout_completed:
                    append_alert(
                        shootout_winner,
                        "shootout_winner",
                        "SHOOTOUT WINNER",
                        _extract_alert_facts(sport, game, shootout_winner, alert_kind="shootout_winner"),
                        1,
                        event_id=f"{game_id}:shootout:{shootout_winner}",
                    )
                    continue
                if family == "football":
                    for play in football_events:
                        identifier = _football_event_identity(play)
                        if not identifier or identifier in seen_football_events:
                            continue
                        seen_football_events.add(identifier)
                        if seed_football_events:
                            continue
                        if play.get("is_scoring"):
                            continue
                        side = _football_event_side(game, play)
                        if not side:
                            continue
                        kind = str(play.get("football_kind") or "").strip().lower()
                        headline = "INTERCEPTION" if kind == "interception" else "FUMBLE" if kind == "fumble" else ""
                        if not headline:
                            continue
                        append_alert(
                            side,
                            kind,
                            headline,
                            _extract_alert_facts(sport, game, side, alert_kind=kind, event=play),
                            0,
                            event_id=f"{game_id}:football:{identifier}",
                        )
                for side, new_score, old_score in (("home", home, previous[0]), ("away", away, previous[1])):
                    delta = new_score - old_score
                    if delta <= 0:
                        continue
                    scoring_play = _latest_scoring_play(game, situation, side, previous_score=old_score)
                    kind, headline = _describe(sport, delta, scoring_play)
                    facts = _extract_alert_facts(sport, game, side, alert_kind=kind, event=scoring_play)
                    if family == "football" and scoring_play:
                        facts["status"] = _football_scoring_status(scoring_play, status, sport)
                    append_alert(
                        side,
                        kind,
                        headline,
                        facts,
                        delta,
                        scoring_play_id=(
                            str(scoring_play.get("play_id") or "")
                            if family in {"hockey", "football"} and scoring_play
                            else ""
                        ),
                    )
            self._scores = {key: value for key, value in self._scores.items() if key in current_ids}
            self._football_events = {
                key: value for key, value in self._football_events.items() if key in current_ids
            }
            self._football_projection_ready = {
                key: value
                for key, value in self._football_projection_ready.items()
                if key in current_ids
            }
            self._alerts = self._alerts[-_MAX_ALERTS:]

    def _hydrate_football_alerts(self, game: Mapping[str, Any]) -> None:
        """Fill delayed football detail without replaying or retiming the alert."""
        situation = game.get("situation") or {}
        for alert in self._alerts:
            if alert.get("game_id") != game.get("id") or int(alert.get("points") or 0) <= 0:
                continue
            side = alert["side"]
            scored_game = {**game, "home_score": alert["home_score"], "away_score": alert["away_score"]}
            old_score = int(alert[f"{side}_score"]) - int(alert["points"])
            play = _latest_scoring_play(scored_game, situation, side, previous_score=old_score)
            if play is None:
                continue
            kind, headline = _describe(game.get("sport"), int(alert["points"]), play)
            facts = _extract_alert_facts(game.get("sport"), scored_game, side, alert_kind=kind, event=play)
            alert.update(facts, kind=kind, headline=headline, big=kind in _BIG_KINDS,
                         status=_football_scoring_status(play, str(alert.get("status") or ""), str(game.get("sport") or "")),
                         scoring_play_id=str(play.get("play_id") or ""))

    def _hydrate_hockey_alerts(self, game: Mapping[str, Any]) -> None:
        """Match delayed ESPN goal details to each alert's score and refresh assists."""

        game_id = str(game.get("id") or "").strip()
        sit = game.get("situation")
        situation = sit if isinstance(sit, Mapping) else {}
        for alert in reversed(self._alerts):
            if alert.get("game_id") != game_id:
                continue
            side = str(alert.get("side") or "")
            if side not in {"home", "away"}:
                continue
            goal_game = {
                **game,
                "home_score": alert.get("home_score"),
                "away_score": alert.get("away_score"),
            }
            scoring_play = _latest_scoring_play(goal_game, situation, side)
            if scoring_play is None:
                continue
            facts = _extract_alert_facts(str(game.get("sport") or "nhl"), goal_game, side)
            if not facts["player"]:
                continue
            play_id = str(scoring_play.get("play_id") or "")
            previous_scorer = str(alert.get("player") or "").strip().upper()
            scorer = str(facts["player"]).strip().upper()
            new_assists = tuple(value for value in (facts["primary_assist"], facts["secondary_assist"]) if value)
            old_assist_count = sum(bool(alert.get(key)) for key in ("primary_assist", "secondary_assist"))
            changed_goal = bool(
                alert.get("scoring_play_id")
                and play_id
                and alert.get("scoring_play_id") != play_id
            )
            improved = (
                not previous_scorer
                or changed_goal
                or bool(scorer and previous_scorer and scorer != previous_scorer)
                or len(new_assists) > old_assist_count
            )
            if not improved:
                continue
            kind, headline = _describe(
                game.get("sport") or "nhl",
                max(1, int(alert.get("points") or 1)),
                scoring_play,
            )
            alert["kind"] = kind
            alert["headline"] = headline
            alert.update(facts)
            alert["big"] = kind in _BIG_KINDS
            if play_id:
                alert["scoring_play_id"] = play_id

    def recent(self, *, max_age: float = _MAX_AGE, delay: float = 0.0) -> tuple[dict[str, Any], ...]:
        """Return alerts visible at the delayed content timestamp."""

        now = float(self._clock()) - max(0.0, float(delay or 0.0))
        cutoff = now - max(0.0, float(max_age))
        with self._lock:
            return tuple(dict(item) for item in self._alerts if cutoff <= item["ts"] <= now)


def alerts_for_settings(
    alerts: Sequence[Mapping[str, Any]], settings: Any
) -> tuple[Mapping[str, Any], ...]:
    """Keep score takeovers scoped to sports mode and followed teams."""

    if settings.mode != "sports" or not settings.score_alerts or not settings.my_teams:
        return ()
    followed = {str(value).strip().lower() for value in settings.my_teams if str(value).strip()}
    return tuple(
        alert
        for alert in alerts
        if allows_college_conferences(
            str(alert.get("sport") or ""),
            (
                alert.get("home_conference_id"),
                alert.get("away_conference_id"),
            ),
            getattr(settings, "active_conferences", {}),
        )
        and (
            matches_followed_team(
                str(alert.get("sport") or ""),
                str(alert.get("team_abbr") or ""),
                followed,
            )
            or (
                str(alert.get("kind") or "").lower() in _FOOTBALL_PLAY_KINDS
                and matches_followed_team(
                    str(alert.get("sport") or ""),
                    str(alert.get("opp_abbr") or ""),
                    followed,
                )
            )
        )
    )


__all__ = ["ScoreAlertTracker", "alerts_for_settings"]


def _extract_alert_facts(
    sport: str,
    game: Mapping[str, Any],
    side: str,
    *,
    alert_kind: str = "",
    event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one score play into separate display facts."""

    sit = game.get("situation")
    situation = sit if isinstance(sit, Mapping) else {}
    family = sport_family(sport)
    facts = {
        "player": "",
        "data": "",
        "primary_assist": "",
        "secondary_assist": "",
        "down_distance": "",
    }
    if family == "football":
        facts["is_red_zone"] = None
    if alert_kind == "shootout_winner":
        return facts

    explicit = str(situation.get("detail") or game.get("detail") or "").strip()

    if family == "football" and alert_kind in {"interception", "fumble", "interception_td", "fumble_td"}:
        turnover = event or _latest_turnover_play(
            game,
            situation,
            side,
            include_non_scoring=alert_kind in {
                "interception", "fumble", "interception_td", "fumble_td"
            },
        )
        if turnover is not None:
            facts["player"] = str(turnover.get("scorer_full") or turnover.get("player_full") or turnover.get("player") or turnover.get("scorer") or "").strip()
            kind = str(turnover.get("football_kind") or "").casefold()
            data = ["INTERCEPTION" if kind == "interception" else "FUMBLE"]
            yards = _number(turnover.get("return_yards"))
            if yards is not None:
                data.append(f"{yards}YD RET")
            facts["data"] = " ".join(data)
            facts["down_distance"] = _football_down_distance(turnover)
            facts["is_red_zone"] = _football_red_zone(turnover)
            return facts

    if family == "baseball":
        play = _latest_scoring_play(game, situation, side)
        if play is not None:
            facts["player"] = _play_player(play)
            play_text = " ".join(str(play.get(key) or "") for key in ("type", "event_type", "text")).lower()
            if re.search(r"\b(home run|homer|homered|homers)\b", play_text):
                metrics = [
                    f"{metric}FT" for metric in (_compact_metric(play.get("home_run_distance")),) if metric
                ]
                exit_velocity = _compact_metric(play.get("exit_velocity"))
                launch_angle = _compact_metric(play.get("launch_angle"))
                if exit_velocity:
                    metrics.append(f"{exit_velocity}EV")
                if launch_angle:
                    metrics.append(f"{launch_angle}LA")
                facts["data"] = " ".join(metrics)
            else:
                stats = []
                hits = str(play.get("player_h") or "").strip()
                at_bats = str(play.get("player_ab") or "").strip()
                average = str(play.get("player_avg") or "").strip()
                if hits or at_bats:
                    stats.append(f"{hits or '-'}/{at_bats or '-'}")
                if average:
                    stats.append(average[1:] if average.startswith("0.") else average)
                speed = str(play.get("pitch_speed") or situation.get("last_pitch_speed") or "").strip()
                pitch = str(play.get("pitch_type") or situation.get("last_pitch_type") or "").strip()
                pitch_detail = " ".join(value for value in (speed, pitch) if value)
                facts["data"] = " ".join((*stats, pitch_detail)).strip()
            return facts

    if family == "hockey":
        play = _latest_scoring_play(game, situation, side)
        if play is not None:
            facts["player"] = _play_player(play)
            assists = _play_assists(play)
            facts["primary_assist"] = assists[0] if assists else ""
            facts["secondary_assist"] = assists[1] if len(assists) > 1 else ""
        return facts

    if family == "soccer":
        events = situation.get("goal_events") or game.get("goal_events")
        if isinstance(events, (list, tuple)):
            is_home = side == "home"
            matching = [event for event in events if isinstance(event, Mapping) and bool(event.get("is_home")) == is_home]
            if matching:
                event = matching[-1]
                facts["player"] = str(event.get("alert_player") or event.get("player_full") or event.get("player") or "").strip()
                minute = str(event.get("minute") or event.get("time") or "").strip()
                goal_type = "OWN GOAL" if event.get("own_goal") else str(event.get("goal_type") or event.get("type") or "").strip().upper()
                facts["data"] = " ".join(value for value in (minute, goal_type) if value)
                assist = str(event.get("alert_assist") or event.get("assist_full") or event.get("assist") or "").strip()
                facts["primary_assist"] = assist
                return facts

    play = event or _latest_scoring_play(game, situation, side)
    if play is not None:
        facts["player"] = _play_player(play)
        assists = _play_assists(play)
        facts["primary_assist"] = assists[0] if assists else ""
        facts["secondary_assist"] = assists[1] if len(assists) > 1 else ""
        event_type = " ".join(str(play.get(key) or "") for key in ("type", "event_type", "scoring_type", "text")).upper()

        if family == "football":
            if alert_kind in {"extra_point", "two_point"}:
                if play.get("conversion_type") == alert_kind:
                    facts["player"] = str(play.get("conversion_player_full") or "")
                facts["data"] = "EXTRA POINT" if alert_kind == "extra_point" else "2-POINT CONV"
                return facts
            yards = _number(play.get("return_yards") if play.get("football_kind") in {"interception", "fumble"} else play.get("yards"))
            if "INTERCEPTION" in event_type:
                facts["data"] = f"INTERCEPTION {yards}YD RET" if yards is not None else "INTERCEPTION RETURN"
            elif "FUMBLE" in event_type:
                facts["data"] = f"FUMBLE {yards}YD RET" if yards is not None else "FUMBLE RECOVERY"
            elif "FIELD GOAL" in event_type:
                facts["data"] = f"{yards}YD FIELD GOAL" if yards is not None else "FIELD GOAL"
            else:
                passer = str(play.get("passer_full") or play.get("passer") or "").strip()
                if "PASS" in event_type and passer:
                    parts = [f"{yards}YD" if yards is not None else "", "PASS", passer]
                else:
                    run_type = "RUSH" if "RUSH" in event_type else ""
                    parts = [run_type, f"{yards}YD" if yards is not None else ""]
                facts["data"] = " ".join(part for part in parts if part)
            facts["down_distance"] = _football_down_distance(play)
            facts["is_red_zone"] = _football_red_zone(play)
        elif family == "basketball":
            points = _number(play.get("score_value"))
            play_text = event_type.lower()
            facts["data"] = "3PT" if "three point" in play_text or points == 3 else "FT" if "free throw" in play_text else "DUNK" if "dunk" in play_text else "2PT"
        elif family == "hockey":
            facts["data"] = ""
        elif family == "baseball":
            facts["data"] = ""
        else:
            scoring_type = str(play.get("type") or play.get("kind") or "").strip().upper()
            facts["data"] = scoring_type
        if facts["player"] or facts["data"]:
            if facts["data"] or not explicit:
                return facts

    if family == "football":
        return facts
    facts["data"] = explicit or str(situation.get("last_play") or game.get("last_play") or "").strip()
    return facts


def _football_scoring_status(play: Mapping[str, Any], current: str, league: str) -> str:
    """Keep the scoring clock separate from the next drive's game clock."""
    period = str(play.get("period") or "")
    clock = str(play.get("clock") or "").rstrip("'")
    match = re.fullmatch(r"Q?(\d+)(?:st|nd|rd|th)?", period, re.IGNORECASE)
    if not match or not clock:
        return current
    number = int(match[1])
    label = f"Q{number}" if number <= 4 else "OT" + (str(number - 4) if number > 5 else "")
    if league in {"ncf_fbs", "ncf_fcs"} and number > 4:
        return label
    return f"{label} {clock}"


def _play_player(play: Mapping[str, Any]) -> str:
    """Return the full provider name for the player who caused the score."""

    return str(
        play.get("scorer_full")
        or play.get("player_full")
        or play.get("scorer")
        or play.get("player")
        or ""
    ).strip()


def _play_assists(play: Mapping[str, Any]) -> tuple[str, ...]:
    """Keep provider assist order so hockey primary and secondary stay distinct."""

    raw = play.get("assists_full") or play.get("assists") or ()
    values = (raw,) if isinstance(raw, str) else raw if isinstance(raw, Sequence) else ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def _football_down_distance(play: Mapping[str, Any]) -> str:
    """Format the play's down and distance as a compact value such as 4&7."""

    goal = re.fullmatch(r"(\d+)(?:ST|ND|RD|TH)?\s*&\s*GOAL", str(play.get("downDist") or "").upper())
    if goal:
        return f"{goal[1]}&GOAL"
    down = _number(play.get("down"))
    distance = play.get("distance")
    if down is not None and distance not in (None, ""):
        distance_number = _number(distance)
        return f"{down}&{distance_number}" if distance_number is not None else f"{down}&{str(distance).strip().upper()}"

    text = str(play.get("downDist") or "").strip().upper().replace(" AND ", " & ")
    match = re.fullmatch(r"(\d+)(?:ST|ND|RD|TH)?\s*&\s*(\d+|GOAL)", text)
    return f"{match.group(1)}&{match.group(2)}" if match else ""


def _football_red_zone(play: Mapping[str, Any]) -> bool | None:
    """Use the scoring play's field position without reading the next drive."""
    value = play.get("is_red_zone")
    return bool(value) if value is not None else None


def _latest_turnover_play(
    game: Mapping[str, Any],
    situation: Mapping[str, Any],
    side: str,
    *,
    include_non_scoring: bool = False,
) -> Mapping[str, Any] | None:
    """Return the newest normalized turnover assigned to one team."""

    plays = situation.get("football_plays") or game.get("football_plays")
    if not isinstance(plays, (list, tuple)):
        return None
    team = str(game.get(f"{side}_abbr") or side).casefold()
    return next(
        (
            play
            for play in reversed(plays)
            if isinstance(play, Mapping)
            and str(play.get("team") or "").casefold() == team
            and (include_non_scoring or bool(play.get("is_scoring")))
        ),
        None,
    )
