"""Native ESPN scoreboard provider."""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from math import isfinite
import time
from threading import RLock
from types import MappingProxyType
from typing import Any

from sports_ticker.domain import ContentItem, DisplaySettings
from sports_ticker.leagues import COLLEGE_FOOTBALL_LEAGUES

from .payloads import as_mapping as _mapping, as_sequence as _sequence, first_mapping as _first_mapping
from .contracts import ProviderHealth, ProviderResult
from .espn_fastcast import EspnFastcastSource
from .http import JsonHttpClient, PooledJsonHttpClient
from .nhl_live import nhl_team_key
from .score_alerts import ScoreAlertTracker, alerts_for_settings
from .singleflight import SingleFlightCache
from .sports_display import (
    SportsDisplayProjector,
    normalize_competition_stage,
    nhl_manpower_situation,
    nhl_goal_display,
    nhl_shootout_display,
    assign_active_team,
    display_situation,
    sports_content_sort_key,
)
from .stale_cache import SettingsResultCache
from .espn_college import (
    _NCAA_COLLEGE_FOOTBALL_RANKING_URLS,
    _needs_ncaa_logo_lookup,
    _parse_ncaa_college_football_rankings,
    _parse_ncaa_school_index,
    _resolve_college_football_rankings,
)
from .espn_details import (
    _event_football_details,
    _event_scoring_details,
    _nhl_event_details,
    _soccer_event_details,
)
from .espn_events import (
    _content_item,
    _event_competition,
    _event_detail_url,
    _event_needs_live_refresh,
    _event_payload,
    _event_time,
    _event_update,
    _events,
    _filter_college_conference_events,
    _find_side,
    _is_current_event,
    _league_needs_refresh,
    _merge_event_collections,
    _merge_mlb_detail_payload,
    _schedule_day,
    _scoreboard_dates,
    _scoreboard_url_for_dates,
    _unique_live_events,
)
from .espn_mlb import (
    _MlbEventKey,
    _MlbLiveDetailCache,
    _MlbScheduleGame,
    _mlb_api_summary_url,
    _mlb_event_details,
    _mlb_has_boxscore,
    _mlb_live_detail_cache_matches,
    _mlb_live_player_ids,
    _mlb_statsapi_summary,
    _mlb_team_abbreviations_match,
)


_SOURCE_CACHE_SECONDS = 5.0


_FASTCAST_EVENT_STALE_SECONDS = 5.0


_FULL_SCOREBOARD_REFRESH_THRESHOLD = 5


_FULL_SCOREBOARD_DISCOVERY_INTERVAL = 60.0


_LIVE_DETAIL_WORKERS = 8


_FOOTBALL_LEAGUES = frozenset(("nfl", "ncf_fbs", "ncf_fcs"))


_MLB_LIVE_DETAIL_CACHE_KEYS = frozenset(
    {
        "batter_name",
        "batter_h",
        "batter_ab",
        "batter_avg",
        "pitcher_name",
        "pitcher_pitches",
        "pitcher_era",
        "last_pitch_speed",
        "last_pitch_type",
        "home_challenges",
        "home_challenges_used",
        "away_challenges",
        "away_challenges_used",
    }
)


_MLB_SCHEDULE_CACHE_SECONDS = 60.0


_MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={}&hydrate=team"


_MLB_LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{}/feed/live"


_RANKINGS_CACHE_SECONDS = 300.0


_NCAA_SCHOOLS_INDEX_URL = "https://ncaa-api.henrygd.me/schools-index"


_NCAA_LOGO_CACHE_SECONDS = 86400.0


_NCAA_LOGO_FAILURE_RETRY_SECONDS = 60.0


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


@dataclass(frozen=True, slots=True)
class _LiveRefresh:
    """Describe one targeted live event refresh and its Fastcast race guard."""

    league: str
    event: Mapping[str, Any]
    fastcast_updated_at: float | None = None


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


