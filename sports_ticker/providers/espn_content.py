"""Project ESPN events into content items with team logos and college rankings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import quote

from sports_ticker.domain import ContentItem
from sports_ticker.leagues import COLLEGE_FOOTBALL_LEAGUES

from .logo_overrides import corrected_logo
from .payloads import as_mapping as _mapping
from .sports_display import normalize_rank
from .espn_values import (
    _SCHEDULED_DATE_PREFIX,
    _SCHEDULED_TIME,
    _competitors,
    _find_side,
    _first_mapping,
    _hex_color,
    _sequence,
    _text,
)
from .espn_schedule import _conference_id


_NCAA_FBS_PLAYOFF_RANKING_URL = "https://ncaa-api.henrygd.me/rankings/football/fbs/college-football-playoff"


_NCAA_FBS_AP_RANKING_URL = "https://ncaa-api.henrygd.me/rankings/football/fbs/associated-press"


_NCAA_FCS_COACHES_RANKING_URL = "https://ncaa-api.henrygd.me/rankings/football/fcs/afca-fcs-coaches-poll"


_NCAA_RANKING_MONTHS = MappingProxyType(
    {name: number for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )}
)


_NCAA_RANKING_THROUGH_DATE = re.compile(r"([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),\s*(\d{4})")


_NCAA_SEASON_START_MONTH = 6


_RANKINGS_CACHE_SECONDS = 300.0


_NCAA_SCHOOLS_INDEX_URL = "https://ncaa-api.henrygd.me/schools-index"


_NCAA_LOGO_CACHE_SECONDS = 86400.0


_NCAA_LOGO_FAILURE_RETRY_SECONDS = 60.0


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


def _needs_ncaa_logo_lookup(
    active_leagues: Sequence[tuple[str, str]],
    events_by_league: Mapping[str, Sequence[Mapping[str, Any]]],
) -> bool:
    """Return whether an active college football event lacks an ESPN logo."""

    for league, _url in active_leagues:
        if league not in COLLEGE_FOOTBALL_LEAGUES:
            continue
        for event in events_by_league.get(league, ()):
            competition = _first_mapping(event.get("competitions"))
            for competitor in _competitors(competition.get("competitors")):
                source = _mapping(competitor.get("team"))
                if not _team_source_logo(source) and _team_name_candidates(source):
                    return True
    return False


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


def _parse_ncaa_school_index(payload: Any) -> dict[str, str]:
    """Map unique NCAA school names to logo slugs."""

    records = _sequence(payload)
    candidates: dict[str, set[str]] = {}
    for record in records:
        source = _mapping(record)
        slug = str(source.get("slug") or "").strip()
        if not slug:
            continue
        for value in (source.get("name"), source.get("long"), slug):
            key = _normalize_team_name(value)
            if key:
                candidates.setdefault(key, set()).add(slug)
    return {
        key: next(iter(slugs))
        for key, slugs in candidates.items()
        if len(slugs) == 1
    }


def _normalize_team_name(value: Any) -> str:
    """Normalize school names for conservative exact matching."""

    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"['ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢]", "", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


_COLLEGE_RANKING_NAME_ALIASES = MappingProxyType(
    {
        "southern cal": "usc",
        "southern california": "usc",
        "miami fl": "miami",
        "miami fla": "miami",
        "miami florida": "miami",
        "miami ohio": "miami oh",
        "pitt": "pittsburgh",
        "uconn": "connecticut",
    }
)


def _ncaa_poll_in_current_season(payload: Any, now: datetime) -> bool:
    """Return whether an NCAA poll's "Through Games" date falls in the current season."""

    match = _NCAA_RANKING_THROUGH_DATE.search(str(_mapping(payload).get("updated") or ""))
    month = _NCAA_RANKING_MONTHS.get(match.group(1).casefold()) if match else None
    if match is None or month is None:
        return False
    season_year = now.year if now.month >= _NCAA_SEASON_START_MONTH else now.year - 1
    try:
        through = date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return False
    return through >= date(season_year, _NCAA_SEASON_START_MONTH, 1)


def _parse_ncaa_college_football_rankings(payload: Any) -> dict[str, str]:
    """Map NCAA ranking rows to normalized school names."""

    result: dict[str, str] = {}
    for entry in _sequence(_mapping(payload).get("data")):
        source = _mapping(entry)
        rank = normalize_rank(source.get("RANK"))
        if not rank:
            continue
        for key in _college_ranking_name_keys(source.get("SCHOOL")):
            result.setdefault(key, rank)
    return result


def _college_ranking_name_keys(value: Any) -> tuple[str, ...]:
    """Return conservative NCAA and ESPN school-name keys for one ranking row."""

    text = re.sub(r"\s*\(\d+\)\s*$", "", str(value or ""))
    normalized = _normalize_team_name(text)
    if not normalized:
        return ()
    words = normalized.split()
    if words[-1] == "st":
        words[-1] = "state"
    normalized = " ".join(words)
    alias = _COLLEGE_RANKING_NAME_ALIASES.get(normalized)
    return tuple(dict.fromkeys(key for key in (normalized, alias) if key))


def _resolve_college_football_rankings(
    rankings: Mapping[str, Mapping[str, str]],
    events_by_league: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, str]:
    """Resolve both NCAA polls to ESPN team IDs carried by scoreboard events."""

    resolved: dict[str, str] = {}
    college_events = tuple(
        event
        for league in COLLEGE_FOOTBALL_LEAGUES
        for event in events_by_league.get(league, ())
    )
    for league, name_rankings in rankings.items():
        if league not in COLLEGE_FOOTBALL_LEAGUES:
            continue
        for event in college_events:
            competition = _first_mapping(event.get("competitions"))
            for competitor in _competitors(competition.get("competitors")):
                team = _mapping(competitor.get("team"))
                team_id = str(team.get("id") or competitor.get("id") or "").strip()
                if not team_id:
                    continue
                rank = next(
                    (
                        name_rankings[key]
                        for candidate in _team_name_candidates(team)
                        for key in _college_ranking_name_keys(candidate)
                        if key in name_rankings
                    ),
                    "",
                )
                if rank:
                    resolved.setdefault(team_id, rank)
    return resolved
