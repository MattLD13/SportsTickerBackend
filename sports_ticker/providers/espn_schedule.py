"""Read ESPN scoreboard events, calendar dates, and live refresh rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sports_ticker.domain import DisplaySettings
from sports_ticker.leagues import allows_college_conferences

from .payloads import as_mapping as _mapping
from .espn_values import (
    _display_timezone,
    _event_time,
    _first_mapping,
    _merge_mapping,
    _sequence,
    _text,
)
from .espn_mlb import _merge_mlb_situation


def _source_key(
    scoreboard_urls: Mapping[str, str],
    settings: DisplaySettings,
    dates: Sequence[date],
) -> tuple[object, ...]:
    """Identify the upstream view without including ticker-specific alert settings."""

    enabled = tuple(
        (league, bool(settings.active_sports.get(league, True)))
        for league in scoreboard_urls
    )
    conferences = tuple(sorted(settings.active_conferences.items()))
    return settings.timezone, tuple(dates), enabled, conferences


def _event_league_priority(league: str) -> int:
    """Give duplicate college football events to the FCS feed before the FBS feed."""

    if league == "ncf_fcs":
        return 0
    if league == "ncf_fbs":
        return 1
    return 2


def _events(payload: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(payload, Mapping):
        raise TypeError("response JSON must be an object")
    events = payload.get("events")
    if events is not None and (
        not isinstance(events, Sequence) or isinstance(events, (str, bytes))
    ):
        raise TypeError("events must be an array")
    if events is None:
        leagues = payload.get("leagues")
        first_league = leagues[0] if isinstance(leagues, Sequence) and leagues else None
        events = first_league.get("events") if isinstance(first_league, Mapping) else ()
    if events is None:
        return ()
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise TypeError("events must be an array")
    return tuple(events)


def _filter_college_conference_events(
    league: str,
    events: Sequence[Mapping[str, Any]],
    active_conferences: Mapping[str, bool],
) -> tuple[Mapping[str, Any], ...]:
    """Keep college events that include at least one enabled conference."""

    return tuple(
        event
        for event in events
        if allows_college_conferences(
            league,
            _event_conference_ids(event),
            active_conferences,
        )
    )


def _event_conference_ids(event: Mapping[str, Any]) -> tuple[str, ...]:
    """Read conference IDs from ESPN scoreboard team records."""

    if not isinstance(event, Mapping):
        return ()
    competition = _first_mapping(event.get("competitions"))
    identifiers: list[str] = []
    for competitor in _sequence(competition.get("competitors")):
        identifier = _conference_id(_mapping(competitor))
        if identifier:
            identifiers.append(identifier)
    return tuple(dict.fromkeys(identifiers))


def _conference_id(competitor: Mapping[str, Any]) -> str:
    """Read one ESPN team's conference ID from a competitor record."""

    team = _mapping(competitor.get("team"))
    return str(
        team.get("conferenceId")
        or team.get("conference_id")
        or competitor.get("conferenceId")
        or ""
    ).strip()


def _event_payload(payload: Any) -> Mapping[str, Any]:
    """Extract one event from ESPN's single-event scoreboard response."""

    source = _mapping(payload)
    if source.get("id") or _mapping(source.get("header")).get("id"):
        return source
    events = _events(source)
    event = next((item for item in events if _mapping(item).get("id")), None)
    if not isinstance(event, Mapping):
        raise TypeError("single-event scoreboard response omitted event")
    return event


def _merge_event_collections(
    fallback: Sequence[Mapping[str, Any]],
    updates: Sequence[Mapping[str, Any]],
    *,
    league: str = "",
) -> tuple[Mapping[str, Any], ...]:
    """Merge one Fastcast event collection into its complete schedule."""

    updates_by_id = {
        str(event.get("id") or "").strip(): event
        for event in updates
        if str(event.get("id") or "").strip()
    }
    merged: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for event in fallback:
        event_id = str(event.get("id") or "").strip()
        update = updates_by_id.get(event_id)
        merged.append(
            _event_update(update, event, league=league) if update is not None else event
        )
        if event_id:
            seen.add(event_id)
    merged.extend(
        event
        for event_id, event in updates_by_id.items()
        if event_id not in seen
    )
    return tuple(merged)


