"""Detect live score changes and project V2 alert facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from threading import Lock
from time import time
from typing import Any, Callable

from ticker.shared.leagues import allows_college_conferences

from ticker.shared.sports_display import matches_followed_team, sport_family


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


_HOME_RUN = re.compile(r"\b(home run|homer|homered|homers)\b")
_BASEBALL_PLAYS = {
    "single": ("single", "SINGLE"),
    "double": ("double", "DOUBLE"),
    "triple": ("triple", "TRIPLE"),
    "sacrifice fly": ("sacrifice_fly", "SAC FLY"),
    "sacrifice bunt": ("sacrifice_bunt", "SAC BUNT"),
    "walk": ("walk", "WALK"),
    "intentional walk": ("intentional_walk", "INTENTIONAL WALK"),
    "hit by pitch": ("hit_by_pitch", "HIT BY PITCH"),
}
_BASEBALL_ABBREVIATIONS = {"sac fly": "sacrifice fly", "sac bunt": "sacrifice bunt"}
_HOCKEY_STRENGTHS = (
    ("empty net", frozenset(("ENG", "EMPTY NET")), ("empty_net", "EMPTY NET GOAL")),
    ("shorthanded", frozenset(("SHG", "SHORT-HANDED")), ("shorthanded", "SHORTHANDED GOAL")),
    ("power play", frozenset(("PPG", "POWER PLAY")), ("power_play_goal", "POWER PLAY GOAL")),
)
_TURNOVER_ALERT_KINDS = frozenset(("interception", "fumble", "interception_td", "fumble_td"))


def _play_text(play: Mapping[str, Any] | None, keys: Sequence[str]) -> str:
    """Join the named text fields of one scoring play in lower case."""

    if not play:
        return ""
    return " ".join(str(play.get(key) or "") for key in keys).lower()


def _describe(
    sport: object,
    delta: int,
    scoring_play: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Return the alert kind and headline for one score increase."""

    describe = _DESCRIBERS.get(sport_family(sport))
    if describe is None:
        return "score", f"+{delta}"
    return describe(delta, scoring_play)


def _describe_football(delta: int, play: Mapping[str, Any] | None) -> tuple[str, str]:
    play_text = _play_text(play, ("type", "event_type", "scoring_type", "text"))
    conversion = play.get("conversion_type") if play else None
    successful_two_point = (
        (re.search(r"\b(?:two|2)[- ]point conversion\b", play_text) is not None
         or conversion == "two_point")
        and re.search(r"\b(?:failed|no good|unsuccessful)\b", play_text) is None
    )
    if conversion == "extra_point" and delta == 1:
        return "extra_point", "EXTRA POINT"
    if conversion == "two_point" and delta == 2:
        return "two_point", "2-POINT CONV"
    if "interception" in play_text and "touchdown" in play_text:
        return "interception_td", "INTERCEPTION TD"
    if "fumble return touchdown" in play_text or "fumble recovery" in play_text:
        return "fumble_td", "FUMBLE TD"
    if "kickoff return touchdown" in play_text or (
        "kickoff" in play_text and "touchdown" in play_text and re.search(r"\breturns?\b", play_text)
    ):
        return "kick_return_td", "KICK RETURN TD"
    if "punt return touchdown" in play_text or ("punt" in play_text and "touchdown" in play_text):
        return "punt_return_td", "PUNT RETURN TD"
    if "blocked field goal" in play_text and "touchdown" in play_text:
        return "blocked_fg_td", "BLOCKED FG TD"
    conversion_suffix = " +2PT" if successful_two_point else ""
    if "passing touchdown" in play_text or ("touchdown" in play_text and "pass" in play_text.split("(", 1)[0]):
        return "passing_td", "PASS TD" + conversion_suffix
    if "rushing touchdown" in play_text or ("touchdown" in play_text and re.search(r"\b(?:run|rush)\b", play_text)):
        return "rushing_td", "RUSH TD" + conversion_suffix
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


