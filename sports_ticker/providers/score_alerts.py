"""Detect live score changes and build V1-compatible overlay payloads."""

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
        "pick_six",
        "fumble_td",
        "kick_return_td",
        "punt_return_td",
        "shorthanded",
        "empty_net",
        "penalty_shot",
        "power_play_goal",
        "safety",
        "lead_taking_dunk",
        "game_winning_dunk",
    )
)
_MAX_ALERTS = 64
_MAX_AGE = 45.0


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
            "two-point conversion" in play_text
            and "failed" not in play_text
        )
        if "interception return touchdown" in play_text:
            return "pick_six", "PICK SIX"
        if "fumble return touchdown" in play_text or "fumble recovery" in play_text:
            return "fumble_td", "FUMBLE TD"
        if "kickoff return touchdown" in play_text:
            return "kick_return_td", "KICK RETURN TD"
        if "punt return touchdown" in play_text or (
            "punt" in play_text and "touchdown" in play_text
        ):
            return "punt_return_td", "PUNT RETURN TD"
        if "blocked field goal" in play_text and "touchdown" in play_text:
            return "blocked_fg_td", "BLOCKED FG TD"
        if "passing touchdown" in play_text:
            return "passing_td", "PASS TD +2PT" if successful_two_point else "PASS TD"
        if "rushing touchdown" in play_text:
            return "rushing_td", "RUSH TD +2PT" if successful_two_point else "RUSH TD"
        if successful_two_point and delta == 2:
            return "two_point", "2-POINT CONV"
        if "field goal" in play_text:
            return "field_goal", "FIELD GOAL"
        if "safety" in play_text:
            return "safety", "SAFETY"
        if "extra point" in play_text or "pat" in play_text:
            return "extra_point", "EXTRA POINT"
        if delta >= 6:
            return "touchdown", "TOUCHDOWN"
        if delta == 3:
            return "field_goal", "FIELD GOAL"
        if delta == 2:
            return "safety", "SAFETY"
        return "extra_point", "EXTRA POINT"
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
    if family == "basketball":
        play_text = " ".join(
            str(scoring_play.get(key) or "")
            for key in ("type", "event_type", "text")
        ).lower() if scoring_play else ""
        points = _number(scoring_play.get("score_value")) if scoring_play else None
        if "free throw" in play_text:
            return "free_throw", "FREE THROW"
        if "three point" in play_text or "3-point" in play_text or points == 3:
            return "three", "3-POINTER"
        if "dunk" in play_text:
            return "dunk", "DUNK"
        if "layup" in play_text or "finger roll" in play_text:
            return "layup", "LAYUP"
        return "bucket", "BUCKET"
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