def _event_update(
    payload: Any,
    fallback: Mapping[str, Any],
    *,
    league: str = "",
) -> Mapping[str, Any]:
    """Merge one native ESPN event update into its cached scoreboard event."""

    source = _mapping(payload)
    header = _mapping(source.get("header"))
    competition = _first_mapping(
        header.get("competitions") or source.get("competitions")
    )
    if not competition:
        return fallback
    event = dict(fallback)
    event_id = str(
        event.get("id")
        or header.get("id")
        or source.get("id")
        or competition.get("id")
        or ""
    ).strip()
    if event_id:
        event["id"] = event_id
    if competition.get("date") or header.get("date") or source.get("date"):
        event["date"] = competition.get("date") or header.get("date") or source.get("date")
    fallback_status = _mapping(event.get("status"))
    update_status = _mapping(
        competition.get("status") or header.get("status") or source.get("status")
    )
    preserve_nhl_live_status = (
        str(league).strip().lower() == "nhl"
        and _status_rank(update_status) == 1
        and _status_rank(fallback_status) == 1
    )
    if preserve_nhl_live_status:
        event["status"] = fallback_status
    elif _status_rank(update_status) >= _status_rank(fallback_status):
        event["status"] = _merge_mapping(fallback_status, update_status)
    scoreboard_competition = _first_mapping(event.get("competitions"))
    merged_competition = _merge_mapping(scoreboard_competition, competition)
    merged_competition["competitors"] = _merge_competitors(
        scoreboard_competition.get("competitors"),
        competition.get("competitors"),
    )
    if preserve_nhl_live_status:
        scoreboard_status = _mapping(scoreboard_competition.get("status"))
        if scoreboard_status:
            merged_competition["status"] = scoreboard_status
    scoreboard_situation = _mapping(scoreboard_competition.get("situation"))
    update_situation = _mapping(source.get("situation")) or _mapping(
        competition.get("situation")
    )
    if scoreboard_situation or update_situation:
        merged_competition["situation"] = _merge_mapping(
            scoreboard_situation,
            update_situation,
        )
        merged_competition["situation"] = _merge_mlb_situation(
            scoreboard_situation,
            merged_competition["situation"],
        )
    event["competitions"] = [merged_competition]
    return event


