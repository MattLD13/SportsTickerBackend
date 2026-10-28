"""Parse, merge, and filter ESPN scoreboard event records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import ContentItem
from sports_ticker.leagues import COLLEGE_FOOTBALL_LEAGUES, allows_college_conferences

from .payloads import (
    as_mapping as _mapping,
    as_sequence as _sequence,
    as_text as _text,
    first_mapping as _first_mapping,
)
from .logo_overrides import corrected_logo


_NCAA_LOGO_PROXY = "https://wsrv.nl/?url={}&output=png"


_NCAA_LOGO_ID_ALIASES = MappingProxyType(
    {
        "2355": "virginia-lynchburg",
        "2471": "northwestern-ia",
        "2595": "st-francis-il",
        "2691": "webber-intl",
        "2824": "okla-panhandle",
        "3077": "ky-christian",
        "102071": "lawrence-tech",
        "102626": "texas-wesleyan",
        "127991": "roosevelt",
    }
)


_COLLEGE_LOGO_DIRECT_URLS = MappingProxyType(
    {
        "2347": "https://dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/"
        "lcwildcats.net/images/responsive_2020/logo_main_new.svg",
    }
)


_NCAA_LOGO_NAME_ALIASES = MappingProxyType(
    {
        "lawrence tech": "lawrence-tech",
        "northwestern ia": "northwestern-ia",
        "oklahoma panhandle state": "okla-panhandle",
        "roosevelt": "roosevelt",
        "st francis il": "st-francis-il",
        "texas wesleyan": "texas-wesleyan",
        "virginia lynchburg": "virginia-lynchburg",
        "webber international": "webber-intl",
    }
)


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


def _merge_mlb_detail_payload(
    base: Mapping[str, Any], enrichment: Mapping[str, Any]
) -> dict[str, Any]:
    """Keep ESPN score fields while adding StatsAPI live detail fields."""

    merged = dict(base)
    for key in (
        "boxscore",
        "plays",
        "scoringPlays",
        "home_challenges",
        "home_challenges_used",
        "away_challenges",
        "away_challenges_used",
    ):
        value = enrichment.get(key)
        if value is not None and value != "":
            merged[key] = value
    situation = _mapping(enrichment.get("situation"))
    if situation:
        merged["situation"] = _merge_mapping(
            _mapping(base.get("situation")),
            situation,
        )
    return merged


def _merge_mlb_situation(
    base: Mapping[str, Any], merged: Mapping[str, Any]
) -> dict[str, Any]:
    """Retain scoreboard athlete names when Fastcast supplies matching IDs only."""

    result = dict(merged)
    for role in ("batter", "pitcher"):
        original = _mapping(base.get(role))
        current = _mapping(merged.get(role))
        if not original or not current:
            continue
        original_id = _mlb_person_id(original)
        current_id = _mlb_person_id(current)
        if original_id and current_id and original_id != current_id:
            continue
        result[role] = _merge_mapping(original, current)
    return result


def _event_competition(payload: Any) -> Mapping[str, Any]:
    """Read one competition from an ESPN event response."""

    source = _mapping(payload)
    header = _mapping(source.get("header"))
    return _first_mapping(header.get("competitions") or source.get("competitions"))


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


def _merge_mapping(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay nonempty source fields while retaining scoreboard fields."""

    merged = dict(base)
    for key, value in overlay.items():
        if value is not None and (not isinstance(value, Mapping) or value):
            merged[key] = value
    return merged


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


def _display_timezone(value: str) -> ZoneInfo:
    """Use the ticker time zone or the established New York default."""

    try:
        return ZoneInfo(value.strip() or "America/New_York")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


