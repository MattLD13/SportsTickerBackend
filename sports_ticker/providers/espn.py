"""Native ESPN scoreboard provider."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from math import isfinite
import re
import time
from threading import RLock
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import ContentItem, DisplaySettings

from .contracts import ProviderHealth, ProviderResult
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


@dataclass(frozen=True, slots=True)
class _ScoreboardSource:
    """Keep one upstream scoreboard view for all matching ticker settings."""

    content: tuple[ContentItem, ...]
    errors: tuple[str, ...]
    active_sources: int
    failed_sources: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class _LeagueSchedule:
    """Keep one league schedule until its next local 3am sweep."""

    events: tuple[Mapping[str, Any], ...]
    schedule_day: date


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
    return settings.timezone, tuple(dates), enabled


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
    ) -> None:
        if not isinstance(scoreboard_urls, Mapping):
            raise TypeError("scoreboard_urls must be a mapping")
        urls = {
            str(league).strip().lower(): str(url).strip()
            for league, url in scoreboard_urls.items()
            if str(league).strip() and str(url).strip()
        }
        self.scoreboard_urls = MappingProxyType(urls)
        self._summary_urls = {league: _summary_url(url) for league, url in urls.items()}
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
        self._league_schedules: dict[tuple[str, str, date], _LeagueSchedule] = {}
        self._source_cache_lock = RLock()

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
        """Fetch scoreboard content and emit only alerts allowed by ticker settings."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")

        current = self._now()
        dates = _scoreboard_dates(settings.timezone, now=current)
        source_key = _source_key(self.scoreboard_urls, settings, dates)
        if cache_source:
            now = self._monotonic()
            with self._source_cache_lock:
                cached = self._source_cache.get(source_key)
                if cached is not None and 0 <= now - cached[0] < 5.0:
                    source = cached[1]
                else:
                    source = self._read_source(settings, current, dates, cache_schedule=True)
                    self._source_cache[source_key] = (now, source)
        else:
            source = self._read_source(settings, current, dates, cache_schedule=False)

        items = source.content
        score_games = [{"kind": item.kind, "id": item.id, **dict(item.data)} for item in items]
        score_alerts.ingest(score_games)
        alerts = alerts_for_settings(
            score_alerts.recent(
                delay=settings.live_delay_seconds if settings.live_delay_mode else 0.0,
            ),
            settings,
        )
        health = ProviderHealth(
            healthy=not source.errors,
            provider="espn",
            error="; ".join(source.errors) if source.errors else None,
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
        if source.active_sources and source.failed_sources == source.active_sources:
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

        items: list[ContentItem] = []
        errors: list[str] = []
        failed_sources = 0
        seen_events: set[tuple[str, str]] = set()
        active_leagues = tuple(
            (league, url)
            for league, url in self.scoreboard_urls.items()
            if settings.active_sports.get(league, True)
        )
        active_sources = len(active_leagues)
        workers = min(8, active_sources)
        schedule_day = _schedule_day(settings.timezone, current)
        cached_events: dict[str, tuple[Mapping[str, Any], ...]] = {}
        refresh_leagues: list[tuple[str, str]] = []
        for league, url in active_leagues:
            cache_key = (settings.timezone, league, schedule_day)
            cached = self._league_schedules.get(cache_key) if cache_schedule else None
            if cached is None or _league_needs_refresh(cached.events, current):
                refresh_leagues.append((league, url))
            else:
                cached_events[league] = cached.events

        workers = min(8, len(refresh_leagues))
        with ThreadPoolExecutor(
            max_workers=max(1, workers),
            thread_name_prefix="espn-scoreboards",
        ) as pool:
            futures = {
                league: pool.submit(self._read_scoreboard, url, dates)
                for league, url in refresh_leagues
            }
            for league, _url in active_leagues:
                if league in futures:
                    try:
                        events = futures[league].result()
                    except Exception as exc:
                        failed_sources += 1
                        errors.append(f"{league}: {exc}")
                        continue
                    events = tuple(events)
                    if cache_schedule:
                        self._league_schedules[(settings.timezone, league, schedule_day)] = _LeagueSchedule(
                            events=events,
                            schedule_day=schedule_day,
                        )
                else:
                    events = cached_events[league]
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
                        errors.append(f"{league} event: {exc}")

        return _ScoreboardSource(
            content=tuple(sorted(self._enrich_live_items(items), key=sports_content_sort_key)),
            errors=tuple(errors),
            active_sources=active_sources,
            failed_sources=failed_sources,
            observed_at=datetime.now(timezone.utc),
        )

    def _read_scoreboard(
        self,
        url: str,
        dates: Sequence[date],
    ) -> tuple[Mapping[str, Any], ...]:
        """Read all games for one league in one request."""

        payload = self.client.get_json(
            _scoreboard_url_for_dates(url, dates),
            timeout=self.timeout,
        )
        return _events(payload)

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

    def _enrich_live_item(self, league: str, item: ContentItem) -> ContentItem:
        """Add detailed live facts after scoreboard projection completes."""

        if str(item.data.get("state") or "").lower() not in {"in", "half", "crit"}:
            return item
        template = self._summary_urls.get(league)
        if not template:
            return item

        try:
            summary = self.client.get_json(template.format(item.id), timeout=self.timeout)
        except Exception:
            return item
        details = _summary_scoring_details(summary, item.data)
        details.update(
            _mlb_summary_details(summary)
            if league == "mlb"
            else _nhl_summary_details(summary, item.data)
            if league == "nhl"
            else _soccer_summary_details(summary, item.data)
            if league.startswith("soccer")
            else display_situation(
                league,
                _first_mapping(_mapping(summary.get("header")).get("competitions")),
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

    def _enrich_live_items(self, items: Sequence[ContentItem]) -> list[ContentItem]:
        """Fetch live game details concurrently without blocking other scoreboards."""

        indexed = list(enumerate(items))
        targets = [
            (index, item)
            for index, item in indexed
            if str(item.data.get("state") or "").lower() in {"in", "half", "crit"}
            and str(item.data.get("sport") or "") in self._summary_urls
        ]
        if not targets:
            return list(items)
        enriched = list(items)
        workers = min(8, len(targets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ticker-details") as pool:
            futures = {
                pool.submit(self._enrich_live_item, str(item.data.get("sport") or ""), item): index
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
        status = _mapping(_mapping(event.get("status")).get("type"))
        state = _text(status.get("state"), "pre").strip().lower()
        if state in {"in", "half", "crit"}:
            return True
        if state in {"post", "final", "canceled", "cancelled"}:
            continue
        start = _event_time(event.get("date"))
        if start is not None and start <= current <= start + timedelta(hours=6):
            return True
    return False


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


def _summary_url(scoreboard_url: str) -> str:
    """Derive the matching ESPN event-summary endpoint from one scoreboard URL."""

    endpoint = scoreboard_url.split("?", 1)[0].rstrip("/")
    base = endpoint.rsplit("/scoreboard", 1)[0]
    return f"{base}/summary?event={{}}"


def _nhl_summary_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Read power-play, empty-net, and shootout state from a live NHL summary."""

    summary = _mapping(payload)
    competition = _first_mapping(_mapping(summary.get("header")).get("competitions"))
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
    shootout = _shootout_summary(summary)
    if shootout is not None:
        details["shootout"] = shootout
    return details


def _soccer_summary_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Read goal, red-card, and penalty facts from an ESPN soccer summary."""

    summary = _mapping(payload)
    competition = _first_mapping(_mapping(summary.get("header")).get("competitions"))
    source = _mapping(summary.get("situation")) or _mapping(competition.get("situation"))
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    details = display_situation("soccer", competition, home_abbr=home_abbr, away_abbr=away_abbr)
    goals: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for play in _summary_plays(summary):
        text = " ".join(
            str(value or "")
            for value in (
                play.get("type"), play.get("text"), play.get("shortText"), play.get("description")
            )
        ).lower()
        if "goal" not in text and "red" not in text:
            continue
        team = _summary_team_abbr(play, competition, home_abbr, away_abbr)
        event = soccer_event(
            is_home=team == home_abbr,
            player=_summary_player(play),
            minute=_summary_clock(play),
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
    shootout = _shootout_summary(summary)
    if shootout is not None:
        details["shootout"] = shootout
    if source.get("possession"):
        details["possession"] = _summary_team_abbr(source, competition, home_abbr, away_abbr)
    return details


def _summary_plays(summary: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return event-like summary records without depending on one ESPN shape."""

    records: list[Mapping[str, Any]] = []
    for key in ("scoringPlays", "plays", "events"):
        records.extend(_mapping(value) for value in _sequence(summary.get(key)))
    return tuple(record for record in records if record)


def _summary_scoring_details(payload: Any, item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize ESPN scoring plays for score-alert detail rendering."""

    summary = _mapping(payload)
    header = _mapping(summary.get("header"))
    competition = _first_mapping(header.get("competitions"))
    home_abbr = str(item.get("home_abbr") or "")
    away_abbr = str(item.get("away_abbr") or "")
    raw_scoring = _sequence(summary.get("scoringPlays"))
    records = raw_scoring or _summary_plays(summary)
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
        team = _summary_team_abbr(play, competition, home_abbr, away_abbr)
        if not team:
            continue
        athlete = _summary_player(play)
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


def _summary_team_abbr(
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


def _summary_player(play: Mapping[str, Any]) -> str:
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


def _summary_clock(play: Mapping[str, Any]) -> str:
    """Return one compact event time for soccer side-lane labels."""

    clock = _mapping(play.get("clock"))
    value = clock.get("displayValue") or clock.get("value") or play.get("time") or ""
    text = str(value).strip()
    return text if not text or text.endswith("'") else f"{text}'"


def _shootout_summary(summary: Mapping[str, Any]) -> dict[str, list[str]] | None:
    """Normalize penalty attempts when ESPN exposes them in the event summary."""

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


def _mlb_summary_details(payload: Any) -> dict[str, Any]:
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
