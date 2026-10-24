"""Read current NHL manpower from the league's public live feed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Thread
import time
from typing import Any

from .http import JsonHttpClient, UrllibJsonHttpClient
from .sports_display import nhl_competition_stage


_SCORE_URL = "https://api-web.nhle.com/v1/score/now"
_PLAY_BY_PLAY_URL = "https://api-web.nhle.com/v1/gamecenter/{}/play-by-play"


class NhlLiveSituationSource:
    """Cache live NHL situation codes without delaying scoreboard refreshes."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 5.0,
        refresh_seconds: float = 8.0,
        cache_seconds: float = 24.0,
        background: bool = True,
        monotonic=time.monotonic,
    ) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._timeout = max(1.0, float(timeout))
        self._refresh_seconds = max(1.0, float(refresh_seconds))
        self._cache_seconds = max(self._refresh_seconds, float(cache_seconds))
        self._background = bool(background)
        self._monotonic = monotonic
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._finished_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._updated_at: float | None = None
        self._last_started = float("-inf")
        self._refreshing = False
        self._lock = Lock()

    def snapshot(self) -> dict[tuple[str, str], dict[str, Any]]:
        """Return cached live situations and refresh them outside the caller."""

        if not self._background:
            self._refresh()
        else:
            self._start_refresh()
        with self._lock:
            if self._updated_at is None or self._monotonic() - self._updated_at > self._cache_seconds:
                return {}
            return {key: dict(value) for key, value in self._cache.items()}

    def _start_refresh(self) -> None:
        now = self._monotonic()
        with self._lock:
            if self._refreshing or now - self._last_started < self._refresh_seconds:
                return
            self._last_started = now
            self._refreshing = True
        Thread(target=self._refresh, name="nhl-situation-refresh", daemon=True).start()

    def _refresh(self) -> None:
        if self._background:
            with self._lock:
                self._refreshing = True
        try:
            payload = self._client.get_json(_SCORE_URL, timeout=self._timeout)
            games = _current_games(payload)
            now = self._monotonic()
            situations: dict[tuple[str, str], dict[str, Any]] = {}
            reads = []
            for game_id, away, home, finished in games:
                cached = self._finished_cache.get(game_id)
                if finished and cached and now - cached[0] < 60.0:
                    situations[(away, home)] = cached[1]
                else:
                    reads.append((game_id, away, home, finished))
            with ThreadPoolExecutor(max_workers=min(8, max(1, len(games)))) as pool:
                futures = {
                    pool.submit(
                        self._read_game_situation,
                        game_id,
                    ): (game_id, away, home, finished)
                    for game_id, away, home, finished in reads
                }
            for future in as_completed(futures):
                game_id, away, home, finished = futures[future]
                try:
                    situation = future.result()
                except Exception:
                    continue
                if situation:
                    situations[(away, home)] = situation
                    if finished:
                        self._finished_cache[game_id] = (self._monotonic(), situation)
            game_ids = {game_id for game_id, _, _, _ in games}
            self._finished_cache = {key: value for key, value in self._finished_cache.items() if key in game_ids}
            with self._lock:
                self._cache = situations
                self._updated_at = self._monotonic()
        except Exception:
            return
        finally:
            if self._background:
                with self._lock:
                    self._refreshing = False

    def _read_game_situation(
        self,
        game_id: str,
    ) -> dict[str, Any]:
        payload = self._client.get_json(
            _PLAY_BY_PLAY_URL.format(game_id),
            timeout=self._timeout,
        )
        game = _mapping(payload)
        if str(game.get("id") or "") != game_id:
            raise ValueError("NHL response game identity does not match")
        period = _mapping(game.get("periodDescriptor"))
        clock = _mapping(game.get("clock"))
        if not period or not clock:
            raise ValueError("NHL response has no current period or clock")
        period_type = str(period.get("periodType") or "").upper()
        phase = {"REG": "regulation", "OT": "overtime", "SO": "shootout"}.get(period_type, "inactive")
        if str(game.get("gameState") or "").upper() not in {"LIVE", "CRIT"}:
            phase = "inactive"
        elif clock.get("inIntermission"):
            phase = "intermission"
        current = _mapping(game.get("situation"))
        code = str(current.get("situationCode") or "").strip()
        away = _mapping(current.get("awayTeam"))
        home = _mapping(current.get("homeTeam"))
        ice = _mapping(_mapping(game.get("summary")).get("iceSurface"))
        return {
            "gameId": game_id,
            "competition_stage": nhl_competition_stage(game),
            "startTimeUTC": str(game.get("startTimeUTC") or ""),
            "phase": phase,
            "situationCode": code,
            "situationOmitted": not current,
            "awayPowerPlay": "PP" in _descriptions(away),
            "homePowerPlay": "PP" in _descriptions(home),
            "powerPlaySecondsRemaining": current.get("secondsRemaining"),
            "penaltyBox": _current_penalties(game, ice),
            **_game_events(game),
        }


