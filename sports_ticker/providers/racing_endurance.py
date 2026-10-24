"""Adapt official WEC, IMSA, and Nürburgring timing into racing records."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .racing_live import (
    _mapping, _sequence, _parse_datetime, _integer, _format_duration, _format_qualifying_time,
    _session_lifecycle_state, _format_local_time, _normalize_racing_flag, _CAUTION_FLAGS,
)
from .racing_sockets import AlkamelSnapshot, open_timing_socket, read_nbr24_snapshot


_WEC = "https://insights.griiip.com"
_CLASS_KEYS = {"GTP": "gtp", "GTDPRO": "gtd_pro", "GTD": "gtd", "LMP2": "lmp2", "HYPERCAR": "hypercar", "LMGT3": "lmgt3"}


def _epoch(value: object) -> datetime | None:
    if not value:
        return None
    number = float(value)
    return datetime.fromtimestamp(number / 1000 if number > 100000000000 else number, timezone.utc)


def _state(start: datetime, end: datetime, now: datetime, zone: str) -> str | None:
    # A race that crosses midnight retains its result until the reset after its finish.
    return _session_lifecycle_state(end if end < now else start, end, now, zone)


def _indexed(rows: object, key: str = "carNumber") -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in _sequence(rows):
        name = str(row.get(key) or "")
        if name and (name not in result or str(row.get("ts", "")) >= str(result[name].get("ts", ""))):
            result[name] = row
    return {name: row for name, row in result.items() if not row.get("isDeleted")}


def _gap(milliseconds: object, laps: object = 0) -> str:
    if _integer(laps) > 0:
        return f"+{_integer(laps)}L"
    try:
        value = float(milliseconds)
    except (ValueError, TypeError):
        return ""
    return f"+{value / 1000:.3f}" if value >= 0 else ""


class RacingImageCatalog:
    """Resolve a car by series, class, number, and verified season."""

    def __init__(self) -> None:
        self.entries = json.loads(Path(__file__).with_name("racing_grid_verified_db.json").read_text(encoding="utf-8"))

    def image(self, sport: str, car: str, class_name: str, year: int) -> str:
        if year != 2026:
            return ""
        if sport == "nbr24":
            return f"https://www.24h-rennen.de/wp-content/uploads/teilnehmer_26h/small/{car}.jpg" if re.fullmatch(r"\d{1,4}", car) else ""
        group = _CLASS_KEYS.get(class_name.replace(" ", "").upper(), "")
        url = str(self.entries.get(sport, {}).get(group, {}).get(car, ""))
        if sport == "wec":
            number = re.search(r"-wec-(\d+)-", url)
        else:
            number = re.search(r"_(?:GTP|GTDPRO|GTD|P2)_(\d+)_", url) or re.search(r"_(\d+)_\d+x\d+", url)
        if number and number.group(1) != car:
            return ""
        return url


class EnduranceRacingSource:
    """Read session identity before accepting a live endurance classification."""

    def __init__(self, client, weather, *, now, clock, timeout=10, socket_factory=open_timing_socket):
        self.client, self.weather, self.now, self.clock = client, weather, now, clock
        self.timeout, self.socket_factory = timeout, socket_factory
        self.cache: dict[str, tuple[float, Any]] = {}
        self.images = RacingImageCatalog()

    def read(self, url: str, ttl: float):
        at, value = self.cache.get(url, (0.0, None))
        if value is None or self.clock() - at >= ttl:
            value = self.client.get_json(url, timeout=self.timeout)
            self.cache[url] = self.clock(), value
        return value

    def fetch(self, sport: str, settings) -> list[dict[str, Any]]:
        if sport == "wec":
            return self.fetch_wec(settings)
        if sport == "imsa":
            return self.fetch_imsa(settings)
        if sport == "nbr24":
            return self.fetch_nbr24(settings)
        raise ValueError("Unknown endurance series")

    def record(self, sport, identifier, event, track, session, state, start, end, drivers, flag, settings,
               *, lap=0, total=0, country="", weather=None):
        now = self.now().astimezone(timezone.utc)
        timed = any(word in session.lower() for word in ("prac", "qual", "hyperpole", "warm"))
        grouped = defaultdict(list)
        for driver in sorted(drivers, key=lambda item: item["pos"]):
            grouped[driver.get("class", "")].append(driver)
        for members in grouped.values():
            for index, driver in enumerate(members, 1):
                driver["class_pos"] = index
                driver["car_illustration"] = self.images.image(sport, driver["car"], driver.get("class", ""), (start or now).year)
        short = ("WEC " if sport == "wec" else "IMSA " if sport == "imsa" else "") + event
        status = "FINAL" if state == "post" else (_format_local_time(start, settings.timezone) if start else "WAITING") if state == "pre" else flag or "LIVE"
        return {
            "id": f"{sport}_{identifier}", "type": "racing", "sport": sport, "state": state,
            "status": status, "is_shown": True, **({"startTimeUTC": start.isoformat()} if start else {}),
            "away_abbr": short, "home_abbr": session, "away_score": "", "home_score": "",
            sport: {
                "event_name": short, "short_name": short, "track_name": track,
                "session_type": session, "session_name": session,
                "qualifying_metric": "time" if timed else "", "position_scope": "overall",
                "lap": lap, "total_laps": total, "laps_remaining": max(0, total - lap),
                "time_to_go": _format_duration((end - now).total_seconds()) if state == "in" and end else "",
                "flag": "CHECKERED" if state == "post" else "WHITE" if state == "pre" else flag,
                "caution": state == "in" and flag in _CAUTION_FLAGS,
                "drivers": sorted(drivers, key=lambda item: item["pos"]),
                "weather": weather if weather and weather.get("available") else self.weather.fetch(track, country),
            },
        }

    def fetch_wec(self, settings) -> list[dict[str, Any]]:
        calendar = self.read(f"{_WEC}/meta/series/10/active-season-calendar", 60)
        now = self.now().astimezone(timezone.utc)
        records = []
        for season in _sequence(calendar):
            if season.get("seriesId") != 10:
                continue
            for event in _sequence(season.get("events")):
                for session in _sequence(event.get("sessions")):
                    start, end = _parse_datetime(session.get("startTime")), _parse_datetime(session.get("endTime"))
                    if start is None or end is None:
                        continue
                    state = _state(start, end, now, settings.timezone)
                    if state is None:
                        continue
                    sid = int(session["id"])
                    drivers, flag, lap = [], "", 0
                    if state != "pre" or (start - now).total_seconds() <= 900:
                        data = self.read(f"{_WEC}/api/v2/public/live/session/{sid}/bootstrap", 15 if state == "in" else 300)
                        info = _mapping(data.get("sessionInfo"))
                        if info.get("seriesId") != 10 or info.get("sid") != sid:
                            raise ValueError("WEC timing does not match its session")
                        official = self.read(f"{_WEC}/meta/sessions/{sid}/results", 300) if state == "post" else {}
                        drivers = wec_drivers(data, timed=str(session.get("sessionType")) != "Race", official=official)
                        flags = _sequence(data.get("raceFlags"))
                        flag = _normalize_racing_flag(flags[-1].get("flag")) if flags else ""
                        lap = max((_integer(row.get("lapNumber")) for row in _sequence(data.get("laps"))), default=0)
                        if now >= start and (session.get("seenChequered") or flag == "CHECKERED"):
                            state = "post"
                        if state == "in" and not drivers:
                            raise ValueError("WEC active session has no classification")
                    track = str(event.get("trackName") or "")
                    event_name = re.sub(r"^FIA WEC\s*-\s*", "", str(event.get("eventName") or track))
                    event_name = re.sub(r"^\d+ Hours of\s+", "", event_name, flags=re.IGNORECASE)
                    records.append(self.record("wec", sid, event_name, track, str(session["name"]), state,
                                               start, end, drivers, flag, settings, lap=lap,
                                               country=str(_mapping(event.get("trackCountry")).get("codeTwo") or "")))
        return records

    def imsa_snapshot(self) -> dict[str, Any]:
        at, cached = self.cache.get("imsa", (0, None))
        if cached is not None and self.clock() - at < 15:
            return cached
        connection = AlkamelSnapshot(self.socket_factory, timeout=self.timeout)
        try:
            docs = connection.read([("livetimingFeed", ["imsa"])])
            feed = next(iter(docs.get("feeds", ())), {})
            if not feed:
                raise ValueError("Official IMSA feed is unavailable")
            docs = connection.read([("sessionInfo", [feed.get("sessions", [])])])
            sessions = [row for row in docs.get("session_info", ())
                        if "WEATHERTECH" in str(_mapping(row.get("info")).get("champShortName", "")).upper()]
            if not sessions:
                self.cache["imsa"] = self.clock(), {}
                return {}
            info = max(sessions, key=lambda row: float(_mapping(row.get("info")).get("date") or 0))
            details = _mapping(info.get("info"))
            end = _epoch(details.get("lastSessionTime")) or _epoch(details.get("date"))
            if end is not None and self.now().astimezone(timezone.utc) - end < timedelta(hours=36):
                ref = info["session"]
                names = ["standings", "entry", "sessionStatus", "weather", "sessionClasses", "raceControl"]
                docs = connection.read([(name, [ref]) for name in names])
            result = {name: values[0] for name, values in docs.items() if values}
            result["session_info"] = info
            self.cache["imsa"] = self.clock(), result
            return result
        finally:
            connection.close()

    def fetch_imsa(self, settings) -> list[dict[str, Any]]:
        data = self.imsa_snapshot()
        info_doc = _mapping(data.get("session_info"))
        info = _mapping(info_doc.get("info"))
        start, end = _epoch(info.get("date")), _epoch(info.get("lastSessionTime"))
        if start is None or end is None:
            return []
        status = _mapping(_mapping(data.get("session_status")).get("status"))
        if not info.get("closed"):
            end = start + timedelta(seconds=float(status.get("finalTime") or 86400))
        now = self.now().astimezone(timezone.utc)
        state = _state(start, end, now, settings.timezone)
        if state is None:
            return []
        if info.get("closed") and now >= end:
            state = "post"
        drivers = imsa_drivers(data, timed=info.get("type") != "RACE")
        track = str(info.get("eventShortName") or "")
        flag = {"GF": "GREEN", "YF": "YELLOW", "RF": "RED FLAG", "SC": "SAFETY CAR", "FF": "CHECKERED"}.get(str(status.get("currentFlag")), "")
        ref = _mapping(info_doc.get("session")).get("$value")
        return [self.record("imsa", ref, str(info.get("eventShortName") or info["eventName"]), track,
                            str(info.get("name") or "Race"), state, start, end, drivers, flag, settings,
                            lap=_integer(status.get("elapsedLaps")), total=_integer(status.get("finalLaps")))]

    def fetch_nbr24(self, settings) -> list[dict[str, Any]]:
        at, data = self.cache.get("nbr24", (0, None))
        if data is None or self.clock() - at >= 15:
            data = read_nbr24_snapshot(self.socket_factory, timeout=self.timeout)
            self.cache["nbr24"] = self.clock(), data
        if not data:
            return []
        header, track = _mapping(data.get("results")), _mapping(data.get("track"))
        cup = str(header.get("CUP") or "")
        if "24" not in cup or not any(term in str(header.get("TRACKNAME", "")).lower() for term in ("nürburgring", "nuerburgring", "nurburgring", "nordschleife")):
            return []
        now = self.now().astimezone(timezone.utc)
        value = track.get("ENDTIME")
        if isinstance(value, Mapping):
            value = value.get("value")
        end = _epoch(value) if value and float(value) > 100000000000 else None
        label = str(header.get("HEAT") or "Race")
        duration = timedelta(hours=24 if str(header.get("HEATTYPE")).upper() == "R" else 2)
        start = end - duration if end else None
        flag = str(track.get("TRACKSTATE") or "").strip().upper()
        flag = _normalize_racing_flag(flag) if flag in {
            "GREEN", "RED", "RED FLAG", "YELLOW", "CHECKERED", "CHEQUERED",
            "SAFETY CAR", "SC", "CODE60", "CODE 60", "WHITE", "FCY",
        } else "UNKNOWN"
        if flag == "CHECKERED" and end is None:
            return []
        state = _state(start, end, now, settings.timezone) if start and end else "in"
        if state is None:
            return []
        drivers = [{
            "pos": _integer(row.get("RANK") or row.get("POSITION"), 999),
            "car": str(row.get("STNR")), "name": str(row.get("NAME") or ""),
            "team": str(row.get("TEAM") or ""), "manufacturer": str(row.get("CAR") or ""),
            "display_name": f"#{row.get('STNR')} {row.get('CAR') or row.get('TEAM') or ''}",
            "class": str(row.get("CLASSNAME") or ""), "class_pos": _integer(row.get("CLASSRANK")),
            "gap": str(row.get("GAP") or ""), "best_time": str(row.get("FASTESTLAP") or ""),
        } for row in _sequence(header.get("RESULT"))]
        if not drivers:
            state = "pre"
        record = self.record("nbr24", f"{header.get('EXPORTID')}_{header.get('SESSION')}", "Nürburgring 24h",
                             str(header.get("TRACKNAME")), label, state, start, end, drivers, flag, settings, country="de")
        if str(track.get("TIMESTATE")) == "0" and value:
            record["nbr24"]["time_to_go"] = _format_duration(float(value) / 1000)
            record["nbr24"]["session_clock_paused"] = True
        return [record]


def wec_drivers(data: Mapping[str, Any], *, timed: bool, official: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    ranks, gaps = _indexed(data.get("ranks")), _indexed(data.get("gaps"))
    best, running = _indexed(data.get("bestLaps")), _indexed(data.get("runningStatuses"))
    final = _indexed((official or {}).get("results"), "sessionParticipantId")
    result = []
    for participant in _sequence(data.get("participants")):
        car = str(participant.get("carNumber") or "")
        rank, gap = ranks.get(car, {}), gaps.get(car, {})
        outcome = final.get(str(participant.get("pid")), {})
        if outcome:
            rank = {"position": outcome["finishedAt"], "overallPosition": outcome["overallFinishedAt"]}
            gap = {"gapToFirstMillis": outcome.get("gapFromFirst"), "gapToFirstLaps": outcome.get("gapFromFirstLaps")}
        if not rank:
            continue
        class_pos = _integer(rank.get("position"))
        lap_time = float(best.get(car, {}).get("lapTimeMillis") or 0)
        formatted = _format_qualifying_time(lap_time / 1000) if lap_time else ""
        delta = formatted if timed and class_pos == 1 else "Leader" if class_pos == 1 else _gap(gap.get("gapToFirstMillis"), gap.get("gapToFirstLaps"))
        driver = next((d for d in _sequence(participant.get("drivers")) if d.get("externalDriverID") == participant.get("currentDriverId")), {})
        result.append({
            "pos": _integer(rank.get("overallPosition"), 999), "class_pos": class_pos,
            "car": car, "class": str(participant.get("classId") or ""),
            "name": str(driver.get("displayName") or participant.get("displayName") or ""),
            "abbr": str(driver.get("threeLettersName") or participant.get("threeLettersName") or ""),
            "team": str(participant.get("teamName") or ""), "manufacturer": str(participant.get("manufacturer") or ""),
            "display_name": f"#{car} {participant.get('manufacturer') or participant.get('teamName') or ''}",
            "gap": delta, "best_time": formatted, "status": str(running.get(car, {}).get("status") or ""),
        })
    return result


def imsa_drivers(data: Mapping[str, Any], *, timed: bool) -> list[dict[str, Any]]:
    entry = _mapping(_mapping(data.get("session_entry")).get("entry"))
    standings = _mapping(_mapping(_mapping(data.get("standings")).get("standings")).get("standings"))
    drivers = []
    for value in standings.values():
        fields = str(value.get("data") or "").split(";")
        if len(fields) < 9:
            raise ValueError("IMSA standing does not match the published timing schema")
        pos, car, status, class_pos, laps = fields[:5]
        person = _mapping(entry.get(car))
        best = float(value.get("bestLapTime") or 0)
        drivers.append({
            "pos": _integer(pos, 999), "car": car,
            "class": str(person.get("class") or value.get("class") or ""), "class_pos": _integer(class_pos),
            "name": f"{person.get('firstname', '')} {person.get('lastname', '')}".strip(),
            "team": str(person.get("team") or ""),
            "manufacturer": str(person.get("vehicle") or ""),
            "display_name": f"#{car} {person.get('vehicle') or person.get('team') or ''}",
            "gap": "", "best_time": _format_qualifying_time(best / 1000) if best else "",
            "status": status, "on_track": fields[8] == "TRACK", "laps_completed": _integer(laps),
            "elapsed_ms": float(value.get("elapsedTime") or 0), "best_lap_ms": best,
        })
    groups = defaultdict(list)
    for driver in sorted(drivers, key=lambda row: row["pos"]):
        groups[driver["class"]].append(driver)
    for members in groups.values():
        leader = members[0]
        for position, driver in enumerate(members, 1):
            driver["class_pos"] = position
            if position == 1:
                driver["gap"] = leader["best_time"] if timed else "Leader"
            elif timed:
                driver["gap"] = _gap(driver["best_lap_ms"] - leader["best_lap_ms"])
            else:
                driver["gap"] = _gap(driver["elapsed_ms"] - leader["elapsed_ms"], leader["laps_completed"] - driver["laps_completed"])
    return drivers
