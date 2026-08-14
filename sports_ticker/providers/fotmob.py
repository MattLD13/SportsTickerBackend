"""Fetch detailed soccer scoreboards from FotMob."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import ContentItem, DisplaySettings

from .contracts import ProviderHealth, ProviderResult
from .http import JsonHttpClient, UrllibJsonHttpClient
from .stale_cache import SettingsResultCache
from .sports_display import normalize_soccer_clock, soccer_event


_MATCHES_URL = "https://www.fotmob.com/api/data/matches"
_DETAIL_URL = "https://www.fotmob.com/api/data/matchDetails?matchId={match_id}"
_SOCCER_ABBREVIATIONS = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE",
    "Brighton & Hove Albion": "BHA", "Burnley": "BUR", "Chelsea": "CHE", "Crystal Palace": "CRY",
    "Everton": "EVE", "Fulham": "FUL", "Leeds United": "LEE", "Leicester City": "LEI",
    "Liverpool": "LIV", "Manchester City": "MCI", "Manchester United": "MUN",
    "Newcastle United": "NEW", "Nottingham Forest": "NFO", "Southampton": "SOU",
    "Tottenham Hotspur": "TOT", "West Ham United": "WHU", "Wolverhampton": "WOL",
    "Blackburn Rovers": "BLA", "Bristol City": "BRC", "Cardiff City": "CAR", "Coventry City": "COV",
    "Derby County": "DER", "Hull City": "HUL", "Middlesbrough": "MID", "Millwall": "MIL",
    "Norwich City": "NOR", "Oxford United": "OXF", "Plymouth Argyle": "PLY", "Portsmouth": "POR",
    "Preston North End": "PNE", "Queens Park Rangers": "QPR", "Sheffield United": "SHU",
    "Sheffield Wednesday": "SHW", "Stoke City": "STK", "Sunderland": "SUN", "Swansea City": "SWA",
    "Watford": "WAT", "West Bromwich Albion": "WBA",
    "Atlanta United": "ATL", "Charlotte FC": "CLT", "Chicago Fire": "CHI", "FC Cincinnati": "CIN",
    "Colorado Rapids": "COL", "Columbus Crew": "CLB", "D.C. United": "DCU", "FC Dallas": "DAL",
    "Houston Dynamo FC": "HOU", "Inter Miami CF": "MIA", "LA Galaxy": "LAG", "Los Angeles FC": "LAF",
    "Minnesota United": "MIN", "CF Montreal": "MTL", "CF Montréal": "MTL", "Nashville SC": "NSH",
    "New England Revolution": "NER", "New York City FC": "NYC", "New York Red Bulls": "NYR",
    "Orlando City SC": "ORL", "Philadelphia Union": "PHI", "Portland Timbers": "POR",
    "Real Salt Lake": "RSL", "San Diego FC": "SD", "San Jose Earthquakes": "SJE",
    "Seattle Sounders FC": "SEA", "Sporting Kansas City": "SKC", "St. Louis City SC": "STL",
    "Toronto FC": "TOR", "Vancouver Whitecaps": "VAN",
}


class FotMobSoccerProvider:
    """Publish FotMob soccer scoreboards and live match facts."""

    provider_name = "fotmob"

    def __init__(
        self,
        leagues: Mapping[str, int],
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        cache_seconds: float = 21_600.0,
    ) -> None:
        self._leagues = {
            str(identifier).strip().lower(): int(league_id)
            for identifier, league_id in leagues.items()
            if str(identifier).strip()
        }
        self._client = client or UrllibJsonHttpClient(user_agent="Mozilla/5.0")
        self._timeout = float(timeout)
        self._cache_seconds = float(cache_seconds)
        self._details: dict[str, tuple[float, Mapping[str, Any]]] = {}
        self._details_lock = Lock()
        self._stale_cache = SettingsResultCache()

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch all enabled soccer leagues inside the local display window."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")
        active = {
            identifier: league_id
            for identifier, league_id in self._leagues.items()
            if settings.active_sports.get(identifier, True)
        }
        if not active:
            return ProviderResult(health=ProviderHealth(provider=self.provider_name))

        records: list[tuple[str, Mapping[str, Any]]] = []
        errors: list[str] = []
        successes = 0
        for day in _display_days(settings.timezone):
            try:
                payload = self._client.get_json(_matches_url(day), timeout=self._timeout)
                records.extend(_league_matches(payload, active))
                successes += 1
            except Exception as error:
                errors.append(f"matches {day:%Y-%m-%d}: {error}")

        selected = _visible_matches(records, settings.timezone)
        details = self._fetch_details(selected)
        content = tuple(
            _content_item(
                identifier,
                match,
                details.get(str(match.get("id") or "")),
                timezone_name=settings.timezone,
            )
            for identifier, match in selected
        )
        health = ProviderHealth(
            healthy=not errors,
            provider=self.provider_name,
            error="; ".join(errors) if errors else None,
        )
        result = ProviderResult(
            content=tuple(sorted(content, key=_sort_key)),
            observed_at=datetime.now(timezone.utc),
            health=health,
        )
        if health.healthy:
            self._stale_cache.set(settings, result)
            return result
        return result if successes else self._stale_result(settings, health.error or "FotMob request failed")

    def _fetch_details(
        self, records: Sequence[tuple[str, Mapping[str, Any]]]
    ) -> dict[str, Mapping[str, Any]]:
        """Fetch live and penalty match details concurrently."""

        targets = [match for _, match in records if _needs_details(match)]
        if not targets:
            return {}
        workers = min(8, len(targets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fotmob-details") as pool:
            futures = {pool.submit(self._details_for, match): str(match.get("id") or "") for match in targets}
            return {
                match_id: detail
                for future, match_id in futures.items()
                if match_id
                for detail in (future.result(),)
                if detail is not None
            }

    def _details_for(self, match: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Return cached or current details for one match."""

        match_id = str(match.get("id") or "").strip()
        if not match_id:
            return None
        now = monotonic()
        ttl = 10.0 if _match_state(match) in {"in", "half"} else 300.0
        with self._details_lock:
            cached = self._details.get(match_id)
            if cached is not None and now - cached[0] < ttl:
                return cached[1]
        try:
            payload = self._client.get_json(_DETAIL_URL.format(match_id=match_id), timeout=self._timeout)
        except Exception:
            return None
        if not isinstance(payload, Mapping):
            return None
        detail = dict(payload)
        with self._details_lock:
            self._details[match_id] = (now, detail)
        return detail

    def _stale_result(self, settings: DisplaySettings, error: str) -> ProviderResult:
        """Keep the matching ticker's last soccer result during an outage."""

        cached = self._stale_cache.get(settings)
        if cached is None:
            return ProviderResult(
                health=ProviderHealth(False, self.provider_name, f"stale: {error}")
            )
        return ProviderResult(
            content=cached.content,
            alerts=cached.alerts,
            news=cached.news,
            observed_at=cached.observed_at,
            health=ProviderHealth(False, self.provider_name, f"stale: {error}"),
        )


