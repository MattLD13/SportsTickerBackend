"""Native ESPN scoreboard provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
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
from .sports_display import SportsDisplayProjector
from .stale_cache import SettingsResultCache


_DETAIL_LEAGUES = frozenset(("mlb", "nhl"))


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
        self._summary_urls = {
            league: _summary_url(url)
            for league, url in urls.items()
            if league in _DETAIL_LEAGUES or league.startswith("soccer")
        }
        self.client = client or UrllibJsonHttpClient()
        self.timeout = float(timeout)
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._stale_cache = SettingsResultCache()
        self._display = SportsDisplayProjector()

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
                        item = self._display.project(_content_item(league, event), event)
                        items.append(item)
                    except (KeyError, TypeError, ValueError) as exc:
                        errors.append(f"{league} event: {exc}")
            except Exception as exc:
                failed_sources += 1
                errors.append(f"{league}: {exc}")

        items = self._enrich_live_items(items)
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
        details = (
            _mlb_summary_details(summary)
            if league == "mlb"
            else _nhl_summary_details(summary, item.data)
            if league == "nhl"
            else _soccer_summary_details(summary, item.data)
        )
        if not details:
            return item
        data = dict(item.data)
        situation = dict(_mapping(data.get("situation")))
        situation.update(details)
        data["situation"] = situation
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
    possession_key = possession.casefold()
    if possession_key in {"home", "home_team"}:
        result["possession"] = home_abbr
    elif possession_key in {"away", "away_team"}:
        result["possession"] = away_abbr
    elif possession and possession == str(_mapping(home.get("team")).get("id") or ""):
        result["possession"] = home_abbr
    elif possession and possession == str(_mapping(away.get("team")).get("id") or ""):
        result["possession"] = away_abbr
    return result


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
    details = _display_situation(competition, home_abbr=home_abbr, away_abbr=away_abbr)
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
    details = _display_situation(competition, home_abbr=home_abbr, away_abbr=away_abbr)
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
        event = {
            "is_home": team == home_abbr,
            "label": _summary_player(play),
            "minute": _summary_clock(play),
        }
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
        "last_pitch_type": abbreviation or full,
        "last_pitch_type_abbr": abbreviation,
        "last_pitch_type_full": full,
    }


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