def _describe_baseball(delta: int, play: Mapping[str, Any] | None) -> tuple[str, str]:
    play_text = _play_text(play, ("type", "kind", "scoring_type", "event_type", "text"))
    if _HOME_RUN.search(play_text):
        runs = _number(play.get("score_value")) if play else None
        runs = delta if runs is None else runs
        if runs >= 4 or "grand slam" in play_text:
            return "grand_slam", "GRAND SLAM"
        if runs == 3:
            return "three_run_hr", "3-RUN HOME RUN"
        if runs == 2:
            return "two_run_hr", "2-RUN HOME RUN"
        return "home_run", "HOME RUN"
    scoring_type = _baseball_scoring_type(play, play_text)
    if play and scoring_type in {"single", "double"}:
        runs = _number(play.get("score_value")) or 0
        if play.get("rbi") or runs > 0:
            if play.get("walk_off"):
                return f"walk_off_rbi_{scoring_type}", f"WALK OFF RBI {scoring_type.upper()}"
            return f"rbi_{scoring_type}", f"RBI {scoring_type.upper()}"
    return _BASEBALL_PLAYS.get(scoring_type, ("run", "RUN SCORES"))


def _baseball_scoring_type(play: Mapping[str, Any] | None, play_text: str) -> str:
    """Normalize the provider play type, and resolve a bare sacrifice from the play text."""

    if not play:
        return ""
    raw = str(play.get("type") or play.get("kind") or play.get("event_type") or "").lower()
    scoring_type = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    scoring_type = _BASEBALL_ABBREVIATIONS.get(scoring_type, scoring_type)
    if scoring_type == "sacrifice":
        for detail in ("sacrifice fly", "sacrifice bunt"):
            if detail in play_text:
                return detail
    return scoring_type


def _describe_hockey(_delta: int, play: Mapping[str, Any] | None) -> tuple[str, str]:
    play_text = _play_text(play, ("type", "event_type", "strength", "text")).replace("-", " ")
    strength = str(play.get("strength") if play else "").upper()
    for phrase, codes, result in _HOCKEY_STRENGTHS:
        if phrase in play_text or strength in codes:
            return result
    if "penalty shot" in play_text:
        return "penalty_shot", "PENALTY SHOT"
    return "goal", "GOAL"


def _describe_soccer(_delta: int, play: Mapping[str, Any] | None) -> tuple[str, str]:
    play_text = _play_text(play, ("type", "event_type", "goal_type", "text"))
    if "own goal" in play_text:
        return "own_goal", "OWN GOAL"
    if "penalty" in play_text:
        return "penalty_goal", "PENALTY GOAL"
    if "header" in play_text:
        return "header_goal", "HEADER GOAL"
    return "goal", "GOAL"


_DESCRIBERS: dict[str, Callable[[int, Mapping[str, Any] | None], tuple[str, str]]] = {
    "football": _describe_football,
    "baseball": _describe_baseball,
    "hockey": _describe_hockey,
    "soccer": _describe_soccer,
}


def _game_situation(game: Mapping[str, Any]) -> Mapping[str, Any]:
    situation = game.get("situation")
    return situation if isinstance(situation, Mapping) else {}


def _scoreboard_key(game: Mapping[str, Any]) -> tuple[str, int, int] | None:
    """Return the ID and both scores of one complete scoreboard game, or None."""

    if str(game.get("kind") or game.get("type") or "") != "scoreboard":
        return None
    game_id = str(game.get("id") or "").strip()
    home = _number(game.get("home_score"))
    away = _number(game.get("away_score"))
    if not game_id or home is None or away is None:
        return None
    return game_id, home, away


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


def _football_event_ids(plays: Sequence[Mapping[str, Any]]) -> set[str]:
    """Return the known identities of normalized football plays."""

    return {identifier for play in plays if (identifier := _football_event_identity(play))}


def _football_event_side(game: Mapping[str, Any], play: Mapping[str, Any]) -> str:
    """Resolve the team that owns one normalized football event."""

    team = str(play.get("team") or "").strip().lower()
    for side in ("home", "away"):
        if team and team == str(game.get(f"{side}_abbr") or "").strip().lower():
            return side
    return ""


def _compact_metric(value: Any) -> str:
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


