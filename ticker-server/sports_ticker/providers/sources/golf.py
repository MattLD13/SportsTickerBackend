"""Read live golf content through an injected source."""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Any, Callable
from sports_ticker.domain import DisplaySettings
from ..espn import _display_timezone, _event_time
from ..http import JsonHttpClient, OwnedClient, PooledJsonHttpClient
from ..payloads import as_mapping as _mapping, mapping_values as _mappings
from ..sports_display import golf_competition_stage
from .values import _timeout


ESPN_GOLF_URL = "https://site.web.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"


class EspnGolfSource:
    """Read the PGA scoreboard directly from ESPN."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client_owner = OwnedClient(client, PooledJsonHttpClient)
        self._client = self._client_owner.client
        self._timeout = _timeout(timeout)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache_lock = Lock()
        self._cache: tuple[float, tuple[str, object], Mapping[str, object]] | None = None

    def close(self) -> None:
        self._client_owner.close()

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        now = self._now()
        cache_key = (settings.timezone, now.astimezone(_display_timezone(settings.timezone)).date())
        monotonic_now = monotonic()
        with self._cache_lock:
            if self._cache is not None:
                cached_at, cached_key, cached_value = self._cache
                if cached_key == cache_key and 0 <= monotonic_now - cached_at < 5.0:
                    return cached_value

            payload = self._client.get_json(ESPN_GOLF_URL, timeout=self._timeout)
            event = _first_event(payload)
            if event is None or not _is_current_golf_event(event, timezone_name=settings.timezone, now=now):
                result: Mapping[str, object] = {"content": []}
            else:
                competition = _first_mapping(event.get("competitions"))
                status = _status(event, competition)
                event_name = str(event.get("name") or "PGA TOUR")
                if _is_golf_match_play(competition):
                    golf = _golf_match_play(event, competition)
                    display_status = "Match Play"
                else:
                    players = [_golf_player(value) for value in _mappings(competition.get("competitors"))]
                    players = _rank_golf_players(value for value in players if value is not None)
                    display_status = status["text"]
                    golf = {
                        "brand": _golf_brand(event_name),
                        "event_name": event_name,
                        "year": _mapping(event.get("season")).get("year", now.year),
                        "round": _golf_round(status["text"]),
                        "players": players,
                    }
                result = {
                    "content": [
                        {
                            "id": f"golf:{event.get('id', 'pga')}",
                            "type": "golf",
                            "sport": "golf",
                            "competition_stage": golf_competition_stage(event),
                            "state": status["state"],
                            "status": display_status,
                            "away_abbr": str(event.get("shortName") or event_name),
                            "golf": golf,
                        }
                    ]
                }
            self._cache = (monotonic_now, cache_key, result)
            return result


def _golf_player(value: Mapping[str, Any]) -> dict[str, object] | None:
    athlete = _mapping(value.get("athlete"))
    name = str(athlete.get("displayName") or athlete.get("shortName") or "").strip()
    if not name:
        return None
    round_scores = _mappings(value.get("linescores"))
    holes = _mappings(round_scores[0].get("linescores")) if round_scores else ()
    return {
        "pos": "-",
        "name": name,
        "total": value.get("score", 0),
        "today": round_scores[0].get("displayValue") if round_scores else None,
        "thru": len(holes),
        "holes": [item.get("value") for item in holes[:18]],
    }


def _rank_golf_players(players: object) -> list[dict[str, object]]:
    """Assign competition ranks so equal totals share a tied position."""

    rows = [dict(value) for value in players if isinstance(value, Mapping)]
    totals = [str(row.get("total") or "").strip().upper() for row in rows]
    rank = 1
    index = 0
    while index < len(rows):
        total = totals[index]
        end = index + 1
        while end < len(rows) and totals[end] == total:
            end += 1
        group_size = end - index
        for row in rows[index:end]:
            row["pos"] = f"T{rank}" if group_size > 1 and total else str(rank) if total else "-"
        rank += group_size
        index = end
    return rows


def _first_event(payload: object) -> Mapping[str, Any] | None:
    return _mappings(_mapping(payload).get("events"))[0] if _mappings(_mapping(payload).get("events")) else None


def _status(event: Mapping[str, Any], competition: Mapping[str, Any]) -> dict[str, str]:
    source = _mapping(competition.get("status")) or _mapping(event.get("status"))
    kind = _mapping(source.get("type"))
    return {
        "state": str(kind.get("state") or "pre").lower(),
        "text": str(kind.get("shortDetail") or kind.get("detail") or kind.get("description") or "Scheduled"),
    }


def _is_current_golf_event(
    event: Mapping[str, Any],
    *,
    timezone_name: str = "",
    now: datetime | None = None,
) -> bool:
    """Return True if one golf event is live or scheduled for the active local day."""

    source = _first_mapping(event.get("competitions")) or event
    status = _mapping(source.get("status")) or _mapping(event.get("status"))
    kind = _mapping(status.get("type"))
    state = str(kind.get("state") or "pre").strip().lower()
    if state in {"in", "half", "crit"}:
        return True

    starts_at = _event_time(event.get("date") or source.get("date"))
    if starts_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    tz = _display_timezone(timezone_name)
    local_now = current.astimezone(tz)
    local_start = starts_at.astimezone(tz)
    current_date = (local_now - timedelta(days=1)).date() if local_now.hour < 3 else local_now.date()

    if state == "pre":
        return current_date >= local_start.date()

    ends_at = _event_time(event.get("endDate") or source.get("endDate")) or starts_at
    local_end = ends_at.astimezone(tz)
    return local_start.date() <= current_date <= local_end.date()


def _golf_round(status: str) -> str:
    """Return a stable golf round label when ESPN provides one."""

    match = re.search(r"\bround\s*(\d+)\b", status, re.IGNORECASE)
    return f"Round {match.group(1)}" if match else status


def _golf_brand(event_name: str) -> str:
    """Return the explicit golf palette brand for one source event."""

    return "masters" if "masters" in event_name.casefold() else "pga"


def _is_golf_match_play(competition: Mapping[str, Any]) -> bool:
    """Identify a team event from its top-level team competitors."""

    competitors = _mappings(competition.get("competitors"))
    return len(competitors) >= 2 and all(
        str(_mapping(value.get("team")).get("abbreviation") or "").strip()
        and not _mapping(value.get("athlete"))
        for value in competitors
    )


def _golf_match_play(event: Mapping[str, Any], competition: Mapping[str, Any]) -> dict[str, object]:
    """Project team totals and match results from an ESPN golf event."""

    teams = []
    for competitor in _mappings(competition.get("competitors")):
        team = _mapping(competitor.get("team"))
        teams.append({
            "abbr": str(team.get("abbreviation") or team.get("shortDisplayName") or "TEAM"),
            "name": str(team.get("shortDisplayName") or team.get("displayName") or team.get("name") or "Team"),
            "score": str(competitor.get("score") or "0"),
        })

    matches = []
    competitions = _mappings(event.get("competitions"))
    for match in competitions[1:]:
        competitors = _mappings(match.get("competitors"))
        sides = []
        for competitor in competitors:
            team = _mapping(competitor.get("team"))
            athlete = _mapping(competitor.get("athlete"))
            name = str(athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "")
            sides.append({
                "team": str(team.get("abbreviation") or "TEAM"),
                "player": name,
                "score": str(competitor.get("score") or ""),
            })
        if len(sides) < 2:
            continue
        match_state = _status(match, {})
        match_type = str(_mapping(match.get("type")).get("id") or "")
        matches.append({
            "type": match_type,
            "status": match_state["text"],
            "state": match_state["state"],
            "sides": sides,
        })
    state_order = {"in": 0, "half": 0, "pre": 1, "post": 2}
    matches.sort(key=lambda value: state_order.get(str(value["state"]), 3))

    event_name = str(event.get("name") or "PGA TOUR")
    return {
        "brand": _golf_brand(event_name),
        "event_name": event_name,
        "year": _mapping(event.get("season")).get("year", ""),
        "format": "match_play",
        "teams": teams,
        "matches": matches,
    }


def _first_mapping(value: object) -> Mapping[str, Any]:
    values = _mappings(value)
    return values[0] if values else {}


__all__ = ['EspnGolfSource']
