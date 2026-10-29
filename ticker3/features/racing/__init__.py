"""The current or next Formula 1 session, with track weather from the weather feature.

The racing worker does not read weather. Its record holds a reference to the
weather feature, and the core joins the track weather into the screen.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ticker3.sdk.feature import Feature, Poll

SEASON_URL = "https://api.jolpi.ca/ergast/f1/current.json"
SESSIONS = (("FirstPractice", "PRACTICE 1", 60), ("SecondPractice", "PRACTICE 2", 60), ("ThirdPractice", "PRACTICE 3", 60),
            ("SprintQualifying", "SPRINT QUALI", 45), ("Sprint", "SPRINT", 45), ("Qualifying", "QUALIFYING", 60),
            ("Race", "RACE", 120))

MANIFEST = {
    "feature": "racing",
    "title": "Formula 1",
    "version": "1",
    "settings": {"fields": {"series": {"type": "enum", "values": ["f1"], "default": "f1"}}},
    "templates": json.loads(Path(__file__).with_name("templates.json").read_text(encoding="utf-8")),
}


def sessions(payload: dict[str, Any]) -> list[tuple[datetime, int, str, dict[str, Any]]]:
    """Return each session of the season as start, minutes, name, and race."""
    found = []
    for race in payload["MRData"]["RaceTable"]["Races"]:
        for key, name, minutes in SESSIONS:
            source = race if key == "Race" else race.get(key)
            if source and source.get("date") and source.get("time"):
                start = datetime.fromisoformat(f"{source['date']}T{source['time'].replace('Z', '+00:00')}")
                found.append((start, minutes, name, race))
    return sorted(found, key=lambda item: item[0])


def records(payload: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Return the record `session` for the live session, or else for the next one."""
    for start, minutes, name, race in sessions(payload):
        end = start + timedelta(minutes=minutes)
        if end <= now:
            continue
        location = race["Circuit"]["Location"]
        state = "in" if start <= now else "pre"
        return [{"id": "session", "template": "racing.session", "tags": ["f1"], "values": {
            "event": race["raceName"].replace("Grand Prix", "GP").upper()[:24],
            "circuit": race["Circuit"]["circuitName"][:32],
            "place": f"{location['locality']}, {location['country']}"[:32],
            "round": f"R{race['round']}",
            "session": name, "state": state, "starts": int(start.timestamp()),
            "weather": {"$ref": {"feature": "weather", "record": "now",
                                 "config": {"latitude": float(location["lat"]), "longitude": float(location["long"])}}},
        }}]
    return []


class Racing(Feature):
    manifest = MANIFEST

    async def poll(self, config, context):
        payload = await context.http.get_json(SEASON_URL, reuse=3600)
        now = datetime.fromtimestamp(context.now(), timezone.utc)
        found = records(payload, now)
        if not found:
            return Poll([], 21600)
        start = found[0]["values"]["starts"]
        # Read again when the session starts and when it ends. The schedule rarely changes.
        delay = 60 if found[0]["values"]["state"] == "in" else max(60, min(3600, start - context.now()))
        return Poll(found, delay)


def create() -> Racing:
    return Racing()