@dataclass(slots=True)
class _FootballScoreMemory:
    """Separate provider play identity from score-only observations."""

    totals: dict[str, int] = field(default_factory=dict)
    plays: set[tuple[str, str, str]] = field(default_factory=set)
    pending: dict[str, tuple[int, int]] = field(default_factory=dict)

    def observe(self, side: str, score: int, play_id: str, kind: str) -> bool:
        """Remember one observation and return whether its event was already known."""
        phase = _football_score_phase(kind)
        identity = (side, phase, play_id)
        duplicate = identity in self.plays if play_id else score <= self.totals.get(side, -1)
        self.totals[side] = max(score, self.totals.get(side, score))
        if play_id:
            self.plays.add(identity)
        return duplicate

    def observe_play(self, side: str, score: int, play: Mapping[str, Any] | None, kind: str) -> bool:
        """Remember the touchdown and conversion identities supplied by one summary entry."""
        play_id = str(play.get("play_id") or "") if play else ""
        duplicate = self.observe(side, score, play_id, kind)
        if play and play_id and _number(play.get(f"{side}_score")) == score:
            conversion = str(play.get("conversion_type") or "")
            if conversion in {"extra_point", "two_point"}:
                self.observe(side, score, play_id, conversion)
                self.observe(side, score, play_id, "touchdown")
        return duplicate


def _football_score_phase(kind: str) -> str:
    """Keep conversions separate from their parent touchdown identity."""
    return "conversion" if kind in {"extra_point", "two_point"} else "score"


def _football_score_memory(game: Mapping[str, Any]) -> _FootballScoreMemory:
    """Seed the baseline without announcing scores that already exist."""
    memory = _FootballScoreMemory()
    situation = _game_situation(game)
    values = situation.get("scoring_plays") or game.get("scoring_plays")
    plays = values if isinstance(values, (list, tuple)) else ()
    for side in ("home", "away"):
        score = _number(game.get(f"{side}_score"))
        if score is None:
            continue
        memory.observe(side, score, "", "score")
        team = str(game.get(f"{side}_abbr") or side).lower()
        other = "away" if side == "home" else "home"
        other_score = _number(game.get(f"{other}_score"))
        for play in plays:
            if not isinstance(play, Mapping) or str(play.get("team") or play.get("side") or "").lower() not in {team, side}:
                continue
            play_score = _number(play.get(f"{side}_score"))
            play_other_score = _number(play.get(f"{other}_score"))
            if play_score is None or play_score > score:
                continue
            if play_other_score is not None and other_score is not None and play_other_score > other_score:
                continue
            kind, _ = _describe(game.get("sport"), _number(play.get("score_value")) or play_score, play)
            memory.observe_play(side, play_score, play, kind)
    return memory


@dataclass(frozen=True, slots=True)
class _GamePoll:
    """Hold one scoreboard game from the current poll and its score in the prior poll."""

    game: Mapping[str, Any]
    game_id: str
    sport: str
    family: str
    status: str
    home: int
    away: int
    previous: tuple[int, int, str, str]
    situation: Mapping[str, Any]
    now: float


def _retained(values: dict[str, Any], game_ids: set[str]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key in game_ids}


