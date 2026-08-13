"""Expose ESPN league and team catalogs for controller clients."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from threading import Lock
from time import monotonic
from typing import Any

from sports_ticker.markets import MARKET_GROUPS

from .http import JsonHttpClient, UrllibJsonHttpClient


_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
_LEAGUE_LABELS = {
    "nfl": "NFL",
    "mlb": "MLB",
    "nhl": "NHL",
    "nba": "NBA",
    "ncf_fbs": "College Football",
    "ncf_fcs": "FCS Football",
    "march_madness": "Men's College Basketball",
    "soccer_epl": "Premier League",
    "soccer_fa_cup": "FA Cup",
    "soccer_champ": "EFL Championship",
    "soccer_champions_league": "Champions League",
    "soccer_mls": "MLS",
}
_MODE_SYMBOLS = {
    "sports": "sportscourt.fill",
    "stock": "chart.line.uptrend.xyaxis",
    "music": "music.note",
    "flights": "airplane.arrival",
    "weather": "cloud.sun.fill",
    "clock": "clock.fill",
}


class EspnTeamCatalog:
    """Cache complete ESPN team lists for the configured scoreboard leagues."""

    def __init__(
        self,
        scoreboard_paths: Mapping[str, str],
        client: JsonHttpClient | None = None,
        *,
        timeout: float = 10.0,
        cache_seconds: float = 21_600.0,
    ) -> None:
        self._paths = {
            str(league).strip().lower(): str(path).strip().strip("/")
            for league, path in scoreboard_paths.items()
            if str(league).strip() and str(path).strip()
        }
        self._client = client or UrllibJsonHttpClient()
        self._timeout = float(timeout)
        self._cache_seconds = float(cache_seconds)
        self._cache: dict[str, tuple[float, tuple[dict[str, str], ...]]] = {}
        self._lock = Lock()

    def leagues(self) -> tuple[dict[str, object], ...]:
        """Return the configured sports leagues in a stable controller format."""

        sports = tuple(
            {
                "id": league,
                "label": _LEAGUE_LABELS.get(league, league.replace("_", " ").title()),
                "type": "sport",
                "enabled": True,
            }
            for league in self._paths
        )
        markets = tuple(
            {
                "id": group.id,
                "label": group.label,
                "type": "stock",
                "enabled": True,
            }
            for group in MARKET_GROUPS
        )
        return (*sports, *markets)

    def modes(self) -> tuple[dict[str, str], ...]:
        """Return the controller mode symbols in their stable display order."""

        return tuple({"id": identifier, "symbol": symbol} for identifier, symbol in _MODE_SYMBOLS.items())

    def teams(self, league: str) -> tuple[dict[str, str], ...]:
        """Return all teams for one configured ESPN league."""

        identifier = str(league).strip().lower()
        path = self._paths.get(identifier)
        if not path:
            raise KeyError(identifier)
        now = monotonic()
        with self._lock:
            cached = self._cache.get(identifier)
            if cached is not None and now - cached[0] < self._cache_seconds:
                return cached[1]
        payload = self._client.get_json(f"{_ESPN_BASE}/{path}/teams", timeout=self._timeout)
        teams = _teams(payload, identifier)
        with self._lock:
            self._cache[identifier] = (now, teams)
        return teams


def _teams(payload: object, league: str) -> tuple[dict[str, str], ...]:
    root = payload if isinstance(payload, Mapping) else {}
    sports = root.get("sports")
    sport = sports[0] if isinstance(sports, Sequence) and not isinstance(sports, (str, bytes)) and sports else {}
    leagues = sport.get("leagues") if isinstance(sport, Mapping) else ()
    league_data = leagues[0] if isinstance(leagues, Sequence) and not isinstance(leagues, (str, bytes)) and leagues else {}
    records = league_data.get("teams") if isinstance(league_data, Mapping) else ()
    values: list[dict[str, str]] = []
    for record in records if isinstance(records, Sequence) and not isinstance(records, (str, bytes)) else ():
        team = record.get("team") if isinstance(record, Mapping) else None
        team = team if isinstance(team, Mapping) else {}
        abbreviation = str(team.get("abbreviation") or "").strip().upper()
        if not abbreviation:
            continue
        values.append(
            {
                "id": f"{league}:{abbreviation}",
                "abbr": abbreviation,
                "logo": _logo(team),
            }
        )
    return tuple(sorted({item["id"]: item for item in values}.values(), key=lambda item: item["abbr"]))


def _logo(team: Mapping[str, object]) -> str:
    """Return the standard ESPN logo from one team catalog record."""

    direct = str(team.get("logo") or "").strip()
    if direct:
        return direct
    logos = team.get("logos")
    if not isinstance(logos, Sequence) or isinstance(logos, (str, bytes)):
        return ""
    for value in logos:
        logo = value if isinstance(value, Mapping) else {}
        relations = logo.get("rel")
        relation_values = relations if isinstance(relations, Sequence) and not isinstance(relations, (str, bytes)) else ()
        if "default" in relation_values:
            return str(logo.get("href") or "").strip()
    for value in logos:
        logo = value if isinstance(value, Mapping) else {}
        href = str(logo.get("href") or "").strip()
        if href:
            return href
    return ""


__all__ = ["EspnTeamCatalog"]