def _matches_url(day) -> str:
    return f"{_MATCHES_URL}?date={day:%Y%m%d}&timezone=UTC&ccode3=USA"


def _display_days(timezone_name: str) -> tuple:
    current = datetime.now(timezone.utc).astimezone(_display_timezone(timezone_name))
    start = (current - timedelta(days=1)).date() if current.hour < 3 else current.date()
    return (start, start + timedelta(days=1))


def _league_matches(payload: object, leagues: Mapping[str, int]) -> list[tuple[str, Mapping[str, Any]]]:
    root = payload if isinstance(payload, Mapping) else {}
    sections = root.get("leagues")
    values = sections if isinstance(sections, Sequence) and not isinstance(sections, (str, bytes)) else ()
    matches: list[tuple[str, Mapping[str, Any]]] = []
    for section in values:
        source = section if isinstance(section, Mapping) else {}
        source_ids = {source.get("id"), source.get("primaryId"), source.get("parentLeagueId")}
        identifiers = [identifier for identifier, league_id in leagues.items() if league_id in source_ids]
        if not identifiers:
            continue
        rows = source.get("matches")
        for match in rows if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else ():
            if isinstance(match, Mapping):
                matches.extend((identifier, match) for identifier in identifiers)
    return matches


def _visible_matches(
    records: Sequence[tuple[str, Mapping[str, Any]]], timezone_name: str
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    start, end = _display_window(timezone_name)
    selected: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    for identifier, match in records:
        match_id = str(match.get("id") or "").strip()
        if not match_id:
            continue
        state = _match_state(match)
        kickoff = _kickoff(match)
        if state not in {"in", "half"} and (kickoff is None or not start <= kickoff < end):
            continue
        selected[(identifier, match_id)] = (identifier, match)
    return tuple(selected.values())


def _display_window(timezone_name: str) -> tuple[datetime, datetime]:
    current = datetime.now(timezone.utc).astimezone(_display_timezone(timezone_name))
    if current.hour < 3:
        start = (current - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = current.replace(hour=3, minute=0, second=0, microsecond=0)
    else:
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end = (current + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _content_item(
    identifier: str,
    match: Mapping[str, Any],
    detail: Mapping[str, Any] | None,
    *,
    timezone_name: str,
) -> ContentItem:
    home = _mapping(match.get("home"))
    away = _mapping(match.get("away"))
    state = _match_state(match)
    status = _match_status(match, state, timezone_name)
    situation = _situation(detail)
    colors = _team_colors(detail)
    home_id = str(home.get("id") or "").strip()
    away_id = str(away.get("id") or "").strip()
    match_id = str(match.get("id") or "").strip()
    data = {
        "type": "scoreboard",
        "sport": identifier,
        "state": state,
        "status": status,
        "startTimeUTC": str(_mapping(match.get("status")).get("utcTime") or ""),
        "estimated_duration": 115,
        "home_abbr": _abbreviation(home),
        "home_score": _score(home),
        "home_logo": _logo(home_id),
        "home_color": colors["home"],
        "home_alt_color": colors["home"],
        "away_abbr": _abbreviation(away),
        "away_score": _score(away),
        "away_logo": _logo(away_id),
        "away_color": colors["away"],
        "away_alt_color": colors["away"],
        "situation": situation,
    }
    return ContentItem(
        id=f"{identifier}:{match_id}",
        family="sports",
        kind="scoreboard",
        is_shown=not bool(_mapping(match.get("status")).get("cancelled")),
        data=data,
    )


def _match_state(match: Mapping[str, Any]) -> str:
    status = _mapping(match.get("status"))
    reason = _mapping(status.get("reason"))
    if bool(status.get("finished")) or bool(status.get("cancelled")):
        return "post"
    if not bool(status.get("started")):
        return "pre"
    if str(reason.get("short") or "").upper() in {"HT", "HALF"}:
        return "half"
    return "in"


def _match_status(match: Mapping[str, Any], state: str, timezone_name: str) -> str:
    status = _mapping(match.get("status"))
    reason = _mapping(status.get("reason"))
    reason_short = str(reason.get("short") or "").upper()
    if state == "pre":
        kickoff = _kickoff(match)
        return kickoff.astimezone(_display_timezone(timezone_name)).strftime("%I:%M %p").lstrip("0") if kickoff else "TBD"
    if state == "post":
        if "PEN" in reason_short:
            return "Final PEN"
        if "AET" in reason_short:
            return "Final AET"
        return "Final"
    if state == "half":
        return "Half"
    live = _mapping(status.get("liveTime"))
    clock = normalize_soccer_clock(live.get("short") or live.get("long"))
    if clock:
        return clock
    return reason_short or "Live"


def _needs_details(match: Mapping[str, Any]) -> bool:
    state = _match_state(match)
    reason = str(_mapping(_mapping(match.get("status")).get("reason")).get("short") or "").upper()
    return state in {"in", "half"} or "PEN" in reason


def _situation(detail: Mapping[str, Any] | None) -> dict[str, object]:
    if detail is None:
        return {"possession": "", "goal_events": [], "red_cards": []}
    content = _mapping(detail.get("content"))
    facts = _mapping(content.get("matchFacts"))
    event_data = _mapping(facts.get("events"))
    events = event_data.get("events")
    goal_events: list[dict[str, object]] = []
    red_cards: list[dict[str, object]] = []
    shootout = {"home": [], "away": []}
    for event in events if isinstance(events, Sequence) and not isinstance(events, (str, bytes)) else ():
        source = event if isinstance(event, Mapping) else {}
        event_type = str(source.get("type") or "").lower()
        is_home = bool(source.get("isHome"))
        minute = _event_minute(source)
        player = _event_player(source)
        if bool(source.get("isPenaltyShootoutEvent")):
            shootout["home" if is_home else "away"].append("goal" if event_type == "goal" else "miss")
        elif event_type == "goal":
            goal_events.append(soccer_event(
                is_home=is_home,
                player=player,
                minute=minute,
                own_goal=bool(source.get("ownGoal")) or "own" in str(source.get("subType") or "").lower(),
            ))
        elif event_type == "card" and "red" in str(source.get("card") or "").lower():
            red_cards.append(soccer_event(is_home=is_home, player=player, minute=minute))
    result: dict[str, object] = {
        "possession": "",
        "goal_events": goal_events,
        "red_cards": red_cards,
    }
    if shootout["home"] or shootout["away"]:
        result["shootout"] = shootout
    return result


def _team_colors(detail: Mapping[str, Any] | None) -> dict[str, str]:
    general = _mapping(detail.get("general")) if detail else {}
    dark = _mapping(_mapping(general.get("teamColors")).get("darkMode"))
    return {"home": _color(dark.get("home")), "away": _color(dark.get("away"))}


def _sort_key(item: ContentItem) -> tuple[str, str]:
    return (str(item.data.get("startTimeUTC") or ""), item.id)


def _kickoff(match: Mapping[str, Any]) -> datetime | None:
    value = _mapping(match.get("status")).get("utcTime")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _display_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value.strip() or "America/New_York")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


def _abbreviation(team: Mapping[str, Any]) -> str:
    name = str(team.get("longName") or team.get("name") or "").strip()
    if name in _SOCCER_ABBREVIATIONS:
        return _SOCCER_ABBREVIATIONS[name]
    letters = "".join(character for character in name.upper() if character.isalnum())
    return letters[:3] or "TBD"


def _score(team: Mapping[str, Any]) -> str:
    value = team.get("score")
    return str(value) if value is not None else "0"


def _logo(team_id: str) -> str:
    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png" if team_id else ""


def _event_player(event: Mapping[str, Any]) -> str:
    player = _mapping(event.get("player"))
    name = str(player.get("name") or event.get("nameStr") or "").strip()
    return name.split()[-1].upper()[:8] if name else ""


def _event_minute(event: Mapping[str, Any]) -> str:
    minute = str(event.get("time") or "").strip()
    added = str(event.get("overloadTime") or "").strip()
    return f"{minute}+{added}'" if minute and added and added != "0" else f"{minute}'" if minute else ""


def _color(value: object) -> str:
    text = str(value or "").strip()
    return text if text.startswith("#") and len(text) == 7 else "#333333"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["FotMobSoccerProvider"]