class ScoreAlertTracker:
    """Keep score memory across scoreboard polls and release recent alerts."""

    def __init__(self, *, clock: Callable[[], float] = time) -> None:
        self._clock = clock
        self._lock = Lock()
        self._scores: dict[str, tuple[int, int, str, str]] = {}
        self._football_events: dict[str, set[str]] = {}
        self._football_projection_ready: dict[str, bool] = {}
        self._football_scores: dict[str, _FootballScoreMemory] = {}
        self._alerts: list[dict[str, Any]] = []

    def prime(self, games: Sequence[Mapping[str, Any]]) -> None:
        """Set a complete source baseline without creating score alerts."""

        scores: dict[str, tuple[int, int, str, str]] = {}
        football_events: dict[str, set[str]] = {}
        projection_ready: dict[str, bool] = {}
        football_scores: dict[str, _FootballScoreMemory] = {}
        for game in games:
            key = _scoreboard_key(game)
            if key is None:
                continue
            game_id, home, away = key
            scores[game_id] = (
                home,
                away,
                str(game.get("status") or ""),
                str(game.get("state") or "").lower(),
            )
            if sport_family(game.get("sport")) == "football":
                football_scores[game_id] = _football_score_memory(game)
            situation = _game_situation(game)
            projection_ready[game_id] = _has_football_projection(situation, game)
            football_events[game_id] = _football_event_ids(_football_events(situation, game))
        with self._lock:
            self._scores = scores
            self._football_events = football_events
            self._football_projection_ready = projection_ready
            self._football_scores = football_scores

    def ingest(self, games: Sequence[Mapping[str, Any]]) -> None:
        """Compare one complete scoreboard observation with the prior poll."""

        now = float(self._clock())
        current_ids: set[str] = set()
        with self._lock:
            for game in games:
                key = _scoreboard_key(game)
                if key is None:
                    continue
                current_ids.add(key[0])
                self._ingest_game(game, *key, now)
            self._scores = _retained(self._scores, current_ids)
            self._football_events = _retained(self._football_events, current_ids)
            self._football_projection_ready = _retained(self._football_projection_ready, current_ids)
            self._alerts = self._alerts[-_MAX_ALERTS:]
            self._football_scores = _retained(self._football_scores, current_ids)

    def _ingest_game(self, game: Mapping[str, Any], game_id: str, home: int, away: int, now: float) -> None:
        """Update the memory of one game and append the alerts its new poll causes."""

        status = str(game.get("status") or "")
        previous = self._scores.get(game_id)
        sport = str(game.get("sport") or "").lower()
        family = sport_family(sport)
        state = str(game.get("state") or "").lower()
        self._scores[game_id] = (home, away, status, state)
        if family == "basketball":
            return
        situation = _game_situation(game)
        football_events = _football_events(situation, game)
        seen_football_events = self._football_events.setdefault(game_id, set())
        projection_ready = _has_football_projection(situation, game)
        if previous is None:
            if family == "football":
                self._football_scores[game_id] = _football_score_memory(game)
            seen_football_events.update(_football_event_ids(football_events))
            self._football_projection_ready[game_id] = projection_ready
            return
        if projection_ready:
            # The first complete play projection is a baseline, so its plays do not alert.
            if family == "football" and not self._football_projection_ready.get(game_id, False):
                seen_football_events.update(_football_event_ids(football_events))
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
            return
        if family == "hockey":
            self._hydrate_hockey_alerts(game_id, game)
        elif family == "football":
            self._hydrate_football_alerts(game_id, game, previous)
        final_score = state in {"post", "final"} and previous[3] in _LIVE_STATES and (
            home > previous[0] or away > previous[1]
        ) and not (family == "hockey" and previous[2] == "S/O")
        if state not in _LIVE_STATES and not shootout_completed and not final_score:
            seen_football_events.update(_football_event_ids(football_events))
            return
        poll = _GamePoll(game, game_id, sport, family, status, home, away, previous, situation, now)
        if shootout_completed:
            self._append_alert(
                poll,
                shootout_winner,
                "shootout_winner",
                "SHOOTOUT WINNER",
                _extract_alert_facts(sport, game, shootout_winner, alert_kind="shootout_winner"),
                1,
                event_id=f"{game_id}:shootout:{shootout_winner}",
            )
            return
        if family == "football":
            self._alert_football_turnovers(poll, football_events, seen_football_events)
        self._alert_score_increases(poll)

    def _alert_football_turnovers(
        self, poll: _GamePoll, plays: Sequence[Mapping[str, Any]], seen: set[str],
    ) -> None:
        """Alert each new non-scoring interception or fumble once."""

        for play in plays:
            identifier = _football_event_identity(play)
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            if play.get("is_scoring"):
                continue
            side = _football_event_side(poll.game, play)
            kind = str(play.get("football_kind") or "").strip().lower()
            if not side or kind not in _FOOTBALL_PLAY_KINDS:
                continue
            self._append_alert(
                poll,
                side,
                kind,
                kind.upper(),
                _extract_alert_facts(poll.sport, poll.game, side, alert_kind=kind, event=play),
                0,
                event_id=f"{poll.game_id}:football:{identifier}",
            )

    def _alert_score_increases(self, poll: _GamePoll) -> None:
        """Alert each team score increase, and merge football conversions into their touchdown."""

        game, game_id, previous = poll.game, poll.game_id, poll.previous
        memory = (
            self._football_scores.setdefault(game_id, _FootballScoreMemory())
            if poll.family == "football" else None
        )
        for side, new_score, prior_score in (("home", poll.home, previous[0]), ("away", poll.away, previous[1])):
            old_score = prior_score
            delta = new_score - old_score
            if memory is not None and side in memory.pending and memory.pending[side][1] != new_score:
                memory.pending.pop(side)
            if delta <= 0:
                # A score-only observation waits in pending until the provider names its play.
                pending = memory.pending.get(side) if memory is not None else None
                if not pending or pending[1] != new_score:
                    continue
                old_score = pending[0]
                delta = new_score - old_score
            scoring_play = _latest_scoring_play(game, poll.situation, side, previous_score=old_score)
            kind, headline = _describe(poll.sport, delta, scoring_play)
            play_id = str(scoring_play.get("play_id") or "") if scoring_play else ""
            if new_score <= prior_score and not play_id:
                continue
            score_event_id = ""
            if memory is not None:
                merged = self._merge_football_conversion(game_id, game, side, old_score, new_score, scoring_play)
                duplicate = memory.observe_play(side, new_score, scoring_play, kind)
                if merged or not duplicate:
                    memory.pending.pop(side, None)
                elif not play_id:
                    memory.pending[side] = (old_score, new_score)
                if merged or duplicate:
                    continue
                if play_id:
                    score_event_id = f"{game_id}:football:{side}:{_football_score_phase(kind)}:{play_id}"
            facts = _extract_alert_facts(poll.sport, game, side, alert_kind=kind, event=scoring_play)
            if poll.family == "football" and scoring_play:
                facts["status"] = _football_scoring_status(scoring_play, poll.status, poll.sport)
            self._append_alert(
                poll,
                side,
                kind,
                headline,
                facts,
                delta,
                event_id=score_event_id,
                scoring_play_id=play_id if poll.family in {"hockey", "football"} else "",
            )

    def _append_alert(
        self,
        poll: _GamePoll,
        side: str,
        kind: str,
        headline: str,
        facts: Mapping[str, Any],
        points: int,
        *,
        event_id: str = "",
        scoring_play_id: str = "",
    ) -> None:
        game = poll.game
        other = "away" if side == "home" else "home"
        identifier = event_id or f"{poll.game_id}:{poll.home}-{poll.away}:{side}"
        if any(alert.get("id") == identifier for alert in self._alerts):
            return
        self._alerts.append(
            {
                "id": identifier,
                "game_id": poll.game_id,
                "event_id": event_id,
                "sport": poll.sport,
                "ts": poll.now,
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
                "home_score": poll.home,
                "away_score": poll.away,
                "status": facts.get("status", poll.status),
                "home_conference_id": game.get("home_conference_id", ""),
                "away_conference_id": game.get("away_conference_id", ""),
                **({"scoring_play_id": scoring_play_id} if scoring_play_id else {}),
            }
        )

    def _merge_football_conversion(
        self, game_id: str, game: Mapping[str, Any], side: str, previous_score: int,
        target: int, play: Mapping[str, Any] | None,
    ) -> bool:
        """Update an observed touchdown when its conversion reaches the scoreboard."""
        delta = target - previous_score
        if delta != 1 and not (delta == 2 and play and play.get("conversion_type") == "two_point"):
            return False
        for alert in reversed(self._alerts):
            if alert.get("game_id") != game_id or alert.get("side") != side:
                continue
            if int(alert.get("points") or 0) <= 0:
                continue
            kind = str(alert.get("kind") or "")
            if (alert.get(f"{side}_score") != previous_score or alert.get("points") != 6
                    or not (kind.endswith("_td") or kind == "touchdown")):
                return False
            alert.update(home_score=game["home_score"], away_score=game["away_score"], points=6 + delta)
            return True
        return False

    def _hydrate_football_alerts(
        self, game_id: str, game: Mapping[str, Any], previous: tuple[int, int, str, str],
    ) -> None:
        """Fill delayed football detail without replaying or retiming the alert."""
        situation = _game_situation(game)
        play_owners = {
            (alert.get("side"), alert["scoring_play_id"]): alert["id"]
            for alert in self._alerts
            if alert.get("game_id") == game_id and alert.get("scoring_play_id")
        }
        for alert in self._alerts:
            if alert.get("game_id") != game_id or int(alert.get("points") or 0) <= 0:
                continue
            side = alert["side"]
            other = "away" if side == "home" else "home"
            for prefix, team_side in (("team", side), ("opp", other)):
                for name in ("logo", "color", "alt_color"):
                    value = game.get(f"{team_side}_{name}")
                    if value:
                        alert[f"{prefix}_{name}"] = value
            scored_game = {**game, "home_score": alert["home_score"], "away_score": alert["away_score"]}
            old_score = int(alert[f"{side}_score"]) - int(alert["points"])
            play = _latest_scoring_play(scored_game, situation, side, previous_score=old_score)
            if play is None:
                continue
            play_id = str(play.get("play_id") or "")
            known_play_id = str(alert.get("scoring_play_id") or "")
            if known_play_id and play_id and known_play_id != play_id:
                continue
            if play_id and play_owners.get((side, play_id), alert["id"]) != alert["id"]:
                continue
            previous_score = previous[0] if side == "home" else previous[1]
            current_score = _number(game.get(f"{side}_score"))
            memory = self._football_scores.setdefault(game_id, _FootballScoreMemory())
            pending = memory.pending.get(side)
            rising = current_score is not None and current_score > previous_score
            awaiting_identity = pending is not None and pending[1] == current_score
            if (not known_play_id and (rising or awaiting_identity)
                    and alert[f"{side}_score"] == current_score):
                continue
            kind, headline = _describe(game.get("sport"), int(alert["points"]), play)
            facts = _extract_alert_facts(game.get("sport"), scored_game, side, alert_kind=kind, event=play)
            alert.update(facts, kind=kind, headline=headline, big=kind in _BIG_KINDS,
                         status=_football_scoring_status(play, str(alert.get("status") or ""), str(game.get("sport") or "")),
                         scoring_play_id=play_id or known_play_id)
            if play_id:
                play_owners[(side, play_id)] = alert["id"]
            memory.observe_play(side, int(alert[f"{side}_score"]),
                                {**play, "play_id": play_id or known_play_id}, kind)

    def _hydrate_hockey_alerts(self, game_id: str, game: Mapping[str, Any]) -> None:
        """Match delayed ESPN goal details to each alert's score and refresh assists."""

        situation = _game_situation(game)
        for alert in reversed(self._alerts):
            if alert.get("game_id") != game_id:
                continue
            side = alert["side"]
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