def _event_league_priority(league: str) -> int:
    """Give duplicate college football events to the FCS feed before the FBS feed."""

    if league == "ncf_fcs":
        return 0
    if league == "ncf_fbs":
        return 1
    return 2


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
        nhl_situation_source: Any | None = None,
    ) -> None:
        if not isinstance(scoreboard_urls, Mapping):
            raise TypeError("scoreboard_urls must be a mapping")
        urls = {
            str(league).strip().lower(): str(url).strip()
            for league, url in scoreboard_urls.items()
            if str(league).strip() and str(url).strip()
        }
        self.scoreboard_urls = MappingProxyType(urls)
        self._event_detail_urls = {
            league: _event_detail_url(league, url) for league, url in urls.items()
        }
        self._owned_client = PooledJsonHttpClient() if client is None else None
        self.client = client if client is not None else self._owned_client
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._stale_cache = SettingsResultCache()
        self._display = SportsDisplayProjector()
        self._score_alerts = ScoreAlertTracker()
        self._score_alerts_by_ticker: dict[str, ScoreAlertTracker] = {}
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._source_cache: dict[tuple[object, ...], tuple[float, _ScoreboardSource, dict[str, str]]] = {}
        self._scoreboard_cache = SingleFlightCache(
            ttl=_SOURCE_CACHE_SECONDS, clock=self._monotonic
        )
        self._event_scoreboard_cache = SingleFlightCache(
            ttl=_SOURCE_CACHE_SECONDS, clock=self._monotonic
        )
        self._mlb_live_detail_cache: dict[str, _MlbLiveDetailCache] = {}
        self._mlb_event_keys: dict[str, _MlbEventKey] = {}
        self._mlb_schedule_cache: dict[
            str, tuple[float, tuple[_MlbScheduleGame, ...]]
        ] = {}
        self._league_schedules: dict[tuple[str, str, date], _LeagueSchedule] = {}
        self._rankings_cache: tuple[float, dict[str, dict[str, str]]] | None = None
        self._ncaa_school_index_cache: tuple[float, dict[str, str]] | None = None
        self._fastcast = fastcast
        self._nhl_situation_source = nhl_situation_source
        self._owned_nhl_situation_source = None
        self._source_cache_lock = RLock()
        self._raw_cache_lock = RLock()
        self._mlb_live_detail_cache_lock = RLock()
        self._projected_events: OrderedDict[tuple[str, str], tuple[object, object, ContentItem]] = OrderedDict()
        self._projection_contexts: dict[str, object] = {}

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch current scoreboard events from each configured active league."""

        return self._fetch(settings, self._score_alerts, cache_source=False)

    def fetch_for_ticker(self, ticker_id: str, settings: DisplaySettings) -> ProviderResult:
        """Fetch one ticker scoreboard with score memory isolated to that ticker."""

        identifier = str(ticker_id).strip()
        tracker = self._score_alerts_by_ticker.setdefault(identifier, ScoreAlertTracker())
        return self._fetch(settings, tracker, cache_source=True)

    def fetch_live_for_ticker(self, ticker_id: str, settings: DisplaySettings) -> ProviderResult:
        """Project retained source updates without starting HTTP reconciliation."""
        tracker = self._score_alerts_by_ticker.setdefault(str(ticker_id).strip(), ScoreAlertTracker())
        return self._fetch(settings, tracker, cache_source=True, live_only=True)

    def fetch_batch_for_tickers(self, settings_by_ticker: Mapping[str, DisplaySettings], *, live_only: bool = False) -> dict[str, object]:
        """Prepare each source view once and keep alert state separate for every ticker."""
        sources = {}
        results = {}
        with self._source_cache_lock:
            current = self._now()
            keys = {ticker_id: _source_key(self.scoreboard_urls, settings, _scoreboard_dates(settings.timezone, now=current))
                    for ticker_id, settings in settings_by_ticker.items()}
            representatives = {keys[ticker_id]: settings for ticker_id, settings in settings_by_ticker.items()}
            for key, settings in representatives.items():
                if not live_only or key not in self._source_cache:
                    try:
                        self._get_source(settings, cache_source=True, current=current)
                    except Exception as error:
                        sources[key] = error
            batch = None
            if self._fastcast is not None:
                versions, views = self._fastcast.capture()
                batch = {"versions": versions, "views": views, "merged": {}}
            for ticker_id, settings in settings_by_ticker.items():
                key = keys[ticker_id]
                if key not in sources:
                    try:
                        sources[key] = self._get_source(settings, cache_source=True, live_only=True, batch=batch, current=current)
                    except Exception as error:
                        sources[key] = error
                source = sources[key]
                if isinstance(source, Exception):
                    results[ticker_id] = source
                    continue
                tracker = self._score_alerts_by_ticker.setdefault(str(ticker_id).strip(), ScoreAlertTracker())
                try:
                    results[ticker_id] = self._result_from_source(settings, tracker, source)
                except Exception as error:
                    results[ticker_id] = error
        return results

    def own_nhl_situation_source(self) -> None:
        self._owned_nhl_situation_source = self._nhl_situation_source

    def close(self) -> None:
        """Stop Fastcast and close this provider's retained HTTP connections."""

        if self._fastcast is not None:
            self._fastcast.close()
        source, self._owned_nhl_situation_source = self._owned_nhl_situation_source, None
        if source is not None:
            source.close()
        if self._owned_client is not None:
            self._owned_client.close()

    def wait_for_changes(self, after: Mapping[str, str], timeout: float) -> dict[str, str]:
        """Expose source notifications to the core or its worker transport."""
        if self._fastcast is None:
            raise RuntimeError("ESPN source notifications require Fastcast")
        return self._fastcast.wait_for_changes(after, timeout)

    def _fetch(
        self,
        settings: DisplaySettings,
        score_alerts: ScoreAlertTracker,
        *,
        cache_source: bool,
        live_only: bool = False,
    ) -> ProviderResult:
        """Fetch scoreboard content and emit only alerts allowed by ticker settings."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")

        source = self._get_source(settings, cache_source=cache_source, live_only=live_only)
        return self._result_from_source(settings, score_alerts, source)

    def _get_source(self, settings: DisplaySettings, *, cache_source: bool, live_only: bool = False,
                    batch: dict | None = None, current: datetime | None = None) -> "_ScoreboardSource":

        current = self._now() if current is None else current
        dates = _scoreboard_dates(settings.timezone, now=current)
        source_key = _source_key(self.scoreboard_urls, settings, dates)
        if cache_source:
            with self._source_cache_lock:
                now = self._monotonic()
                cached = self._source_cache.get(source_key)
                versions = self._source_versions(settings) if batch is None else {
                    league: version for league, version in batch["versions"].items()
                    if league in self.scoreboard_urls and settings.active_sports.get(league, True)}
                if cached is not None and (live_only or 0 <= now - cached[0] < 5.0):
                    if versions == cached[2]:
                        source = cached[1]
                    else:
                        source = self._read_source(settings, current, dates, cache_schedule=True, live_only=True, batch=batch)
                        source = replace(source, errors=cached[1].errors, failed_sources=cached[1].failed_sources,
                                         invalid_sources=cached[1].invalid_sources)
                        self._source_cache[source_key] = (cached[0], source, versions)
                else:
                    source = self._read_source(settings, current, dates, cache_schedule=True)
                    self._source_cache[source_key] = (self._monotonic(), source, versions)
        else:
            source = self._read_source(settings, current, dates, cache_schedule=False)
        return source

    def _result_from_source(self, settings: DisplaySettings, score_alerts: ScoreAlertTracker,
                            source: "_ScoreboardSource") -> ProviderResult:
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
            return self._stale_cache.stale_result(settings, health.error or "all sources failed", provider="espn")
        return result

    def _source_versions(self, settings: DisplaySettings) -> dict[str, str]:
        if self._fastcast is None:
            return {}
        return {league: version for league, version in self._fastcast.versions().items()
                if league in self.scoreboard_urls and settings.active_sports.get(league, True)}

    def _read_source(
        self,
        settings: DisplaySettings,
        current: datetime,
        dates: Sequence[date],
        *,
        cache_schedule: bool,
        live_only: bool = False,
        batch: dict | None = None,
    ) -> "_ScoreboardSource":
        """Read one shared ESPN source view for all tickers with matching source settings."""

        if self._fastcast is not None:
            self._fastcast.start()
        items: list[ContentItem] = []
        errors: list[str] = []
        seen_event_ids: set[str] = set()
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
        live_refreshes: list[_LiveRefresh] = []
        live_detail_suppressed: set[str] = set()
        for league, url in active_leagues:
            cache_key = (settings.timezone, league, schedule_day)
            cached = self._league_schedules.get(cache_key) if cache_schedule else None
            raw_schedule_events = (
                self._fastcast_events(league, cached.events, batch=batch)
                if cached is not None and cache_schedule
                else cached.events if cached is not None else ()
            )
            schedule_events = _filter_college_conference_events(
                league,
                raw_schedule_events,
                settings.active_conferences,
            )
            if live_only:
                cached_events[league] = schedule_events
                continue
            if cached is None:
                refresh_leagues.append((league, url))
            elif monotonic_now - cached.discovery_at >= _FULL_SCOREBOARD_DISCOVERY_INTERVAL:
                cached_events[league] = schedule_events
                discovery_ages[league] = cached.discovery_at
                refresh_leagues.append((league, url))
            elif _league_needs_refresh(schedule_events, current):
                cached_events[league] = schedule_events
                discovery_ages[league] = cached.discovery_at
                if self._fastcast_active(league) and league != "mlb":
                    live_events = _unique_live_events(schedule_events, current)
                    stale_live_events = self._stale_fastcast_events(
                        league,
                        live_events,
                        monotonic_now,
                    )
                    if league == "nhl":
                        live_refreshes.extend(self._live_refresh(league, event) for event in live_events)
                    else:
                        live_detail_suppressed.add(league)
                    if league == "nhl":
                        # ESPN Fastcast updates NHL scores quickly, but it does not carry a
                        # continuously changing game clock. Refresh the scoreboard clock directly.
                        refresh_leagues.append((league, url))
                    elif not stale_live_events:
                        continue
                    elif (
                        not self._event_detail_urls.get(league)
                        or len(stale_live_events) >= _FULL_SCOREBOARD_REFRESH_THRESHOLD
                    ):
                        refresh_leagues.append((league, url))
                    else:
                        live_refreshes.extend(self._live_refresh(league, event) for event in stale_live_events)
                elif self._event_detail_urls.get(league):
                    live_events = _unique_live_events(schedule_events, current)
                    if league == "nhl":
                        # Keep the NHL clock owned by the complete scoreboard response.
                        refresh_leagues.append((league, url))
                    elif len(live_events) >= _FULL_SCOREBOARD_REFRESH_THRESHOLD:
                        refresh_leagues.append((league, url))
                        if league != "mlb":
                            live_detail_suppressed.add(league)
                    else:
                        live_refreshes.extend(
                            _LiveRefresh(league=league, event=event)
                            for event in live_events
                        )
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
        live_update_expected_fastcast_at: dict[tuple[str, str], float | None] = {}
        ncaa_logo_future: Any | None = None
        workers = min(
            8,
            max(
                1,
                len(refresh_leagues),
                min(_LIVE_DETAIL_WORKERS, len(live_refreshes)),
            ),
        )
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="espn-refresh",
        ) as pool:
            rankings_future = (
                pool.submit(self._read_college_football_rankings)
                if not live_only and any(league in COLLEGE_FOOTBALL_LEAGUES for league, _url in active_leagues)
                else None
            )
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
            for refresh in live_refreshes:
                event_id = str(refresh.event.get("id") or "").strip()
                if not event_id:
                    continue
                key = (refresh.league, event_id)
                live_update_futures[key] = pool.submit(
                    self._read_event_scoreboard,
                    refresh.league,
                    event_id,
                    cache_source=cache_schedule,
                )
                live_update_expected_fastcast_at[key] = refresh.fastcast_updated_at
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
                    if self._fastcast_active(league) and league != "mlb":
                        if league != "nhl":
                            live_detail_suppressed.add(league)
                        elif self._event_detail_urls.get(league):
                            self._submit_event_reads(pool, league, live_events, live_update_futures,
                                                     live_update_expected_fastcast_at, cache_schedule)
                    elif self._event_detail_urls.get(league):
                        dense_live = len(live_events) >= _FULL_SCOREBOARD_REFRESH_THRESHOLD
                        if dense_live and league != "mlb" and league != "nhl":
                            live_detail_suppressed.add(league)
                        if (
                            (not dense_live or league == "mlb" or league == "nhl")
                            and (cache_schedule or league == "nhl")
                        ):
                            self._submit_event_reads(pool, league, live_events, live_update_futures,
                                                     live_update_expected_fastcast_at, cache_schedule)
            for (league, event_id), future in live_update_futures.items():
                attempted_live_update_ids.add((league, event_id))
                try:
                    update = future.result()
                except Exception:
                    continue
                live_update_payloads[(league, event_id)] = update
                events = events_by_league.get(league, ())
                updated_event: Mapping[str, Any] | None = None
                updated_events_list: list[Mapping[str, Any]] = []
                for event in events:
                    if str(event.get("id") or "").strip() == event_id:
                        updated_event = _event_update(update, event, league=league)
                        updated_events_list.append(updated_event)
                    else:
                        updated_events_list.append(event)
                updated_events = tuple(updated_events_list)
                events_by_league[league] = _filter_college_conference_events(
                    league,
                    updated_events,
                    settings.active_conferences,
                )
                if self._fastcast is not None and updated_event is not None:
                    self._fastcast.prime_event(
                        league,
                        updated_event,
                        if_updated_at=live_update_expected_fastcast_at.get(
                            (league, event_id)
                        ),
                    )
                if cache_schedule:
                    cached_schedule = self._league_schedules.get(
                        (settings.timezone, league, schedule_day)
                    )
                    stored_events = cached_schedule.events if cached_schedule is not None else updated_events
                    stored_events = tuple(
                        _event_update(update, event, league=league)
                        if str(event.get("id") or "").strip() == event_id
                        else event
                        for event in stored_events
                    )
                    self._league_schedules[(settings.timezone, league, schedule_day)] = _LeagueSchedule(
                        events=stored_events,
                        schedule_day=schedule_day,
                        discovery_at=discovery_ages.get(league, self._monotonic()),
                    )
            if not live_only and _needs_ncaa_logo_lookup(active_leagues, events_by_league):
                ncaa_logo_future = pool.submit(self._read_ncaa_school_index)

        if batch is None:
            for league, _url in active_leagues:
                events_by_league[league] = self._fastcast_events(league, events_by_league.get(league, ()))
        ranking_names = self._rankings_cache[1] if live_only and self._rankings_cache is not None else {}
        if rankings_future is not None:
            ranking_names = rankings_future.result()
        football_rankings = _resolve_college_football_rankings(
            ranking_names,
            events_by_league,
        )
        ncaa_logo_index = self._ncaa_school_index_cache[1] if live_only and self._ncaa_school_index_cache is not None else {}
        if ncaa_logo_future is not None:
            ncaa_logo_index = ncaa_logo_future.result()
        failed_sources = len(failed_leagues)
        suppressed_live_update_ids = {
            (league, str(event.get("id") or "").strip())
            for league in live_detail_suppressed
            for event in events_by_league.get(league, ())
            if str(event.get("id") or "").strip()
            and _event_needs_live_refresh(event, current)
        }
        event_leagues = sorted(
            active_leagues,
            key=lambda entry: _event_league_priority(entry[0]),
        )
        for league, _url in event_leagues:
            context = (tuple(sorted(football_rankings.items())) if league in COLLEGE_FOOTBALL_LEAGUES else (),
                       tuple(sorted(ncaa_logo_index.items())) if league in COLLEGE_FOOTBALL_LEAGUES else ())
            # Keep the stored context object while it is equal, because the
            # projection cache compares contexts by identity.
            if self._projection_contexts.get(league) != context:
                self._projection_contexts[league] = context
            context = self._projection_contexts[league]
            events = events_by_league.get(league, ())
            for event in events:
                event_id = str(event.get("id") or "").strip()
                if event_id and event_id in seen_event_ids:
                    continue
                if event_id:
                    seen_event_ids.add(event_id)
                if not _is_current_event(
                    event,
                    timezone_name=settings.timezone,
                    now=current,
                ):
                    continue
                try:
                    key = (league, event_id)
                    trace = _mapping(event.get("_source_timing")).get("trace_id")
                    cached_item = self._projected_events.get(key) if trace else None
                    if cached_item is not None and cached_item[0] == trace and cached_item[1] is context:
                        item = cached_item[2]
                        self._projected_events.move_to_end(key)
                    else:
                        item = self._display.project(
                            _content_item(league, event, ncaa_logo_index=ncaa_logo_index), event,
                            football_rankings=football_rankings)
                        if trace:
                            self._projected_events[key] = (trace, context, item)
                            self._projected_events.move_to_end(key)
                            while len(self._projected_events) > 4096:
                                self._projected_events.popitem(last=False)
                    items.append(item)
                except (KeyError, TypeError, ValueError) as exc:
                    invalid_leagues.add(league)
                    errors.append(f"{league} event: {exc}")

        return _ScoreboardSource(
            content=tuple(
                sorted(
                    self._enrich_nhl_live_items(items) if live_only else self._enrich_live_items(
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

    def _live_refresh(self, league: str, event: Mapping[str, Any]) -> "_LiveRefresh":
        """Pair one live event with the Fastcast update time its detail read must not overwrite."""
        return _LiveRefresh(
            league=league,
            event=event,
            fastcast_updated_at=self._fastcast.event_updated_at(league, str(event.get("id") or "").strip())
            if self._fastcast is not None
            else None,
        )

    def _submit_event_reads(self, pool, league, events, futures, expected_fastcast_at, cache_schedule) -> None:
        """Submit one event scoreboard read for each live event that has no read yet."""
        for event in events:
            event_id = str(event.get("id") or "").strip()
            if event_id and (league, event_id) not in futures:
                futures[(league, event_id)] = pool.submit(
                    self._read_event_scoreboard,
                    league,
                    event_id,
                    cache_source=cache_schedule,
                )
                expected_fastcast_at[(league, event_id)] = None

    def _fastcast_active(self, league: str) -> bool:
        """Return whether one league can use its shared Fastcast state."""

        return self._fastcast is not None and self._fastcast.active(league)

    def _read_college_football_rankings(self) -> dict[str, dict[str, str]]:
        """Read cached NCAA AP and Stats Perform polls without affecting scoreboard health."""

        now = self._monotonic()
        with self._raw_cache_lock:
            cached = self._rankings_cache
            if cached is not None and 0 <= now - cached[0] < _RANKINGS_CACHE_SECONDS:
                return cached[1]
        rankings = {
            league: {}
            for league in _NCAA_COLLEGE_FOOTBALL_RANKING_URLS
        }
        for league, url in _NCAA_COLLEGE_FOOTBALL_RANKING_URLS.items():
            try:
                payload = self.client.get_json(url, timeout=self.timeout)
                rankings[league] = _parse_ncaa_college_football_rankings(payload)
            except Exception:
                continue
        with self._raw_cache_lock:
            self._rankings_cache = (self._monotonic(), rankings)
        return rankings

    def _read_ncaa_school_index(self) -> dict[str, str]:
        """Read the cached NCAA school index for teams missing ESPN logos."""

        now = self._monotonic()
        with self._raw_cache_lock:
            cached = self._ncaa_school_index_cache
            if cached is not None:
                age = now - cached[0]
                limit = _NCAA_LOGO_CACHE_SECONDS if cached[1] else _NCAA_LOGO_FAILURE_RETRY_SECONDS
                if 0 <= age < limit:
                    return cached[1]
        try:
            payload = self.client.get_json(
                _NCAA_SCHOOLS_INDEX_URL,
                timeout=self.timeout,
            )
            index = _parse_ncaa_school_index(payload)
        except Exception:
            index = {}
        with self._raw_cache_lock:
            self._ncaa_school_index_cache = (self._monotonic(), index)
        return index

    def _stale_fastcast_events(
        self,
        league: str,
        events: Sequence[Mapping[str, Any]],
        monotonic_now: float,
    ) -> tuple[Mapping[str, Any], ...]:
        """Return live events that lack a recent event-specific Fastcast update."""

        if self._fastcast is None:
            return tuple(events)
        stale: list[Mapping[str, Any]] = []
        for event in events:
            event_id = str(event.get("id") or "").strip()
            updated_at = self._fastcast.event_updated_at(league, event_id)
            if (
                updated_at is None
                or monotonic_now < updated_at
                or monotonic_now - updated_at >= _FASTCAST_EVENT_STALE_SECONDS
            ):
                stale.append(event)
        return tuple(stale)

    def _fastcast_events(
        self,
        league: str,
        fallback: Sequence[Mapping[str, Any]],
        *,
        batch: dict | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        """Merge one Fastcast snapshot over the last complete schedule."""

        if self._fastcast is None:
            return tuple(fallback)
        key = (league, id(fallback))
        if batch is not None and key in batch["merged"]:
            return batch["merged"][key][1]
        snapshot, timings = self._fastcast.timed_snapshot(league) if batch is None else batch["views"].get(league, (None, {}))
        if snapshot is None:
            return tuple(fallback)
        try:
            events = _events(snapshot)
        except (TypeError, ValueError):
            return tuple(fallback)
        merged = _merge_event_collections(fallback, events, league=league)
        result = tuple(
            {**event, "_source_timing": timings[str(event.get("id") or "")]} if str(event.get("id") or "") in timings else event
            for event in merged
        )
        if batch is not None:
            batch["merged"][key] = (fallback, result)
        return result

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
            events = _events(payload)
            self._remember_mlb_events(league, events)
            return events

        response = self._cached_scoreboard(request_url)
        if response.error:
            raise _ScoreboardReadError(
                response.error,
                request_failed=response.request_failed,
            )
        if self._fastcast is not None and response.payload is not None:
            self._fastcast.prime(league, response.payload)
        events = response.events or ()
        self._remember_mlb_events(league, events)
        return events

    def _read_event_scoreboard(
        self,
        league: str,
        event_id: str,
        *,
        cache_source: bool = False,
    ) -> Mapping[str, Any]:
        """Read one live event from ESPN's compact single-event scoreboard resource."""

        template = self._event_detail_urls.get(league)
        if not template:
            return {}
        request_url = template.format(event_id)
        if not cache_source:
            return self._read_event_payload(league, event_id, request_url)

        response = self._cached_event_scoreboard((league, event_id), request_url)
        if response.error:
            raise RuntimeError(response.error)
        return response.payload or {}

    def _read_event_payload(
        self, league: str, event_id: str, request_url: str
    ) -> Mapping[str, Any]:
        """Read one event payload and retry MLB detail data through ESPN's API host."""

        try:
            payload = self.client.get_json(request_url, timeout=self.timeout)
            event = _event_payload(payload)
        except Exception:
            event = {}
        if league != "mlb" and event:
            return event
        fallback_url = _mlb_api_summary_url(request_url) if league == "mlb" else ""
        needs_mlb_fallback = not event or not _mlb_has_boxscore(event)
        if fallback_url and fallback_url != request_url and needs_mlb_fallback:
            try:
                payload = self.client.get_json(fallback_url, timeout=self.timeout)
                fallback_event = _event_payload(payload)
                event = (
                    _merge_mlb_detail_payload(event, fallback_event)
                    if event and fallback_event
                    else fallback_event or event
                )
            except Exception:
                pass
        if league == "mlb":
            self._remember_mlb_events(league, (event,))
            statsapi_event = self._read_mlb_statsapi_event(event_id)
            if statsapi_event:
                event = _merge_mlb_detail_payload(event, statsapi_event)
        if event:
            return event
        raise RuntimeError(f"{league} event detail request failed for {event_id}")

    def _remember_mlb_events(
        self, league: str, events: Sequence[Mapping[str, Any]]
    ) -> None:
        """Index MLB ESPN events by their teams and complete start timestamp."""

        if league != "mlb":
            return
        for event in events:
            header = _mapping(event.get("header"))
            event_id = str(event.get("id") or header.get("id") or "").strip()
            competition = _first_mapping(
                event.get("competitions") or header.get("competitions")
            )
            date_text = str(
                event.get("date")
                or header.get("date")
                or competition.get("date")
                or ""
            ).strip()
            competitors = tuple(
                _mapping(value) for value in _sequence(competition.get("competitors"))
            )
            away = _find_side(competitors, "away")
            home = _find_side(competitors, "home")
            away_abbr = str(_mapping(away.get("team")).get("abbreviation") or "").strip().upper()
            home_abbr = str(_mapping(home.get("team")).get("abbreviation") or "").strip().upper()
            if event_id and away_abbr and home_abbr and len(date_text) >= 10:
                try:
                    game_date = date.fromisoformat(date_text[:10])
                except ValueError:
                    continue
                self._mlb_event_keys[event_id] = _MlbEventKey(
                    away_abbr=away_abbr,
                    home_abbr=home_abbr,
                    event_date=game_date,
                    event_start=_event_time(date_text),
                )

    def _read_mlb_statsapi_event(self, event_id: str) -> Mapping[str, Any]:
        """Read one MLB live feed after ESPN summary endpoints omit player rows."""

        event_key = self._mlb_event_keys.get(str(event_id).strip())
        if event_key is None:
            return {}
        game_pk = self._mlb_game_pk(
            event_key.away_abbr,
            event_key.home_abbr,
            event_key.event_date,
            event_start=event_key.event_start,
        )
        if not game_pk:
            return {}
        try:
            payload = self.client.get_json(
                _MLB_LIVE_FEED_URL.format(game_pk),
                timeout=self.timeout,
            )
        except Exception:
            return {}
        return _mlb_statsapi_summary(payload, str(event_id).strip())

    def _mlb_game_pk(
        self,
        away_abbr: str,
        home_abbr: str,
        event_date: date,
        *,
        event_start: datetime | None = None,
    ) -> str:
        """Match one ESPN MLB event to its closest StatsAPI game identifier."""

        candidates: list[_MlbScheduleGame] = []
        for schedule_date in (event_date, event_date - timedelta(days=1)):
            schedule_key = schedule_date.isoformat()
            now = self._monotonic()
            cached = self._mlb_schedule_cache.get(schedule_key)
            if cached is None or now - cached[0] >= _MLB_SCHEDULE_CACHE_SECONDS:
                try:
                    payload = self.client.get_json(
                        _MLB_SCHEDULE_URL.format(schedule_key),
                        timeout=self.timeout,
                    )
                except Exception:
                    continue
                games: list[_MlbScheduleGame] = []
                for day in _sequence(_mapping(payload).get("dates")):
                    for game in _sequence(_mapping(day).get("games")):
                        teams = _mapping(game).get("teams")
                        away = _mapping(_mapping(teams).get("away")).get("team")
                        home = _mapping(_mapping(teams).get("home")).get("team")
                        key = (
                            str(_mapping(away).get("abbreviation") or "").strip().upper(),
                            str(_mapping(home).get("abbreviation") or "").strip().upper(),
                        )
                        game_pk = str(_mapping(game).get("gamePk") or "").strip()
                        if key[0] and key[1] and game_pk:
                            games.append(
                                _MlbScheduleGame(
                                    game_pk=game_pk,
                                    away_abbr=key[0],
                                    home_abbr=key[1],
                                    game_start=_event_time(
                                        str(_mapping(game).get("gameDate") or "")
                                    ),
                                )
                            )
                self._mlb_schedule_cache[schedule_key] = (now, tuple(games))
            else:
                games = cached[1]
            candidates.extend(
                game
                for game in games
                if _mlb_team_abbreviations_match(away_abbr, game.away_abbr)
                and _mlb_team_abbreviations_match(home_abbr, game.home_abbr)
            )
        if not candidates:
            return ""
        if event_start is None:
            return candidates[0].game_pk
        reference = (
            event_start.replace(tzinfo=timezone.utc)
            if event_start.tzinfo is None
            else event_start.astimezone(timezone.utc)
        )
        return min(
            candidates,
            key=lambda game: (
                abs((game.game_start - reference).total_seconds())
                if game.game_start is not None
                else float("inf")
            ),
        ).game_pk

    def _cached_scoreboard(self, request_url: str) -> _RawScoreboardResponse:
        """Read one scoreboard URL once per freshness window, including temporary failures."""
        def load() -> _RawScoreboardResponse:
            try:
                payload = self.client.get_json(request_url, timeout=self.timeout)
            except Exception as error:
                return _RawScoreboardResponse(
                    events=None,
                    error=str(error) or type(error).__name__,
                    request_failed=True,
                    completed_at=self._monotonic(),
                )
            try:
                events = _events(payload)
            except Exception as error:
                return _RawScoreboardResponse(
                    events=None,
                    error=str(error) or type(error).__name__,
                    request_failed=False,
                    completed_at=self._monotonic(),
                )
            return _RawScoreboardResponse(
                events=events,
                error=None,
                request_failed=False,
                completed_at=self._monotonic(),
                payload=payload,
            )

        return self._scoreboard_cache.get(request_url, load)

    def _cached_event_scoreboard(
        self,
        key: tuple[str, str],
        request_url: str,
    ) -> _RawEventScoreboardResponse:
        """Read one event scoreboard once per freshness window, including failures."""

        def load() -> _RawEventScoreboardResponse:
            try:
                event = self._read_event_payload(key[0], key[1], request_url)
            except Exception as error:
                return _RawEventScoreboardResponse(
                    payload=None,
                    error=str(error) or type(error).__name__,
                    completed_at=self._monotonic(),
                )
            return _RawEventScoreboardResponse(
                payload=event,
                error=None,
                completed_at=self._monotonic(),
            )

        return self._event_scoreboard_cache.get(key, load)

    def _enrich_live_item(
        self,
        league: str,
        item: ContentItem,
        *,
        update: Any | None = None,
    ) -> ContentItem:
        """Add detailed live facts after scoreboard projection completes."""

        if str(item.data.get("state") or "").lower() not in {"in", "half", "crit"}:
            if league == "mlb":
                self._clear_mlb_live_detail(item.id)
            return item
        template = self._event_detail_urls.get(league)
        if not template:
            return item

        if update is None:
            try:
                update = self._read_event_scoreboard(league, item.id, cache_source=True)
            except Exception:
                if league != "mlb":
                    return item
                update = {}
        details = _event_scoring_details(update, item.data)
        details.update(
            _mlb_event_details(update)
            if league == "mlb"
            else _nhl_event_details(update, item.data)
            if league == "nhl"
            else _soccer_event_details(update, item.data)
            if league.startswith("soccer")
            else _event_football_details(update, item.data)
            if league in _FOOTBALL_LEAGUES
            else display_situation(
                league,
                _event_competition(update),
                home_abbr=str(item.data.get("home_abbr") or ""),
                away_abbr=str(item.data.get("away_abbr") or ""),
            )
        )
        if league == "mlb":
            details = self._merge_mlb_live_details(item.id, update, details)
        if not details:
            return item
        data = dict(item.data)
        if league == "nhl" and details.get("shootout") is not None:
            data["status"] = "S/O"
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

    def _merge_mlb_live_details(
        self,
        event_id: str,
        update: Any,
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Keep successful MLB detail fields through partial live polls."""

        batter_id, pitcher_id = _mlb_live_player_ids(update)
        with self._mlb_live_detail_cache_lock:
            cached = self._mlb_live_detail_cache.get(event_id)
            if cached is not None and not _mlb_live_detail_cache_matches(
                cached,
                batter_id=batter_id,
                pitcher_id=pitcher_id,
                details=details,
            ):
                cached = None
                self._mlb_live_detail_cache.pop(event_id, None)
            fresh = {
                key: value
                for key, value in details.items()
                if key in _MLB_LIVE_DETAIL_CACHE_KEYS and value not in (None, "")
            }
            if fresh:
                values = dict(cached.values) if cached is not None else {}
                values.update(fresh)
                cached = _MlbLiveDetailCache(
                    values=values,
                    batter_id=batter_id or (cached.batter_id if cached else ""),
                    pitcher_id=pitcher_id or (cached.pitcher_id if cached else ""),
                )
                self._mlb_live_detail_cache[event_id] = cached
            retained = dict(cached.values) if cached is not None else {}
        retained.update(details)
        return retained

    def _clear_mlb_live_detail(self, event_id: str) -> None:
        """Remove cached MLB details after one event leaves live state."""

        with self._mlb_live_detail_cache_lock:
            self._mlb_live_detail_cache.pop(event_id, None)

    def _prune_mlb_live_detail_cache(self, items: Sequence[ContentItem]) -> None:
        """Remove cached MLB details for events explicitly observed outside live state."""

        observed_states = {
            item.id: str(item.data.get("state") or "").lower()
            for item in items
            if str(item.data.get("sport") or "") == "mlb"
        }
        with self._mlb_live_detail_cache_lock:
            for event_id, state in observed_states.items():
                if state not in {"in", "half", "crit"}:
                    self._mlb_live_detail_cache.pop(event_id, None)

    def _enrich_live_items(
        self,
        items: Sequence[ContentItem],
        *,
        update_payloads: Mapping[tuple[str, str], Any] | None = None,
        attempted_update_ids: set[tuple[str, str]] | None = None,
        suppressed_update_ids: set[tuple[str, str]] | None = None,
    ) -> list[ContentItem]:
        """Fetch live game details concurrently without blocking other scoreboards."""

        self._prune_mlb_live_detail_cache(items)
        provided_updates = update_payloads or {}
        attempted_updates = attempted_update_ids or set()
        indexed = list(enumerate(items))
        targets = [
            (index, item)
            for index, item in indexed
            if str(item.data.get("state") or "").lower() in {"in", "half", "crit"}
            and str(item.data.get("sport") or "") in self._event_detail_urls
            and not (
                suppressed_update_ids
                and (str(item.data.get("sport") or ""), item.id) in suppressed_update_ids
            )
            and not (
                attempted_updates
                and (str(item.data.get("sport") or ""), item.id) in attempted_updates
                and (str(item.data.get("sport") or ""), item.id) not in provided_updates
                and str(item.data.get("sport") or "") != "mlb"
            )
        ]
        if not targets:
            return self._enrich_nhl_live_items(items)
        enriched = list(items)
        workers = min(8, len(targets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ticker-details") as pool:
            futures = {
                pool.submit(
                    self._enrich_live_item,
                    str(item.data.get("sport") or ""),
                    item,
                    update=(
                        provided_updates[(str(item.data.get("sport") or ""), item.id)]
                        if (str(item.data.get("sport") or ""), item.id) in provided_updates
                        else {}
                        if (str(item.data.get("sport") or ""), item.id) in attempted_updates
                        else None
                    ),
                ): index
                for index, item in targets
            }
            for future, index in futures.items():
                try:
                    enriched[index] = future.result()
                except Exception:
                    continue
        return self._enrich_nhl_live_items(enriched)

    def _enrich_nhl_live_items(
        self,
        items: Sequence[ContentItem],
    ) -> list[ContentItem]:
        """Add cached NHL manpower facts without waiting for ESPN detail polls."""

        source = self._nhl_situation_source
        if source is None:
            return list(items)
        try:
            snapshot = source.snapshot()
        except Exception:
            snapshot = {}
        if not isinstance(snapshot, Mapping):
            snapshot = {}
        result = list(items)
        for index, item in enumerate(result):
            data = item.data
            if (
                str(data.get("sport") or "") != "nhl"
                or str(data.get("state") or "").lower() not in {"in", "half", "crit", "post"}
            ):
                continue
            key = (
                nhl_team_key(data.get("away_abbr")),
                nhl_team_key(data.get("home_abbr")),
            )
            facts = snapshot.get(key)
            if not isinstance(facts, Mapping):
                facts = {}
            start = _event_time(data.get("startTimeUTC"))
            fact_start = _event_time(facts.get("startTimeUTC"))
            if start and fact_start and start.date() != fact_start.date():
                facts = {}
            if str(data.get("status") or "") == "S/O":
                facts = {**facts, "phase": "shootout"}
            updated = dict(data)
            updated["competition_stage"] = max(
                normalize_competition_stage(data.get("competition_stage")),
                normalize_competition_stage(facts.get("competition_stage")),
            )
            facts = {**facts, "competition_stage": updated["competition_stage"]}
            details = nhl_manpower_situation(
                facts,
                home_abbr=str(data.get("home_abbr") or ""),
                away_abbr=str(data.get("away_abbr") or ""),
            )
            situation = dict(_mapping(data.get("situation")))
            situation.update(details)
            if "goals" in facts:
                situation["hockeyGoals"] = nhl_goal_display(facts)
            if "shootout" in facts:
                situation["shootout"] = nhl_shootout_display(facts)
                if situation["shootout"] is not None:
                    updated["status"] = "FINAL S/O" if data.get("state") == "post" else "S/O"
            updated["situation"] = situation
            result[index] = ContentItem(
                id=item.id,
                family=item.family,
                kind=item.kind,
                is_shown=item.is_shown,
                data=updated,
            )
        return result


__all__ = ["EspnScoreboardProvider"]
