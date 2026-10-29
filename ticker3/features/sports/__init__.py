"""Scores from the ESPN scoreboards. Each league is one subscription for all tickers."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ticker3.sdk.feature import Feature, Poll

SCOREBOARD = "https://site.web.api.espn.com/apis/site/v2/sports/{path}/scoreboard"


class League:
    def __init__(self, path: str, sport: str, regulation: int, periods: str, *, halves: bool = False, query: str = "") -> None:
        self.path, self.sport, self.regulation, self.periods, self.halves, self.query = path, sport, regulation, periods, halves, query


LEAGUES = {
    "nfl": League("football/nfl", "football", 4, "Q"),
    "ncaaf": League("football/college-football", "football", 4, "Q", query="groups=80"),
    "nba": League("basketball/nba", "basketball", 4, "Q"),
    "wnba": League("basketball/wnba", "basketball", 4, "Q"),
    "ncaab": League("basketball/mens-college-basketball", "basketball", 2, "H", halves=True, query="groups=50"),
    "nhl": League("hockey/nhl", "hockey", 3, "P"),
    "mlb": League("baseball/mlb", "baseball", 9, ""),
}
RANK = {"in": 0, "pre": 1, "post": 2}

MANIFEST = {
    "feature": "sports",
    "title": "Sports scores",
    "version": "1",
    "settings": {"fields": {
        "leagues": {"type": "list", "items": {"type": "enum", "values": list(LEAGUES)}, "default": ["nfl", "nba", "nhl", "mlb"],
                    "min_items": 1, "role": "fanout", "as": "league"},
        "teams": {"type": "list", "items": {"type": "string", "lower": True, "pattern": "[a-z]+:[a-z0-9]{1,6}"}, "default": [],
                  "role": "filter"},
    }},
    "templates": json.loads(Path(__file__).with_name("templates.json").read_text(encoding="utf-8")),
}


def scoreboard_url(league: str) -> str:
    entry = LEAGUES[league]
    return SCOREBOARD.format(path=entry.path) + (f"?{entry.query}" if entry.query else "")


def records(payload: dict[str, Any], league: str) -> list[dict[str, Any]]:
    """Return one card record for each event of one league scoreboard."""
    entry = LEAGUES[league]
    found = []
    for index, event in enumerate(payload.get("events", ())):
        competition = (event.get("competitions") or [{}])[0]
        teams = {team.get("homeAway"): team for team in competition.get("competitors", ())}
        if set(teams) != {"home", "away"}:
            continue
        status = event.get("status") or competition.get("status") or {}
        state = (status.get("type") or {}).get("state", "pre")
        values: dict[str, Any] = {"sport": entry.sport, "league": league, "state": state}
        for side in ("away", "home"):
            team = teams[side]["team"]
            values[f"{side}.abbr"] = team.get("abbreviation", "")[:5]
            values[f"{side}.color"] = _color(team.get("color"), team.get("alternateColor"))
            values[f"{side}.logo"] = team.get("logo") or ""
            values[f"{side}.score"] = "" if state == "pre" else str(teams[side].get("score", "0"))
        if state == "pre":
            values["starts"] = int(_parse_time(event.get("date", "")).timestamp())
        else:
            values["status"] = status_text(entry, status, state)
        if state == "post":
            scores = [_integer(teams[side].get("score")) for side in ("away", "home")]
            if scores[0] != scores[1]:
                values["winner"] = "away" if scores[0] > scores[1] else "home"
        if state == "in":
            values.update(_situation(entry, competition, teams))
        tags = sorted({f"{league}:{values[f'{side}.abbr'].lower()}" for side in ("away", "home") if values[f"{side}.abbr"]})
        # Live games come first, then games to start, then final games. Each group runs by start time.
        minute = int(_parse_time(event["date"]).timestamp() // 60) if event.get("date") else index
        found.append({"id": f"{league}-{event['id']}", "template": "sports.card", "values": values, "tags": tags,
                      "order": RANK.get(state, 1) * 100_000_000 + minute % 100_000_000})
    return found


def status_text(entry: League, status: dict[str, Any], state: str) -> str:
    """Return the short status text: Q3 8:12, HALF, END P2, BOT 7, FINAL OT, and so on."""
    kind = status.get("type") or {}
    detail = str(kind.get("shortDetail") or kind.get("detail") or "").strip()
    upper = detail.upper()
    period = _integer(status.get("period"))
    clock = str(status.get("displayClock") or "").strip()
    if any(word in upper for word in ("POSTPON", "CANCEL", "SUSPEND", "DELAY")):
        return detail.split(",", 1)[0].upper()[:12]
    if state == "post":
        extra = period - entry.regulation
        if entry.sport == "baseball" or extra <= 0:
            return "FINAL"
        if entry.sport == "hockey" and re.search(r"\bS/?O\b|SHOOTOUT", upper):
            return "FINAL S/O"
        return f"FINAL OT{extra if extra > 1 else ''}"
    if entry.sport == "baseball":
        match = re.match(r"(TOP|BOT|BOTTOM|MID|MIDDLE|END)\s+(\d+)", upper)
        if match:
            return f"{match.group(1)[:3]} {match.group(2)}"
        return detail.upper()[:12] or "LIVE"
    if kind.get("name") == "STATUS_HALFTIME" or "HALFTIME" in upper:
        return "HALF"
    label = _period(entry, period)
    if upper.startswith("END OF") or kind.get("name") == "STATUS_END_PERIOD" or re.fullmatch(r"0+(:0+)?(\.0+)?", clock or "x"):
        return f"END {label}"
    return f"{label} {clock}".strip()


def _period(entry: League, period: int) -> str:
    if period > entry.regulation:
        extra = period - entry.regulation
        return f"OT{extra if extra > 1 else ''}"
    return f"{entry.periods}{period}" if period else entry.periods


def _situation(entry: League, competition: dict[str, Any], teams: dict[str, Any]) -> dict[str, Any]:
    situation = competition.get("situation") or {}
    values: dict[str, Any] = {}
    if entry.sport == "football":
        holder = str(situation.get("possession") or "")
        for side in ("away", "home"):
            if holder and holder == str(teams[side].get("id") or teams[side]["team"].get("id")):
                values["possession"] = side
        if situation.get("shortDownDistanceText"):
            values["down"] = str(situation["shortDownDistanceText"]).upper()[:16]
        values["redzone"] = bool(situation.get("isRedZone"))
    if entry.sport == "baseball":
        values["bases"] = "".join("1" if situation.get(base) else "0" for base in ("onFirst", "onSecond", "onThird"))
        values["outs"] = _integer(situation.get("outs"))
    return values


def _color(primary: Any, alternate: Any) -> str:
    """Return a team color that shows on an LED panel.

    A dark color falls back to the alternate color, then to white. Dark means a
    perceived brightness below 70 of 255.
    """
    for value in (primary, alternate):
        text = str(value or "").strip().lower().lstrip("#")
        if re.fullmatch(r"[0-9a-f]{6}", text):
            red, green, blue = (int(text[i:i + 2], 16) for i in (0, 2, 4))
            if 0.299 * red + 0.587 * green + 0.114 * blue >= 70:
                return f"#{text}"
    return "#ffffff"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _integer(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class Sports(Feature):
    manifest = MANIFEST

    async def poll(self, config, context):
        league = config["league"]
        found = records(await context.http.get_json(scoreboard_url(league), reuse=2), league)
        states = {record["values"]["state"] for record in found}
        if "in" in states:
            delay = 5
        elif any(record["values"]["state"] == "pre" and record["values"]["starts"] - context.now() < 900 for record in found):
            delay = 30
        else:
            delay = 300
        return Poll(found, delay)


def create() -> Sports:
    return Sports()
