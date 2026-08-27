"""Native ESPN scoreboard provider."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from math import isfinite
import re
import time
from threading import Event, RLock
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import ContentItem, DisplaySettings
from sports_ticker.leagues import COLLEGE_FOOTBALL_LEAGUES, allows_college_conferences

from .contracts import ProviderHealth, ProviderResult
from .espn_fastcast import EspnFastcastSource
from .http import JsonHttpClient, UrllibJsonHttpClient
from .logo_overrides import corrected_logo
from .score_alerts import ScoreAlertTracker, alerts_for_settings
from .sports_display import (
    SportsDisplayProjector,
    assign_active_team,
    display_situation,
    soccer_event,
    sports_content_sort_key,
)
from .stale_cache import SettingsResultCache


_MLB_PITCH_LABELS = {
    "four seam fastball": "4S Fastball",
    "two seam fastball": "2S Fastball",
    "cutter": "Cutter",
    "changeup": "Changeup",
    "curveball": "Curveball",
    "knuckle curve": "Knuckle Curve",
    "knuckleball": "Knuckleball",
    "sinker": "Sinker",
    "slider": "Slider",
    "splitter": "Splitter",
    "sweeper": "Sweeper",
}
_MLB_PITCH_ABBREVIATIONS = {
    "2SFB": "2S Fastball",
    "4SFB": "4S Fastball",
    "CH": "Changeup",
    "CU": "Curveball",
    "FC": "Cutter",
    "FF": "4S Fastball",
    "FS": "Splitter",
    "KC": "Knuckle Curve",
    "KN": "Knuckleball",
    "SI": "Sinker",
    "SL": "Slider",
    "ST": "Sweeper",
    "SV": "Sweeper",
}
_SOURCE_CACHE_SECONDS = 5.0
_FULL_SCOREBOARD_REFRESH_THRESHOLD = 5
_FULL_SCOREBOARD_DISCOVERY_INTERVAL = 60.0


@dataclass(frozen=True, slots=True)
class _ScoreboardSource:
    """Keep one upstream scoreboard view for all matching ticker settings."""

    content: tuple[ContentItem, ...]
    errors: tuple[str, ...]
    active_sources: int
    failed_sources: int
    invalid_sources: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class _LeagueSchedule:
    """Keep one league schedule until its next local 3am sweep."""

    events: tuple[Mapping[str, Any], ...]
    schedule_day: date
    discovery_at: float


@dataclass(frozen=True, slots=True)
class _RawScoreboardResponse:
    """Store one canonical ESPN scoreboard response or its short-lived failure."""

    events: tuple[Mapping[str, Any], ...] | None
    error: str | None
    request_failed: bool
    completed_at: float
    payload: Any | None = None


@dataclass(frozen=True, slots=True)
class _RawEventScoreboardResponse:
    """Store one canonical ESPN single-event scoreboard response."""

    payload: Mapping[str, Any] | None
    error: str | None
    completed_at: float


class _ScoreboardReadError(RuntimeError):
    """Identify whether one cached scoreboard error came from transport or schema parsing."""

    def __init__(self, message: str, *, request_failed: bool) -> None:
        super().__init__(message)
        self.request_failed = request_failed


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


class EspnScoreboardProvider:
    """Fetch explicitly enabled ESPN scoreboard leagues into canonical content."""

    def __init__(
        self,
        scoreboard_urls: Mapping[str, str],
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        fastcast: EspnFastcastSource | None = None,
    ) -> None:
        if not isinstance(scoreboard_urls, Mapping):
            raise TypeError("scoreboard_urls must be a mapping")
        urls = {
            str(league).strip().lower(): str(url).strip()
            for league, url in scoreboard_urls.items()
            if str(league).strip() and str(url).strip()
        }
        self.scoreboard_urls = MappingProxyType(urls)
        self._event_scoreboard_urls = {
            league: _event_scoreboard_url(url) for league, url in urls.items()
        }
        self.client = client or UrllibJsonHttpClient()
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._stale_cache = SettingsResultCache()
        self._display = SportsDisplayProjector()
        self._score_alerts = ScoreAlertTracker()
        self._score_alerts_by_ticker: dict[str, ScoreAlertTracker] = {}
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._source_cache: dict[tuple[object, ...], tuple[float, _ScoreboardSource]] = {}
        self._scoreboard_cache: dict[str, _RawScoreboardResponse] = {}
        self._scoreboard_inflight: dict[str, Event] = {}
        self._event_scoreboard_cache: dict[tuple[str, str], _RawEventScoreboardResponse] = {}
        self._event_scoreboard_inflight: dict[tuple[str, str], Event] = {}
        self._league_schedules: dict[tuple[str, str, date], _LeagueSchedule] = {}
        self._fastcast = fastcast
        self._source_cache_lock = RLock()
        self._raw_cache_lock = RLock()

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch current scoreboard events from each configured active league."""

        return self._fetch(settings, self._score_alerts, cache_source=False)

    def fetch_for_ticker(self, ticker_id: str, settings: DisplaySettings) -> ProviderResult:
        """Fetch one ticker scoreboard with score memory isolated to that ticker."""

        identifier = str(ticker_id).strip()
        tracker = self._score_alerts_by_ticker.setdefault(identifier, ScoreAlertTracker())
        return self._fetch(settings, tracker, cache_source=True)

    def close(self) -> None:
        """Stop the optional shared Fastcast stream."""

        if self._fastcast is not None:
            self._fastcast.close()

    def _fetch(
        self,
        settings: DisplaySettings,
        score_alerts: ScoreAlertTracker,
        *,
        cache_source: bool,
    ) -> ProviderResult:
        """Fetch scoreboard content and emit only alerts allowed by ticker settings."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")

        current = self._now()
        dates = _scoreboard_dates(settings.timezone, now=current)
        source_key = _source_key(self.scoreboard_urls, settings, dates)
        if cache_source:
            with self._source_cache_lock:
                now = self._monotonic()
                cached = self._source_cache.get(source_key)
                if cached is not None and 0 <= now - cached[0] < 5.0:
                    source = cached[1]
                else:
                    source = self._read_source(settings, current, dates, cache_schedule=True)
                    self._source_cache[source_key] = (self._monotonic(), source)
        else:
            source = self._read_source(settings, current, dates, cache_schedule=False)

        items = source.content
        score_games = [{"kind": item.kind, "id": item.id, **dict(item.data)} for item in items]
        request_failed = source.failed_sources > 0
        invalid_source = source.invalid_sources > 0
        unusable_sources = source.failed_sources + source.invalid_sources
        fully_failed = bool(
            source.active_sources and unusable_sources == source.active_sources
        )
        partially_failed = request_failed and not invalid_source and not fully_failed
        health = ProviderHealth(
            healthy=not invalid_source and (partially_failed or not source.errors),
            provider="espn",
            error="; ".join(source.errors) if source.errors else None,
        )
        alerts: tuple[Mapping[str, Any], ...] = ()
        if health.healthy:
            score_alerts.ingest(score_games)
            alerts = alerts_for_settings(
                score_alerts.recent(
                    delay=settings.live_delay_seconds if settings.live_delay_mode else 0.0,
                ),
                settings,
            )
        result = ProviderResult(
            content=items,
            alerts=alerts,
            observed_at=source.observed_at,
            health=health,
        )
        if health.healthy:
            self._stale_cache.set(settings, result)
            return result
        if fully_failed:
            return self._stale_result(settings, health.error or "all sources failed")
        return result

    def _read_source(
        self,
        settings: DisplaySettings,
        current: datetime,
        dates: Sequence[date],
        *,
        cache_schedule: bool,
    ) -> "_ScoreboardSource":
        """Read one shared ESPN source view for all tickers with matching source settings."""

        if self._fastcast is not None:
            self._fastcast.start()
        items: list[ContentItem] = []
        errors: list[str] = []
        seen_events: set[tuple[str, str]] = set()
        active_leagues = tuple(
            (league, url)
            for league, url in self.scoreboard_urls.items()
            if settings.active_sports.get(league, True)
        )
        active_sources = len(active_leagues)
        schedule_day = _schedule_day(settings.timezone, current)
        monotonic_now = self._monotonic()
        cached_events: dict[str, tuple[Mapping[str, Any], ...]] = {}
        discovery_ages: dict[str, float] = {}
        refresh_leagues: list[tuple[str, str]] = []
        live_refreshes: list[tuple[str, Mapping[str, Any]]] = []
        live_detail_suppressed: set[str] = set()
        for league, url in active_leagues:
            cache_key = (settings.timezone, league, schedule_day)
            cached = self._league_schedules.get(cache_key) if cache_schedule else None
            raw_schedule_events = (
                self._fastcast_events(league, cached.events)
                if cached is not None and cache_schedule
                else cached.events if cached is not None else ()
            )
            schedule_events = _filter_college_conference_events(
                league,
                raw_schedule_events,
                settings.active_conferences,
            )
            if cached is None:
                refresh_leagues.append((league, url))
            elif monotonic_now - cached.discovery_at >= _FULL_SCOREBOARD_DISCOVERY_INTERVAL:
                cached_events[league] = schedule_events
                discovery_ages[league] = cached.discovery_at
                refresh_leagues.append((league, url))
            elif _league_needs_refresh(schedule_events, current):
                cached_events[league] = schedule_events
                discovery_ages[league] = cached.discovery_at
                if self._fastcast_active(league):
                    live_detail_suppressed.add(league)
                elif self._event_scoreboard_urls.get(league):
                    live_events = _unique_live_events(schedule_events, current)
                    if len(live_events) >= _FULL_SCOREBOARD_REFRESH_THRESHOLD:
                        refresh_leagues.append((league, url))
                        live_detail_suppressed.add(league)
                    else:
                        live_refreshes.extend((league, event) for event in live_events)
                else:
                    refresh_leagues.append((league, url))
            else:
                cached_events[league] = schedule_events
                discovery_ages[league] = cached.discovery_at

        events_by_league: dict[str, tuple[Mapping[str, Any], ...]] = dict(cached_events)
        live_update_payloads: dict[tuple[str, str], Any] = {}
        attempted_live_update_ids: set[tuple[str, str]] = set()
        failed_leagues: set[str] = set()
        invalid_leagues: set[str] = set()
        live_update_futures: dict[tuple[str, str], Any] = {}
        workers = min(
            8,
            max(1, len(refresh_leagues) + len(live_refreshes), _FULL_SCOREBOARD_REFRESH_THRESHOLD - 1),
        )
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="espn-refresh",
        ) as pool:
            scoreboard_futures = {
                league: pool.submit(
                    self._read_scoreboard,
                    league,
                    url,
                    dates,
                    cache_source=cache_schedule,
                )
                for league, url in refresh_leagues
            }
            live_update_futures.update({
                (league, str(event.get("id") or "").strip()): pool.submit(
                    self._read_event_scoreboard,
                    league,
                    str(event.get("id") or "").strip(),
                    cache_source=cache_schedule,
                )
                for league, event in live_refreshes
                if str(event.get("id") or "").strip()
            })
            for league, _url in active_leagues:
                if league in scoreboard_futures:
                    try:
                        events = tuple(scoreboard_futures[league].result())
                    except _ScoreboardReadError as exc:
                        if exc.request_failed:
                            failed_leagues.add(league)
                        else:
                            invalid_leagues.add(league)
                        errors.append(f"{league}: {exc}")
                        continue
                    except Exception as exc:
                        failed_leagues.add(league)
                        errors.append(f"{league}: {exc}")
                        continue
                    events_by_league[league] = _filter_college_conference_events(
                        league,
                        events,
                        settings.active_conferences,
                    )
                    if cache_schedule:
                        self._league_schedules[(settings.timezone, league, schedule_day)] = _LeagueSchedule(
                            events=events,
                            schedule_day=schedule_day,
                            discovery_at=self._monotonic(),
                        )
                        discovery_ages[league] = self._league_schedules[
                            (settings.timezone, league, schedule_day)
                        ].discovery_at
                    live_events = _unique_live_events(events_by_league[league], current)
                    for event in live_events:
                        event_id = str(event.get("id") or "").strip()
                        if event_id:
                            live_update_payloads.setdefault((league, event_id), event)
                    if self._fastcast_active(league):
                        live_detail_suppressed.add(league)
                    elif self._event_scoreboard_urls.get(league):
                        if len(live_events) >= _FULL_SCOREBOARD_REFRESH_THRESHOLD:
                            live_detail_suppressed.add(league)
                        elif cache_schedule:
                            for event in live_events:
                                event_id = str(event.get("id") or "").strip()
                                if event_id and (league, event_id) not in live_update_futures:
                                    live_update_futures[(league, event_id)] = pool.submit(
                                        self._read_event_scoreboard,
                                        league,
                                        event_id,
                                        cache_source=cache_schedule,
                                    )
            for (league, event_id), future in live_update_futures.items():
                attempted_live_update_ids.add((league, event_id))
                try:
                    update = future.result()
                except Exception:
                    continue
                live_update_payloads[(league, event_id)] = update
                events = events_by_league.get(league, ())
                updated_events = tuple(
                    _event_update(update, event) if str(event.get("id") or "").strip() == event_id else event
                    for event in events
                )
                events_by_league[league] = _filter_college_conference_events(
                    league,
                    updated_events,
                    settings.active_conferences,
                )
                if cache_schedule:
                    cached_schedule = self._league_schedules.get(
                        (settings.timezone, league, schedule_day)
                    )
                    stored_events = cached_schedule.events if cached_schedule is not None else updated_events
                    stored_events = tuple(
                        _event_update(update, event)
                        if str(event.get("id") or "").strip() == event_id
                        else event
                        for event in stored_events
                    )
                    self._league_schedules[(settings.timezone, league, schedule_day)] = _LeagueSchedule(
                        events=stored_events,
                        schedule_day=schedule_day,
                        discovery_at=discovery_ages.get(league, self._monotonic()),
                    )

        failed_sources = len(failed_leagues)
        suppressed_live_update_ids = {
            (league, str(event.get("id") or "").strip())
            for league in live_detail_suppressed
            for event in events_by_league.get(league, ())
            if str(event.get("id") or "").strip() and _event_needs_live_refresh(event, current)
        }
        for league, _url in active_leagues:
            events = events_by_league.get(league, ())
            for event in events:
                event_id = str(event.get("id") or "").strip()
                if event_id and (league, event_id) in seen_events:
                    continue
                if event_id:
                    seen_events.add((league, event_id))
                if not _is_current_event(
                    event,
                    timezone_name=settings.timezone,
                    now=current,
                ):
                    continue
                try:
                    item = self._display.project(_content_item(league, event), event)
                    items.append(item)
                except (KeyError, TypeError, ValueError) as exc:
                    invalid_leagues.add(league)
                    errors.append(f"{league} event: {exc}")

        return _ScoreboardSource(
            content=tuple(
                sorted(
                    self._enrich_live_items(
                        items,
                        update_payloads=live_update_payloads,
                        attempted_update_ids=attempted_live_update_ids,
                        suppressed_update_ids=suppressed_live_update_ids,
                    ),
                    key=sports_content_sort_key,
                )
            ),
            errors=tuple(errors),
            active_sources=active_sources,
            failed_sources=failed_sources,
            invalid_sources=len(invalid_leagues),
            observed_at=datetime.now(timezone.utc),
        )

    def _fastcast_active(self, league: str) -> bool:
        """Return whether one league can use its shared Fastcast state."""

        return self._fastcast is not None and self._fastcast.active(league)

    def _fastcast_events(
        self,
        league: str,
        fallback: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], ...]:
        """Merge one Fastcast snapshot over the last complete schedule."""

        if self._fastcast is None:
            return tuple(fallback)
        snapshot = self._fastcast.snapshot(league)
        if snapshot is None:
            return tuple(fallback)
        try:
            events = _events(snapshot)
        except (TypeError, ValueError):
            return tuple(fallback)
        return _merge_event_collections(fallback, events)

    def _read_scoreboard(
        self,
        league: str,
        url: str,
        dates: Sequence[date],
        *,
        cache_source: bool = False,
    ) -> tuple[Mapping[str, Any], ...]:
        """Read all games for one league in one request."""

        request_url = _scoreboard_url_for_dates(url, dates)
        if not cache_source:
            payload = self.client.get_json(request_url, timeout=self.timeout)
            if self._fastcast is not None:
                self._fastcast.prime(league, payload)
            return _events(payload)

        response = self._cached_scoreboard(request_url)
        if response.error:
            raise _ScoreboardReadError(
                response.error,
                request_failed=response.request_failed,
            )
        if self._fastcast is not None and response.payload is not None:
            self._fastcast.prime(league, response.payload)
        return response.events or ()

    def _read_event_scoreboard(
        self,
        league: str,
        event_id: str,
        *,
        cache_source: bool = False,
    ) -> Mapping[str, Any]:
        """Read one live event from ESPN's compact single-event scoreboard resource."""

        template = self._event_scoreboard_urls.get(league)
        if not template:
            return {}
        request_url = template.format(event_id)
        if not cache_source:
            return _event_payload(self.client.get_json(request_url, timeout=self.timeout))

        response = self._cached_event_scoreboard((league, event_id), request_url)
        if response.error:
            raise RuntimeError(response.error)
        return response.payload or {}

    def _cached_scoreboard(self, request_url: str) -> _RawScoreboardResponse:
        """Read one scoreboard URL once per freshness window, including temporary failures."""

        while True:
            with self._raw_cache_lock:
                now = self._monotonic()
                cached = self._scoreboard_cache.get(request_url)
                if cached is not None and 0 <= now - cached.completed_at < _SOURCE_CACHE_SECONDS:
                    return cached
                waiter = self._scoreboard_inflight.get(request_url)
                if waiter is None:
                    waiter = Event()
                    self._scoreboard_inflight[request_url] = waiter
                    break
            waiter.wait()

        response: _RawScoreboardResponse
        try:
            try:
                payload = self.client.get_json(request_url, timeout=self.timeout)
            except Exception as error:
                response = _RawScoreboardResponse(
                    events=None,
                    error=str(error) or type(error).__name__,
                    request_failed=True,
                    completed_at=self._monotonic(),
                )
            else:
                try:
                    events = _events(payload)
                except Exception as error:
                    response = _RawScoreboardResponse(
                        events=None,
                        error=str(error) or type(error).__name__,
                        request_failed=False,
                        completed_at=self._monotonic(),
                    )
                else:
                    response = _RawScoreboardResponse(
                        events=events,
                        error=None,
                        request_failed=False,
                        completed_at=self._monotonic(),
                        payload=payload,
                    )
        finally:
            with self._raw_cache_lock:
                self._scoreboard_cache[request_url] = response
                active = self._scoreboard_inflight.pop(request_url, None)
                if active is not None:
                    active.set()
        return response

    def _cached_event_scoreboard(
        self,
        key: tuple[str, str],
        request_url: str,
    ) -> _RawEventScoreboardResponse:
        """Read one event scoreboard once per freshness window, including failures."""

        while True:
            with self._raw_cache_lock:
                now = self._monotonic()
                cached = self._event_scoreboard_cache.get(key)
                if cached is not None and 0 <= now - cached.completed_at < _SOURCE_CACHE_SECONDS:
                    return cached
                waiter = self._event_scoreboard_inflight.get(key)
                if waiter is None:
                    waiter = Event()
                    self._event_scoreboard_inflight[key] = waiter
                    break
            waiter.wait()

        response: _RawEventScoreboardResponse
        try:
            try:
                payload = self.client.get_json(request_url, timeout=self.timeout)
                event = _event_payload(payload)
            except Exception as error:
                response = _RawEventScoreboardResponse(
                    payload=None,
                    error=str(error) or type(error).__name__,
                    completed_at=self._monotonic(),
                )
            else:
                response = _RawEventScoreboardResponse(
                    payload=event,
                    error=None,
                    completed_at=self._monotonic(),
                )
        finally:
            with self._raw_cache_lock:
                self._event_scoreboard_cache[key] = response
                active = self._event_scoreboard_inflight.pop(key, None)
                if active is not None:
                    active.set()
        return response

    def _stale_result(self, settings: DisplaySettings, error: str) -> ProviderResult:
        """Return last successful content with an unhealthy stale status."""

        result = self._stale_cache.get(settings)
        if result is None:
            return ProviderResult(
                health=ProviderHealth(
                    healthy=False,
                    provider="espn",
                    error=f"stale: {error}",
                )
            )
        return ProviderResult(
            content=result.content,
            alerts=result.alerts,
            news=result.news,
            observed_at=result.observed_at,
            health=ProviderHealth(
                healthy=False,
                provider="espn",
                error=f"stale: {error}",
            ),
        )

    def _enrich_live_item(
        self,
        league: str,
        item: ContentItem,
        *,
        update: Any | None = None,
    ) -> ContentItem:
        """Add detailed live facts after scoreboard projection completes."""

        if str(item.data.get("state") or "").lower() not in {"in", "half", "crit"}:
            return item
        template = self._event_scoreboard_urls.get(league)
        if not template:
            return item

        if update is None:
            try:
                update = self._read_event_scoreboard(league, item.id, cache_source=True)
            except Exception:
                return item
        details = _event_scoring_details(update, item.data)
        details.update(
            _mlb_event_details(update)
            if league == "mlb"
            else _nhl_event_details(update, item.data)
            if league == "nhl"
            else _soccer_event_details(update, item.data)
            if league.startswith("soccer")
            else display_situation(
                league,
                _event_competition(update),
                home_abbr=str(item.data.get("home_abbr") or ""),
                away_abbr=str(item.data.get("away_abbr") or ""),
            )
        )
        if not details:
            return item
        data = dict(item.data)
        situation = dict(_mapping(data.get("situation")))
        situation.update(details)
        data["situation"] = assign_active_team(
            league,
            str(data.get("state") or ""),
            str(data.get("status") or ""),
            situation,
            home_abbr=str(data.get("home_abbr") or ""),
            away_abbr=str(data.get("away_abbr") or ""),
        )
        return ContentItem(
            id=item.id,
            family=item.family,
            kind=item.kind,
            is_shown=item.is_shown,
            data=data,
        )

    def _enrich_live_items(
        self,
        items: Sequence[ContentItem],
        *,
        update_payloads: Mapping[tuple[str, str], Any] | None = None,
        attempted_update_ids: set[tuple[str, str]] | None = None,
        suppressed_update_ids: set[tuple[str, str]] | None = None,
    ) -> list[ContentItem]:
        """Fetch live game details concurrently without blocking other scoreboards."""

        indexed = list(enumerate(items))
        targets = [
            (index, item)
            for index, item in indexed
            if str(item.data.get("state") or "").lower() in {"in", "half", "crit"}
            and str(item.data.get("sport") or "") in self._event_scoreboard_urls
            and not (
                suppressed_update_ids
                and (str(item.data.get("sport") or ""), item.id) in suppressed_update_ids
            )
            and not (
                attempted_update_ids
                and (str(item.data.get("sport") or ""), item.id) in attempted_update_ids
                and (str(item.data.get("sport") or ""), item.id) not in (update_payloads or {})
            )
        ]
        if not targets:
            return list(items)
        enriched = list(items)
        workers = min(8, len(targets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ticker-details") as pool:
            futures = {
                pool.submit(
                    self._enrich_live_item,
                    str(item.data.get("sport") or ""),
                    item,
                    update=(update_payloads or {}).get(
                        (str(item.data.get("sport") or ""), item.id)
                    ),
                ): index
                for index, item in targets
            }
            for future, index in futures.items():
                try:
                    enriched[index] = future.result()
                except Exception:
                    continue
        return enriched



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
    if source.get("id"):
        return source
    events = _events(source)
    event = next((item for item in events if _mapping(item).get("id")), None)
    if not isinstance(event, Mapping):
        raise TypeError("single-event scoreboard response omitted event")
    return event


def _merge_event_collections(
    fallback: Sequence[Mapping[str, Any]],
    updates: Sequence[Mapping[str, Any]],
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
        merged.append(_event_update(update, event) if update is not None else event)
        if event_id:
            seen.add(event_id)
    merged.extend(
        event
        for event_id, event in updates_by_id.items()
        if event_id not in seen
    )
    return tuple(merged)


def _event_update(payload: Any, fallback: Mapping[str, Any]) -> Mapping[str, Any]:
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
    if _status_rank(update_status) >= _status_rank(fallback_status):
        event["status"] = _merge_mapping(fallback_status, update_status)
    scoreboard_competition = _first_mapping(event.get("competitions"))
    merged_competition = _merge_mapping(scoreboard_competition, competition)
    merged_competition["competitors"] = _merge_competitors(
        scoreboard_competition.get("competitors"),
        competition.get("competitors"),
    )
    scoreboard_situation = _mapping(scoreboard_competition.get("situation"))
    update_situation = _mapping(source.get("situation"))
    if scoreboard_situation or update_situation:
        merged_competition["situation"] = _merge_mapping(
            scoreboard_situation,
            update_situation,
        )
    event["competitions"] = [merged_competition]
    return event


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
        if value is not None:
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
    """Add one explicit ESPN calendar date or inclusive range without dropping query values."""

    parsed = urlsplit(scoreboard_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "dates"]
    values = tuple(dates)
    if not values:
        raise ValueError("dates must not be empty")
    date_value = "-".join(day.strftime("%Y%m%d") for day in values)
    query.append(("dates", date_value))
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


def _content_item(league: str, event: Mapping[str, Any]) -> ContentItem:
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
    home_team = _team(home)
    away_team = _team(away)
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


def _team(competitor: Mapping[str, Any]) -> Mapping[str, Any]:
    source = _mapping(competitor.get("team"))
    logos = source.get("logos")
    logo = source.get("logo")
    if logo is None and isinstance(logos, Sequence) and not isinstance(logos, (str, bytes)):
        logo = _mapping(logos[0]).get("href") if logos else None
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


def _event_scoreboard_url(scoreboard_url: str) -> str:
    """Derive ESPN's compact single-event scoreboard endpoint from one league URL."""

    endpoint = scoreboard_url.split("?", 1)[0].rstrip("/")
    return f"{endpoint}/{{}}"


def _nhl_event_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Read power-play, empty-net, and shootout state from a live NHL event."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    source = _mapping(summary.get("situation")) or _mapping(competition.get("situation"))
    if not source and not competition:
        return {}
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    details = display_situation("nhl", competition, home_abbr=home_abbr, away_abbr=away_abbr)
    details["powerPlay"] = bool(
        source.get("powerPlay") or source.get("isPowerPlay") or source.get("hasPowerPlay")
    )
    details["emptyNet"] = bool(source.get("emptyNet") or source.get("isEmptyNet"))
    code = str(source.get("situationCode") or "")
    if len(code) >= 4 and code[:4].isdigit():
        away_goalie, away_skaters, home_skaters, home_goalie = (int(value) for value in code[:4])
        if away_skaters > home_skaters:
            details["powerPlay"] = True
            details["possession"] = away_abbr
        elif home_skaters > away_skaters:
            details["powerPlay"] = True
            details["possession"] = home_abbr
        if away_goalie == 0:
            details["emptyNet"] = True
            details["emptyNetSide"] = away_abbr
        elif home_goalie == 0:
            details["emptyNet"] = True
            details["emptyNetSide"] = home_abbr
    shootout = _shootout_details(summary)
    if shootout is not None:
        details["shootout"] = shootout
    return details


def _soccer_event_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Read goal, red-card, and penalty facts from a live soccer event."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    source = _mapping(summary.get("situation")) or _mapping(competition.get("situation"))
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    details = display_situation("soccer", competition, home_abbr=home_abbr, away_abbr=away_abbr)
    goals: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for play in _event_plays(summary):
        text = " ".join(
            str(value or "")
            for value in (
                play.get("type"), play.get("text"), play.get("shortText"), play.get("description")
            )
        ).lower()
        if "goal" not in text and "red" not in text:
            continue
        team = _event_team_abbr(play, competition, home_abbr, away_abbr)
        event = soccer_event(
            is_home=team == home_abbr,
            player=_event_player(play),
            minute=_event_clock(play),
            own_goal="own goal" in text,
        )
        if "goal" in text:
            goals.append(event)
        if "red" in text:
            cards.append(event)
    if goals:
        details["goal_events"] = goals
    if cards:
        details["red_cards"] = cards
    shootout = _shootout_details(summary)
    if shootout is not None:
        details["shootout"] = shootout
    if source.get("possession"):
        details["possession"] = _event_team_abbr(source, competition, home_abbr, away_abbr)
    return details


def _event_plays(summary: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return event-like records without depending on one ESPN shape."""

    records: list[Mapping[str, Any]] = []
    for key in ("scoringPlays", "plays", "events"):
        records.extend(_mapping(value) for value in _sequence(summary.get(key)))
    return tuple(record for record in records if record)


def _event_scoring_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize ESPN scoring plays for score-alert detail rendering."""

    summary = _mapping(payload)
    competition = _event_competition(summary)
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    raw_scoring = _sequence(summary.get("scoringPlays"))
    records = raw_scoring or _event_plays(summary)
    scoring_plays: list[dict[str, Any]] = []
    for raw_play in records:
        play = _mapping(raw_play)
        text = str(
            play.get("shortText")
            or play.get("text")
            or play.get("description")
            or ""
        ).strip()
        score_value = play.get("scoreValue")
        is_scoring = bool(
            raw_scoring
            or play.get("scoringPlay")
            or play.get("isScoringPlay")
            or score_value not in (None, "", 0, "0")
            or re.search(r"\b(score|goal|touchdown|field goal|home run|homer|three.?pointer|free throw)\b", text, re.IGNORECASE)
        )
        if not is_scoring:
            continue
        team = _event_team_abbr(play, competition, home_abbr, away_abbr)
        if not team:
            continue
        athlete = _event_player(play)
        scoring_type = str(
            _mapping(play.get("scoringType")).get("displayName")
            or _mapping(play.get("type")).get("text")
            or play.get("scoringType")
            or ""
        ).strip()
        scoring_plays.append(
            {
                "team": team,
                "scorer": athlete,
                "player": athlete,
                "type": scoring_type[:18],
                "text": text[:48],
            }
        )
    return {"scoring_plays": scoring_plays} if scoring_plays else {}


def _event_team_abbr(
    value: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
) -> str:
    """Resolve an ESPN team identifier to the compact display abbreviation."""

    raw = value.get("team") or value.get("teamId") or value.get("team_id") or value.get("possession")
    team = _mapping(raw)
    candidate = str(team.get("abbreviation") or team.get("id") or raw or "").strip()
    if candidate.upper() in {home_abbr.upper(), away_abbr.upper()}:
        return candidate.upper()
    for competitor in _competitors(competition.get("competitors")):
        source = _mapping(competitor.get("team"))
        if candidate and candidate == str(source.get("id") or ""):
            return home_abbr if str(competitor.get("homeAway") or "").lower() == "home" else away_abbr
    return ""


def _event_player(play: Mapping[str, Any]) -> str:
    """Return the scorer or carded player's compact surname."""

    athlete = _mapping(play.get("athlete") or play.get("player"))
    text = str(
        athlete.get("displayName")
        or athlete.get("shortName")
        or play.get("athleteName")
        or play.get("playerName")
        or ""
    ).strip()
    return text.split()[-1].upper()[:12] if text else ""


def _event_clock(play: Mapping[str, Any]) -> str:
    """Return one compact event time for soccer side-lane labels."""

    clock = _mapping(play.get("clock"))
    value = clock.get("displayValue") or clock.get("value") or play.get("time") or ""
    text = str(value).strip()
    return text if not text or text.endswith("'") else f"{text}'"


def _shootout_details(summary: Mapping[str, Any]) -> dict[str, list[str]] | None:
    """Normalize penalty attempts when ESPN exposes them in one event."""

    raw = summary.get("shootout") or summary.get("shootoutDetails") or summary.get("penaltyShootout")
    source = _mapping(raw)
    if not source:
        return None

    def side(name: str) -> list[str]:
        values = _sequence(source.get(name) or source.get(f"{name}Results"))
        outcome: list[str] = []
        for value in values:
            item = _mapping(value)
            text = str(item.get("result") or item.get("outcome") or value).lower()
            outcome.append(
                "goal" if text in {"goal", "score", "scored", "made"}
                else "miss" if text in {"miss", "missed", "save", "saved", "failed"}
                else "pending"
            )
        return outcome

    home = side("home")
    away = side("away")
    return {"home": home, "away": away} if home or away else None


def _mlb_event_details(payload: Any) -> dict[str, Any]:
    """Extract the small live MLB detail set used by the full panel."""

    summary = _mapping(payload)
    situation = _mapping(summary.get("situation"))
    if not situation:
        return {}
    batter_id = _mlb_person_id(situation.get("batter"))
    pitcher_id = _mlb_person_id(situation.get("pitcher"))
    players = _mlb_players(_mapping(summary.get("boxscore")))
    batter = players.get(batter_id, {})
    pitcher = players.get(pitcher_id, {})
    result: dict[str, Any] = {
        "balls": _mlb_number(situation.get("balls")),
        "strikes": _mlb_number(situation.get("strikes")),
        "outs": _mlb_number(situation.get("outs")),
        "onFirst": bool(situation.get("onFirst")),
        "onSecond": bool(situation.get("onSecond")),
        "onThird": bool(situation.get("onThird")),
        "batter_name": batter.get("name", ""),
        "batter_h": _mlb_value(batter.get("batting"), "hits"),
        "batter_ab": _mlb_value(batter.get("batting"), "atBats"),
        "batter_avg": _mlb_value(batter.get("batting"), "avg"),
        "pitcher_name": pitcher.get("name", ""),
        "pitcher_pitches": _mlb_value(pitcher.get("pitching"), "pitches"),
    }
    result.update(_mlb_last_pitch(summary, situation))
    return {key: value for key, value in result.items() if value not in (None, "")}


def _mlb_players(boxscore: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index summary player names and boxscore columns by ESPN athlete ID."""

    players: dict[str, dict[str, Any]] = {}
    for team in _sequence(boxscore.get("players")):
        for block in _sequence(_mapping(team).get("statistics")):
            values = _mapping(block)
            keys = tuple(str(value) for value in _sequence(values.get("keys")))
            category = "batting" if "atBats" in keys else "pitching" if "pitches" in keys else ""
            if not category:
                continue
            for row in _sequence(values.get("athletes")):
                record = _mapping(row)
                athlete = _mapping(record.get("athlete"))
                identifier = str(athlete.get("id") or "").strip()
                if not identifier:
                    continue
                stats = {
                    key: value
                    for key, value in zip(keys, _sequence(record.get("stats")))
                }
                entry = players.setdefault(identifier, {})
                entry["name"] = str(athlete.get("displayName") or entry.get("name") or "")
                entry[category] = stats
    return players


def _mlb_last_pitch(summary: Mapping[str, Any], situation: Mapping[str, Any]) -> dict[str, Any]:
    """Read pitch speed and type from the summary play matching lastPlay."""

    last = _mapping(situation.get("lastPlay"))
    identifier = str(last.get("id") or "")
    play = next(
        (item for item in _sequence(summary.get("plays")) if str(_mapping(item).get("id") or "") == identifier),
        {},
    )
    data = _mapping(play)
    speed = _mlb_number(data.get("pitchVelocity") or data.get("velocity") or data.get("speed"))
    pitch = _mapping(data.get("pitchType"))
    abbreviation = str(pitch.get("abbreviation") or data.get("pitchTypeAbbreviation") or "").strip()
    full = str(pitch.get("text") or data.get("pitchTypeText") or "").strip()
    return {
        "last_pitch_speed": speed,
        "last_pitch_type": _mlb_pitch_label(full, abbreviation),
    }


def _mlb_pitch_label(full: str, abbreviation: str) -> str:
    """Return the short fixed MLB pitch label for a 384-pixel panel."""

    normalized = re.sub(r"[^a-z0-9]+", " ", full.lower()).strip()
    if normalized in _MLB_PITCH_LABELS:
        return _MLB_PITCH_LABELS[normalized]
    normalized_abbreviation = abbreviation.upper().replace("-", "").replace(" ", "")
    if normalized_abbreviation in _MLB_PITCH_ABBREVIATIONS:
        return _MLB_PITCH_ABBREVIATIONS[normalized_abbreviation]
    return full.title()[:12] if full else normalized_abbreviation[:12]


def _mlb_person_id(value: Any) -> str:
    return str(_mapping(value).get("playerId") or _mapping(value).get("id") or "").strip()


def _mlb_value(values: Any, key: str) -> str:
    value = _mapping(values).get(key)
    return "" if value is None else str(value).strip()


def _mlb_number(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return ()


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


def _first_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and value:
        return _mapping(value[0])
    return {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


__all__ = ["EspnScoreboardProvider"]
