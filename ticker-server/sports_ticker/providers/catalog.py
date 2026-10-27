"""Expose ESPN league and team catalogs for controller clients."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
from typing import TypeVar, cast
from urllib.parse import urlparse

from sports_ticker.leagues import LEAGUES, league_for
from sports_ticker.markets import MARKET_OPTIONS

from .http import JsonHttpClient, OwnedClient, PooledJsonHttpClient
from .logo_overrides import corrected_logo


_ESPN_BASE = "https://site.web.api.espn.com/apis/site/v2/sports"
_ESPN_CORE_COLLEGE_BASE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
_COLLEGE_GROUPS = {"ncf_fbs": "80", "ncf_fcs": "81"}
_COLLEGE_GROUP_QUERY = "?lang=en&region=us&limit=1000"
_MODE_SYMBOLS = {
    "sports": "sportscourt.fill",
    "stock": "chart.line.uptrend.xyaxis",
    "music": "music.note",
    "flights": "airplane.arrival",
    "weather": "cloud.sun.fill",
    "clock": "clock.fill",
}

_T = TypeVar("_T")


class _CatalogCache:
    """Cache successful reads using their start time and allow concurrent loads."""

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._values: dict[Hashable, tuple[float, object]] = {}
        self._lock = Lock()

    def get(self, key: Hashable, load: Callable[[], _T]) -> _T:
        now = monotonic()
        with self._lock:
            cached = self._values.get(key)
            if cached is not None and now - cached[0] < self._ttl:
                return cast(_T, cached[1])
        value = load()
        with self._lock:
            self._values[key] = (now, value)
        return value


class _CatalogLease:
    def __init__(self, catalog):
        self._catalog = catalog

    def close(self):
        catalog, self._catalog = self._catalog, None
        if catalog is not None:
            catalog._release()


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
        self._client_owner = OwnedClient(client, PooledJsonHttpClient)
        self._client = self._client_owner.client
        self._lifecycle_lock = Lock()
        self._leases = 0
        self._closing = False
        self._timeout = float(timeout)
        self._cache = _CatalogCache(float(cache_seconds))

    def close(self) -> None:
        with self._lifecycle_lock:
            self._closing = True
            ready = self._leases == 0
        if ready:
            self._client_owner.close()

    def lease(self):
        """Retain the client until a dependent background source stops."""
        with self._lifecycle_lock:
            if self._closing:
                raise RuntimeError("catalog is closed")
            self._leases += 1
        return _CatalogLease(self)

    def _release(self):
        with self._lifecycle_lock:
            self._leases -= 1
            ready = self._closing and self._leases == 0
        if ready:
            self._client_owner.close()

    def leagues(self) -> tuple[dict[str, object], ...]:
        """Return the configured sports leagues in a stable controller format."""

        conferences = self._college_conference_options()
        sports_list: list[dict[str, object]] = []
        for league in LEAGUES:
            sports_list.append(self._league_payload(league, conferences))
            sports_list.extend(
                self._conference_payload(league, conference)
                for conference in conferences.get(league.id, ())
            )
        sports = tuple(sports_list)
        markets = tuple(
            {
                "id": group.id,
                "label": group.label,
                "type": "stock",
                "enabled": True,
            }
            for group in MARKET_OPTIONS
        )
        return (*sports, *markets)

    def _league_payload(
        self,
        league,
        conferences: Mapping[str, tuple[dict[str, object], ...]],
    ) -> dict[str, object]:
        """Build one league catalog record with optional conference metadata."""

        payload: dict[str, object] = {
            "id": league.id,
            "label": league.label,
            "type": "sport",
            "enabled": True,
            "my_teams_enabled": league.my_teams_enabled,
        }
        if league.conference_filter_enabled:
            payload["conferences"] = list(conferences.get(league.id, ()))
        return payload

    @staticmethod
    def _conference_payload(
        league,
        conference: Mapping[str, object],
    ) -> dict[str, object]:
        """Build one conference as a normal league option for old controllers."""

        return {
            "id": conference["id"],
            "label": conference["label"],
            "type": "sport",
            "enabled": True,
            "my_teams_enabled": False,
            "conference_id": conference["conference_id"],
            "conference_parent": league.id,
        }

    def modes(self) -> tuple[dict[str, str], ...]:
        """Return the controller mode symbols in their stable display order."""

        return tuple({"id": identifier, "symbol": symbol} for identifier, symbol in _MODE_SYMBOLS.items())

    def teams(self, league: str) -> tuple[dict[str, str], ...]:
        """Return all teams for one configured ESPN league."""

        return tuple(
            {key: team[key] for key in ("id", "abbr", "logo")}
            for team in self._team_records(league)
        )

    def team_colors(self, league: str) -> dict[str, dict[str, str]]:
        """Return ESPN primary and alternate colors by team abbreviation."""

        return {
            team["abbr"]: {
                "color": team["color"],
                "alt_color": team["alt_color"],
            }
            for team in self._team_records(league)
        }

    def team_name_map(self, league: str) -> dict[str, str]:
        """Return canonical ESPN display names by team abbreviation."""

        return {
            team["name"]: team["abbr"]
            for team in self._team_records(league)
            if team.get("name")
        }

    def _team_records(self, league: str) -> tuple[dict[str, str], ...]:
        """Return cached team records with display colors."""

        identifier = str(league).strip().lower()
        definition = league_for(identifier)
        if not definition.my_teams_enabled:
            return ()
        path = self._paths.get(identifier)
        if not path:
            raise KeyError(identifier)
        return self._cache.get(("teams", identifier), lambda: self._load_team_records(identifier, path, definition))

    def _load_team_records(self, identifier, path, definition):
        if identifier in _COLLEGE_GROUPS:
            teams = self._college_teams(identifier, definition)
        else:
            payload = self._client.get_json(f"{_ESPN_BASE}/{path}/teams", timeout=self._timeout)
            teams = tuple(
                team
                for team in _teams(payload, identifier)
                if definition.allows_team(team["abbr"])
            )
        return teams

    def _college_teams(self, identifier: str, definition) -> tuple[dict[str, str], ...]:
        """Build one NCAA division from ESPN's authoritative group membership."""

        payload = self._college_team_payload()
        season = _college_season(payload)
        group = _COLLEGE_GROUPS[identifier]
        allowed_ids = self._college_team_ids(season, group)
        return tuple(
            team
            for team in _teams(payload, identifier, source_ids=allowed_ids)
            if definition.allows_team(team["abbr"])
        )

    def _college_conference_options(self) -> Mapping[str, tuple[dict[str, object], ...]]:
        """Return current FBS and FCS conferences from ESPN's season group catalog."""

        return self._cache.get(("conferences",), self._load_college_conferences)

    def _load_college_conferences(self) -> Mapping[str, tuple[dict[str, object], ...]]:
        season = _college_season(self._college_team_payload())
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="espn-conference-groups") as pool:
            child_futures = {
                identifier: pool.submit(self._college_child_group_ids, season, group)
                for identifier, group in _COLLEGE_GROUPS.items()
            }
            child_groups = {
                identifier: future.result()
                for identifier, future in child_futures.items()
            }

        group_futures = {}
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="espn-conference-catalog") as pool:
            for identifier, group_ids in child_groups.items():
                for group_id in group_ids:
                    group_futures[(identifier, group_id)] = pool.submit(
                        self._college_conference,
                        season,
                        identifier,
                        group_id,
                    )
            options: dict[str, tuple[dict[str, object], ...]] = {}
            for identifier in _COLLEGE_GROUPS:
                values = [
                    option
                    for (option_identifier, _group_id), future in group_futures.items()
                    if option_identifier == identifier
                    for option in (future.result(),)
                    if option is not None
                ]
                options[identifier] = tuple(sorted(values, key=lambda item: str(item["label"]).lower()))

        result: Mapping[str, tuple[dict[str, object], ...]] = {
            identifier: tuple(values)
            for identifier, values in options.items()
        }
        return result

    def _college_child_group_ids(self, season: int, group: str) -> tuple[str, ...]:
        """Read conference identifiers below one FBS or FCS division."""

        url = (
            f"{_ESPN_CORE_COLLEGE_BASE}/seasons/{season}/types/2/groups/{group}/children"
            f"{_COLLEGE_GROUP_QUERY}"
        )
        payload = self._client.get_json(url, timeout=self._timeout)
        root = payload if isinstance(payload, Mapping) else {}
        items = root.get("items")
        values = items if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else ()
        identifiers = {
            identifier
            for item in values
            if isinstance(item, Mapping)
            for identifier in (
                urlparse(str(item.get("$ref") or "")).path.rstrip("/").rpartition("/")[2],
            )
            if identifier
        }
        if not identifiers:
            raise ValueError(f"ESPN college group {group} did not include conferences")
        return tuple(sorted(identifiers))

    def _college_conference(
        self,
        season: int,
        division: str,
        group_id: str,
    ) -> dict[str, object] | None:
        """Read one ESPN conference name and stable group identifier."""

        url = f"{_ESPN_CORE_COLLEGE_BASE}/seasons/{season}/types/2/groups/{group_id}{_COLLEGE_GROUP_QUERY}"
        payload = self._client.get_json(url, timeout=self._timeout)
        if not isinstance(payload, Mapping) or payload.get("isConference") is False:
            return None
        label = str(
            payload.get("midsizeName")
            or payload.get("shortName")
            or payload.get("name")
            or ""
        ).strip()
        if not label:
            raise ValueError(f"ESPN college conference {group_id} omitted a name")
        return {
            "id": f"{division}:{group_id}",
            "label": label,
            "conference_id": group_id,
        }

    def _college_team_payload(self) -> object:
        """Fetch the full NCAA team catalog once for both divisions."""

        return self._cache.get(
            ("college_payload",),
            lambda: self._client.get_json(
                f"{_ESPN_BASE}/football/college-football/teams?limit=1000",
                timeout=self._timeout,
            ),
        )

    def _college_team_ids(self, season: int, group: str) -> frozenset[str]:
        """Read one NCAA division from ESPN's group endpoint."""

        return self._cache.get(("college_group", season, group), lambda: self._load_college_team_ids(season, group))

    def _load_college_team_ids(self, season: int, group: str) -> frozenset[str]:
        url = (
            f"{_ESPN_CORE_COLLEGE_BASE}/seasons/{season}/types/2/groups/{group}/teams"
            "?lang=en&region=us&limit=1000"
        )
        payload = self._client.get_json(url, timeout=self._timeout)
        team_ids = _source_team_ids(payload)
        return team_ids