def _extract_alert_detail(sport: str, game: Mapping[str, Any], side: str) -> str:
    """Extract clean play details (scorer, assists, goal type) for score alerts."""

    sit = game.get("situation")
    situation = sit if isinstance(sit, Mapping) else {}
    family = sport_family(sport)
    if family == "baseball":
        return _baseball_alert_detail(game, situation, side)
    explicit = str(situation.get("detail") or game.get("detail") or "").strip()
    if explicit:
        return explicit[:24].upper()

    is_home = (side == "home")

    if family == "soccer":
        goal_events = situation.get("goal_events") or game.get("goal_events")
        if isinstance(goal_events, (list, tuple)) and goal_events:
            matching = [
                g for g in goal_events
                if isinstance(g, Mapping) and bool(g.get("is_home")) == is_home
            ]
            if matching:
                last_g = matching[-1]
                player = str(last_g.get("player") or "").strip().upper()
                minute = str(last_g.get("minute") or last_g.get("time") or "").strip()
                own_goal = bool(last_g.get("own_goal"))
                g_type = str(last_g.get("goal_type") or last_g.get("type") or "").strip().upper()

                base = " ".join(part for part in (player, minute) if part).strip()
                typed = base
                if own_goal:
                    typed = f"{base} (OG)".strip()
                elif g_type in {"PEN", "PENALTY", "HEADER", "FREE KICK", "VOLLEY"}:
                    typed = f"{base} ({g_type[:3] if g_type == 'PENALTY' else g_type})".strip()
                assist = str(last_g.get("assist") or "").strip().upper()
                candidates = [
                    f"{base} A:{assist}".strip() if assist else "",
                    typed,
                    base,
                    player,
                ]
                for candidate in candidates:
                    if candidate and len(candidate) <= 24:
                        return candidate
                if candidates[0]:
                    return candidates[0][:24].rstrip()
                if typed:
                    return typed[:24].rstrip()

    if family == "hockey":
        scoring_plays = situation.get("scoring_plays") or game.get("scoring_plays")
        if isinstance(scoring_plays, (list, tuple)) and scoring_plays:
            matching = [
                p for p in scoring_plays
                if isinstance(p, Mapping) and (
                    str(p.get("team") or p.get("side") or "").lower() == str(game.get(f"{side}_abbr") or side).lower()
                )
            ]
            if matching:
                last_p = matching[-1]
                scorer = str(last_p.get("scorer") or last_p.get("player") or "").strip().upper()
                strength = str(last_p.get("strength") or "").strip().upper()
                assists = [
                    str(a).strip().upper()
                    for a in (last_p.get("assists") or ())
                    if str(a).strip()
                ]
                if scorer:
                    if assists:
                        for count in (2, 1):
                            candidate = f"{scorer} ({', '.join(assists[:count])})"
                            if len(candidate) <= 24:
                                return candidate
                        return scorer[:24]
                    if strength in {"PPG", "SHG", "ENG", "OTG"}:
                        return f"{scorer} {strength}"[:24]
                    return scorer[:24]

    if family in {"football", "basketball"}:
        play = _latest_scoring_play(game, situation, side)
        if play is not None:
            scorer = str(play.get("scorer") or play.get("player") or "").strip().upper()
            if scorer:
                if family == "football":
                    yards = str(play.get("yards") or "").strip()
                    passer = str(play.get("passer") or "").strip().upper()
                    event_type = str(play.get("event_type") or play.get("type") or "").upper()
                    if "PASS" in event_type and passer:
                        return f"{scorer} {yards}YD {passer}".strip()[:24]
                    if yards:
                        return f"{scorer} {yards}YD"[:24]
                    return scorer[:24]
                points = _number(play.get("score_value"))
                play_text = " ".join(
                    str(play.get(key) or "") for key in ("type", "event_type", "text")
                ).lower()
                shot = "3PT" if "three point" in play_text or points == 3 else "FT" if "free throw" in play_text else "DUNK" if "dunk" in play_text else "2PT"
                assists = [str(value).strip().upper() for value in play.get("assists", ()) if str(value).strip()]
                suffix = f" A:{assists[0]}" if assists else ""
                return f"{scorer} {shot}{suffix}"[:24]

    play = _latest_scoring_play(game, situation, side)
    if play is not None:
        scorer = str(play.get("scorer") or play.get("player") or "").strip().upper()
        scoring_type = str(play.get("type") or play.get("kind") or "").strip().upper()
        text = str(play.get("text") or "").strip().upper()
        if scorer and scoring_type and scoring_type not in scorer:
            return f"{scorer} {scoring_type}"[:24]
        if scorer:
            return scorer[:24]
        if text:
            return text[:24]

    last_play = str(situation.get("last_play") or game.get("last_play") or "").strip()
    if last_play:
        return last_play[:24].upper()

    return ""


def _baseball_alert_detail(
    game: Mapping[str, Any], situation: Mapping[str, Any], side: str
) -> str:
    """Build compact MLB player context without repeating the alert headline."""

    play = _latest_scoring_play(game, situation, side)
    if play is None:
        return ""
    player = str(play.get("scorer") or play.get("player") or "").strip().upper()
    if not player:
        return ""
    play_text = " ".join(
        str(play.get(key) or "") for key in ("type", "event_type", "text")
    ).lower()
    if re.search(r"\b(home run|homer|homered|homers)\b", play_text):
        metrics: list[str] = []
        distance = _compact_metric(play.get("home_run_distance"))
        exit_velocity = _compact_metric(play.get("exit_velocity"))
        launch_angle = _compact_metric(play.get("launch_angle"))
        if distance:
            metrics.append(f"{distance}FT")
        if exit_velocity:
            metrics.append(f"{exit_velocity}EV")
        if launch_angle:
            metrics.append(f"{launch_angle}LA")
        if metrics:
            separator = " | " if len(metrics) > 1 else " "
            return f"{player} {metrics[0]}{separator}{' '.join(metrics[1:])}"[:24]
    parts = [player]
    hits = str(play.get("player_h") or "").strip()
    at_bats = str(play.get("player_ab") or "").strip()
    average = str(play.get("player_avg") or "").strip()
    if hits or at_bats:
        parts.append(f"{hits or '-'}/{at_bats or '-'}")
    if average:
        parts.append(average[1:] if average.startswith("0.") else average)
    speed = str(play.get("pitch_speed") or situation.get("last_pitch_speed") or "").strip()
    pitch = str(play.get("pitch_type") or situation.get("last_pitch_type") or "").strip()
    if speed or pitch:
        parts.extend(("|", speed, pitch))
    return " ".join(part for part in parts if part).upper()[:24]