def _is_current_event(
    event: Mapping[str, Any],
    *,
    timezone_name: str = "",
    now: datetime | None = None,
) -> bool:
    """Match the original local-day window that ends at 3 AM."""

    status = _mapping(_mapping(event.get("status")).get("type"))
    state = _text(status.get("state"), "pre").strip().lower()
    if state in {"in", "half", "crit"}:
        return True

    starts_at = _event_time(event.get("date"))
    if starts_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(_display_timezone(timezone_name))
    if local_now.hour < 3:
        visible_start = (local_now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        visible_end = local_now.replace(hour=3, minute=0, second=0, microsecond=0)
    else:
        visible_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        visible_end = (local_now + timedelta(days=1)).replace(
            hour=3, minute=0, second=0, microsecond=0
        )
    return visible_start.astimezone(timezone.utc) <= starts_at < visible_end.astimezone(timezone.utc)


def _scoreboard_dates(
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> tuple[date, ...]:
    """Return ESPN dates needed for the current local display window."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(_display_timezone(timezone_name))
    today = local_now.date()
    if local_now.hour < 3:
        return (today - timedelta(days=1), today)
    return (today, today + timedelta(days=1))


def _schedule_day(timezone_name: str, now: datetime) -> date:
    """Group schedules into the local day that owns the 3am full sweep."""

    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(_display_timezone(timezone_name))
    return local_now.date() if local_now.hour >= 3 else local_now.date() - timedelta(days=1)


def _league_needs_refresh(events: Sequence[Mapping[str, Any]], now: datetime) -> bool:
    """Refresh one cached league when it contains a live or newly starting game."""

    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    for event in events:
        if _event_needs_live_refresh(event, current):
            return True
    return False


def _event_needs_live_refresh(event: Mapping[str, Any], now: datetime) -> bool:
    """Refresh a cached event when it can contain live score changes."""

    status = _mapping(_mapping(event.get("status")).get("type"))
    state = _text(status.get("state"), "pre").strip().lower()
    if state in {"in", "half", "crit"}:
        return True
    if state in {"post", "final", "canceled", "cancelled"}:
        return False
    start = _event_time(event.get("date"))
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    return start is not None and start <= current <= start + timedelta(hours=6)


def _unique_live_events(
    events: Sequence[Mapping[str, Any]],
    now: datetime,
) -> tuple[Mapping[str, Any], ...]:
    """Return live-refresh candidates once per event identifier."""

    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        event_id = str(event.get("id") or "").strip()
        if not event_id or event_id in seen or not _event_needs_live_refresh(event, now):
            continue
        seen.add(event_id)
        unique.append(event)
    return tuple(unique)


def _status_rank(status: Mapping[str, Any]) -> int:
    """Rank event status without allowing a live event to regress to pregame."""

    state = str(_mapping(status.get("type")).get("state") or "pre").strip().lower()
    if state in {"post", "final"}:
        return 2
    if state in {"in", "half", "crit"}:
        return 1
    return 0


def _merge_competitors(base: Any, overlay: Any) -> list[Mapping[str, Any]]:
    """Merge event competitors without dropping scoreboard team metadata."""

    scoreboard = list(_sequence(base))
    summary = list(_sequence(overlay))
    used: set[int] = set()
    merged: list[Mapping[str, Any]] = []
    for original in scoreboard:
        original_mapping = _mapping(original)
        match_index = next(
            (
                index
                for index, candidate in enumerate(summary)
                if index not in used and _competitor_key(candidate) == _competitor_key(original_mapping)
            ),
            None,
        )
        if match_index is None:
            merged.append(original_mapping)
            continue
        used.add(match_index)
        candidate = _mapping(summary[match_index])
        item = _merge_mapping(original_mapping, candidate)
        item["team"] = _merge_mapping(
            _mapping(original_mapping.get("team")),
            _mapping(candidate.get("team")),
        )
        merged.append(item)
    merged.extend(
        _mapping(candidate)
        for index, candidate in enumerate(summary)
        if index not in used and _mapping(candidate)
    )
    return merged


def _competitor_key(value: Mapping[str, Any]) -> tuple[str, str]:
    """Identify one competitor by side and team identifier."""

    team = _mapping(value.get("team"))
    return (
        str(value.get("homeAway") or "").strip().lower(),
        str(value.get("id") or team.get("id") or "").strip(),
    )


def _scoreboard_url_for_dates(scoreboard_url: str, dates: Sequence[date]) -> str:
    """Add explicit ESPN calendar dates without dropping existing query values."""

    parsed = urlsplit(scoreboard_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "dates"]
    values = tuple(dates)
    if not values:
        raise ValueError("dates must not be empty")
    query.extend(("dates", day.strftime("%Y%m%d")) for day in values)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _event_detail_url(league: str, scoreboard_url: str) -> str:
    """Derive the ESPN summary endpoint that carries live scoring facts."""

    endpoint = scoreboard_url.split("?", 1)[0].rstrip("/")
    del league
    scoreboard_root = endpoint.removesuffix("/scoreboard")
    return f"{scoreboard_root}/summary?event={{}}"


def _mlb_api_summary_url(request_url: str) -> str:
    """Return ESPN's API-host equivalent for one MLB summary URL."""

    return request_url.replace(
        "site.web.api.espn.com",
        "site.api.espn.com",
    )