def _extract_alert_facts(
    sport: object,
    game: Mapping[str, Any],
    side: str,
    *,
    alert_kind: str = "",
    event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one score play into separate display facts."""

    situation = _game_situation(game)
    family = sport_family(sport)
    facts: dict[str, Any] = {
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

    if family == "football" and alert_kind in _TURNOVER_ALERT_KINDS:
        turnover = event or _latest_turnover_play(game, situation, side)
        if turnover is not None:
            facts.update(_turnover_facts(turnover))
            return facts

    if family == "baseball":
        play = _latest_scoring_play(game, situation, side)
        if play is not None:
            facts.update(player=_play_player(play), data=_baseball_data(play, situation))
            return facts

    if family == "hockey":
        play = _latest_scoring_play(game, situation, side)
        if play is not None:
            facts.update(_scorer_facts(play))
        return facts

    if family == "soccer":
        goal = _soccer_goal_facts(game, situation, side)
        if goal is not None:
            facts.update(goal)
            return facts

    play = event or _latest_scoring_play(game, situation, side)
    if play is not None:
        facts.update(_scorer_facts(play))
        event_type = " ".join(str(play.get(key) or "") for key in ("type", "event_type", "scoring_type", "text")).upper()
        if family == "football":
            if alert_kind in {"extra_point", "two_point"}:
                if play.get("conversion_type") == alert_kind:
                    facts["player"] = str(play.get("conversion_player_full") or "")
                facts["data"] = "EXTRA POINT" if alert_kind == "extra_point" else "2-POINT CONV"
                return facts
            kick_return = alert_kind == "kick_return_td"
            facts["data"] = _football_play_data(play, event_type)
            facts["down_distance"] = "" if kick_return else _football_down_distance(play)
            facts["is_red_zone"] = None if kick_return else _football_red_zone(play)
        elif family == "basketball":
            facts["data"] = _basketball_shot(play, event_type)
        elif family != "baseball":
            facts["data"] = str(play.get("type") or play.get("kind") or "").strip().upper()
        if (facts["player"] or facts["data"]) and (facts["data"] or not explicit):
            return facts

    if family == "football":
        return facts
    facts["data"] = explicit or str(situation.get("last_play") or game.get("last_play") or "").strip()
    return facts


def _scorer_facts(play: Mapping[str, Any]) -> dict[str, str]:
    assists = _play_assists(play)
    return {
        "player": _play_player(play),
        "primary_assist": assists[0] if assists else "",
        "secondary_assist": assists[1] if len(assists) > 1 else "",
    }


def _turnover_facts(turnover: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(turnover.get("football_kind") or "").casefold()
    data = ["INTERCEPTION" if kind == "interception" else "FUMBLE"]
    yards = _number(turnover.get("return_yards"))
    if yards is not None:
        data.append(f"{yards}YD RET")
    return {
        "player": str(
            turnover.get("scorer_full")
            or turnover.get("player_full")
            or turnover.get("player")
            or turnover.get("scorer")
            or ""
        ).strip(),
        "data": " ".join(data),
        "down_distance": _football_down_distance(turnover),
        "is_red_zone": _football_red_zone(turnover),
    }


def _baseball_data(play: Mapping[str, Any], situation: Mapping[str, Any]) -> str:
    """Show Statcast metrics for a home run, or the batter line and last pitch for other plays."""

    play_text = " ".join(str(play.get(key) or "") for key in ("type", "event_type", "text")).lower()
    if _HOME_RUN.search(play_text):
        metrics = (
            (_compact_metric(play.get("home_run_distance")), "FT"),
            (_compact_metric(play.get("exit_velocity")), "EV"),
            (_compact_metric(play.get("launch_angle")), "LA"),
        )
        return " ".join(f"{value}{unit}" for value, unit in metrics if value)
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
    return " ".join((*stats, pitch_detail)).strip()


def _soccer_goal_facts(
    game: Mapping[str, Any], situation: Mapping[str, Any], side: str,
) -> dict[str, str] | None:
    """Read the scorer, minute, and assist of the team's latest goal event."""

    events = situation.get("goal_events") or game.get("goal_events")
    if not isinstance(events, (list, tuple)):
        return None
    is_home = side == "home"
    matching = [event for event in events if isinstance(event, Mapping) and bool(event.get("is_home")) == is_home]
    if not matching:
        return None
    event = matching[-1]
    minute = str(event.get("minute") or event.get("time") or "").strip()
    goal_type = "OWN GOAL" if event.get("own_goal") else str(event.get("goal_type") or event.get("type") or "").strip().upper()
    return {
        "player": str(event.get("alert_player") or event.get("player_full") or event.get("player") or "").strip(),
        "data": " ".join(value for value in (minute, goal_type) if value),
        "primary_assist": str(event.get("alert_assist") or event.get("assist_full") or event.get("assist") or "").strip(),
    }


def _football_play_data(play: Mapping[str, Any], event_type: str) -> str:
    """Describe a football score as a return, a field goal, a pass, or a rush."""

    yards = _number(play.get("return_yards") if play.get("football_kind") in _FOOTBALL_PLAY_KINDS else play.get("yards"))
    distance = f"{yards}YD" if yards is not None else ""
    if "INTERCEPTION" in event_type:
        return f"INTERCEPTION {distance} RET" if distance else "INTERCEPTION RETURN"
    if "FUMBLE" in event_type:
        return f"FUMBLE {distance} RET" if distance else "FUMBLE RECOVERY"
    if "FIELD GOAL" in event_type:
        return f"{distance} FIELD GOAL" if distance else "FIELD GOAL"
    passer = str(play.get("passer_full") or play.get("passer") or "").strip()
    if "PASS" in event_type and passer:
        parts = [distance, "PASS", passer]
    else:
        parts = ["RUSH" if "RUSH" in event_type else "", distance]
    return " ".join(part for part in parts if part)


def _basketball_shot(play: Mapping[str, Any], event_type: str) -> str:
    points = _number(play.get("score_value"))
    play_text = event_type.lower()
    if "three point" in play_text or points == 3:
        return "3PT"
    if "free throw" in play_text:
        return "FT"
    if "dunk" in play_text:
        return "DUNK"
    return "2PT"


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
            if isinstance(play, Mapping) and str(play.get("team") or "").casefold() == team
        ),
        None,
    )


__all__ = ["ScoreAlertTracker", "alerts_for_settings"]