def _compact_metric(value: object) -> str:
    """Round one Statcast metric for the narrow LED detail line."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(round(number))) if number.is_integer() or abs(number) >= 10 else f"{number:.1f}".rstrip("0").rstrip(".")


def _latest_scoring_play(
    game: Mapping[str, Any], situation: Mapping[str, Any], side: str
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


def _is_basketball_dunk(scoring_play: Mapping[str, Any] | None) -> bool:
    """Identify a basketball dunk from the provider play description."""

    if not scoring_play:
        return False
    play_text = " ".join(
        str(scoring_play.get(key) or "")
        for key in ("type", "event_type", "text")
    ).lower()
    return "dunk" in play_text


class ScoreAlertTracker:
    """Keep score memory across scoreboard polls and release recent alerts."""

    def __init__(self, *, clock: Callable[[], float] = time) -> None:
        self._clock = clock
        self._lock = Lock()
        self._scores: dict[str, tuple[int, int, str, str]] = {}
        self._alerts: list[dict[str, Any]] = []

    def prime(self, games: Sequence[Mapping[str, Any]]) -> None:
        """Set a complete source baseline without creating score alerts."""

        scores: dict[str, tuple[int, int, str, str]] = {}
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
        with self._lock:
            self._scores = scores

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
                if previous is None or (
                    state not in _LIVE_STATES
                    and not (family == "basketball" and state in {"post", "final"})
                ):
                    continue
                lead_change = (
                    family == "basketball"
                    and (previous[0] - previous[1]) * (home - away) < 0
                )
                game_ending = (
                    family == "basketball"
                    and state in {"post", "final"}
                    and previous[3] not in {"post", "final"}
                )

                def append_alert(
                    side: str,
                    kind: str,
                    headline: str,
                    detail: str,
                    points: int,
                ) -> None:
                    other = "away" if side == "home" else "home"
                    self._alerts.append(
                        {
                            "id": f"{game_id}:{home}-{away}:{side}",
                            "game_id": game_id,
                            "sport": sport,
                            "ts": now,
                            "side": side,
                            "kind": kind,
                            "headline": headline,
                            "detail": detail,
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
                            "status": status,
                            "home_conference_id": game.get("home_conference_id", ""),
                            "away_conference_id": game.get("away_conference_id", ""),
                        }
                    )

                sit = game.get("situation")
                situation = sit if isinstance(sit, Mapping) else {}
                for side, new_score, old_score in (("home", home, previous[0]), ("away", away, previous[1])):
                    delta = new_score - old_score
                    if delta <= 0:
                        continue
                    scoring_play = _latest_scoring_play(game, situation, side)
                    if family == "basketball":
                        other_side = "away" if side == "home" else "home"
                        other_old = previous[1] if side == "home" else previous[0]
                        other_new = away if side == "home" else home
                        winning_score = new_score > other_new and old_score <= other_old
                        if game_ending and not (winning_score and scoring_play):
                            continue
                        if not game_ending and not lead_change:
                            continue
                    kind, headline = _describe(sport, delta, scoring_play)
                    if family == "basketball" and _is_basketball_dunk(scoring_play):
                        if game_ending:
                            kind, headline = "game_winning_dunk", "GAME WINNING DUNK"
                        elif lead_change:
                            kind, headline = "lead_taking_dunk", "LEAD TAKING DUNK"
                    detail = _extract_alert_detail(sport, game, side)
                    append_alert(side, kind, headline, detail, delta)
            self._scores = {key: value for key, value in self._scores.items() if key in current_ids}
            self._alerts = self._alerts[-_MAX_ALERTS:]

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
        and matches_followed_team(
            str(alert.get("sport") or ""),
            str(alert.get("team_abbr") or ""),
            followed,
        )
    )


__all__ = ["ScoreAlertTracker", "alerts_for_settings"]
