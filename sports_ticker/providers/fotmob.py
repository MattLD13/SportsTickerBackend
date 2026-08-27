"""Fetch detailed soccer scoreboards from FotMob."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, RLock
from time import monotonic as default_monotonic
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import ContentItem, DisplaySettings

from .contracts import ProviderHealth, ProviderResult
from .http import JsonHttpClient, UrllibJsonHttpClient
from .score_alerts import ScoreAlertTracker, alerts_for_settings
from .stale_cache import SettingsResultCache
from .sports_display import normalize_soccer_clock, soccer_event


_MATCHES_URL = "https://www.fotmob.com/api/data/matches"
_DETAIL_URL = "https://www.fotmob.com/api/data/matchDetails?matchId={match_id}"
_LIVE_DETAIL_SECONDS = 5.0
_SOURCE_CACHE_SECONDS = 5.0
_DENSE_LIVE_DETAIL_THRESHOLD = 5
_MAX_NONLIVE_DETAIL_WARM = 8
_SOCCER_ABBREVIATIONS = {
    # Premier League
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE",
    "Brighton & Hove Albion": "BHA", "Burnley": "BUR", "Chelsea": "CHE", "Crystal Palace": "CRY",
    "Everton": "EVE", "Fulham": "FUL", "Ipswich Town": "IPS", "Leeds United": "LEE",
    "Leicester City": "LEI", "Liverpool": "LIV", "Manchester City": "MCI", "Manchester United": "MUN",
    "Newcastle United": "NEW", "Nottingham Forest": "NFO", "Southampton": "SOU",
    "Tottenham Hotspur": "TOT", "West Ham United": "WHU", "Wolverhampton": "WOL",
    "Wolverhampton Wanderers": "WOL",
    # Championship
    "Blackburn Rovers": "BLA", "Bristol City": "BRC", "Cardiff City": "CAR", "Coventry City": "COV",
    "Derby County": "DER", "Hull City": "HUL", "Luton Town": "LUT", "Middlesbrough": "MID",
    "Millwall": "MIL", "Norwich City": "NOR", "Oxford United": "OXF", "Plymouth Argyle": "PLY",
    "Portsmouth": "POR", "Preston North End": "PNE", "Queens Park Rangers": "QPR",
    "Sheffield United": "SHU", "Sheffield Wednesday": "SHW", "Stoke City": "STK",
    "Sunderland": "SUN", "Swansea City": "SWA", "Watford": "WAT", "West Bromwich Albion": "WBA",
    "Wrexham": "WXM", "Wrexham AFC": "WXM",
    # MLS
    "Atlanta United": "ATL", "Austin FC": "ATX", "Charlotte FC": "CLT", "Chicago Fire": "CHI",
    "FC Cincinnati": "CIN", "Colorado Rapids": "COL", "Columbus Crew": "CLB", "D.C. United": "DC",
    "FC Dallas": "DAL", "Houston Dynamo FC": "HOU", "Inter Miami CF": "MIA", "LA Galaxy": "LA",
    "Los Angeles FC": "LAFC", "Minnesota United": "MIN", "CF Montreal": "MTL", "CF Montréal": "MTL",
    "Nashville SC": "NSH", "New England Revolution": "NE", "New York City FC": "NYC",
    "New York Red Bulls": "RBNY", "Orlando City SC": "ORL", "Philadelphia Union": "PHI",
    "Portland Timbers": "POR", "Real Salt Lake": "RSL", "San Diego FC": "SD",
    "San Jose Earthquakes": "SJ", "Seattle Sounders FC": "SEA", "Sporting Kansas City": "SKC",
    "St. Louis City SC": "STL", "Toronto FC": "TOR", "Vancouver Whitecaps": "VAN",
}


@dataclass(frozen=True, slots=True)
class _DetailCacheEntry:
    """Store one detail payload with its terminal-state certainty."""

    fetched_at: float
    state: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _MatchSource:
    """Store one projected FotMob source view before ticker-specific alerts."""

    content: tuple[ContentItem, ...]
    errors: tuple[str, ...]
    successes: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class _RawMatchesResponse:
    """Store one canonical date response or its temporary failure."""

    payload: object | None
    error: str | None
    completed_at: float


class FotMobSoccerProvider:
    """Publish FotMob soccer scoreboards and live match facts."""

    provider_name = "fotmob"

    def __init__(
        self,
        leagues: Mapping[str, int],
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        cache_seconds: float = 86_400.0,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        detail_executor: Executor | None = None,
    ) -> None:
        self._leagues = {
            str(identifier).strip().lower(): int(league_id)
            for identifier, league_id in leagues.items()
            if str(identifier).strip()
        }
        self._client = client or UrllibJsonHttpClient(user_agent="Mozilla/5.0")
        self._timeout = float(timeout)
        self._cache_seconds = float(cache_seconds)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or default_monotonic
        self._details: dict[str, _DetailCacheEntry] = {}
        self._details_lock = Lock()
        self._detail_executor: Executor | None = detail_executor
        self._detail_inflight: set[str] = set()
        self._matches_cache: dict[str, _RawMatchesResponse] = {}
        self._matches_inflight: dict[str, Event] = {}
        self._matches_cache_lock = RLock()
        self._stale_cache = SettingsResultCache()
        self._score_alerts = ScoreAlertTracker()
        self._score_alerts_by_ticker: dict[str, ScoreAlertTracker] = {}
        self._alert_baseline_after_failure: set[ScoreAlertTracker] = set()

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch current scoreboard events from each configured active league."""

        return self._fetch(settings, self._score_alerts, cache_source=False)

    def fetch_for_ticker(self, ticker_id: str, settings: DisplaySettings) -> ProviderResult:
        """Fetch one ticker scoreboard with score memory isolated to that ticker."""

        identifier = str(ticker_id).strip()
        tracker = self._score_alerts_by_ticker.setdefault(identifier, ScoreAlertTracker())
        return self._fetch(settings, tracker, cache_source=True)

    def _fetch(
        self,
        settings: DisplaySettings,
        score_alerts: ScoreAlertTracker,
        *,
        cache_source: bool,
    ) -> ProviderResult:
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

        current = self._now()
        dates = _display_days(settings.timezone, now=current)
        source = self._read_source(
            settings,
            active,
            dates,
            cache_source=cache_source,
            now=current,
        )
        content = source.content
        score_games = [
            {"kind": item.kind, "id": item.id, **dict(item.data)}
            for item in content
        ]
        if source.errors:
            self._alert_baseline_after_failure.add(score_alerts)
        elif score_alerts in self._alert_baseline_after_failure:
            score_alerts.prime(score_games)
            self._alert_baseline_after_failure.discard(score_alerts)
        else:
            score_alerts.ingest(score_games)
        alerts = alerts_for_settings(
            score_alerts.recent(
                delay=settings.live_delay_seconds if settings.live_delay_mode else 0.0
            ),
            settings,
        )
        health = ProviderHealth(
            healthy=not source.errors,
            provider=self.provider_name,
            error="; ".join(source.errors) if source.errors else None,
        )
        result = ProviderResult(
            content=content,
            alerts=alerts,
            observed_at=source.observed_at,
            health=health,
        )
        if health.healthy:
            self._stale_cache.set(settings, result)
            return result
        return result if source.successes else self._stale_result(settings, health.error or "FotMob request failed")

    def _read_source(
        self,
        settings: DisplaySettings,
        active: Mapping[str, int],
        dates: Sequence,
        *,
        cache_source: bool,
        now: datetime,
    ) -> _MatchSource:
        """Read date responses concurrently and build content before alerts."""

        records: list[tuple[str, Mapping[str, Any]]] = []
        errors: list[str] = []
        successes = 0
        workers = min(8, len(dates))
        with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="fotmob-matches") as pool:
            futures = {
                day: pool.submit(self._read_matches, day, active, cache_source=cache_source)
                for day in dates
            }
            for day, future in futures.items():
                try:
                    day_records = future.result()
                except Exception as error:
                    errors.append(f"matches {day:%Y-%m-%d}: {error}")
                else:
                    records.extend(day_records)
                    successes += 1

        selected = _visible_matches(records, settings.timezone, now=now)
        self._schedule_detail_warm(selected)
        details = self._detail_snapshot(selected)
        content = tuple(
            _content_item(
                identifier,
                match,
                details.get(str(match.get("id") or "")),
                timezone_name=settings.timezone,
            )
            for identifier, match in selected
        )
        return _MatchSource(
            content=tuple(sorted(content, key=_sort_key)),
            errors=tuple(errors),
            successes=successes,
            observed_at=self._now(),
        )

    def _read_matches(
        self, day, active: Mapping[str, int], *, cache_source: bool
    ) -> list[tuple[str, Mapping[str, Any]]]:
        """Read and filter one canonical date response by enabled leagues."""

        response = self._matches_response(day, cache_source=cache_source)
        if response.error:
            raise RuntimeError(response.error)
        return _league_matches(response.payload, active)

    def _matches_response(self, day, *, cache_source: bool) -> _RawMatchesResponse:
        """Read one date response with completion freshness and failure backoff."""

        url = _matches_url(day)
        if not cache_source:
            try:
                payload = self._client.get_json(url, timeout=self._timeout)
            except Exception as error:
                return _RawMatchesResponse(None, str(error), self._monotonic())
            return _RawMatchesResponse(payload, None, self._monotonic())

        while True:
            with self._matches_cache_lock:
                now = self._monotonic()
                cached = self._matches_cache.get(url)
                if cached is not None and 0 <= now - cached.completed_at < _SOURCE_CACHE_SECONDS:
                    return cached
                waiter = self._matches_inflight.get(url)
                if waiter is None:
                    waiter = Event()
                    self._matches_inflight[url] = waiter
                    break
            waiter.wait()

        try:
            payload = self._client.get_json(url, timeout=self._timeout)
        except Exception as error:
            response = _RawMatchesResponse(None, str(error), self._monotonic())
        else:
            response = _RawMatchesResponse(payload, None, self._monotonic())
        with self._matches_cache_lock:
            self._matches_cache[url] = response
            self._matches_inflight.pop(url).set()
        return response

    def _schedule_detail_warm(
        self, records: Sequence[tuple[str, Mapping[str, Any]]]
    ) -> None:
        """Warm sparse live and capped non-live details without delaying scores."""

        live = [match for _, match in records if _match_state(match) in {"in", "half"}]
        live_targets = live if len(live) < _DENSE_LIVE_DETAIL_THRESHOLD else []
        nonlive = [
            match
            for _, match in records
            if _match_state(match) in {"post", "pre"}
            and _needs_details(match)
            and not self._detail_is_fresh(str(match.get("id") or "").strip(), _match_state(match))
        ]
        nonlive.sort(key=lambda match: 0 if _match_state(match) == "post" else 1)
        targets = live_targets + nonlive[:_MAX_NONLIVE_DETAIL_WARM]
        unique: dict[str, Mapping[str, Any]] = {
            str(match.get("id") or ""): match
            for match in targets
            if str(match.get("id") or "").strip()
        }
        for match_id, match in unique.items():
            if self._detail_is_fresh(match_id, _match_state(match)):
                continue
            with self._details_lock:
                if match_id in self._detail_inflight:
                    continue
                self._detail_inflight.add(match_id)
                if self._detail_executor is None:
                    self._detail_executor = ThreadPoolExecutor(
                        max_workers=8,
                        thread_name_prefix="fotmob-details",
                    )
                executor = self._detail_executor
            try:
                executor.submit(self._warm_detail, match)
            except Exception:
                with self._details_lock:
                    self._detail_inflight.discard(match_id)

    def _warm_detail(self, match: Mapping[str, Any]) -> None:
        """Refresh one optional detail payload and release its single-flight marker."""

        match_id = str(match.get("id") or "").strip()
        try:
            self._details_for(match)
        except Exception:
            pass
        finally:
            with self._details_lock:
                self._detail_inflight.discard(match_id)

    def _detail_snapshot(
        self, records: Sequence[tuple[str, Mapping[str, Any]]]
    ) -> dict[str, Mapping[str, Any]]:
        """Copy only current-state-fresh optional details for shared content."""

        with self._details_lock:
            now = self._monotonic()
            details: dict[str, Mapping[str, Any]] = {}
            for _, match in records:
                match_id = str(match.get("id") or "").strip()
                entry = self._details.get(match_id)
                if match_id and entry is not None and _detail_entry_is_fresh(
                    entry, _match_state(match), now, self._cache_seconds
                ):
                    details[match_id] = entry.payload
            return details

    def _detail_is_fresh(self, match_id: str, state: str) -> bool:
        """Return whether one cached detail can serve the current match state."""

        with self._details_lock:
            cached = self._details.get(match_id)
            if cached is None:
                return False
            return _detail_entry_is_fresh(cached, state, self._monotonic(), self._cache_seconds)

    def _details_for(self, match: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Return live details or one final snapshot for one match."""

        match_id = str(match.get("id") or "").strip()
        if not match_id:
            return None
        now = self._monotonic()
        state = _match_state(match)
        fallback: Mapping[str, Any] | None = None
        with self._details_lock:
            cached = self._details.get(match_id)
            if cached is not None:
                fallback = cached.payload
                if _detail_entry_is_fresh(cached, state, now, self._cache_seconds):
                    return cached.payload
        try:
            payload = self._client.get_json(_DETAIL_URL.format(match_id=match_id), timeout=self._timeout)
        except Exception:
            return fallback
        if not isinstance(payload, Mapping):
            return fallback
        detail = dict(payload)
        completed = self._monotonic()
        with self._details_lock:
            self._details[match_id] = _DetailCacheEntry(completed, state, detail)
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


def _detail_entry_is_fresh(
    entry: _DetailCacheEntry,
    state: str,
    now: float,
    cache_seconds: float = 86_400.0,
) -> bool:
    age = now - entry.fetched_at
    if state in {"pre", "post"}:
        return entry.state == state and age < cache_seconds
    return state in {"in", "half"} and entry.state in {"in", "half"} and age < _LIVE_DETAIL_SECONDS


def _display_days(timezone_name: str, *, now: datetime | None = None) -> tuple:
    current = (now or datetime.now(timezone.utc)).astimezone(_display_timezone(timezone_name))
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
    records: Sequence[tuple[str, Mapping[str, Any]]],
    timezone_name: str,
    *,
    now: datetime | None = None,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    start, end = _display_window(timezone_name, now=now)
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


def _display_window(
    timezone_name: str, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    current = (now or datetime.now(timezone.utc)).astimezone(_display_timezone(timezone_name))
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
    if bool(status.get("finished")) or bool(status.get("cancelled")):
        return "post"
    if not bool(status.get("started")):
        return "pre"
    if _is_halftime(status):
        return "half"
    return "in"


def _is_halftime(status: Mapping[str, Any]) -> bool:
    """Recognize halftime from either FotMob status location."""

    reason = _mapping(status.get("reason"))
    live = _mapping(status.get("liveTime"))
    labels = (
        reason.get("short"),
        reason.get("long"),
        live.get("short"),
        live.get("long"),
    )
    return any(_status_label(value) in {"HT", "HALF", "HALF TIME"} for value in labels)


def _status_label(value: object) -> str:
    """Return one comparable FotMob phase label."""

    text = str(value or "").replace("\u200e", "").replace("\u200f", "").replace("\ufffd", "")
    return " ".join(text.replace("-", " ").upper().split())


def _fotmob_period(status: Mapping[str, Any]) -> int:
    """Determine the match period (1=1st half, 2=2nd half, 3+=ET) from FotMob status."""
    halfs = _mapping(status.get("halfs"))
    live = _mapping(status.get("liveTime"))
    max_time = _integer(live.get("maxTime") or live.get("basePeriod"), 0)

    if halfs.get("secondHalfStarted") or max_time >= 90:
        return 2 if max_time <= 90 else 3
    if halfs.get("firstHalfStarted") or max_time == 45:
        return 1
    return _integer(status.get("period"), _integer(live.get("period"), 0))


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
    period = _fotmob_period(status)
    for value in (live.get("long"), live.get("short")):
        clock = normalize_soccer_clock(value, period=period)
        if clock:
            return clock
    return reason_short or "Live"


def _needs_details(match: Mapping[str, Any]) -> bool:
    """Return true because FotMob details own colors for every match state."""

    del match
    return True


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


def _integer(value: object, fallback: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["FotMobSoccerProvider"]
