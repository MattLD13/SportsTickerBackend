"""Read live NHL situation codes from the league feed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Thread
import time
from typing import Any

from .http import JsonHttpClient, UrllibJsonHttpClient


_SCORE_URL = "https://api-web.nhle.com/v1/score/now"
_PLAY_BY_PLAY_URL = "https://api-web.nhle.com/v1/gamecenter/{}/play-by-play"


class NhlLiveSituationSource:
    """Cache NHL manpower facts without delaying scoreboard refreshes."""

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
        self._updated_at: float | None = None
        self._last_started = float("-inf")
        self._refreshing = False
        self._lock = Lock()

    def snapshot(self) -> dict[tuple[str, str], dict[str, Any]]:
        """Return cached situations and refresh outside the caller."""

        if self._background:
            self._start_refresh()
        else:
            self._refresh()
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
            games = _live_games(self._client.get_json(_SCORE_URL, timeout=self._timeout))
            situations: dict[tuple[str, str], dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=min(8, max(1, len(games)))) as pool:
                futures = {
                    pool.submit(self._read_game_situation, game_id): (away, home)
                    for game_id, away, home in games
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        situation = future.result()
                    except Exception:
                        continue
                    if situation:
                        situations[key] = situation
            with self._lock:
                live_keys = {(away, home) for _, away, home in games}
                for key, value in self._cache.items():
                    if key in live_keys:
                        situations.setdefault(key, value)
                self._cache = situations
                self._updated_at = self._monotonic()
        except Exception:
            return
        finally:
            if self._background:
                with self._lock:
                    self._refreshing = False

    def _read_game_situation(self, game_id: str) -> dict[str, Any]:
        payload = self._client.get_json(
            _PLAY_BY_PLAY_URL.format(game_id), timeout=self._timeout
        )
        code = _latest_situation_code(payload)
        if not code:
            return {}
        summary = _mapping(_mapping(payload).get("summary"))
        ice = _mapping(summary.get("iceSurface"))
        away = _mapping(ice.get("awayTeam"))
        home = _mapping(ice.get("homeTeam"))
        return {
            "situationCode": code,
            "awayPenaltyBoxCount": _count(away.get("penaltyBox")),
            "homePenaltyBoxCount": _count(home.get("penaltyBox")),
        }


def _live_games(payload: object) -> tuple[tuple[str, str, str], ...]:
    games = _mapping(payload).get("games")
    if not isinstance(games, Sequence) or isinstance(games, (str, bytes)):
        return ()
    result = []
    for value in games:
        game = _mapping(value)
        if str(game.get("gameState") or "").upper() not in {"LIVE", "CRIT"}:
            continue
        game_id = str(game.get("id") or "").strip()
        away = str(_mapping(game.get("awayTeam")).get("abbrev") or "").strip().upper()
        home = str(_mapping(game.get("homeTeam")).get("abbrev") or "").strip().upper()
        if game_id and away and home:
            result.append((game_id, away, home))
    return tuple(result)


def _latest_situation_code(payload: object) -> str:
    plays = _mapping(payload).get("plays")
    if not isinstance(plays, Sequence) or isinstance(plays, (str, bytes)):
        return ""
    candidates = []
    for play in plays:
        source = _mapping(play)
        code = str(source.get("situationCode") or "").strip()
        if len(code) != 4 or not code.isdigit():
            continue
        try:
            order = int(source.get("sortOrder") or -1)
        except (TypeError, ValueError):
            order = -1
        candidates.append((order, code))
    return max(candidates, default=(-1, ""))[1]


def _count(value: object) -> int:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    return 1 if value else 0


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["NhlLiveSituationSource"]
