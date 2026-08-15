"""Detect live scoring changes and build V1-compatible overlay payloads."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from sports_ticker.domain import DisplaySettings


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


def _sport_family(sport: object) -> str:
    value = str(sport or "").lower()
    if value in {"mlb", "wbc"} or "baseball" in value:
        return "baseball"
    if value == "nfl" or value.startswith("ncf") or "football" in value:
        return "football"
    if value in {"nhl"} or "hockey" in value:
        return "hockey"
    if value in {"nba", "wnba"} or value.startswith(("ncb", "ncw")) or "basketball" in value:
        return "basketball"
    if value.startswith("soccer"):
        return "soccer"
    return "other"


def _describe(sport: object, delta: int) -> tuple[str, str]:
    family = _sport_family(sport)
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


class ScoreAlertTracker:
    """Keep score memory across ESPN polls and release recent score alerts."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
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
                if previous is None:
                    continue
                live = str(game.get("state") or "").lower() in _LIVE_STATES
                if not live:
                    continue
                sport = str(game.get("sport") or "").lower()
                for side, new_score, old_score in (("home", home, previous[0]), ("away", away, previous[1])):
                    delta = new_score - old_score
                    if delta <= 0:
                        continue
                    kind, headline = _describe(sport, delta)
                    other = "away" if side == "home" else "home"
                    team_abbr = str(game.get(f"{side}_abbr") or "").upper()
                    alert = {
                        "id": f"{game_id}:{home}-{away}:{side}",
                        "game_id": game_id,
                        "sport": sport,
                        "ts": now,
                        "side": side,
                        "kind": kind,
                        "headline": headline,
                        "detail": "",
                        "points": delta,
                        "big": kind in _BIG_KINDS,
                        "team_abbr": team_abbr,
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
                    self._alerts.append(alert)
            self._scores = {key: value for key, value in self._scores.items() if key in current_ids}
            self._alerts = self._alerts[-_MAX_ALERTS:]

    def recent(self, *, max_age: float = _MAX_AGE, delay: float = 0.0) -> tuple[dict[str, Any], ...]:
        """Return alerts that are visible at the delayed content timestamp."""

        now = float(self._clock()) - max(0.0, float(delay or 0.0))
        cutoff = now - max(0.0, float(max_age))
        with self._lock:
            return tuple(dict(item) for item in self._alerts if cutoff <= item["ts"] <= now)


def alerts_for_settings(
    alerts: Sequence[Mapping[str, Any]], settings: DisplaySettings
) -> tuple[Mapping[str, Any], ...]:
    """Keep score takeovers scoped to the sports mode and followed teams."""

    if settings.mode != "sports" or not settings.score_alerts or not settings.my_teams:
        return ()
    followed = {str(value).strip().lower() for value in settings.my_teams}
    return tuple(
        alert
        for alert in alerts
        if f"{str(alert.get('sport') or '').lower()}:{str(alert.get('team_abbr') or '').lower()}" in followed
    )


__all__ = ["ScoreAlertTracker", "alerts_for_settings"]
