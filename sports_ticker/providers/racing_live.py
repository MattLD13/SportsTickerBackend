"""Poll official live timing sources for F1 and IndyCar V2 content."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import DisplaySettings

from .http import JsonHttpClient, TextHttpClient, UrllibJsonHttpClient, UrllibTextHttpClient


_F1_ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"
_INDYCAR_ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard"
_NASCAR_ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/racing/nascar-premier/scoreboard"
_NASCAR_LIVE_URL = "https://cf.nascar.com/live/feeds/live-feed.json"
_OPENF1_BASE = "https://api.openf1.org/v1"
_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
_INDYCAR_BLOB_BASE = "https://indycar.blob.core.windows.net/racecontrol"
_IMS_LAT = 39.7950
_IMS_LON = -86.2340

_F1_SESSION_ORDER = (
    ("FirstPractice", "Practice 1", True, 90),
    ("SecondPractice", "Practice 2", True, 90),
    ("ThirdPractice", "Practice 3", True, 60),
    ("SprintQualifying", "Sprint Qualifying", False, 60),
    ("Sprint", "Sprint", False, 60),
    ("Qualifying", "Qualifying", False, 70),
    ("Race", "Race", False, 130),
)
_F1_ESPN_ABBREVIATIONS = {
    "FP1": "FirstPractice",
    "FP2": "SecondPractice",
    "FP3": "ThirdPractice",
    "SS": "SprintQualifying",
    "SR": "Sprint",
    "QUAL": "Qualifying",
    "RACE": "Race",
}
_F1_TEAM_SLUGS = {
    "mclaren": "mclaren",
    "mercedes": "mercedes",
    "ferrari": "ferrari",
    "red bull": "redbullracing",
    "racing bulls": "racingbulls",
    "aston martin": "astonmartin",
    "alpine": "alpine",
    "williams": "williams",
    "haas": "haasf1team",
    "audi": "audi",
    "sauber": "audi",
    "cadillac": "cadillac",
}
_F1_TEAM_COLORS = {
    "mclaren": "#FF8000",
    "mercedes": "#27F4D2",
    "ferrari": "#E8002D",
    "red bull": "#3671C6",
    "racing bulls": "#6692FF",
    "aston martin": "#229971",
    "alpine": "#FF87BC",
    "williams": "#64C4FF",
    "haas": "#B6BABD",
    "sauber": "#BB0000",
    "audi": "#BB0000",
    "cadillac": "#9CA3AF",
}
_INDYCAR_LIVERIES = {
    "ganassi": ("#E31937", "#002D62"),
    "andretti": ("#112A5A", "#FFFFFF"),
    "penske": ("#00327A", "#FFD700"),
    "mclaren": ("#FF8000", "#000000"),
    "rahal": ("#7B0D1E", "#C5A028"),
    "coyne": ("#0033A0", "#FFFFFF"),
    "juncos": ("#141414", "#FF0000"),
    "shank": ("#1E3A5F", "#C5A028"),
    "foyt": ("#003087", "#FFD700"),
    "prema": ("#E31937", "#FFFFFF"),
    "carpenter": ("#012169", "#FFFFFF"),
    "abel": ("#CC0000", "#FFFFFF"),
}
_INDYCAR_DAY_RE = re.compile(r"<h3[^>]*>[A-Za-z]+,\s*([A-Za-z]+)\s*(\d{1,2})</h3>")
_INDYCAR_ENTRY_RE = re.compile(
    r'<div class="schedule-entry">.*?<div class="schedule-time">([^<]+)</div>'
    r'.*?<div class="schedule-description">([^<]+)</div>',
    re.DOTALL,
)
_INDYCAR_SLUG_MAP = {
    "alabama": "Barber",
    "barber": "Barber",
    "illinois": "WWTR",
    "wwtr": "WWTR",
    "gateway": "WWTR",
    "monterey": "Laguna-Seca",
    "laguna": "Laguna-Seca",
    "ontario": "Markham",
    "markham": "Markham",
    "st. petersburg": "St-Petersburg",
    "phoenix": "Phoenix",
    "arlington": "Arlington",
    "long beach": "Long-Beach",
    "indianapolis 500": "Indianapolis-500",
    "indy 500": "Indianapolis-500",
    "indianapolis (road course)": "Indianapolis",
    "indianapolis": "Indianapolis",
    "detroit": "Detroit",
    "road america": "Road-America",
    "mid-ohio": "Mid-Ohio",
    "nashville": "Nashville",
    "portland": "Portland",
    "washington": "Washington-DC",
    "milwaukee race 1": "Milwaukee-Race1",
    "milwaukee race 2": "Milwaukee-Race2",
}


class LiveRacingSource:
    """Fetch F1 and IndyCar sessions from their authoritative timing feeds."""

    def __init__(
        self,
        client: JsonHttpClient | None = None,
        text_client: TextHttpClient | None = None,
        *,
        timeout: float = 10.0,
        clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client or UrllibJsonHttpClient()
        self._text_client = text_client or UrllibTextHttpClient()
        self._timeout = float(timeout)
        if self._timeout <= 0:
            raise ValueError("timeout must be positive")
        self._clock = clock
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._f1_schedule: tuple[float, list[dict[str, Any]]] = (0.0, [])
        self._f1_games: dict[str, dict[str, Any]] = {}
        self._f1_results: tuple[float, list[Mapping[str, Any]]] = (0.0, [])
        self._indy_schedule: tuple[float, list[dict[str, Any]]] = (0.0, [])
        self._indy_games: dict[str, dict[str, Any]] = {}
        self._indy_timing: tuple[float, dict[str, Any] | None] = (0.0, None)
        self._indy_drivers: tuple[float, dict[str, Mapping[str, Any]]] = (0.0, {})
        self._indy_event_pages: dict[str, tuple[float, dict[str, tuple[datetime, int, str, bool]]]] = {}
        self._nascar_schedule: tuple[float, list[dict[str, Any]]] = (0.0, [])
        self._nascar_games: dict[str, dict[str, Any]] = {}
        self._nascar_timing: tuple[float, dict[str, Any] | None] = (0.0, None)

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        """Return current F1, IndyCar, and NASCAR content for one ticker settings view."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")
        records: list[dict[str, Any]] = []
        failures: list[str] = []
        if settings.active_sports.get("f1", True):
            try:
                records.extend(self._fetch_f1(settings))
            except Exception as error:
                failures.append(f"f1: {error}")
                records.extend(self._f1_games.values())
        if settings.active_sports.get("indycar", True):
            try:
                records.extend(self._fetch_indycar(settings))
            except Exception as error:
                failures.append(f"indycar: {error}")
                records.extend(self._indy_games.values())
        if settings.active_sports.get("nascar", False):
            try:
                records.extend(self._fetch_nascar(settings))
            except Exception as error:
                failures.append(f"nascar: {error}")
                records.extend(self._nascar_games.values())
        result: dict[str, object] = {"content": records}
        if failures:
            result["health"] = {
                "provider": "racing",
                "healthy": False,
                "error": "; ".join(failures),
            }
        return result

    def _fetch_f1(self, settings: DisplaySettings) -> list[dict[str, Any]]:
        now = self._now().astimezone(timezone.utc)
        races = self._fetch_f1_schedule()
        sessions = _f1_relevant_sessions(races, now, settings.timezone)
        if not sessions:
            return list(self._f1_games.values()) if not races else []
        games: list[dict[str, Any]] = []
        active_ids: set[str] = set()
        for race, key, name, practice, start, end, state in sessions:
            identifier = f"f1_{race['round']}_{key.lower()}"
            active_ids.add(identifier)
            game = self._build_f1_game(
                race, key, name, practice, start, end, state, now, settings.timezone
            )
            if game is not None:
                self._f1_games[identifier] = game
                games.append(game)
        for identifier in tuple(self._f1_games):
            if identifier not in active_ids:
                del self._f1_games[identifier]
        return games

    def _fetch_f1_schedule(self) -> list[dict[str, Any]]:
        now = self._clock()
        cached_at, cached = self._f1_schedule
        if cached and now - cached_at < 3600:
            return cached
        payload = self._client.get_json(_F1_ESPN_URL, timeout=self._timeout)
        events = _sequence(_mapping(payload).get("events"))
        races = [_f1_event_to_race(event) for event in events if _mapping(event)]
        races = [race for race in races if race.get("sessions")]
        self._f1_schedule = (now, races)
        return races

    def _build_f1_game(
        self,
        race: Mapping[str, Any],
        session_key: str,
        session_name: str,
        practice: bool,
        start: datetime,
        end: datetime,
        state: str,
        now: datetime,
        timezone_name: str,
    ) -> dict[str, Any] | None:
        identifier = f"f1_{race['round']}_{session_key.lower()}"
        drivers: list[dict[str, Any]] = []
        flag = "WHITE" if state == "pre" else "CHECKERED" if state == "post" else "GREEN"
        ended = False
        if state in {"in", "post"}:
            drivers, ended, live_flag, lap, total_laps = self._fetch_openf1(start, state)
            if state == "in" and ended and not practice:
                state = "post"
                flag = "CHECKERED"
            elif live_flag:
                flag = live_flag
        else:
            lap, total_laps = 0, 0
        if not drivers and state == "post":
            drivers = list(self._f1_games.get(identifier, {}).get("f1", {}).get("drivers", ()))
        if not drivers and state == "post" and session_key == "Race":
            drivers = self._f1_result_drivers()

        if state == "post":
            status = "FINAL"
        elif state == "in":
            status = f"Lap {lap}/{total_laps}" if lap and total_laps else flag
        else:
            status = _format_local_time(start, timezone_name)
        event_name = _f1_short_event(str(race.get("race_name") or "Formula 1"))
        track = str(race.get("track") or race.get("location") or event_name)
        return {
            "id": identifier,
            "type": "racing",
            "sport": "f1",
            "state": state,
            "status": status,
            "is_shown": True,
            "startTimeUTC": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "away_abbr": event_name,
            "home_abbr": session_name,
            "away_score": "",
            "home_score": "",
            "f1": {
                "event_name": event_name,
                "short_name": event_name,
                "track_name": track,
                "session_type": session_name,
                "session_name": session_name,
                "lap": lap,
                "total_laps": total_laps,
                "laps_remaining": max(0, total_laps - lap),
                "time_to_go": _format_duration(
                    (start - now).total_seconds()
                    if state == "pre"
                    else (end - now).total_seconds()
                    if state == "in" and practice
                    else 0
                ),
                "caution": flag in {"YELLOW", "SAFETY CAR", "VSC", "RED FLAG"},
                "flag": flag,
                "drivers": drivers,
                "weather": {},
            },
        }

    def _fetch_openf1(
        self,
        start: datetime,
        state: str,
    ) -> tuple[list[dict[str, Any]], bool, str, int, int]:
        session = self._openf1_session(start, state)
        if session is None:
            return [], False, "", 0, 0
        session_key = session.get("session_key")
        if session_key is None:
            return [], False, "", 0, 0
        ended = _session_ended(session, self._now().astimezone(timezone.utc))
        drivers_raw = _sequence(
            self._client.get_json(
                f"{_OPENF1_BASE}/drivers?session_key={session_key}",
                timeout=self._timeout,
            )
        )
        driver_info = {
            str(item.get("driver_number")): item
            for item in drivers_raw
            if _mapping(item).get("driver_number") is not None
        }
        positions_raw = _sequence(
            self._client.get_json(
                f"{_OPENF1_BASE}/position?session_key={session_key}",
                timeout=self._timeout,
            )
        )
        latest_positions: dict[str, Mapping[str, Any]] = {}
        for position in positions_raw:
            key = str(position.get("driver_number") or "")
            if key and (
                key not in latest_positions
                or str(position.get("date", "")) > str(latest_positions[key].get("date", ""))
            ):
                latest_positions[key] = position
        session_name = str(session.get("session_name") or "").lower()
        qualifying = "qual" in session_name
        best_laps: dict[str, float] = {}
        latest_laps: dict[str, int] = {}
        lap_rows = _sequence(
            self._client.get_json(
                f"{_OPENF1_BASE}/laps?session_key={session_key}",
                timeout=self._timeout,
            )
        )
        for lap in lap_rows:
            key = str(lap.get("driver_number") or "")
            duration = _number(lap.get("lap_duration"))
            if duration and (key not in best_laps or duration < best_laps[key]):
                best_laps[key] = duration
            lap_number = _integer(lap.get("lap_number"))
            if key and lap_number > latest_laps.get(key, 0):
                latest_laps[key] = lap_number
        intervals: dict[str, Mapping[str, Any]] = {}
        if not qualifying:
            interval_rows = _sequence(
                self._client.get_json(
                    f"{_OPENF1_BASE}/intervals?session_key={session_key}",
                    timeout=self._timeout,
                )
            )
            for interval in interval_rows:
                key = str(interval.get("driver_number") or "")
                if key and (
                    key not in intervals
                    or str(interval.get("date", "")) > str(intervals[key].get("date", ""))
                ):
                    intervals[key] = interval
        positions = sorted(
            latest_positions.values(),
            key=lambda value: _integer(value.get("position"), 999),
        )
        leader_lap = (
            best_laps.get(str(positions[0].get("driver_number")))
            if positions and qualifying
            else None
        )
        previous_gap = 0.0
        computed_intervals: dict[str, float] = {}
        for position in positions:
            key = str(position.get("driver_number") or "")
            raw_gap = _number(intervals.get(key, {}).get("gap_to_leader"))
            if not qualifying and raw_gap is not None:
                computed_intervals[key] = raw_gap - previous_gap
                previous_gap = raw_gap
        drivers: list[dict[str, Any]] = []
        for position in positions:
            key = str(position.get("driver_number") or "")
            info = driver_info.get(key, {})
            pos = _integer(position.get("position"), 999)
            team = str(info.get("team_name") or "")
            gap = ""
            if qualifying:
                best = best_laps.get(key)
                if best:
                    gap = (
                        _format_qualifying_time(best)
                        if pos == 1 or leader_lap is None
                        else f"+{best - leader_lap:.3f}"
                    )
            elif pos == 1:
                gap = "Leader"
            else:
                interval = intervals.get(key, {}).get("interval_to_position_ahead")
                interval_value = _number(interval)
                if interval_value is None:
                    interval_value = computed_intervals.get(key)
                if interval_value is not None:
                    gap = f"+{abs(interval_value):.3f}s"
            drivers.append({
                "pos": pos,
                "name": str(info.get("full_name") or f"Driver {key}").title(),
                "abbr": str(info.get("name_acronym") or key)[:3].upper(),
                "car": key,
                "team": team,
                "team_logo": "",
                "car_illustration": _f1_car_url(team),
                "livery_primary": _f1_team_color(team),
                "livery_secondary": "#111111",
                "gap": gap,
                "speed": "",
                "status": "Active",
                "on_track": True,
            })
        flag = self._openf1_flag(session_key) if state == "in" else ""
        lap = max(latest_laps.values(), default=0)
        total_laps = _integer(session.get("total_laps"))
        return drivers, ended, flag, lap, total_laps

    def _openf1_session(self, start: datetime, state: str) -> Mapping[str, Any] | None:
        if state == "in":
            values = _sequence(
                self._client.get_json(
                    f"{_OPENF1_BASE}/sessions?session_key=latest",
                    timeout=self._timeout,
                )
            )
        else:
            begin = (start - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = (start + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            query = urlencode({"date_start>": begin, "date_start<": end})
            values = _sequence(
                self._client.get_json(
                    f"{_OPENF1_BASE}/sessions?{query}",
                    timeout=self._timeout,
                )
            )
        if not values:
            return None
        return min(
            values,
            key=lambda value: abs(
                ((_parse_datetime(value.get("date_start")) or start) - start).total_seconds()
            ),
        )

    def _openf1_flag(self, session_key: object) -> str:
        try:
            rows = _sequence(
                self._client.get_json(
                    f"{_OPENF1_BASE}/race_control?session_key={session_key}",
                    timeout=self._timeout,
                )
            )
        except Exception:
            return "GREEN"
        for row in reversed(rows):
            message = str(row.get("message") or row.get("flag") or "").upper()
            flag = _normalize_racing_flag(message)
            if flag != "GREEN":
                return flag
        return "GREEN"

    def _f1_result_drivers(self) -> list[dict[str, Any]]:
        now = self._clock()
        cached_at, cached = self._f1_results
        if not cached or now - cached_at >= 1800:
            try:
                payload = self._client.get_json(
                    f"{_JOLPICA_BASE}/current/last/results.json",
                    timeout=self._timeout,
                )
                races = _sequence(_mapping(_mapping(payload).get("MRData")).get("RaceTable"))
                cached = [_mapping(value) for value in _sequence(races[0].get("Results"))] if races else []
                self._f1_results = (now, cached)
            except Exception:
                cached = cached or []
        drivers: list[dict[str, Any]] = []
        for result in cached:
            driver = _mapping(result.get("Driver"))
            constructor = _mapping(result.get("Constructor"))
            pos = _integer(result.get("position"), 999)
            value = _mapping(result.get("Time")).get("time") or result.get("status")
            drivers.append({
                "pos": pos,
                "name": f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip().title() or "Driver",
                "abbr": str(driver.get("code") or "")[:3].upper(),
                "car": str(driver.get("permanentNumber") or result.get("number") or ""),
                "team": str(constructor.get("name") or ""),
                "team_logo": "",
                "car_illustration": _f1_car_url(constructor.get("name")),
                "livery_primary": _f1_team_color(constructor.get("name")),
                "livery_secondary": "#111111",
                "gap": "Leader" if pos == 1 else str(value or "")[:12],
                "speed": "",
                "status": "Active",
                "on_track": True,
            })
        return sorted(drivers, key=lambda value: value["pos"])

    def _fetch_indycar(self, settings: DisplaySettings) -> list[dict[str, Any]]:
        now = self._now().astimezone(timezone.utc)
        races = self._fetch_indycar_schedule()
        sessions = _indycar_relevant_sessions(races, now, settings.timezone)
        if not sessions:
            if not races:
                timing_payload = self._fetch_indycar_timing()
                timing = _mapping(_mapping(timing_payload).get("timing_results"))
                heartbeat = _mapping(timing.get("heartbeat"))
                if heartbeat:
                    series = str(heartbeat.get("Series") or "").strip().upper()
                    session_status = str(heartbeat.get("SessionStatus") or "").upper()
                    flag = _normalize_racing_flag(heartbeat.get("currentFlag") or heartbeat.get("SessionStatus"))
                    is_live = session_status in {"LIVE", "RUNNING", "OPEN", "GREEN", "YELLOW", "RED", "CHECKERED"} or flag in {"GREEN", "YELLOW", "RED", "CHECKERED", "SAFETY CAR", "VSC"}
                    if is_live and (not series or series == "I"):
                        session_name = str(heartbeat.get("SessionName") or heartbeat.get("EventSessionLabel") or "Race").strip()
                        event_name = str(heartbeat.get("eventName") or "IndyCar").strip()
                        track_name = str(heartbeat.get("trackName") or "").strip()
                        start = _parse_datetime(_first_text(heartbeat, "startTimeUTC", "StartTimeUTC")) or now
                        race = {
                            "round": str(heartbeat.get("EventID") or heartbeat.get("EventSessionID") or "event"),
                            "race_name": event_name,
                            "track": track_name,
                            "location": track_name,
                            "sessions": {
                                session_name: (start, 180, session_name, "practice" in session_name.lower())
                            },
                        }
                        game = self._build_indycar_game(
                            race, session_name, session_name, "practice" in session_name.lower(), start, start + timedelta(minutes=180), "in", now, settings.timezone
                        )
                        if game is not None:
                            return [game]
            return list(self._indy_games.values()) if not races else []
        games: list[dict[str, Any]] = []
        active_ids: set[str] = set()
        for race, key, name, practice, start, end, state in sessions:
            identifier = f"indycar_{race['round']}_{key.lower()}"
            active_ids.add(identifier)
            game = self._build_indycar_game(
                race, key, name, practice, start, end, state, now, settings.timezone
            )
            if game is not None:
                self._indy_games[identifier] = game
                games.append(game)
        for identifier in tuple(self._indy_games):
            if identifier not in active_ids:
                del self._indy_games[identifier]
        return games

    def _fetch_indycar_schedule(self) -> list[dict[str, Any]]:
        now_dt = self._now().astimezone(timezone.utc)
        now_ts = self._clock()
        cached_at, cached = self._indy_schedule
        if cached and now_ts - cached_at < 3600:
            return cached
        try:
            payload = self._client.get_json(
                f"{_INDYCAR_ESPN_URL}?dates={now_dt.year}",
                timeout=self._timeout,
            )
            events = _sequence(_mapping(payload).get("events"))
            races = [_indycar_event_to_race(event) for event in events if _mapping(event)]
        except Exception:
            return []
        for race in races:
            race_sessions = _mapping(race.get("sessions"))
            race_start = next((val[0] for val in race_sessions.values()), None)
            if race_start is None:
                continue
            if abs((race_start - now_dt).total_seconds()) <= 4 * 86400:
                slug = _indycar_event_slug(race["race_name"])
                if slug:
                    weekend_sessions = self._fetch_indycar_weekend_sessions(race_start.year, slug)
                    if weekend_sessions:
                        race["sessions"] = weekend_sessions
        races = [race for race in races if race.get("sessions")]
        self._indy_schedule = (now_ts, races)
        return races

    def _fetch_indycar_weekend_sessions(
        self,
        year: int,
        slug: str,
    ) -> dict[str, tuple[datetime, int, str, bool]]:
        now_ts = self._clock()
        key = f"{year}/{slug}"
        cached = self._indy_event_pages.get(key)
        if cached and now_ts - cached[0] < 1800:
            return cached[1]
        try:
            page = self._text_client.get_text(
                f"https://www.indycar.com/Schedule/{year}/{slug}",
                timeout=self._timeout,
            )
            sessions = _parse_indycar_weekend_html(page, year)
            if sessions:
                self._indy_event_pages[key] = (now_ts, sessions)
                return sessions
        except Exception:
            pass
        return {}

    def _build_indycar_game(
        self,
        race: Mapping[str, Any],
        session_key: str,
        session_name: str,
        practice: bool,
        start: datetime,
        end: datetime,
        state: str,
        now: datetime,
        timezone_name: str,
    ) -> dict[str, Any] | None:
        identifier = f"indycar_{race['round']}_{session_key.lower()}"
        event_name = str(race.get("race_name") or "IndyCar")
        track_name = str(race.get("track") or "")
        short_event = _indycar_short_event(event_name, track_name)
        drivers_index = self._fetch_indycar_drivers()
        timing_payload = self._fetch_indycar_timing()
        timing = _mapping(_mapping(timing_payload).get("timing_results")) if timing_payload else {}
        heartbeat = _mapping(timing.get("heartbeat")) if timing else {}
        is_live_on_feed = self._indycar_timing_matches_session(heartbeat, session_key, session_name)
        flag = "WHITE" if state == "pre" else "CHECKERED" if state == "post" else "GREEN"
        items: tuple[Mapping[str, Any], ...] = ()
        total_laps = 0
        current_lap = 0
        time_to_go = ""
        track_type = str(heartbeat.get("trackType") or heartbeat.get("TrackType") or "").strip().upper()
        qualifying_metric = "mph" if track_type == "O" else "time"
        if is_live_on_feed:
            flag = _normalize_racing_flag(heartbeat.get("currentFlag") or heartbeat.get("SessionStatus"))
            items = _sequence(timing.get("Item"))
            total_laps = _integer(heartbeat.get("totalLaps") or heartbeat.get("TotalLaps") or heartbeat.get("lapsInEvent"))
            current_lap = max((_integer(item.get("laps")) for item in items), default=0)
            time_to_go = str(heartbeat.get("overallTimeToGo") or "").strip()
        drivers = [_indycar_driver(item, drivers_index, session_key, track_type) for item in items]
        drivers = sorted((driver for driver in drivers if driver is not None), key=lambda value: value["pos"] or 999)

        if state == "post":
            status = "FINAL"
        elif state == "in":
            status = _indycar_live_status(session_key, flag, current_lap, total_laps, time_to_go) if is_live_on_feed else "LIVE"
        else:
            status = _format_local_time(start, timezone_name)

        return {
            "id": identifier,
            "type": "racing",
            "sport": "indycar",
            "state": state,
            "status": status,
            "is_shown": True,
            "startTimeUTC": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "away_abbr": short_event,
            "home_abbr": session_name,
            "away_score": "",
            "home_score": "",
            "indycar": {
                "event_name": short_event,
                "short_name": short_event,
                "raw_event_name": event_name,
                "raw_session_name": session_name,
                "events_session_id": str(heartbeat.get("EventSessionID") or heartbeat.get("EventsSessionID") or ""),
                "track_name": track_name,
                "track_type": track_type,
                "qualifying_metric": qualifying_metric,
                "session_type": session_name,
                "session_name": session_name,
                "lap": current_lap,
                "total_laps": total_laps,
                "laps_remaining": max(0, total_laps - current_lap),
                "time_to_go": time_to_go,
                "caution": flag in _CAUTION_FLAGS,
                "flag": flag,
                "drivers": drivers,
                "weather": self._fetch_indycar_weather(),
            },
        }

    def _fetch_indycar_timing(self) -> dict[str, Any] | None:
        now = self._clock()
        cached_at, cached = self._indy_timing
        if cached is not None and now - cached_at < 8:
            return cached
        try:
            payload = self._client.get_json(
                f"{_INDYCAR_BLOB_BASE}/timingscoring-ris.json?{urlencode({'_': int(now * 1000)})}",
                timeout=self._timeout,
            )
            data = _mapping(payload)
            self._indy_timing = (now, data if data else None)
            return data
        except Exception:
            return None

    def _indycar_timing_matches_session(
        self,
        heartbeat: Mapping[str, Any],
        session_key: str,
        session_name: str,
    ) -> bool:
        if not heartbeat:
            return False
        series = str(heartbeat.get("Series") or "").strip().upper()
        if series and series != "I":
            return False
        feed_type = str(heartbeat.get("SessionType") or "").strip().upper()
        feed_name = str(heartbeat.get("SessionName") or heartbeat.get("EventSessionLabel") or "").strip().lower()
        key_lower = session_key.lower()
        name_lower = session_name.lower()
        if key_lower == "race" and feed_type in {"R", "RACE"}:
            return True
        if "qual" in key_lower and ("qual" in feed_name or feed_type in {"Q", "QUAL"}):
            return True
        if "practice" in key_lower and ("practice" in feed_name or feed_type in {"P", "PRACTICE"}):
            return True
        if "warm" in key_lower and "warm" in feed_name:
            return True
        return feed_name in name_lower or name_lower in feed_name

    def _fetch_indycar_drivers(self) -> dict[str, Mapping[str, Any]]:
        now = self._clock()
        cached_at, cached = self._indy_drivers
        if now - cached_at < 300:
            return cached
        try:
            payload = self._client.get_json(
                f"{_INDYCAR_BLOB_BASE}/driversfeed.json?{urlencode({'_': int(now * 1000)})}",
                timeout=self._timeout,
            )
            values = _sequence(_mapping(_mapping(payload).get("drivers")).get("driver"))
            result = {str(item.get("number")): item for item in values if item.get("number") is not None}
            self._indy_drivers = (now, result)
            return result
        except Exception:
            return {}

    def _fetch_indycar_weather(self) -> dict[str, str]:
        url = f"https://api.open-meteo.com/v1/forecast?{urlencode({'latitude': _IMS_LAT, 'longitude': _IMS_LON, 'current': 'temperature_2m,wind_speed_10m,wind_direction_10m', 'temperature_unit': 'fahrenheit', 'wind_speed_unit': 'mph', 'timezone': 'auto'})}"
        try:
            current = _mapping(_mapping(self._client.get_json(url, timeout=self._timeout)).get("current"))
            return {
                "air_temp": _rounded(current.get("temperature_2m")),
                "wind_mph": _rounded(current.get("wind_speed_10m")),
                "wind_dir": _rounded(current.get("wind_direction_10m")),
            }
        except Exception:
            return {}

    def _fetch_nascar(self, settings: DisplaySettings) -> list[dict[str, Any]]:
        now = self._now().astimezone(timezone.utc)
        races = self._fetch_nascar_schedule()
        sessions = _nascar_relevant_sessions(races, now, settings.timezone)
        if not sessions:
            if not races:
                timing_payload = self._fetch_nascar_timing()
                if timing_payload:
                    flag_state = _integer(timing_payload.get("flag_state"))
                    is_live = flag_state in {1, 2, 3}
                    if is_live:
                        event_name = str(timing_payload.get("run_name") or "NASCAR").strip()
                        track_name = str(timing_payload.get("track_name") or "").strip()
                        start = now
                        race = {
                            "round": str(timing_payload.get("race_id") or "event"),
                            "race_name": event_name,
                            "track": track_name,
                            "location": track_name,
                            "sessions": {"Race": (start, 240, "Race", False)},
                        }
                        game = self._build_nascar_game(
                            race, "Race", "Race", False, start, start + timedelta(minutes=240), "in", now, settings.timezone
                        )
                        if game is not None:
                            return [game]
            return list(self._nascar_games.values()) if not races else []
        games: list[dict[str, Any]] = []
        active_ids: set[str] = set()
        for race, key, name, practice, start, end, state in sessions:
            identifier = f"nascar_{race['round']}_{key.lower()}"
            active_ids.add(identifier)
            game = self._build_nascar_game(
                race, key, name, practice, start, end, state, now, settings.timezone
            )
            if game is not None:
                self._nascar_games[identifier] = game
                games.append(game)
        for identifier in tuple(self._nascar_games):
            if identifier not in active_ids:
                del self._nascar_games[identifier]
        return games

    def _fetch_nascar_schedule(self) -> list[dict[str, Any]]:
        now_ts = self._clock()
        cached_at, cached = self._nascar_schedule
        if cached and now_ts - cached_at < 3600:
            return cached
        try:
            payload = self._client.get_json(
                f"{_NASCAR_ESPN_URL}?dates={self._now().year}",
                timeout=self._timeout,
            )
            events = _sequence(_mapping(payload).get("events"))
            races = [_nascar_event_to_race(event) for event in events if _mapping(event)]
        except Exception:
            return []
        races = [race for race in races if race.get("sessions")]
        self._nascar_schedule = (now_ts, races)
        return races

    def _fetch_nascar_timing(self) -> dict[str, Any] | None:
        now = self._clock()
        cached_at, cached = self._nascar_timing
        if cached is not None and now - cached_at < 8:
            return cached
        try:
            payload = self._client.get_json(
                f"{_NASCAR_LIVE_URL}?{urlencode({'_': int(now * 1000)})}",
                timeout=self._timeout,
            )
            data = _mapping(payload)
            self._nascar_timing = (now, data if data else None)
            return data
        except Exception:
            return None

    def _build_nascar_game(
        self,
        race: Mapping[str, Any],
        session_key: str,
        session_name: str,
        practice: bool,
        start: datetime,
        end: datetime,
        state: str,
        now: datetime,
        timezone_name: str,
    ) -> dict[str, Any] | None:
        identifier = f"nascar_{race['round']}_{session_key.lower()}"
        event_name = str(race.get("race_name") or "NASCAR")
        track_name = str(race.get("track") or "")
        short_event = _nascar_short_event(event_name, track_name)
        timing = self._fetch_nascar_timing() or {}
        flag_num = _integer(timing.get("flag_state"))
        flag = _NASCAR_FLAGS.get(flag_num, "GREEN")
        is_live_on_feed = flag_num in {1, 2, 3}
        total_laps = _integer(timing.get("laps_in_race"))
        current_lap = _integer(timing.get("lap_number"))
        vehicles = _sequence(timing.get("vehicles")) if is_live_on_feed or state == "post" else ()
        drivers = [_nascar_driver(v) for v in vehicles]
        drivers = sorted((d for d in drivers if d is not None), key=lambda value: value["pos"] or 999)

        if state == "post":
            status = "FINAL"
        elif state == "in":
            status = f"Lap {current_lap}/{total_laps}" if current_lap and total_laps else flag
        else:
            status = _format_local_time(start, timezone_name)

        stage_info = _mapping(timing.get("stage"))
        stage_num = _integer(stage_info.get("stage_num"))

        return {
            "id": identifier,
            "type": "racing",
            "sport": "nascar",
            "state": state,
            "status": status,
            "is_shown": True,
            "startTimeUTC": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "away_abbr": short_event,
            "home_abbr": session_name,
            "away_score": "",
            "home_score": "",
            "nascar": {
                "event_name": short_event,
                "short_name": short_event,
                "raw_event_name": event_name,
                "raw_session_name": session_name,
                "track_name": track_name,
                "session_type": session_name,
                "session_name": session_name,
                "lap": current_lap,
                "total_laps": total_laps,
                "laps_remaining": max(0, total_laps - current_lap),
                "stage": f"Stage {stage_num}" if stage_num else "",
                "caution": flag in _CAUTION_FLAGS,
                "flag": flag,
                "drivers": drivers,
            },
        }


def _f1_event_to_race(event: Mapping[str, Any]) -> dict[str, Any]:
    circuit = _mapping(event.get("circuit"))
    address = _mapping(circuit.get("address"))
    sessions: dict[str, tuple[datetime, int, str, bool]] = {}
    for competition in _sequence(event.get("competitions")):
        type_info = _mapping(competition.get("type"))
        abbreviation = str(type_info.get("abbreviation") or "").upper()
        key = _F1_ESPN_ABBREVIATIONS.get(abbreviation)
        if key is None:
            key = next(
                (
                    candidate
                    for candidate, label, _practice, _duration in _F1_SESSION_ORDER
                    if label.casefold() in str(type_info.get("text") or "").casefold()
                ),
                None,
            )
        start = _parse_datetime(competition.get("startDate") or competition.get("date"))
        if key and start is not None:
            duration = next(
                duration
                for candidate, _label, _practice, duration in _F1_SESSION_ORDER
                if candidate == key
            )
            label = next(
                label
                for candidate, label, _practice, _duration in _F1_SESSION_ORDER
                if candidate == key
            )
            sessions[key] = (
                start,
                duration,
                label,
                next(
                    practice
                    for candidate, _name, practice, _duration in _F1_SESSION_ORDER
                    if candidate == key
                ),
            )
    return {
        "round": str(event.get("id") or "event"),
        "race_name": str(event.get("name") or "Formula 1"),
        "track": str(circuit.get("fullName") or address.get("city") or ""),
        "location": str(address.get("city") or ""),
        "sessions": sessions,
    }


def _f1_relevant_sessions(
    races: Sequence[Mapping[str, Any]],
    now: datetime,
    timezone_name: str,
) -> list[tuple[Mapping[str, Any], str, str, bool, datetime, datetime, str]]:
    for race in sorted(
        races,
        key=lambda item: min(
            (value[0] for value in _mapping(item.get("sessions")).values()),
            default=datetime.max.replace(tzinfo=timezone.utc),
        ),
    ):
        sessions = []
        for key, start_data in _mapping(race.get("sessions")).items():
            start, duration, label, practice = start_data
            end = start + timedelta(minutes=duration)
            sessions.append((key, label, practice, start, end))
        if not sessions:
            continue
        relevant = []
        for key, label, practice, start, end in sessions:
            state = _session_lifecycle_state(start, end, now, timezone_name)
            if state:
                relevant.append((race, key, label, practice, start, end, state))
        if relevant:
            return sorted(relevant, key=lambda value: value[4])
    return []


def _f1_short_event(value: str) -> str:
    text = re.sub(r"^.*?\s+([A-Za-zÀ-ÿ -]+?)\s+Grand Prix.*$", r"\1 GP", value, flags=re.IGNORECASE)
    text = text.replace("FORMULA 1", "").strip()
    return " ".join(text.split()).title() or "Formula 1"


def _f1_team_match(value: object) -> str:
    lower = str(value or "").strip().lower()
    return next((key for key in sorted(_F1_TEAM_SLUGS, key=len, reverse=True) if key in lower), "")


def _f1_team_color(value: object) -> str:
    return _F1_TEAM_COLORS.get(_f1_team_match(value), "#888888")


def _f1_car_url(value: object) -> str:
    slug = _F1_TEAM_SLUGS.get(_f1_team_match(value))
    return (
        f"https://media.formula1.com/image/upload/c_lfill,h_224/q_auto/v1740000001/common/f1/2026/{slug}/2026{slug}carright.webp"
        if slug
        else ""
    )


def _indycar_event_to_race(event: Mapping[str, Any]) -> dict[str, Any]:
    competitions = _sequence(event.get("competitions"))
    venue = _mapping(competitions[0].get("venue")) if competitions else {}
    address = _mapping(venue.get("address"))
    start = _parse_datetime(event.get("date") or (competitions[0].get("date") if competitions else None))
    sessions: dict[str, tuple[datetime, int, str, bool]] = {}
    if start is not None:
        sessions["Race"] = (start, 180, "Race", False)
    race_name = str(event.get("name") or "IndyCar")
    track = str(venue.get("fullName") or address.get("city") or race_name)
    location = str(address.get("city") or "")
    round_id = str(event.get("id") or "event")
    return {
        "round": round_id,
        "race_name": race_name,
        "track": track,
        "location": location,
        "sessions": sessions,
    }


def _indycar_event_slug(race_name: str) -> str | None:
    lowered = race_name.lower()
    return next((slug for key, slug in _INDYCAR_SLUG_MAP.items() if key in lowered), None)


def _parse_indycar_weekend_html(page: str, year: int) -> dict[str, tuple[datetime, int, str, bool]]:
    day_matches = [(m.start(), "day", m.groups()) for m in _INDYCAR_DAY_RE.finditer(page)]
    entry_matches = [(m.start(), "entry", m.groups()) for m in _INDYCAR_ENTRY_RE.finditer(page)]
    all_markers = sorted(day_matches + entry_matches, key=lambda x: x[0])
    current_day = None
    sessions: dict[str, tuple[datetime, int, str, bool]] = {}
    for _pos, kind, data in all_markers:
        if kind == "day":
            current_day = data
        elif kind == "entry" and current_day:
            time_str, desc = data
            if "NTT INDYCAR SERIES" in desc and "Pre-Race" not in desc:
                session_raw = desc.split(" - ", 1)[-1].strip()
                key = re.sub(r"[^A-Za-z0-9]", "", session_raw)
                time_clean = time_str.replace(" ET", "").strip()
                month, day = current_day
                try:
                    dt = datetime.strptime(
                        f"{month} {day} {year} {time_clean}", "%b %d %Y %I:%M%p"
                    ).replace(tzinfo=ZoneInfo("America/New_York"))
                except ValueError:
                    continue
                lowered = session_raw.lower()
                practice = "practice" in lowered or "warm" in lowered
                duration = 90 if "practice" in lowered else 60 if "qual" in lowered else 30 if "warm" in lowered else 180
                sessions[key] = (dt.astimezone(timezone.utc), duration, session_raw, practice)
    return sessions


def _indycar_relevant_sessions(
    races: Sequence[Mapping[str, Any]],
    now: datetime,
    timezone_name: str,
) -> list[tuple[Mapping[str, Any], str, str, bool, datetime, datetime, str]]:
    for race in sorted(
        races,
        key=lambda item: min(
            (value[0] for value in _mapping(item.get("sessions")).values()),
            default=datetime.max.replace(tzinfo=timezone.utc),
        ),
    ):
        sessions = []
        for key, start_data in _mapping(race.get("sessions")).items():
            start, duration, label, practice = start_data
            end = start + timedelta(minutes=duration)
            sessions.append((key, label, practice, start, end))
        if not sessions:
            continue
        relevant = []
        for key, label, practice, start, end in sessions:
            state = _session_lifecycle_state(start, end, now, timezone_name)
            if state:
                relevant.append((race, key, label, practice, start, end, state))
        if relevant:
            return sorted(relevant, key=lambda value: value[4])
    return []


def _indycar_short_event(event_name: str, track_name: str) -> str:
    value = _clean_race_name(event_name or track_name or "IndyCar")
    lowered = value.casefold()
    if "indy 500" in lowered or "indianapolis 500" in lowered:
        return "Indy 500"
    distance = re.search(r"\b([A-Za-z][A-Za-z .&'-]*?)\s+(\d{3})$", value)
    if distance:
        return f"{_title_race_words(distance.group(1))} {distance.group(2)}"
    match = re.search(r"grand\s+prix\s+(?:of|at)\s+(.+)", value, re.IGNORECASE)
    if match:
        location = re.split(r"\s+presented\s+by\b", match.group(1), flags=re.IGNORECASE)[0]
        return f"{_title_race_words(location)} GP"
    match = re.search(r"\bat\s+(.+)$", value, re.IGNORECASE)
    if match:
        return f"{_title_race_words(match.group(1))} GP"
    if "music city" in lowered:
        return "Music City GP"
    if re.search(r"\bgrand\s+prix\b", value, re.IGNORECASE):
        location = re.split(r"\bgrand\s+prix\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
        return f"{_title_race_words(location)} GP"
    return _title_race_words(value) or "IndyCar"


def _clean_race_name(value: str) -> str:
    """Remove race sponsors and ordinal wording before display shortening."""
    value = re.sub(r"\b(?:110th|\d+th)\s+Running of the\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+presented by\b.*$", "", value, flags=re.IGNORECASE)
    return " ".join(value.replace("–", "-").split()).strip(" .,")


def _title_race_words(value: str) -> str:
    """Return compact race words with title casing and clean punctuation."""
    words = " ".join(value.replace("-", " ").split()).strip(" .,")
    return re.sub(r"\bGp\b", "GP", words.title().replace(" Of ", " of "))


def _is_timed_session(session: object) -> bool:
    name = str(session or "").lower()
    return any(
        keyword in name
        for keyword in (
            "qual",
            "fast",
            "top 12",
            "last chance",
            "hyperpole",
            "pole",
            "shootout",
            "prac",
            "fp",
            "warm",
            "shakedown",
            "test",
            "time trial",
        )
    )


def _indycar_driver(
    item: Mapping[str, Any],
    index: Mapping[str, Any],
    session_type: str,
    track_type: str,
) -> dict[str, Any] | None:
    pos = _integer(item.get("rank") or item.get("overallRank"))
    if not pos:
        return None
    car = str(item.get("no") or "").strip()
    first = str(item.get("firstName") or "").strip()
    last = str(item.get("lastName") or "").strip()
    team = str(item.get("team") or "").strip()
    feed = index.get(car, {})
    flag = _normalize_racing_flag(item.get("flag") or item.get("status"))
    speed = str(item.get("qualSpeed") or item.get("BestSpeed") or item.get("LastSpeed") or "").strip()
    best_time = str(item.get("qualTime") or item.get("bestLapTime") or "").strip()
    raw_gap = str(item.get("diff") or item.get("gap") or "").strip()
    qualifying_metric = "mph" if track_type == "O" else "time"
    qualifying_value = f"{float(speed):.3f}" if qualifying_metric == "mph" and _number(speed) is not None else speed if qualifying_metric == "mph" else best_time
    is_timed = _is_timed_session(session_type)
    if is_timed:
        gap = qualifying_value or (best_time if qualifying_metric == "time" else speed) or ("Leader" if pos == 1 else raw_gap)
    else:
        gap = "Leader" if pos == 1 else raw_gap
    return {
        "pos": pos,
        "name": f"{first} {last}".strip() or "Unknown",
        "abbr": _driver_abbr(first, last),
        "car": car,
        "team": team,
        "team_logo": str(feed.get("endplatesmall") or feed.get("endplatelarge") or feed.get("headshot") or ""),
        "car_illustration": str(feed.get("carillustration") or ""),
        "livery_primary": _team_livery(team)[0],
        "livery_secondary": _team_livery(team)[1],
        "gap": gap,
        "qualifying_value": qualifying_value,
        "laps": str(item.get("laps") or "").strip(),
        "speed": speed or (qualifying_value if qualifying_metric == "mph" else ""),
        "best_time": best_time,
        "status": str(item.get("status") or "Active"),
        "on_track": str(item.get("onTrack") or "").lower() == "true",
        "flag": flag,
    }


def _team_livery(value: object) -> tuple[str, str]:
    lower = str(value or "").lower()
    return next((colors for key, colors in _INDYCAR_LIVERIES.items() if key in lower), ("#888888", "#333333"))


def _indycar_live_status(session_type: str, flag: str, lap: int, total_laps: int, time_to_go: str) -> str:
    session_lower = session_type.lower()
    if session_lower == "race" and total_laps:
        return f"{lap}/{total_laps}"
    if "qual" in session_lower and time_to_go:
        return time_to_go
    return {"YELLOW": "YELLOW", "RED": "RED FLAG", "CHECKERED": "CHECKERED"}.get(flag, "GREEN")


_FLAG_MAP = {
    "VIRTUAL SAFETY CAR": "VSC",
    "VSC ENDING": "VSC ENDING",
    "SAFETY CAR ENDING": "SC ENDING",
    "SC ENDING": "SC ENDING",
    "SAFETY CAR": "SAFETY CAR",
    "DOUBLE YELLOW": "DOUBLE YELLOW",
    "DOUBLE_YELLOW": "DOUBLE YELLOW",
    "FULL COURSE YELLOW": "FCY",
    "BLACK AND ORANGE": "MEATBALL",
    "BLACK AND WHITE": "BLACK AND WHITE",
    "BLACK WHITE": "BLACK AND WHITE",
    "ROLLING START": "GREEN",
    "FORMATION LAP": "GREEN",
    "CHECKERED FLAG": "CHECKERED",
    "CHEQUERED": "CHECKERED",
    "CHECKERED": "CHECKERED",
    "YELLOW FLAG": "YELLOW",
    "RED FLAG": "RED FLAG",
    "RED_FLAG": "RED FLAG",
    "PACE CAR": "SAFETY CAR",
    "MEATBALL": "MEATBALL",
    "STOPPED": "RED FLAG",
    "CAUTION": "YELLOW",
    "YELLOW": "YELLOW",
    "GREEN": "GREEN",
    "CLEAR": "GREEN",
    "FINAL": "CHECKERED",
    "WHITE": "WHITE",
    "CHKD": "CHECKERED",
    "BLUE": "BLUE",
    "GWC": "GWC",
    "VSC": "VSC",
    "FCY": "FCY",
    "SC": "SAFETY CAR",
    "RED": "RED FLAG",
}
_SORTED_FLAG_KEYS = sorted(_FLAG_MAP.keys(), key=len, reverse=True)

_CAUTION_FLAGS = {
    "YELLOW",
    "DOUBLE YELLOW",
    "SAFETY CAR",
    "VSC",
    "FCY",
    "RED",
    "RED FLAG",
    "SC ENDING",
    "VSC ENDING",
}


def _normalize_racing_flag(flag: object, status: object = None) -> str:
    raw = str(flag or status or "").strip().upper()
    if not raw:
        return "GREEN"
    if raw in _FLAG_MAP:
        return _FLAG_MAP[raw]
    for key in _SORTED_FLAG_KEYS:
        pattern = r"\b" + re.escape(key) + r"\b"
        if re.search(pattern, raw):
            return _FLAG_MAP[key]
    return "GREEN"


def _driver_abbr(first: object, last: object) -> str:
    letters = "".join(char for char in str(last or "") if char.isalnum())
    if len(letters) >= 3:
        return letters[:3].upper()
    return (letters + "".join(char for char in str(first or "") if char.isalnum()))[:3].upper() or "???"


_NASCAR_FLAGS = {
    1: "GREEN",
    2: "YELLOW",
    3: "RED",
    4: "CHECKERED",
    8: "WARMUP",
    9: "COLD",
}


def _nascar_event_to_race(event: Mapping[str, Any]) -> dict[str, Any]:
    competitions = _sequence(event.get("competitions"))
    venue = _mapping(competitions[0].get("venue")) if competitions else {}
    address = _mapping(venue.get("address"))
    start = _parse_datetime(event.get("date") or (competitions[0].get("date") if competitions else None))
    sessions: dict[str, tuple[datetime, int, str, bool]] = {}
    if start is not None:
        sessions["Race"] = (start, 240, "Race", False)
    race_name = str(event.get("name") or "NASCAR")
    track = str(venue.get("fullName") or address.get("city") or race_name)
    location = str(address.get("city") or "")
    round_id = str(event.get("id") or "event")
    return {
        "round": round_id,
        "race_name": race_name,
        "track": track,
        "location": location,
        "sessions": sessions,
    }


def _nascar_relevant_sessions(
    races: Sequence[Mapping[str, Any]],
    now: datetime,
    timezone_name: str,
) -> list[tuple[Mapping[str, Any], str, str, bool, datetime, datetime, str]]:
    for race in sorted(
        races,
        key=lambda item: min(
            (value[0] for value in _mapping(item.get("sessions")).values()),
            default=datetime.max.replace(tzinfo=timezone.utc),
        ),
    ):
        sessions = []
        for key, start_data in _mapping(race.get("sessions")).items():
            start, duration, label, practice = start_data
            end = start + timedelta(minutes=duration)
            sessions.append((key, label, practice, start, end))
        if not sessions:
            continue
        relevant = []
        for key, label, practice, start, end in sessions:
            state = _session_lifecycle_state(start, end, now, timezone_name)
            if state:
                relevant.append((race, key, label, practice, start, end, state))
        if relevant:
            return sorted(relevant, key=lambda value: value[4])
    return []


def _nascar_short_event(event_name: str, track_name: str) -> str:
    value = _clean_race_name(event_name or track_name or "NASCAR")
    lowered = value.casefold()
    if "daytona 500" in lowered:
        return "Daytona 500"
    if "coca-cola 600" in lowered or "coke 600" in lowered:
        return "Coke 600"
    if "southern 500" in lowered:
        return "Southern 500"
    if "brickyard 400" in lowered:
        return "Brickyard 400"
    distance = re.search(r"\b([A-Za-z][A-Za-z .&'-]*?)\s+(\d{3})$", value)
    if distance:
        return f"{_title_race_words(distance.group(1))} {distance.group(2)}"
    return _title_race_words(value) or "NASCAR"


_NASCAR_LIVERIES_CACHE: dict[str, str] = {}


def _get_nascar_car_url(car_num: str) -> str:
    global _NASCAR_LIVERIES_CACHE
    if not _NASCAR_LIVERIES_CACHE:
        try:
            import json
            from pathlib import Path
            db_path = Path(__file__).parent / "racing_grid_verified_db.json"
            if db_path.exists():
                data = json.loads(db_path.read_text(encoding="utf-8"))
                _NASCAR_LIVERIES_CACHE = data.get("nascar", {}).get("cup", {})
        except Exception:
            _NASCAR_LIVERIES_CACHE = {}
    clean_num = str(car_num or "").strip().lstrip("0") or "0"
    return _NASCAR_LIVERIES_CACHE.get(clean_num, "")


def _nascar_driver(vehicle: Mapping[str, Any]) -> dict[str, Any] | None:
    pos = _integer(vehicle.get("running_position"))
    if not pos:
        return None
    driver = _mapping(vehicle.get("driver"))
    name = str(driver.get("full_name") or f"{driver.get('first_name', '')} {driver.get('last_name', '')}").strip()
    first = str(driver.get("first_name") or "")
    last = str(driver.get("last_name") or "")
    car = str(vehicle.get("vehicle_number") or "").strip()
    sponsor = str(vehicle.get("sponsor_name") or "").strip()
    mfr = str(vehicle.get("vehicle_manufacturer") or "").strip()
    delta = _number(vehicle.get("delta"))
    gap = "Leader" if pos == 1 else f"+{delta:.3f}s" if delta is not None else ""
    return {
        "pos": pos,
        "name": name or "Unknown",
        "abbr": _driver_abbr(first, last),
        "car": car,
        "team": sponsor or mfr,
        "team_logo": "",
        "car_illustration": _get_nascar_car_url(car),
        "livery_primary": "#FFD700",
        "livery_secondary": "#111111",
        "gap": gap,
        "speed": str(vehicle.get("last_lap_speed") or ""),
        "status": "Active" if vehicle.get("is_on_track") else "Out",
        "on_track": bool(vehicle.get("is_on_track")),
        "flag": "",
    }


def _session_lifecycle_state(
    start: datetime,
    end: datetime,
    now: datetime,
    timezone_name: str,
) -> str | None:
    """Match the sports display lifecycle: appears on event day, disappears at 3 AM next day."""
    if start <= now <= end:
        return "in"
    if end < now:
        return "post" if _in_reset_window(start, now, timezone_name) else None
    zone = _display_timezone(timezone_name)
    local_now = now.astimezone(zone)
    local_start = start.astimezone(zone)
    if local_now.hour < 3:
        if local_start.date() == (local_now - timedelta(days=1)).date() or local_start.date() == local_now.date():
            return "pre"
    else:
        if local_start.date() == local_now.date():
            return "pre"
    return None


def _in_reset_window(start: datetime, now: datetime, timezone_name: str) -> bool:
    zone = _display_timezone(timezone_name)
    local_now = now.astimezone(zone)
    boundary = local_now.replace(hour=3, minute=0, second=0, microsecond=0)
    if local_now < boundary:
        boundary -= timedelta(days=1)
    return start.astimezone(zone) >= boundary


def _display_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(value).strip() or "America/New_York")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


def _format_local_time(value: datetime, timezone_name: str) -> str:
    return value.astimezone(_display_timezone(timezone_name)).strftime("%I:%M %p").lstrip("0")


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    if not total:
        return ""
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _format_qualifying_time(value: float) -> str:
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes)}:{seconds:06.3f}" if minutes else f"{seconds:.3f}"


def _session_ended(value: Mapping[str, Any], now: datetime | None = None) -> bool:
    end = _parse_datetime(value.get("date_end"))
    return end is not None and end < (now or datetime.now(timezone.utc))


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rounded(value: object) -> str:
    number = _number(value)
    return str(int(round(number))) if number is not None else ""


def _first_text(mapping: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


__all__ = ["LiveRacingSource"]