def _event_time(value: object) -> datetime | None:
    """Read one ESPN event start time as a UTC datetime."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _content_item(
    league: str,
    event: Mapping[str, Any],
    *,
    ncaa_logo_index: Mapping[str, str] | None = None,
) -> ContentItem:
    if not isinstance(event, Mapping):
        raise TypeError("event must be an object")
    event_id = str(event.get("id", "")).strip()
    if not event_id:
        raise ValueError("event id is missing")

    competition = _first_mapping(event.get("competitions"))
    competitors = _competitors(competition.get("competitors"))
    home = _find_side(competitors, "home")
    away = _find_side(competitors, "away")
    status_obj = _mapping(event.get("status"))
    type_obj = _mapping(status_obj.get("type"))
    state = _text(type_obj.get("state"), "pre")
    status = _text(
        type_obj.get("shortDetail")
        or type_obj.get("detail")
        or type_obj.get("description")
        or status_obj.get("displayValue")
        or state,
    )
    if state == "pre":
        status = _SCHEDULED_DATE_PREFIX.sub("", status)
        time_match = _SCHEDULED_TIME.search(status)
        if time_match:
            status = f"{time_match.group('time')} {time_match.group('meridiem')}"
    home_team = _team(home, ncaa_logo_index if league in COLLEGE_FOOTBALL_LEAGUES else {})
    away_team = _team(away, ncaa_logo_index if league in COLLEGE_FOOTBALL_LEAGUES else {})
    home_team["logo"] = corrected_logo(league, home_team["abbreviation"], home_team["logo"])
    away_team["logo"] = corrected_logo(league, away_team["abbreviation"], away_team["logo"])
    display_data = {
        "type": "scoreboard",
        "sport": league,
        "id": event_id,
        "state": state,
        "status": status,
        "startTimeUTC": _text(event.get("date")),
        "estimated_duration": 180,
        "home_abbr": home_team["abbreviation"],
        "home_score": home_team["score"],
        "home_logo": home_team["logo"],
        "home_color": home_team["color"],
        "home_alt_color": home_team["alt_color"],
        "away_abbr": away_team["abbreviation"],
        "away_score": away_team["score"],
        "away_logo": away_team["logo"],
        "away_color": away_team["color"],
        "away_alt_color": away_team["alt_color"],
    }
    if isinstance(event.get("_source_timing"), Mapping):
        display_data["_source_timing"] = event["_source_timing"]
    if league in COLLEGE_FOOTBALL_LEAGUES:
        display_data.update(
            {
                "home_conference_id": _conference_id(home),
                "away_conference_id": _conference_id(away),
            }
        )
    return ContentItem(
        id=event_id,
        family="sports",
        kind="scoreboard",
        is_shown=True,
        data=display_data,
    )


def _competitors(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("competition competitors must be an array")
    return tuple(item for item in value if isinstance(item, Mapping))


def _find_side(competitors: Sequence[Mapping[str, Any]], side: str) -> Mapping[str, Any]:
    for competitor in competitors:
        if str(competitor.get("homeAway", "")).strip().lower() == side:
            return competitor
    index = 0 if side == "home" else 1
    return competitors[index] if len(competitors) > index else {}


def _team(
    competitor: Mapping[str, Any],
    ncaa_logo_index: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    source = _mapping(competitor.get("team"))
    logo = _team_source_logo(source)
    if not logo:
        logo = _ncaa_logo_url(source, ncaa_logo_index or {})
    return {
        "abbreviation": _text(
            source.get("abbreviation")
            or source.get("shortDisplayName")
            or source.get("displayName")
        ),
        "score": _text(competitor.get("score", competitor.get("displayScore"))),
        "logo": None if logo is None else str(logo),
        "color": _hex_color(source.get("color")),
        "alt_color": _hex_color(source.get("alternateColor")),
    }


def _team_source_logo(source: Mapping[str, Any]) -> str:
    """Return the first usable logo URL supplied by ESPN."""

    logo = source.get("logo")
    if str(logo or "").strip():
        return str(logo).strip()
    for value in _sequence(source.get("logos")):
        href = _mapping(value).get("href")
        if str(href or "").strip():
            return str(href).strip()
    return ""


def _team_name_candidates(source: Mapping[str, Any]) -> tuple[str, ...]:
    """Return stable source names for NCAA school matching."""

    values = (
        source.get("id"),
        source.get("location"),
        source.get("shortDisplayName"),
        source.get("displayName"),
    )
    return tuple(str(value).strip() for value in values if str(value or "").strip())


def _ncaa_logo_url(source: Mapping[str, Any], index: Mapping[str, str]) -> str | None:
    """Build a raster logo URL when NCAA can identify an ESPN team."""

    candidates = _team_name_candidates(source)
    svg_url = _COLLEGE_LOGO_DIRECT_URLS.get(candidates[0], "") if candidates else ""
    if not svg_url:
        slug = _NCAA_LOGO_ID_ALIASES.get(candidates[0], "") if candidates else ""
        if not slug:
            for candidate in candidates[1:]:
                slug = _NCAA_LOGO_NAME_ALIASES.get(_normalize_team_name(candidate), "")
                if slug:
                    break
                slug = index.get(_normalize_team_name(candidate), "")
                if slug:
                    break
        if not slug:
            return None
        svg_url = f"https://ncaa-api.henrygd.me/logo/{slug}.svg?dark=true"
    return _NCAA_LOGO_PROXY.format(quote(svg_url, safe=""))


def _normalize_team_name(value: Any) -> str:
    """Normalize school names for conservative exact matching."""

    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"['ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢]", "", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _event_detail_url(league: str, scoreboard_url: str) -> str:
    """Derive the ESPN summary endpoint that carries live scoring facts."""

    endpoint = scoreboard_url.split("?", 1)[0].rstrip("/")
    del league
    scoreboard_root = endpoint.removesuffix("/scoreboard")
    return f"{scoreboard_root}/summary?event={{}}"


def _mlb_person_id(value: Any) -> str:
    player = _mapping(value)
    athlete = _mapping(player.get("athlete"))
    return str(
        player.get("playerId") or player.get("id") or athlete.get("id") or ""
    ).strip()


def _hex_color(value: Any) -> str:
    """Return a renderer-ready six digit color or an empty value."""

    text = _text(value).strip().lstrip("#")
    if len(text) != 6:
        return ""
    try:
        int(text, 16)
    except ValueError:
        return ""
    return f"#{text.upper()}"


_SCHEDULED_DATE_PREFIX = re.compile(r"^\d{1,2}/\d{1,2}\s*-\s*")


_SCHEDULED_TIME = re.compile(r"(?P<time>\d{1,2}:\d{2})\s*(?P<meridiem>[AP]M)\b")
