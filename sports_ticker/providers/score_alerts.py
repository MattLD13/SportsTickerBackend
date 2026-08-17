"""Detect live score changes and build V1-compatible overlay payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from threading import Lock
from time import time
from typing import Any, Callable

from .sports_display import matches_followed_team, sport_family


_LIVE_STATES = frozenset(("in", "half", "crit"))
_BIG_KINDS = frozenset(
    (
        "walk_off",
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
        "safety",
    )
)
_MAX_ALERTS = 64
_MAX_AGE = 45.0


def _number(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _describe(sport: object, delta: int) -> tuple[str, str]:
    family = sport_family(sport)
    if family == "football":
        if delta >= 6:
            return "touchdown", "TOUCHDOWN"
        if delta == 3:
            return "field_goal", "FIELD GOAL"
        if delta == 2:
            return "safety", "SAFETY"
        return "extra_point", "EXTRA POINT"
    if family == "baseball":
        if delta >= 4:
            return "grand_slam", "GRAND SLAM"
        if delta == 3:
            return "three_run_hr", "3-RUN HOME RUN"
        if delta == 2:
            return "two_run_hr", "2-RUN HOME RUN"
        return "run", "RUN SCORES"
    if family == "hockey":
        return "goal", "GOAL"
    if family == "basketball":
        return ("three", "3-POINTER") if delta >= 3 else ("bucket", "BUCKET")
    if family == "soccer":
        return "goal", "GOAL"
    return "score", f"+{delta}"


def _extract_alert_detail(sport: str, game: Mapping[str, Any], side: str) -> str:
    """Extract clean play details (scorer, assists, goal type) for score alerts."""

    sit = game.get("situation")
    situation = sit if isinstance(sit, Mapping) else {}
    explicit = str(situation.get("detail") or game.get("detail") or "").strip()
    if explicit:
        return explicit[:24].upper()

    family = sport_family(sport)
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
                minute = str(last_g.get("minute") or "").strip()
                own_goal = bool(last_g.get("own_goal"))
                g_type = str(last_g.get("goal_type") or last_g.get("type") or "").strip().upper()

                parts: list[str] = []
                if player:
                    parts.append(player)
                if minute:
                    parts.append(minute)
                if own_goal:
                    parts.append("(OG)")
                elif g_type in {"PEN", "PENALTY", "HEADER", "FREE KICK", "VOLLEY"}:
                    parts.append(f"({g_type[:3] if g_type == 'PENALTY' else g_type})")
                elif last_g.get("assist"):
                    parts.append(f"({str(last_g['assist']).strip().upper()})")
                if parts:
                    return " ".join(parts)[:24]

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
                        return f"{scorer} ({', '.join(assists[:2])})"[:24]
                    if strength in {"PPG", "SHG", "ENG", "OTG"}:
                        return f"{scorer} {strength}"[:24]
                    return scorer[:24]

    last_play = str(situation.get("last_play") or game.get("last_play") or "").strip()
    if last_play:
        return last_play[:24].upper()

    return ""


class ScoreAlertTracker:
    """Keep score memory across scoreboard polls and release recent alerts."""

    def __init__(self, *, clock: Callable[[], float] = time) -> None:
        self._clock = clock
        self._lock = Lock()
        self._scores: dict[str, tuple[int, int, str]] = {}
        self._alerts: list[dict[str, Any]] = []

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
                self._scores[game_id] = (home, away, status)
                if previous is None or str(game.get("state") or "").lower() not in _LIVE_STATES:
                    continue
                sport = str(game.get("sport") or "").lower()
                for side, new_score, old_score in (("home", home, previous[0]), ("away", away, previous[1])):
                    delta = new_score - old_score
                    if delta <= 0:
                        continue
                    kind, headline = _describe(sport, delta)
                    detail = _extract_alert_detail(sport, game, side)
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
                            "points": delta,
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
                        }
                    )
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
        if matches_followed_team(
            str(alert.get("sport") or ""),
            str(alert.get("team_abbr") or ""),
            followed,
        )
    )


__all__ = ["ScoreAlertTracker", "alerts_for_settings"]