def _teams(
    payload: object,
    league: str,
    *,
    source_ids: frozenset[str] | None = None,
) -> tuple[dict[str, str], ...]:
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
        source_id = str(team.get("id") or "").strip()
        if source_ids is not None and source_id not in source_ids:
            continue
        abbreviation = str(team.get("abbreviation") or "").strip().upper()
        if not abbreviation:
            continue
        values.append(
            {
                "id": f"{league}:{abbreviation}",
                "abbr": abbreviation,
                "name": str(
                    team.get("displayName")
                    or team.get("shortDisplayName")
                    or f"{team.get('location') or ''} {team.get('name') or ''}"
                ).strip(),
                "logo": corrected_logo(league, abbreviation, _logo(team)) or "",
                "color": _hex_color(team.get("color")),
                "alt_color": _hex_color(team.get("alternateColor")),
            }
        )
    return tuple(sorted({item["id"]: item for item in values}.values(), key=lambda item: item["abbr"]))


def _college_season(payload: object) -> int:
    """Read the active NCAA season from the complete ESPN team catalog."""

    root = payload if isinstance(payload, Mapping) else {}
    sports = root.get("sports")
    sport = sports[0] if isinstance(sports, Sequence) and not isinstance(sports, (str, bytes)) and sports else {}
    leagues = sport.get("leagues") if isinstance(sport, Mapping) else ()
    league = leagues[0] if isinstance(leagues, Sequence) and not isinstance(leagues, (str, bytes)) and leagues else {}
    season = league.get("season") if isinstance(league, Mapping) else {}
    try:
        year = int(season.get("year")) if isinstance(season, Mapping) else 0
    except (TypeError, ValueError):
        year = 0
    if year < 2000:
        raise ValueError("ESPN college team catalog did not include a valid season")
    return year


def _source_team_ids(payload: object) -> frozenset[str]:
    """Extract team identifiers from ESPN core group membership links."""

    root = payload if isinstance(payload, Mapping) else {}
    items = root.get("items")
    values = items if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else ()
    identifiers = set()
    for item in values:
        reference = str(item.get("$ref") or "") if isinstance(item, Mapping) else ""
        identifier = urlparse(reference).path.rstrip("/").rpartition("/")[2]
        if identifier:
            identifiers.add(identifier)
    if not identifiers:
        raise ValueError("ESPN college group did not include team identifiers")
    return frozenset(identifiers)


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


def _hex_color(value: object) -> str:
    """Return one valid six-digit ESPN team color without a hash."""

    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return ""
    try:
        int(text, 16)
    except ValueError:
        return ""
    return text.upper()


__all__ = ["EspnTeamCatalog"]
