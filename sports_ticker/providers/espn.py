"""Native ESPN scoreboard provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from math import isfinite
import re
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import ContentItem, DisplaySettings

from .contracts import ProviderHealth, ProviderResult
from .http import JsonHttpClient, UrllibJsonHttpClient
from .logo_overrides import corrected_logo
from .stale_cache import SettingsResultCache


class EspnScoreboardProvider:
    """Fetch explicitly enabled ESPN scoreboard leagues into canonical content."""

    def __init__(
        self,
        scoreboard_urls: Mapping[str, str],
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
    ) -> None:
        if not isinstance(scoreboard_urls, Mapping):
            raise TypeError("scoreboard_urls must be a mapping")
        urls = {
            str(league).strip().lower(): str(url).strip()
            for league, url in scoreboard_urls.items()
            if str(league).strip() and str(url).strip()
        }
        self.scoreboard_urls = MappingProxyType(urls)
        self.client = client or UrllibJsonHttpClient()
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._stale_cache = SettingsResultCache()

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch current scoreboard events from each configured active league."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")

        items: list[ContentItem] = []
        errors: list[str] = []
        active_sources = 0
        failed_sources = 0
        for league, url in self.scoreboard_urls.items():
            if not settings.active_sports.get(league, True):
                continue
            active_sources += 1
            try:
                payload = self.client.get_json(url, timeout=self.timeout)
                for event in _events(payload):
                    if not _is_current_event(event, timezone_name=settings.timezone):
                        continue
                    try:
                        items.append(_content_item(league, event))
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append(f"{league} event: {exc}")
            except Exception as exc:
                failed_sources += 1
                errors.append(f"{league}: {exc}")

        health = ProviderHealth(
            healthy=not errors,
            provider="espn",
            error="; ".join(errors) if errors else None,
        )
        result = ProviderResult(
            content=tuple(sorted(items, key=_content_sort_key)),
            observed_at=datetime.now(timezone.utc),
            health=health,
        )
        if health.healthy:
            self._stale_cache.set(settings, result)
            return result
        if active_sources and failed_sources == active_sources:
            return self._stale_result(settings, health.error or "all sources failed")
        return result

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


def _content_sort_key(item: ContentItem) -> tuple[int, str, str, str, str]:
    """Keep the original scoreboard order after all leagues merge."""

    data = item.data
    state = _text(data.get("state"), "pre").lower()
    status = _text(data.get("status")).upper()
    priority = 3 if state == "post" or "FINAL" in status else 2
    return (
        priority,
        _text(data.get("startTimeUTC"), "9999"),
        _text(data.get("sport")),
        _text(data.get("home_abbr")),
        _text(data.get("away_abbr")),
    )


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
    clock = _text(
        status_obj.get("displayClock")
        or status_obj.get("clock")
        or _mapping(competition.get("situation")).get("clock")
    ) or None

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
        "situation": _display_situation(
            competition,
            home_abbr=home_team["abbreviation"],
            away_abbr=away_team["abbreviation"],
        ),
    }
    if clock:
        display_data["situation"]["clock"] = clock
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


def _display_situation(
    competition: Mapping[str, Any],
    *,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Keep only live facts that a 384 by 32 renderer can draw."""

    source = _mapping(competition.get("situation"))
    allowed = (
        "balls", "strikes", "outs", "onFirst", "onSecond", "onThird",
        "down", "distance", "yardLine", "downDistanceText",
        "shortDownDistanceText", "isRedZone", "powerPlay", "emptyNet",
        "period", "periodName", "batterName", "pitcherName",
        "batterAvg", "pitcherPitches", "lastPitchSpeed", "lastPitchType",
    )
    result = {key: source[key] for key in allowed if key in source}
    possession = str(source.get("possession") or "").strip()
    competitors = _competitors(competition.get("competitors"))
    home = _find_side(competitors, "home")
    away = _find_side(competitors, "away")
    if possession and possession == str(_mapping(home.get("team")).get("id") or ""):
        result["possession"] = home_abbr
    elif possession and possession == str(_mapping(away.get("team")).get("id") or ""):
        result["possession"] = away_abbr
    return result


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
