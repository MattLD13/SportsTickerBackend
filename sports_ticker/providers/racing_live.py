"""Poll official live timing sources for F1 and IndyCar V2 content."""

from __future__ import annotations

import html
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
_OPENF1_BASE = "https://api.openf1.org/v1"
_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
_INDYCAR_BLOB_BASE = "https://indycar.blob.core.windows.net/racecontrol"
_INDYCAR_SCHEDULE_URL = "https://www.indycar.com/Schedule"
_INDYCAR_RESULTS_BASE = "https://www.indycar.com/api/results"
_INDYCAR_SERIES_ID = "b856a4f1-e85c-4fac-8c36-fd58d962227a"
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
_INDYCAR_SESSION_DURATIONS = {
    "Practice": 90,
    "Practice 1": 90,
    "Practice 2": 90,
    "Practice 3": 90,
    "Qualifying": 60,
    "Fast 10": 30,
    "Fast 12": 30,
    "Fast 6": 20,
    "Warmup": 30,
    "Warm Up": 30,
    "Race": 180,
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
_INDYCAR_INDEX_HREF_RE = re.compile(r'href="/Schedule/(\d{4})/([^"]+)"')
_INDYCAR_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
_INDYCAR_DAY_RE = re.compile(r"<h3>[A-Za-z]+, ([A-Za-z]+) (\d{1,2})</h3>")
_INDYCAR_ENTRY_RE = re.compile(
    r'<div class="schedule-entry">.*?<div class="schedule-time">([^<]+)</div>'
    r'.*?<div class="schedule-description">([^<]+)</div>',
    re.DOTALL,
)


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
        self._indy_timing: tuple[float, dict[str, Any] | None] = (0.0, None)
        self._indy_drivers: tuple[float, dict[str, Mapping[str, Any]]] = (0.0, {})
        self._indy_schedule: tuple[float, list[tuple[str, str, datetime]]] = (0.0, [])
        self._indy_index: tuple[float, list[tuple[str, str]]] = (0.0, [])
        self._indy_event_pages: dict[str, tuple[float, list[tuple[str, str, datetime]], str]] = {}
        self._indy_session_ids: tuple[float, object] = (0.0, ())
        self._indy_results: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def fetch(self, settings: DisplaySettings) -> Mapping[str, object]:
        """Return current F1 and IndyCar content for one ticker settings view."""

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
                game = self._fetch_indycar(settings)
            except Exception as error:
                failures.append(f"indycar: {error}")
                game = self._indy_timing[1]
            if game is not None:
                records.append(game)
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
                    (start - now).total_seconds() if state == "pre" else (end - now).total_seconds() if state == "in" and practice else 0
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
        drivers_raw = _sequence(self._client.get_json(
            f"{_OPENF1_BASE}/drivers?session_key={session_key}", timeout=self._timeout
        ))
        driver_info = {
            str(item.get("driver_number")): item
            for item in drivers_raw
            if _mapping(item).get("driver_number") is not None
        }
        positions_raw = _sequence(self._client.get_json(
            f"{_OPENF1_BASE}/position?session_key={session_key}", timeout=self._timeout
        ))
        latest_positions: dict[str, Mapping[str, Any]] = {}
        for position in positions_raw:
            key = str(position.get("driver_number") or "")
            if key and (key not in latest_positions or str(position.get("date", "")) > str(latest_positions[key].get("date", ""))):
                latest_positions[key] = position
        session_name = str(session.get("session_name") or "").lower()
        qualifying = "qual" in session_name
        best_laps: dict[str, float] = {}
        latest_laps: dict[str, int] = {}
        lap_rows = _sequence(self._client.get_json(
            f"{_OPENF1_BASE}/laps?session_key={session_key}", timeout=self._timeout
        ))
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
            interval_rows = _sequence(self._client.get_json(
                f"{_OPENF1_BASE}/intervals?session_key={session_key}", timeout=self._timeout
            ))
            for interval in interval_rows:
                key = str(interval.get("driver_number") or "")
                if key and (key not in intervals or str(interval.get("date", "")) > str(intervals[key].get("date", ""))):
                    intervals[key] = interval
        positions = sorted(latest_positions.values(), key=lambda value: _integer(value.get("position"), 999))
        leader_lap = best_laps.get(str(positions[0].get("driver_number"))) if positions and qualifying else None
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
                    gap = _format_qualifying_time(best) if pos == 1 or leader_lap is None else f"+{best - leader_lap:.3f}"
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
            values = _sequence(self._client.get_json(f"{_OPENF1_BASE}/sessions?session_key=latest", timeout=self._timeout))
        else:
            begin = (start - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end = (start + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            query = urlencode({"date_start>": begin, "date_start<": end})
            values = _sequence(self._client.get_json(f"{_OPENF1_BASE}/sessions?{query}", timeout=self._timeout))
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
            rows = _sequence(self._client.get_json(f"{_OPENF1_BASE}/race_control?session_key={session_key}", timeout=self._timeout))
        except Exception:
            return "GREEN"
        for row in reversed(rows):
            message = str(row.get("message") or row.get("flag") or "").upper()
            if "RED FLAG" in message:
                return "RED FLAG"
            if "VIRTUAL SAFETY CAR" in message or "VSC" in message:
                return "VSC"
            if "SAFETY CAR" in message:
                return "SAFETY CAR"
            if "YELLOW" in message:
                return "YELLOW"
            if "GREEN" in message:
                return "GREEN"
        return "GREEN"

    def _f1_result_drivers(self) -> list[dict[str, Any]]:
        now = self._clock()
        cached_at, cached = self._f1_results
        if not cached or now - cached_at >= 1800:
            try:
                payload = self._client.get_json(f"{_JOLPICA_BASE}/current/last/results.json", timeout=self._timeout)
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

    def _fetch_indycar(self, settings: DisplaySettings) -> dict[str, Any] | None:
        now = self._clock()
        cached_at, cached = self._indy_timing
        if cached is not None and now - cached_at < 8:
            return cached
        payload = self._client.get_json(
            f"{_INDYCAR_BLOB_BASE}/timingscoring-ris.json?{urlencode({'_': int(now * 1000)})}",
            timeout=self._timeout,
        )
        timing = _mapping(_mapping(payload).get("timing_results"))
        if timing:
            game = self._build_indycar_game(timing, settings)
        else:
            game = self._build_indycar_schedule_game(settings)
        self._indy_timing = (now, game)
        return game

    def _build_indycar_game(self, timing: Mapping[str, Any], settings: DisplaySettings) -> dict[str, Any] | None:
        heartbeat = _mapping(timing.get("heartbeat"))
        series = str(heartbeat.get("Series") or "").strip().upper()
        if series and series != "I" or "NXT" in str(heartbeat.get("eventName") or "").upper():
            return self._build_indycar_schedule_game(settings)
        drivers_index = self._fetch_indycar_drivers()
        event_name = str(heartbeat.get("eventName") or "IndyCar").strip()
        track_name = str(heartbeat.get("trackName") or "").strip()
        session_raw = str(heartbeat.get("SessionType") or "R").strip().upper()
        session_name = str(heartbeat.get("SessionName") or heartbeat.get("EventSessionLabel") or "").strip()
        session = _indycar_session_name(session_raw, session_name)
        track_type = str(heartbeat.get("trackType") or heartbeat.get("TrackType") or "").strip().upper()
        qualifying_metric = "mph" if track_type == "O" else "time"
        flag = _normalize_flag(heartbeat.get("currentFlag") or heartbeat.get("SessionStatus"))
        session_status = str(heartbeat.get("SessionStatus") or "").upper()
        state = "post" if session_status in {"FINAL", "ENDED", "UNOFFICIAL", "OFFICIAL", "CHKD", "COLD"} or flag in {"FINAL", "ENDED", "UNOFFICIAL", "OFFICIAL", "CHKD", "COLD"} else "in" if session_status in {"LIVE", "RUNNING", "OPEN", "GREEN", "YELLOW", "RED", "CHECKERED"} or flag in {"GREEN", "YELLOW", "RED", "CHECKERED", "SAFETY CAR", "VSC"} else "pre"
        start = _first_text(heartbeat, "startTimeUTC", "StartTimeUTC", "SessionStartUTC", "SessionStartTimeUTC", "SessionStartTime", "EventStartTimeUTC", "EventStartTime")
        if not start and state in {"pre", "post"}:
            schedule = self._fetch_indycar_schedule()
            match = _indycar_relevant_session(schedule, self._now().astimezone(timezone.utc), settings.timezone)
            if match:
                start = match[2].strftime("%Y-%m-%dT%H:%M:%SZ")
            elif state == "pre":
                return None
            else:
                start = self._now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = _sequence(timing.get("Item"))
        total_laps = _integer(heartbeat.get("totalLaps") or heartbeat.get("TotalLaps") or heartbeat.get("lapsInEvent"))
        current_lap = max((_integer(item.get("laps")) for item in items), default=0)
        time_to_go = str(heartbeat.get("overallTimeToGo") or "").strip()
        drivers = [_indycar_driver(item, drivers_index, session_raw, track_type) for item in items]
        drivers = sorted((driver for driver in drivers if driver is not None), key=lambda value: value["pos"] or 999)
        short_event = _indycar_short_event(event_name, track_name)
        status = "FINAL" if state == "post" else _indycar_live_status(session_raw, flag, current_lap, total_laps, time_to_go) if state == "in" else f"Starts {_format_local_time(_parse_datetime(start), settings.timezone)}"
        event_id = str(heartbeat.get("EventID") or heartbeat.get("EventSessionID") or "indycar_live").strip()
        return {
            "id": event_id,
            "type": "racing",
            "sport": "indycar",
            "state": state,
            "status": status,
            "is_shown": True,
            "startTimeUTC": start,
            "away_abbr": short_event,
            "home_abbr": session,
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
                "session_type": session,
                "session_name": session,
                "lap": current_lap,
                "total_laps": total_laps,
                "laps_remaining": _integer(heartbeat.get("lapsToGo") or heartbeat.get("LapsToGo")),
                "time_to_go": time_to_go,
                "caution": flag in {"YELLOW", "RED", "SAFETY CAR", "VSC"},
                "flag": flag,
                "drivers": drivers,
                "weather": self._fetch_indycar_weather(),
            },
        }

    def _fetch_indycar_drivers(self) -> dict[str, Mapping[str, Any]]:
        now = self._clock()
        cached_at, cached = self._indy_drivers
        if now - cached_at < 300:
            return cached
        payload = self._client.get_json(
            f"{_INDYCAR_BLOB_BASE}/driversfeed.json?{urlencode({'_': int(now * 1000)})}",
            timeout=self._timeout,
        )
        values = _sequence(_mapping(_mapping(payload).get("drivers")).get("driver"))
        result = {str(item.get("number")): item for item in values if item.get("number") is not None}
        self._indy_drivers = (now, result)
        return result

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

    def _fetch_indycar_schedule(self) -> list[tuple[str, str, datetime]]:
        now = self._clock()
        cached_at, cached = self._indy_schedule
        if cached and now - cached_at < 3600:
            return cached
        payload = self._client.get_json(f"{_INDYCAR_ESPN_URL}?dates={self._now().year}", timeout=self._timeout)
        events = _sequence(_mapping(payload).get("events"))
        sessions = [
            (str(event.get("shortName") or event.get("name") or "IndyCar"), "Race", _parse_datetime(event.get("date")))
            for event in events
            if _parse_datetime(event.get("date")) is not None
        ]
        sessions = [(name, session, start) for name, session, start in sessions if start is not None]
        try:
            weekend = self._fetch_indycar_weekend(sessions, now)
            if weekend:
                event_name, detail = weekend
                sessions = [item for item in sessions if item[0] != event_name] + detail
        except Exception:
            pass
        sessions.sort(key=lambda item: item[2])
        self._indy_schedule = (now, sessions)
        return sessions

    def _fetch_indycar_weekend(
        self,
        espn_sessions: list[tuple[str, str, datetime]],
        now: float,
    ) -> tuple[str, list[tuple[str, str, datetime]]] | None:
        current = _indycar_relevant_session(espn_sessions, self._now().astimezone(timezone.utc), "America/New_York")
        if not current:
            return None
        event_name = current[0]
        index = next((index for index, item in enumerate(espn_sessions) if item[0] == event_name), -1)
        if index < 0:
            return None
        index_at, index_data = self._indy_index
        if not index_data or now - index_at >= 21600:
            page = self._text_client.get_text(_INDYCAR_SCHEDULE_URL, timeout=self._timeout)
            index_data = _indycar_schedule_index(page)
            self._indy_index = (now, index_data)
        if index >= len(index_data):
            return None
        year, slug = index_data[index]
        key = f"{year}/{slug}"
        entry = self._indy_event_pages.get(key)
        if entry is None or now - entry[0] >= 1800:
            page = self._text_client.get_text(f"{_INDYCAR_SCHEDULE_URL}/{year}/{slug}", timeout=self._timeout)
            details = _indycar_event_sessions(page, int(year), event_name)
            h1 = _INDYCAR_H1_RE.search(page)
            full_name = html.unescape(_strip_tags(h1.group(1))) if h1 else ""
            entry = (now, details, full_name)
            self._indy_event_pages[key] = entry
        return event_name, entry[1]

    def _build_indycar_schedule_game(self, settings: DisplaySettings) -> dict[str, Any] | None:
        match = _indycar_relevant_session(self._fetch_indycar_schedule(), self._now().astimezone(timezone.utc), settings.timezone)
        if not match:
            return None
        event_name, session_name, start, _end, state = match
        short_event = _indycar_short_event(event_name, event_name)
        session = _indycar_session_name("", session_name)
        status = "LIVE" if state == "in" else "FINAL" if state == "post" else f"Starts {_format_local_time(start, settings.timezone)}"
        return {
            "id": f"indycar_sched_{start.strftime('%Y%m%dT%H%M')}",
            "type": "racing",
            "sport": "indycar",
            "state": state,
            "status": status,
            "is_shown": True,
            "startTimeUTC": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "away_abbr": short_event,
            "home_abbr": session,
            "away_score": "",
            "home_score": "",
            "indycar": {
                "event_name": short_event,
                "short_name": short_event,
                "track_name": "",
                "track_type": "",
                "qualifying_metric": "time",
                "session_type": session,
                "session_name": session,
                "lap": 0,
                "total_laps": 0,
                "laps_remaining": 0,
                "time_to_go": "",
                "caution": False,
                "flag": "CHECKERED" if state == "post" else "GREEN",
                "drivers": [],
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
            key = next((candidate for candidate, label, _practice, _duration in _F1_SESSION_ORDER if label.casefold() in str(type_info.get("text") or "").casefold()), None)
        start = _parse_datetime(competition.get("startDate") or competition.get("date"))
        if key and start is not None:
            duration = next(duration for candidate, _label, _practice, duration in _F1_SESSION_ORDER if candidate == key)
            label = next(label for candidate, label, _practice, _duration in _F1_SESSION_ORDER if candidate == key)
            sessions[key] = (start, duration, label, next(practice for candidate, _name, practice, _duration in _F1_SESSION_ORDER if candidate == key))
    return {
        "round": str(event.get("id") or "event"),
        "race_name": str(event.get("name") or "Formula 1"),
        "track": str(circuit.get("fullName") or address.get("city") or ""),
        "location": str(address.get("city") or ""),
        "sessions": sessions,
    }


def _f1_relevant_sessions(races: Sequence[Mapping[str, Any]], now: datetime, timezone_name: str) -> list[tuple[Mapping[str, Any], str, str, bool, datetime, datetime, str]]:
    for race in sorted(races, key=lambda item: min((value[0] for value in _mapping(item.get("sessions")).values()), default=datetime.max.replace(tzinfo=timezone.utc))):
        sessions = []
        for key, start_data in _mapping(race.get("sessions")).items():
            start, duration, label, practice = start_data
            end = start + timedelta(minutes=duration)
            sessions.append((key, label, practice, start, end))
        if not sessions:
            continue
        weekend_start = min(value[3] for value in sessions)
        weekend_end = max(value[4] for value in sessions)
        if weekend_start - timedelta(days=1) <= now <= weekend_end + timedelta(days=1):
            relevant = []
            for key, label, practice, start, end in sessions:
                if start <= now <= end:
                    state = "in"
                elif end < now and _in_reset_window(start, now, timezone_name):
                    state = "post"
                elif start > now and start - now < timedelta(hours=48):
                    state = "pre"
                else:
                    continue
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
    return f"https://media.formula1.com/image/upload/c_lfill,h_224/q_auto/v1740000001/common/f1/2026/{slug}/2026{slug}carright.webp" if slug else ""


def _indycar_relevant_session(sessions: Sequence[tuple[str, str, datetime]], now: datetime, timezone_name: str) -> tuple[str, str, datetime, datetime, str] | None:
    best_post = None
    for event_name, session_name, start in sorted(sessions, key=lambda value: value[2]):
        duration = _INDYCAR_SESSION_DURATIONS.get(session_name, 60)
        end = start + timedelta(minutes=duration)
        if start <= now <= end:
            return event_name, session_name, start, end, "in"
        if end < now and _in_reset_window(start, now, timezone_name):
            best_post = (event_name, session_name, start, end, "post")
        elif start > now:
            return best_post or (event_name, session_name, start, end, "pre")
    return best_post


def _indycar_schedule_index(value: str) -> list[tuple[str, str]]:
    marker = value.find("Full Schedule</h2>")
    body = value[marker:] if marker >= 0 else value
    result = []
    seen = set()
    for year, slug in _INDYCAR_INDEX_HREF_RE.findall(body):
        if slug in seen:
            break
        seen.add(slug)
        result.append((year, slug))
    return result


def _indycar_event_sessions(value: str, year: int, event_name: str) -> list[tuple[str, str, datetime]]:
    markers = [(match.start(), "day", match.groups()) for match in _INDYCAR_DAY_RE.finditer(value)]
    markers.extend((match.start(), "entry", match.groups()) for match in _INDYCAR_ENTRY_RE.finditer(value))
    markers.sort(key=lambda item: item[0])
    current_day = None
    result = []
    for _position, kind, data in markers:
        if kind == "day":
            current_day = data
            continue
        if not current_day or not data[1].startswith("NTT INDYCAR SERIES"):
            continue
        time_text, description = data
        session_name = description.split(" - ", 1)[-1].strip()
        time_text = time_text.replace(" ET", "").strip()
        try:
            local = datetime.strptime(f"{current_day[0]} {current_day[1]} {year} {time_text}", "%b %d %Y %I:%M%p").replace(tzinfo=ZoneInfo("America/New_York"))
        except ValueError:
            continue
        result.append((event_name, session_name, local.astimezone(timezone.utc)))
    return result


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


def _indycar_session_name(raw_type: str, value: str) -> str:
    lowered = (value or raw_type or "Race").lower()
    if "fast 12" in lowered:
        return "Fast 12"
    if "fast 6" in lowered:
        return "Fast 6"
    if "fast 10" in lowered:
        return "Fast 10"
    if "qual" in lowered:
        return "Qualifying"
    if "practice" in lowered or lowered == "p":
        return "Practice"
    if "warm" in lowered:
        return "Warm Up"
    if "race" in lowered or lowered == "r":
        return "Race"
    return value or raw_type or "Race"


def _indycar_driver(
    item: Mapping[str, Any],
    index: Mapping[str, Mapping[str, Any]],
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
    flag = _normalize_flag(item.get("flag") or item.get("status"))
    speed = str(item.get("qualSpeed") or item.get("BestSpeed") or item.get("LastSpeed") or "").strip()
    best_time = str(item.get("qualTime") or item.get("bestLapTime") or "").strip()
    raw_gap = str(item.get("diff") or item.get("gap") or "").strip()
    qualifying_metric = "mph" if track_type == "O" else "time"
    qualifying_value = f"{float(speed):.3f}" if qualifying_metric == "mph" and _number(speed) is not None else best_time
    gap = qualifying_value if session_type == "Q" else "Leader" if pos == 1 and not raw_gap else raw_gap
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
        "speed": speed,
        "best_time": best_time,
        "status": str(item.get("status") or "Active"),
        "on_track": str(item.get("onTrack") or "").lower() == "true",
        "flag": flag,
    }


def _team_livery(value: object) -> tuple[str, str]:
    lower = str(value or "").lower()
    return next((colors for key, colors in _INDYCAR_LIVERIES.items() if key in lower), ("#888888", "#333333"))


def _indycar_live_status(session_type: str, flag: str, lap: int, total_laps: int, time_to_go: str) -> str:
    if session_type == "R" and total_laps:
        return f"Lap {lap}/{total_laps}"
    if session_type in {"Q", "F"} and time_to_go:
        return time_to_go
    return {"YELLOW": "YELLOW", "RED": "RED FLAG", "CHECKERED": "CHECKERED"}.get(flag, "GREEN")


def _normalize_flag(value: object) -> str:
    text = re.sub(r"[^A-Za-z ]", "", str(value or "")).strip().upper()
    return {"YELLOW FLAG": "YELLOW", "RED FLAG": "RED", "CHECKERED FLAG": "CHECKERED"}.get(text, text or "GREEN")


def _driver_abbr(first: object, last: object) -> str:
    letters = "".join(char for char in str(last or "") if char.isalnum())
    if len(letters) >= 3:
        return letters[:3].upper()
    return (letters + "".join(char for char in str(first or "") if char.isalnum()))[:3].upper() or "???"


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


def _first_text(value: Mapping[str, Any], *keys: str) -> str:
    return next((str(value[key]).strip() for key in keys if value.get(key)), "")


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


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


__all__ = ["LiveRacingSource"]
