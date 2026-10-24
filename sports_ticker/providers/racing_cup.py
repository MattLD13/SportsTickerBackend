"""Read NASCAR Cup schedules and timing from race-specific official feeds."""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

from .sports_display import nascar_competition_stage
from .racing_live import (
    _mapping, _sequence, _parse_datetime, _session_lifecycle_state, _format_local_time,
    _format_qualifying_time, _nascar_driver, _nascar_short_event, _NASCAR_FLAGS, _CAUTION_FLAGS,
)


class CupRacingSource:
    """Keep Cup timing separate from the rotating NASCAR series feed."""

    def __init__(self, client, weather, *, now, clock, timeout=10):
        self.client, self.weather = client, weather
        self.now, self.clock, self.timeout = now, clock, timeout
        self.schedule: tuple[float, list] = (0, [])
        self.responses: dict[str, tuple[float, dict]] = {}

    def read(self, url: str, ttl: float) -> dict:
        at, cached = self.responses.get(url, (0, {}))
        if cached and self.clock() - at < ttl:
            return cached
        value = dict(_mapping(self.client.get_json(url, timeout=self.timeout)))
        self.responses[url] = self.clock(), value
        return value

    def fetch(self, settings) -> list[dict[str, Any]]:
        now = self.now().astimezone(timezone.utc)
        at, races = self.schedule
        if not races or self.clock() - at >= 1800:
            payload = self.client.get_json(
                f"https://cf.nascar.com/cacher/{now.year}/race_list_basic.json", timeout=self.timeout,
            )
            races = list(_sequence(_mapping(payload).get("series_1")))
            self.schedule = self.clock(), races
        records = []
        for race in races:
            if race.get("series_id") != 1:
                continue
            for session in _sequence(race.get("schedule")):
                run_type = int(session.get("run_type") or 0)
                start = _parse_datetime(session.get("start_time_utc"))
                if run_type not in {1, 2, 3} or start is None:
                    continue
                end = start + timedelta(minutes=360 if run_type == 3 else 90)
                state = _session_lifecycle_state(start, end, now, settings.timezone)
                if state is None:
                    continue
                identifier = int(race["race_id"])
                year = int(race["race_season"])
                timed = run_type != 3
                label = {1: "Practice", 2: "Qualifying", 3: "Race"}[run_type]
                timing: dict = {}
                drivers = []
                if start <= now:
                    if run_type == 3:
                        timing = self.read(f"https://cf.nascar.com/live/feeds/series_1/{identifier}/live_feed.json", 8)
                        if timing.get("series_id") != 1 or timing.get("race_id") != identifier:
                            raise ValueError("NASCAR Cup timing does not match its scheduled race")
                        if int(timing.get("run_type") or 0) == 3:
                            drivers = [driver for item in _sequence(timing.get("vehicles"))
                                       if (driver := _nascar_driver(item)) is not None]
                        else:
                            timing = {}
                    else:
                        weekend = self.read(f"https://cf.nascar.com/cacher/{year}/1/{identifier}/weekend-feed.json", 30)
                        run = next((r for r in _sequence(weekend.get("weekend_runs"))
                                    if r.get("run_type") == run_type), {})
                        for row in _sequence(run.get("results")):
                            driver = _nascar_driver({
                                "vehicle_number": row.get("vehicle_number") or row.get("car_number"),
                                "running_position": row.get("finishing_position"),
                                "driver": {"full_name": row.get("driver_name")},
                                "delta": row.get("delta_leader"), "is_on_track": False,
                            })
                            if driver is not None:
                                best = float(row.get("best_lap_time") or 0)
                                driver["best_time"] = _format_qualifying_time(best) if best else ""
                                driver["gap"] = driver["best_time"] if driver["pos"] == 1 else driver["gap"]
                                drivers.append(driver)
                total = int(timing.get("laps_in_race") or race.get("scheduled_laps") or 0) if not timed else 0
                lap = int(timing.get("lap_number") or 0)
                flag_number = int(timing.get("flag_state") or 0)
                complete = (not timed and total > 0 and lap >= total) or flag_number == 4
                if complete:
                    state = "post"
                elif state == "in" and not drivers:
                    state = "pre"
                flag = "CHECKERED" if state == "post" else "WHITE" if state == "pre" else _NASCAR_FLAGS.get(flag_number, "")
                event = _nascar_short_event(str(race["race_name"]), str(race["track_name"]))
                records.append({
                    "id": f"nascar_{identifier}_{run_type}", "type": "racing", "sport": "nascar",
                    "competition_stage": nascar_competition_stage(race),
                    "state": state, "status": "FINAL" if state == "post" else _format_local_time(start, settings.timezone)
                    if state == "pre" else f"Lap {lap}/{total}" if lap and total else flag,
                    "startTimeUTC": start.isoformat(), "away_abbr": event, "home_abbr": label,
                    "away_score": "", "home_score": "", "is_shown": True,
                    "nascar": {
                        "event_name": event, "short_name": event, "track_name": str(race["track_name"]),
                        "session_type": label, "session_name": label, "qualifying_metric": "time" if timed else "",
                        "lap": lap, "total_laps": total, "laps_remaining": max(0, total - lap),
                        "flag": flag, "caution": flag in _CAUTION_FLAGS,
                        "stage": f"Stage {timing['stage']['stage_num']}" if _mapping(timing.get("stage")).get("stage_num") else "",
                        "drivers": sorted(drivers, key=lambda driver: driver["pos"]),
                        "weather": self.weather.fetch(str(race["track_name"])),
                    },
                })
        return records
