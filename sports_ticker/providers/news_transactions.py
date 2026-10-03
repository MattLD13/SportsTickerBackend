"""Verify NHL trade alerts against the league trade tracker."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from threading import Lock
from time import monotonic
from typing import Protocol

from .http import TextHttpClient, UrllibTextHttpClient


_TRACKER_ROW = re.compile(
    r"\*\*(?P<month>[A-Z]+)\s+(?P<day>\d{1,2}):\*\*\s*"
    r"(?P<details>.*?)\s*\|\s*\*\*\[(?P<headline>[^\]]+)\]"
    r"\((?P<url>https?://[^)]+)\)\*\*",
    re.DOTALL,
)
_MONTHS = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}


@dataclass(frozen=True, slots=True)
class ConfirmedTrade:
    """Describe one current trade listed by the official NHL tracker."""

    from_abbr: str
    to_abbr: str
    occurred_at: date
    source_url: str
    headline: str
    details: str


class TradeConfirmationSource(Protocol):
    """Confirm one player trade from a trusted league source."""

    def confirm_trade(
        self,
        league: str,
        athlete_names: Sequence[str],
        team_abbreviations: Sequence[str],
        *,
        now: datetime,
    ) -> ConfirmedTrade | None:
        """Return a recent confirmed trade that matches the article facts."""


class NhlTradeTrackerSource:
    """Read completed NHL trades and reject older article references."""

    def __init__(
        self,
        team_name_map: Callable[[str], Mapping[str, str]],
        client: TextHttpClient | None = None,
        *,
        cache_seconds: float = 300.0,
        clock: Callable[[], float] = monotonic,
        max_age_days: int = 2,
    ) -> None:
        self._team_name_map = team_name_map
        self._client = client or UrllibTextHttpClient()
        self._cache_seconds = max(1.0, float(cache_seconds))
        self._clock = clock
        self._max_age_days = max(0, int(max_age_days))
        self._cache: tuple[float, tuple[ConfirmedTrade, ...]] | None = None
        self._lock = Lock()

    def confirm_trade(
        self,
        league: str,
        athlete_names: Sequence[str],
        team_abbreviations: Sequence[str],
        *,
        now: datetime,
    ) -> ConfirmedTrade | None:
        """Confirm one recent NHL trade against tracked player and team facts."""

        if str(league).strip().lower() != "nhl":
            return None
        observed_at = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
        athlete_values = tuple(name for name in (_normalize(value) for value in athlete_names) if name)
        article_teams = {str(value).strip().upper() for value in team_abbreviations if str(value).strip()}
        if not athlete_values or not article_teams:
            return None
        for trade in self._records(observed_at):
            age_days = (observed_at.date() - trade.occurred_at).days
            if age_days < 0 or age_days > self._max_age_days:
                continue
            if not article_teams.intersection((trade.from_abbr, trade.to_abbr)):
                continue
            details = _normalize(trade.details)
            if any(_contains_name(details, name) for name in athlete_values):
                return trade
        return None

    def _records(self, now: datetime) -> tuple[ConfirmedTrade, ...]:
        timestamp = self._clock()
        with self._lock:
            cached = self._cache
            if cached is not None and timestamp - cached[0] < self._cache_seconds:
                return cached[1]
            try:
                html = self._client.get_text(_tracker_url(now), timeout=15.0)
                records = _parse_tracker(html, now, self._team_name_map("nhl"))
            except Exception:
                records = ()
            self._cache = (timestamp, records)
            return records


def _tracker_url(now: datetime) -> str:
    """Build the active NHL season trade tracker URL."""

    season_start = now.year if now.month >= 7 else now.year - 1
    season_end = str(season_start + 1)[-2:]
    return f"https://www.nhl.com/news/topic/trade-coverage/{season_start}-{season_end}-nhl-trades"


def _parse_tracker(
    html: str,
    now: datetime,
    team_name_map: Mapping[str, str],
) -> tuple[ConfirmedTrade, ...]:
    """Parse dated deal rows from the NHL trade tracker page."""

    season_start = now.year if now.month >= 7 else now.year - 1
    aliases = sorted(
        (
            (_normalize(name), str(abbreviation).strip().upper())
            for name, abbreviation in team_name_map.items()
            if _normalize(name) and str(abbreviation).strip()
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    records: list[ConfirmedTrade] = []
    for match in _TRACKER_ROW.finditer(html):
        month = _MONTHS.get(match.group("month"))
        if month is None:
            continue
        year = season_start if month >= 7 else season_start + 1
        try:
            occurred_at = date(year, month, int(match.group("day")))
        except ValueError:
            continue
        details = match.group("details").strip()
        normalized_details = _normalize(details)
        acquire_at = normalized_details.find(" acquire ")
        from_at = normalized_details.find(" from ", acquire_at + 1)
        if acquire_at < 0 or from_at < 0:
            continue
        spans = []
        for name, abbreviation in aliases:
            start = normalized_details.find(name)
            if start < 0:
                continue
            end = start + len(name)
            if any(existing[2] == abbreviation for existing in spans):
                continue
            spans.append((start, end, abbreviation))
        destinations = [span for span in spans if span[1] <= acquire_at]
        origins = [span for span in spans if span[0] >= from_at]
        if not destinations or not origins:
            continue
        to_abbr = max(destinations, key=lambda span: span[1])[2]
        from_abbr = min(origins, key=lambda span: span[0])[2]
        if from_abbr == to_abbr:
            continue
        records.append(
            ConfirmedTrade(
                from_abbr=from_abbr,
                to_abbr=to_abbr,
                occurred_at=occurred_at,
                source_url=match.group("url").strip(),
                headline=match.group("headline").strip(),
                details=details,
            )
        )
    return tuple(records)


def _normalize(value: object) -> str:
    """Normalize names for exact tracker matching."""

    folded = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(character for character in folded if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).split())


def _contains_name(text: str, name: str) -> bool:
    """Match a normalized name at word boundaries."""

    return f" {name} " in f" {text} "


__all__ = ["ConfirmedTrade", "NhlTradeTrackerSource", "TradeConfirmationSource"]