def _current_games(payload: object) -> tuple[tuple[str, str, str, bool], ...]:
    source = _mapping(payload)
    games = source.get("games")
    if not isinstance(games, Sequence) or isinstance(games, (str, bytes)):
        return ()
    result = []
    for value in games:
        game = _mapping(value)
        state = str(game.get("gameState") or "").upper()
        if state not in {"LIVE", "CRIT", "OFF", "FINAL"}:
            continue
        game_id = str(game.get("id") or "").strip()
        away = nhl_team_key(_mapping(game.get("awayTeam")).get("abbrev"))
        home = nhl_team_key(_mapping(game.get("homeTeam")).get("abbrev"))
        if game_id and away and home:
            result.append((game_id, away, home, state in {"OFF", "FINAL"}))
    return tuple(result)


def nhl_team_key(value: object) -> str:
    """Match ESPN and NHL team identities before joining live facts."""

    abbreviation = str(value or "").strip().upper()
    return {
        "NJ": "NJD", "LA": "LAK", "SJ": "SJS", "TB": "TBL",
        "WAS": "WSH", "VEG": "VGK", "UTAH": "UTA",
    }.get(abbreviation, abbreviation)


def _descriptions(team: Mapping[str, Any]) -> tuple[str, ...]:
    values = team.get("situationDescriptions")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return tuple(str(value).upper() for value in values)


def _current_penalties(game: Mapping[str, Any], ice: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Attach recorded penalty kinds to current penalty-box timers."""

    kinds: dict[str, str] = {}
    for play in sorted(_records(game.get("plays")), key=lambda value: int(value.get("sortOrder") or 0)):
        if play.get("typeDescKey") != "penalty":
            continue
        details = _mapping(play.get("details"))
        kind = str(details.get("typeCode") or "").upper()
        for key in ("committedByPlayerId", "servedByPlayerId"):
            if details.get(key) is not None:
                kinds[str(details[key])] = kind
    return {
        side: [{
            "jerseyNumber": player.get("sweaterNumber"),
            "secondsRemaining": player.get("secondsRemaining"),
            "kind": kinds.get(str(player.get("playerId")), ""),
        } for player in _records(_mapping(ice.get(f"{side}Team")).get("penaltyBox"))]
        for side in ("away", "home")
    }


def _game_events(game: Mapping[str, Any]) -> dict[str, Any]:
    """Read goal scorers and shootout attempts from the complete NHL ledger."""

    roster = {
        str(player.get("playerId")): player
        for player in _records(game.get("rosterSpots"))
    }
    team_ids = {
        str(_mapping(game.get(f"{side}Team")).get("id")): side
        for side in ("away", "home")
    }
    goals = []
    attempts: dict[str, list[str]] = {"away": [], "home": []}
    first_side = ""
    complete = str(game.get("gameState") or "").upper() in {"OFF", "FINAL"}
    seen: set[str] = set()
    for play in sorted(_records(game.get("plays")), key=lambda value: int(value.get("sortOrder") or 0)):
        identifier = str(play.get("eventId") or "")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        kind = str(play.get("typeDescKey") or "")
        period = _mapping(play.get("periodDescriptor"))
        details = _mapping(play.get("details"))
        if period.get("periodType") == "SO" and kind == "shootout-complete":
            complete = True
        side = team_ids.get(str(details.get("eventOwnerTeamId")))
        if side is None:
            continue
        if period.get("periodType") == "SO":
            if kind in {"goal", "shot-on-goal", "missed-shot", "failed-shot-attempt"}:
                if not first_side:
                    first_side = side
                attempts[side].append("goal" if kind == "goal" else "miss")
            continue
        if kind != "goal" or period.get("periodType") not in {"REG", "OT"}:
            continue
        player = _mapping(roster.get(str(details.get("scoringPlayerId"))))
        goals.append({
            "id": identifier,
            "side": side,
            "lastName": str(_mapping(player.get("lastName")).get("default") or ""),
            "jerseyNumber": player.get("sweaterNumber"),
            "period": period.get("number"),
            "clock": str(play.get("timeInPeriod") or ""),
        })
    shootout = {
        **attempts,
        "state": "complete" if complete else "active",
        "firstSide": first_side,
    } if _mapping(game.get("periodDescriptor")).get("periodType") == "SO" else None
    return {"goals": goals, "shootout": shootout}


def _records(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(record for record in value if isinstance(record, Mapping))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["NhlLiveSituationSource", "nhl_team_key"]
