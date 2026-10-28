"""Build stable sport display facts from ESPN scoreboard records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from hashlib import sha1
import unicodedata
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sports_ticker.domain import ContentItem


_FOOTBALL = frozenset(("nfl", "ncf_fbs", "ncf_fcs"))
_COLLEGE_FOOTBALL = frozenset(("ncf_fbs", "ncf_fcs"))
_BASKETBALL = frozenset(("nba", "march_madness"))
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


# Physical flags and race-control boards share explicit identities across devices.
# Labels describe the signal. Scope identifies the affected track, sector, or car.
RACING_FLAGS = {
    "NONE": ("WAIT", "No active flag", "solid", (95, 105, 120), (95, 105, 120)),
    "UNKNOWN": ("?", "Unknown signal", "unknown", (110, 115, 130), (235, 235, 235)),
    "GREEN": ("GREEN", "Track clear", "solid", (55, 190, 90), (55, 190, 90)),
    "YELLOW": ("YEL", "Caution", "solid", (255, 215, 0), (255, 215, 0)),
    "DOUBLE YELLOW": ("2YEL", "Double yellow", "double", (255, 215, 0), (25, 25, 20)),
    "RED FLAG": ("RED", "Session stopped", "solid", (230, 70, 70), (230, 70, 70)),
    "WHITE": ("WHITE", "White flag", "solid", (235, 235, 235), (235, 235, 235)),
    "BLUE": ("BLUE", "Approaching car", "solid", (60, 110, 245), (60, 110, 245)),
    "BLUE YELLOW": ("BLUE", "Approaching car", "diagonal", (60, 110, 245), (255, 215, 0)),
    "BLACK": ("PIT", "Report to pits", "border", (20, 20, 20), (190, 195, 205)),
    "BLACK AND WHITE": ("WARN", "Driving warning", "diagonal_split", (235, 235, 235), (20, 20, 20)),
    "BLACK WHITE CROSS": ("NOSCR", "Scoring stopped", "cross", (20, 20, 20), (235, 235, 235)),
    "MEATBALL": ("MECH", "Mechanical problem", "disc", (20, 20, 20), (255, 130, 0)),
    "SURFACE": ("SURF", "Reduced grip or debris", "stripes", (255, 215, 0), (225, 45, 40)),
    "WHITE RED CROSS": ("RESCU", "Safety personnel or vehicles", "cross", (235, 235, 235), (225, 45, 40)),
    "RED YELLOW CROSS": ("PITCL", "Pit lane closed", "cross", (225, 45, 40), (255, 215, 0)),
    "RED YELLOW STRIPE": ("PITCL", "Pit lane closed", "diagonal", (225, 45, 40), (255, 215, 0)),
    "RED BLACK": ("END", "Session ended", "split", (225, 45, 40), (20, 20, 20)),
    "BLACK ALL": ("PITS", "All cars return to pits", "border", (20, 20, 20), (235, 235, 235)),
    "BLACK FURLED": ("WARN", "Driving warning", "furled", (20, 20, 20), (190, 195, 205)),
    "CHECKERED": ("FIN", "Session finished", "checkered", (235, 235, 235), (25, 25, 25)),
    "STAGE END": ("STAGE", "Stage finished", "checkered", (235, 235, 235), (25, 25, 25)),
    "GREEN CHECKERED": ("STAGE", "Stage finished", "green_checkered", (235, 235, 235), (55, 190, 90)),
    "GREEN CHECKERED YELLOW": ("STG/Y", "Stage finished under caution", "stage_split", (235, 235, 235), (255, 215, 0)),
    "HALFWAY": ("HALF", "Halfway point", "crossed_checkers", (235, 235, 235), (25, 25, 25)),
    "GREEN YELLOW": ("PACE", "Laps count under caution", "split", (55, 190, 90), (255, 215, 0)),
    "GREEN WHITE": ("LAST", "Restart on the last lap", "split", (55, 190, 90), (235, 235, 235)),
    "GWC": ("OT", "Overtime finish procedure", "green_checkered", (235, 235, 235), (55, 190, 90)),
    "SAFETY CAR": ("SC", "Safety car deployed", "board", (255, 180, 0), (20, 20, 20)),
    "SC ENDING": ("SCEND", "Safety car ending", "split", (255, 180, 0), (55, 190, 90)),
    "VSC": ("VSC", "Virtual safety car", "board", (255, 180, 0), (20, 20, 20)),
    "VSC ENDING": ("VSCEN", "Virtual safety car ending", "split", (255, 180, 0), (55, 190, 90)),
    "FCY": ("FCY", "Full course yellow", "double", (255, 215, 0), (25, 25, 20)),
    "SLOW ZONE": ("SLOW", "Local speed-controlled zone", "stripes", (255, 215, 0), (20, 20, 20)),
    "NEXT SLOW": ("NEXT", "Slow zone ahead", "diagonal", (255, 215, 0), (20, 20, 20)),
    "CODE60": ("C60", "Code 60 speed limit", "disc", (145, 65, 195), (235, 235, 235)),
    "NATIONAL START": ("START", "Start by national flag", "board", (235, 235, 235), (35, 80, 145)),
    "LAST LAP": ("LAST", "Last lap", "solid", (235, 235, 235), (235, 235, 235)),
    "WHITE YELLOW": ("W/Y", "White and yellow flags", "split", (235, 235, 235), (255, 215, 0)),
    "WHITE SC": ("W/SC", "White flag and safety car", "split", (235, 235, 235), (255, 180, 0)),
    "LAST LAP YELLOW": ("LASTY", "Last lap under yellow", "split", (235, 235, 235), (255, 215, 0)),
    "LAST LAP SC": ("LASTS", "Last lap behind safety car", "split", (235, 235, 235), (255, 180, 0)),
    "LAST LAP VSC": ("LASTV", "Last lap under virtual safety car", "split", (235, 235, 235), (255, 180, 0)),
    "CHECKERED YELLOW": ("FIN/Y", "Finished under yellow", "finish_split", (235, 235, 235), (255, 215, 0)),
    "CHECKERED SC": ("FINSC", "Finished behind safety car", "finish_split", (235, 235, 235), (255, 180, 0)),
    "CHECKERED VSC": ("FINVS", "Finished under virtual safety car", "finish_split", (235, 235, 235), (255, 180, 0)),
}
RACING_CAUTION_FLAGS = frozenset((
    "YELLOW", "DOUBLE YELLOW", "RED FLAG", "SAFETY CAR", "SC ENDING", "VSC", "VSC ENDING",
    "FCY", "SLOW ZONE", "NEXT SLOW", "CODE60", "GREEN YELLOW", "SURFACE", "WHITE RED CROSS",
    "WHITE YELLOW", "WHITE SC", "LAST LAP YELLOW", "LAST LAP SC", "LAST LAP VSC",
    "CHECKERED YELLOW", "CHECKERED SC", "CHECKERED VSC",
    "GREEN CHECKERED YELLOW",
))
_RACING_FLAG_ALIASES = {
    "RED": "RED FLAG", "RED_FLAG": "RED FLAG", "RF": "RED FLAG", "GREEN FLAG": "GREEN", "GF": "GREEN",
    "YELLOW FLAG": "YELLOW", "YF": "YELLOW", "CAUTION": "YELLOW", "CLEAR": "GREEN",
    "LOCAL YELLOW": "YELLOW", "SINGLE YELLOW": "YELLOW", "YELLOW WAVED": "YELLOW",
    "SINGLE WAVED YELLOW": "YELLOW", "STANDING YELLOW": "YELLOW", "WAVED YELLOW": "YELLOW",
    "DOUBLE WAVED YELLOW": "DOUBLE YELLOW", "DOUBLE YELLOW FLAGS": "DOUBLE YELLOW",
    "CHEQUERED": "CHECKERED", "CHKD": "CHECKERED", "FF": "CHECKERED", "FINISH": "CHECKERED",
    "CHECKERED FLAG": "CHECKERED", "CHEQUERED FLAG": "CHECKERED", "BLACK AND WHITE CHECKERED": "CHECKERED",
    "WF": "WHITE", "WHITE FLAG": "WHITE", "BLUE FLAG": "BLUE",
    "BLUE WITH YELLOW STRIPE": "BLUE YELLOW", "BLUE WITH DIAGONAL YELLOW STRIPE": "BLUE YELLOW",
    "BLACK FLAG": "BLACK", "BLACK WITH WHITE CROSS": "BLACK WHITE CROSS", "BLACK CROSS": "BLACK WHITE CROSS",
    "BLACK WITH ORANGE DISC": "MEATBALL", "BLACK WITH ORANGE DISK": "MEATBALL",
    "BLACK AND ORANGE": "MEATBALL", "BLACK WHITE": "BLACK AND WHITE", "BLACK AND WHITE DIAGONAL": "BLACK AND WHITE",
    "YELLOW RED": "SURFACE", "YELLOW WITH RED STRIPES": "SURFACE", "RED AND YELLOW STRIPES": "SURFACE",
    "ALTERNATING RED AND YELLOW STRIPES": "SURFACE", "OIL FLAG": "SURFACE", "DEBRIS": "SURFACE",
    "WHITE WITH RED CROSS": "WHITE RED CROSS", "WHITE WITH DIAGONAL RED CROSS": "WHITE RED CROSS",
    "RED WITH YELLOW CROSS": "RED YELLOW CROSS", "PIT CLOSED": "RED YELLOW CROSS",
    "RED WITH YELLOW STRIPE": "RED YELLOW STRIPE", "RED FLAG WITH YELLOW STRIPE": "RED YELLOW STRIPE",
    "RED AND BLACK": "RED BLACK", "BLACK FLAG ALL": "BLACK ALL", "ALL BLACK": "BLACK ALL",
    "FURLED BLACK": "BLACK FURLED",
    "CROSSED CHECKERED FLAGS": "HALFWAY", "STAGE CHECKERED": "STAGE END",
    "GREEN AND YELLOW": "GREEN YELLOW", "GREEN AND WHITE": "GREEN WHITE",
    "GREEN WHITE CHECKERED": "GWC", "GREEN-WHITE-CHECKERED": "GWC",
    "GREEN AND WHITE CHECKERED FLAG": "GREEN CHECKERED", "GREEN WHITE CHECKERED FLAG": "GREEN CHECKERED",
    "GREEN WHITE CHECKERED AND YELLOW": "GREEN CHECKERED YELLOW",
    "SC": "SAFETY CAR", "PACE CAR": "SAFETY CAR", "VIRTUAL SAFETY CAR": "VSC",
    "SAFETY CAR ENDING": "SC ENDING", "FULL COURSE YELLOW": "FCY", "CODE 60": "CODE60",
    "NATIONAL FLAG": "NATIONAL START", "ROLLING START": "GREEN", "FORMATION LAP": "NONE",
    "WARMUP": "NONE", "WARM UP": "NONE", "WARM": "NONE", "COLD": "NONE", "NOT ACTIVE": "NONE",
    "PRE": "NONE", "STANDBY": "NONE", "FINAL": "CHECKERED", "STOPPED": "RED FLAG", "STOP": "RED FLAG",
    "CHEQUERED YELLOW": "CHECKERED YELLOW", "CHEQUERED SAFETY CAR": "CHECKERED SC",
    "CHEQUERED VIRTUAL SAFETY CAR": "CHECKERED VSC", "TEMPORARY CHEQUERED": "CHECKERED",
    "WHITE SAFETY CAR": "WHITE SC", "LAST LAP SAFETY CAR": "LAST LAP SC",
    "LAST LAP VIRTUAL SAFETY CAR": "LAST LAP VSC", "C60": "CODE60",
    "BLACK AND RED COMBINED": "RED BLACK", "BLACK AND RED": "RED BLACK",
    "BLACK / WHITE DIVIDED DIAGONALLY": "BLACK AND WHITE",
    "BLACK WITH ORANGE CIRCLE": "MEATBALL", "BLACK FLAG WITH ORANGE CIRCLE": "MEATBALL",
    "BLUE FLAG WITH YELLOW STRIPE": "BLUE YELLOW", "BLACK FLAG WITH WHITE CROSS": "BLACK WHITE CROSS",
    "YELLOW FLAG WITH RED STRIPES": "SURFACE", "RED AND BLACK FLAGS TOGETHER": "RED BLACK",
}


def racing_flag_code(raw: object, series: str = "") -> str:
    """Resolve exact provider aliases. Never treat an unknown value as green."""
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(raw or "").strip()).upper()
    value = " ".join(value.replace("_", " ").replace("-", " ").split())
    value = re.sub(r"\s+IN SECTOR\s+\d+$", "", value)
    if value.endswith(" DEPLOYED"):
        value = value[:-9]
    code = value if value in RACING_FLAGS else _RACING_FLAG_ALIASES.get(value)
    if code:
        return code
    value = " ".join(re.sub(r"\b(?:WAVED|STANDING|MOTIONLESS)\b", "", value).split())
    value = re.sub(r"\s+FLAGS?$", "", value)
    return value if value in RACING_FLAGS else _RACING_FLAG_ALIASES.get(value, "UNKNOWN")


def racing_signal(raw: object, series: str, *, scope: str = "track", car: object = "", sector: object = "") -> dict[str, Any]:
    """Project one reported signal with its scope and physical flag pattern."""
    code = racing_flag_code(raw, series)
    short, meaning, pattern, ink, accent = RACING_FLAGS[code]
    annotated_sector = re.search(r"\bIN SECTOR\s+(\d+)$", str(raw).upper())
    if annotated_sector and not sector:
        scope, sector = "sector", annotated_sector.group(1)
    if scope == "track" and code in {"BLACK", "BLACK AND WHITE", "BLACK WHITE CROSS", "MEATBALL", "BLUE", "BLUE YELLOW", "BLACK FURLED"}:
        scope = "car"
    if scope == "track" and code in {"RED YELLOW CROSS", "RED YELLOW STRIPE"}:
        scope = "pit"
    if scope == "track" and code in {"SLOW ZONE", "NEXT SLOW"}:
        scope = "sector"
    if code == "WHITE":
        meaning = "Last lap" if scope == "track" and series in {"indycar", "nascar", "imsa"} else "Slow vehicle ahead"
        short = "LAST" if meaning == "Last lap" else "SLOW"
    if code == "RED BLACK" and series == "imsa":
        short, meaning = "STOP", "Stop beside the track"
    if code == "BLACK" and series in {"f1", "wec"}:
        short, meaning = "DSQ", "Disqualified; return to pits"
    if code == "BLUE" and series == "nascar" and not car:
        scope, short, meaning = "sector", "HAZ", "Obstruction ahead on road course"
    if code == "YELLOW" and scope == "sector":
        short = "LOCAL"
    return {
        "code": code, "label": short, "meaning": meaning, "scope": scope,
        "car": str(car or ""), "sector": str(sector or ""), "raw": str(raw or ""),
        "known": code != "UNKNOWN", "pattern": pattern, "color_rgb": list(ink), "accent_rgb": list(accent),
        "caution": code in RACING_CAUTION_FLAGS,
        "motion": "waved" if "WAVED" in str(raw).upper() else "standing" if any(word in str(raw).upper() for word in ("STANDING", "MOTIONLESS")) else "unspecified",
    }


def racing_flag_pixel(signal: Mapping[str, Any], x: int, y: int, width: int, height: int) -> tuple[int, int, int]:
    """Rasterize a physical flag pattern for both native panel sizes."""
    ink = tuple(signal.get("color_rgb") or (110, 115, 130))
    accent = tuple(signal.get("accent_rgb") or (235, 235, 235))
    pattern = signal.get("pattern")
    if pattern in {"checkered", "green_checkered", "crossed_checkers"}:
        if pattern == "crossed_checkers" and abs(x * (height - 1) - y * (width - 1)) > width and abs(x * (height - 1) + y * (width - 1) - (width - 1) * (height - 1)) > width:
            return (95, 105, 120)
        cell = 1 if width < 12 else 2
        return accent if (x // cell + y // cell) % 2 else ink
    if pattern == "double":
        return accent if y == height // 2 else ink
    if pattern == "stripes":
        return accent if (x // max(1, width // 4)) % 2 else ink
    if pattern == "split":
        return ink if x < width // 2 else accent
    if pattern == "diagonal_split":
        return accent if x * height + y * width < width * height else ink
    if pattern == "diagonal":
        return accent if abs(x * (height - 1) + y * (width - 1) - (width - 1) * (height - 1)) <= width else ink
    if pattern == "cross":
        return accent if abs(x * (height - 1) - y * (width - 1)) <= width // 2 or abs(x * (height - 1) + y * (width - 1) - (width - 1) * (height - 1)) <= width // 2 else ink
    if pattern == "disc":
        return accent if ((x - (width - 1) / 2) / max(1, width / 3)) ** 2 + ((y - (height - 1) / 2) / max(1, height / 3)) ** 2 <= 1 else ink
    if pattern in {"border", "furled", "board"}:
        return accent if x in {0, width - 1} or y in {0, height - 1} else ink
    if pattern == "finish_split":
        return accent if x >= width // 2 else (235, 235, 235) if (x + y) % 2 else (25, 25, 25)
    if pattern == "stage_split":
        return accent if x >= width // 2 else (235, 235, 235) if (x + y) % 2 else (55, 190, 90)
    if pattern == "unknown":
        return accent if (x == width // 2 and y < height - 2) or (x == width // 2 and y == height - 1) else ink
    return ink


@lru_cache(maxsize=1)
def _racing_number_colors() -> Mapping[str, Any]:
    return json.loads(Path(__file__).with_name("racing_number_colors.json").read_text(encoding="utf-8"))


def racing_number_style(series: str, driver: Mapping[str, Any], season: int) -> dict[str, Any]:
    """Keep verified number art and livery accents distinct from missing color data."""
    registry = _racing_number_colors()
    group = str(driver.get("class") or "").replace(" ", "").upper()
    entry = registry.get("styles", {}).get(series, {}).get(group, {}).get(str(driver.get("car") or ""), {}) if season == registry.get("season") else {}
    raw = str(entry.get("color") or (driver.get("livery_primary") if series in {"f1", "indycar"} else "") or "FFFFFF").lstrip("#")
    outline = str(entry.get("outline") or "").lstrip("#")
    def rgb(value):
        return [int(value[i:i + 2], 16) for i in (0, 2, 4)] if re.fullmatch(r"[0-9a-fA-F]{6}", value) else [235, 235, 235]
    return {"color_rgb": rgb(raw), "outline_rgb": rgb(outline) if outline else [],
            "source": entry.get("source") or ("team" if series in {"f1", "indycar"} and driver.get("livery_primary") else "unavailable")}


_RACING_VENUES = (
    ("circuit of the americas", "COTA"), ("circuito de barcelona", "Barcelona"),
    ("barcelona", "Barcelona"), ("spa-francorchamps", "Spa"), ("spa francorchamps", "Spa"),
    ("sao paulo", "Sao Paulo"), ("interlagos", "Sao Paulo"), ("fuji", "Fuji"),
    ("monza", "Monza"), ("imola", "Imola"), ("bahrain", "Bahrain"), ("qatar", "Qatar"),
    ("lusail", "Qatar"), ("le mans", "Le Mans"), ("laguna seca", "Laguna Seca"),
    ("road atlanta", "Road Atlanta"), ("road america", "Road America"),
    ("watkins glen", "Watkins Glen"), ("sebring", "Sebring"), ("daytona", "Daytona"),
    ("canadian tire", "Mosport"), ("mosport", "Mosport"), ("long beach", "Long Beach"),
    ("detroit", "Detroit"), ("indianapolis", "Indy"), ("homestead", "Homestead"),
    ("bowman gray", "Bowman Gray"), ("north wilkesboro", "North Wilkesboro"),
    ("new hampshire", "New Hampshire"), ("world wide technology", "Gateway"),
    ("gateway", "Gateway"), ("las vegas", "Las Vegas"), ("phoenix", "Phoenix"),
    ("talladega", "Talladega"), ("martinsville", "Martinsville"), ("darlington", "Darlington"),
    ("bristol", "Bristol"), ("charlotte", "Charlotte"), ("atlanta", "Atlanta"),
    ("texas", "Texas"), ("kansas", "Kansas"), ("dover", "Dover"), ("nashville", "Nashville"),
    ("michigan", "Michigan"), ("pocono", "Pocono"), ("san diego", "San Diego"),
    ("sonoma", "Sonoma"), ("chicagoland", "Chicagoland"), ("iowa", "Iowa"),
    ("richmond", "Richmond"),
)


def racing_short_name(series: str, event_name: str, track_name: str = "") -> str:
    """Use familiar race names before sponsor titles or circuit legal names."""
    event = " ".join(str(event_name or "").split())
    folded = event.casefold().replace("–", "-")
    track = str(track_name or "").casefold()
    if series == "nascar":
        for phrase, name in (
            ("daytona 500", "Daytona 500"), ("coca-cola 600", "Coke 600"),
            ("coca cola 600", "Coke 600"), ("coke 600", "Coke 600"),
            ("southern 500", "Southern 500"), ("brickyard 400", "Brickyard 400"),
            ("coke zero", "Daytona 400"), ("all-star", "All-Star Race"),
            ("all star", "All-Star Race"), ("clash", "The Clash"), ("duel", "Daytona Duel"),
        ):
            if phrase in folded:
                return name
        if "bristol" in track and "night race" in folded:
            return "Bristol Night"
        if "charlotte" in track and "roval" in folded:
            return "Charlotte Roval"
    elif series == "imsa":
        if "petit le mans" in folded:
            return "Petit Le Mans"
        if "rolex 24" in folded or ("daytona" in track and "24" in folded):
            return "Rolex 24"
        if "sebring" in folded and re.search(r"\b(?:12|twelve)\b", folded):
            return "Sebring 12h"
    elif series == "wec" and "lone star le mans" in folded:
        return "Lone Star Le Mans"
    venue = next((name for fragment, name in _RACING_VENUES if fragment in track), "")
    if not venue:
        venue = next((name for fragment, name in _RACING_VENUES if fragment in folded), "")
    if venue:
        if series in {"wec", "imsa"}:
            duration = re.search(r"\b(\d+|six|eight|ten|twelve|twenty-four)\s*(?:hours?|h)\b", folded)
            if duration:
                hours = {"six": "6", "eight": "8", "ten": "10", "twelve": "12", "twenty-four": "24"}.get(duration.group(1), duration.group(1))
                return f"{venue} {hours}h"
            if "le mans" in folded and series == "wec":
                return "Le Mans 24h"
        return venue
    # Keep unfamiliar events readable without inventing a known race identity.
    clean = re.sub(r"\s+(?:presented by|powered by)\b.*$", "", event, flags=re.IGNORECASE)
    clean = re.sub(r"^(?:FIA WEC\s*-\s*|\d+(?:st|nd|rd|th)\s+Annual\s+)", "", clean, flags=re.IGNORECASE)
    return clean.strip() or str(track_name or series.upper()).strip()


@dataclass(slots=True)
class SportsDisplayProjector:
    """Own sport status, facts, and short-lived live state for one provider."""

    _football: dict[str, dict[str, Any]] = field(default_factory=dict)

    def project(
        self,
        item: ContentItem,
        event: Mapping[str, Any],
        *,
        football_rankings: Mapping[str, str] | None = None,
    ) -> ContentItem:
        """Return one renderer-ready item without exposing ESPN display quirks."""

        data = dict(item.data)
        competition = _first_mapping(event.get("competitions"))
        data["competition_stage"] = espn_competition_stage(event)
        league = str(data.get("sport") or "").lower()
        state = str(data.get("state") or "pre").lower()
        prior = _mapping(data.get("situation"))
        situation = display_situation(
            league,
            competition,
            home_abbr=str(data.get("home_abbr") or ""),
            away_abbr=str(data.get("away_abbr") or ""),
        )
        if prior.get("clock"):
            situation["clock"] = prior["clock"]
        data["status"] = _status(league, state, event, competition, data)
        if league == "nhl":
            shootout = _nhl_has_shootout_marker(event, competition)
            completed = state in {"post", "final"}
            situation["shootout_state"] = (
                "completed" if shootout and completed else "active" if shootout else "none"
            )
            situation["shootout_winner"] = next(
                (
                    str(competitor.get("homeAway") or "").lower()
                    for competitor in _sequence(competition.get("competitors"))
                    if isinstance(competitor, Mapping) and competitor.get("winner") is True
                ),
                "",
            ) if shootout and completed else ""
        situation = self._stable_situation(
            item.id, league, state, str(data["status"]), situation,
            scope=(str(_mapping(event.get("status")).get("period") or ""),
                   str(data.get("home_score") or "0"), str(data.get("away_score") or "0")),
        )
        data["situation"] = assign_active_team(
            league,
            state,
            str(data["status"]),
            situation,
            home_abbr=str(data.get("home_abbr") or ""),
            away_abbr=str(data.get("away_abbr") or ""),
        )
        if league == "march_madness":
            data.update(_seeds(competition))
        elif league in _COLLEGE_FOOTBALL:
            data.update(_football_ranks(competition, football_rankings))
        return ContentItem(
            id=item.id,
            family=item.family,
            kind=item.kind,
            is_shown=item.is_shown,
            data=data,
        )

    def _stable_situation(
        self,
        identifier: str,
        league: str,
        state: str,
        status: str,
        situation: dict[str, Any],
        *,
        scope: tuple[str, str, str],
    ) -> dict[str, Any]:
        """Keep missing down facts only within the same football possession and score."""
        if league not in _FOOTBALL:
            return situation
        if sports_game_phase({"sport": league, "state": state, "status": status}) != "playing":
            self._football.pop(identifier, None)
            return situation
        cached = self._football.get(identifier, {})
        if cached.get("scope") != scope:
            cached = {}
        possession = str(situation.get("possession") or cached.get("possession") or "")
        if not situation.get("downDist") and possession == cached.get("possession"):
            situation.update(cached.get("down", {}))
        situation["possession"] = possession
        self._football[identifier] = {
            "scope": scope, "possession": possession,
            "down": {key: value for key, value in situation.items() if key in _FOOTBALL_DOWN_KEYS},
        }
        return situation


def sports_content_sort_key(item: ContentItem) -> tuple[int, str, str, str, str]:
    """Order scoreboard items consistently after ESPN and FotMob content merge."""

    data = item.data
    state = str(data.get("state") or "pre").lower()
    status = str(data.get("status") or "").upper()
    priority = 3 if state == "post" or "FINAL" in status else 2
    return (
        priority,
        str(data.get("startTimeUTC") or "9999"),
        str(data.get("sport") or ""),
        str(data.get("home_abbr") or ""),
        str(data.get("away_abbr") or ""),
    )


def _status(
    league: str,
    state: str,
    event: Mapping[str, Any],
    competition: Mapping[str, Any],
    data: Mapping[str, Any],
) -> str:
    """Return the exact concise status language used by the ticker layouts."""

    status = _mapping(event.get("status"))
    kind = _mapping(status.get("type"))
    detail = str(
        kind.get("shortDetail") or kind.get("detail") or data.get("status") or ""
    ).strip()
    raw_clock = status.get("displayClock")
    if raw_clock is None or not str(raw_clock).strip():
        raw_clock = status.get("clock")
    clock = str(raw_clock if raw_clock is not None else "").strip()
    period = _integer(status.get("period"), _integer(kind.get("period"), 0))
    if not clock:
        clock = str(_mapping(competition.get("situation")).get("clock") or "").strip()
    upper = detail.upper()

    if "POSTPON" in upper or "CANCEL" in upper or "SUSPEND" in upper or "DELAY" in upper:
        return detail.split(",", 1)[0].title()
    if "FINAL" in upper or state in {"post", "final"}:
        return _final_status(league, upper, period)
    if state == "pre":
        return str(data.get("status") or detail or "TBD")
    if league == "nhl" and state in {"in", "half", "crit"} and _nhl_has_shootout_marker(
        event, competition
    ):
        return "S/O"
    if league.startswith("soccer") and re.search(r"\b(?:PENALTIES|SHOOTOUT)\b|^PENS?\.?$", upper):
        return "PEN"
    if league == "nhl" and (upper.startswith("END OF") or "INTERMISSION" in upper):
        return _period_status("P", period, "END", overtime_base=3)
    if state == "half" or "HALFTIME" in upper or upper in {"HT", "HALF"}:
        return "Half" if league.startswith("soccer") else "Halftime"
    if league in _COLLEGE_FOOTBALL and period > 4:
        return _period_status("Q", period, "", overtime_base=4)
    if league in _FOOTBALL | _BASKETBALL and upper.startswith("END OF"):
        if league == "march_madness" and period in {1, 2}:
            return f"H{period} END"
        return _period_status("Q", period, "END", overtime_base=2 if league == "march_madness" else 4)
    if league in _FOOTBALL and period > 0 and _is_zero_clock(clock):
        return _period_status("Q", period, "END", overtime_base=4)
    if league == "nhl" and period > 0 and _is_zero_clock(clock):
        return _period_status("P", period, "END", overtime_base=3)
    if league in _BASKETBALL and period > 0 and _is_zero_clock(clock):
        if league == "march_madness" and period in {1, 2}:
            return f"H{period} END"
        overtime_base = 2 if league == "march_madness" else 4
        return _period_status("Q", period, "END", overtime_base=overtime_base)
    if league in _FOOTBALL:
        return _period_status("Q", period, clock, overtime_base=4)
    if league in _BASKETBALL:
        if league == "march_madness" and period in {1, 2}:
            return f"H{period} {clock}".strip()
        overtime_base = 2 if league == "march_madness" else 4
        return _period_status("Q", period, clock, overtime_base=overtime_base)
    if league == "nhl":
        return _period_status("P", period, clock, overtime_base=3)
    if league.startswith("soccer"):
        label = normalize_soccer_clock(clock, period=period) or normalize_soccer_clock(detail, period=period)
        if label:
            return f"ET {label}" if period >= 3 or "ET" in upper else label
        return "ET" if period >= 3 or "ET" in upper else detail
    if league == "mlb":
        return _baseball_status(detail)
    return detail or str(data.get("status") or state)


def display_situation(
    league: str,
    competition: Mapping[str, Any],
    *,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Return all facts consumed by compact and pinned renderer ports."""

    source = _mapping(competition.get("situation"))
    possession = _possession(source.get("possession"), competition, home_abbr, away_abbr)
    if league in _FOOTBALL:
        return _football_situation(source, possession, home_abbr, away_abbr)
    if league == "mlb":
        result = {
            "balls": _integer(source.get("balls")),
            "strikes": _integer(source.get("strikes")),
            "outs": _integer(source.get("outs")),
            "onFirst": bool(source.get("onFirst")),
            "onSecond": bool(source.get("onSecond")),
            "onThird": bool(source.get("onThird")),
            "possession": possession,
        }
        batter = source.get("batter") or _first_mapping(source.get("dueUp"))
        batter_stats = baseball_player_stats(batter)
        for key, target in (
            ("hits", "batter_h"),
            ("atBats", "batter_ab"),
            ("avg", "batter_avg"),
        ):
            if batter_stats.get(key) not in (None, ""):
                result[target] = batter_stats[key]
        pitcher_stats = baseball_player_stats(source.get("pitcher"))
        for key, target in (("pitches", "pitcher_pitches"), ("era", "pitcher_era")):
            if pitcher_stats.get(key) not in (None, ""):
                result[target] = pitcher_stats[key]
        for role in ("batter", "pitcher"):
            name = _baseball_player_name(source.get(role))
            if role == "batter" and not name:
                name = _baseball_player_name(_first_mapping(source.get("dueUp")))
            if name:
                result[f"{role}_name"] = name
        return result
    if league == "nhl":
        return _nhl_situation(source, possession, home_abbr, away_abbr)
    if league.startswith("soccer"):
        return {
            "possession": possession,
            "shootout": _shootout(source.get("shootout") or source.get("shootoutDetails")),
            "goal_events": _events(source.get("goalEvents") or source.get("goals"), home_abbr, away_abbr),
            "red_cards": _events(source.get("redCards") or source.get("cards"), home_abbr, away_abbr),
        }
    return {"possession": possession}


def assign_active_team(
    league: str,
    state: str,
    status: str,
    situation: Mapping[str, Any],
    *,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Set live-play ownership only while the game remains active."""

    result = dict(situation)
    if state not in {"in", "half", "crit"}:
        for key in _LIVE_PLAY_KEYS:
            result.pop(key, None)
        return result
    if league == "nhl":
        active_team = str(
            result.get("emptyNetSide") or result.get("powerPlayTeam") or ""
        ).strip()
    else:
        active_team = str(result.get("possession") or "").strip()
    if league == "mlb" and not active_team:
        active_team = _baseball_batting_team(status, home_abbr, away_abbr)
    if active_team:
        result["activeTeam"] = active_team
    else:
        result.pop("activeTeam", None)
    return result


_LIVE_PLAY_KEYS = frozenset(
    {
        "activeTeam",
        "possession",
        "downDist",
        "downDistFull",
        "down",
        "ballOn",
        "yardLine",
        "yardsToGo",
        "yardsToGoal",
        "isGoalToGo",
        "goalToGo",
        "isRedZone",
        "balls",
        "strikes",
        "outs",
        "onFirst",
        "onSecond",
        "onThird",
        "batter_name",
        "batter_h",
        "batter_ab",
        "batter_avg",
        "pitcher_name",
        "pitcher_pitches",
        "pitcher_era",
        "home_challenges",
        "home_challenges_used",
        "away_challenges",
        "away_challenges_used",
        "last_pitch_speed",
        "last_pitch_type",
        "powerPlay",
        "powerPlayTeam",
        "manpower",
        "hockeyGoals",
        "emptyNet",
        "emptyNetSide",
    }
)

_FOOTBALL_DOWN_KEYS = frozenset({
    "downDist", "downDistFull", "down", "ballOn", "yardLine", "yardsToGo", "yardsToGoal",
    "isGoalToGo", "goalToGo", "isRedZone",
})


def _baseball_batting_team(status: str, home_abbr: str, away_abbr: str) -> str:
    """Resolve batting ownership from the provider-normalized inning status."""

    half = baseball_inning_display({"state": "in", "status": status})["half"]
    return away_abbr if half == "top" else home_abbr if half == "bottom" else ""


def _baseball_player_name(value: Any) -> str:
    """Read one live MLB player name from the scoreboard situation."""

    player = _mapping(value)
    athlete = _mapping(player.get("athlete"))
    return str(
        athlete.get("displayName")
        or athlete.get("fullName")
        or player.get("displayName")
        or player.get("fullName")
        or ""
    ).strip()


def baseball_player_stats(value: Any) -> dict[str, str]:
    """Read available MLB player stats from scoreboard situation data."""

    player = _mapping(value)
    stats: dict[str, str] = {}
    sources = [
        player,
        _mapping(player.get("stats")),
        _mapping(player.get("statistics")),
        _mapping(player.get("batting")),
        _mapping(player.get("pitching")),
    ]
    aliases = {
        "hits": ("hits", "H"),
        "atBats": ("atBats", "AB", "at_bats"),
        "avg": ("avg", "AVG", "average"),
        "pitches": ("pitches", "pitchCount", "pitch_count"),
        "era": ("era", "ERA"),
    }
    for target, keys in aliases.items():
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    stats[target] = str(value).strip()
                    break
            if target in stats:
                break
    summary = str(player.get("summary") or "").strip()
    match = re.match(r"^(\d+)\s*-\s*(\d+)\b", summary)
    if match:
        stats.setdefault("hits", match.group(1))
        stats.setdefault("atBats", match.group(2))
    return stats


def _football_situation(
    source: Mapping[str, Any], possession: str, home_abbr: str, away_abbr: str
) -> dict[str, Any]:
    """Normalize football down, spot, first-down, and red-zone facts."""

    full = str(source.get("downDistanceText") or "").strip()
    short = str(source.get("shortDownDistanceText") or "").strip()
    down = _integer_or_none(source.get("down"))
    distance = _integer_or_none(source.get("distance"))
    yard_line = _integer_or_none(source.get("yardLine"))
    if yard_line is None:
        yard_line = _yard_line(full, home_abbr, away_abbr)
    if yard_line is not None:
        yard_line = max(0, min(100, yard_line))
    if not short:
        short = full.split(" at ", 1)[0].strip()
    if not short and down in _ORDINALS and distance is not None:
        short = f"{_ORDINALS[down]} & {distance}"
    ball_on = str(source.get("possessionText") or "").strip()
    if not ball_on and " at " in full:
        ball_on = full.split(" at ", 1)[1].strip()
    to_goal = None
    if possession.upper() == away_abbr.upper():
        to_goal = yard_line
    elif possession.upper() == home_abbr.upper() and yard_line is not None:
        to_goal = 100 - yard_line
    goal_to_go = "goal" in short.lower() or "goal" in full.lower()
    if to_goal is not None and distance is not None and distance >= to_goal:
        goal_to_go = True
    red_zone = bool(source.get("isRedZone"))
    if possession and to_goal is not None:
        red_zone = to_goal <= 20
    return {
        "possession": possession,
        "downDist": short,
        "downDistFull": full,
        "ballOn": ball_on,
        "down": down,
        "yardsToGo": distance,
        "yardLine": yard_line,
        "isGoalToGo": goal_to_go,
        "isRedZone": red_zone,
    }


def _final_status(league: str, detail: str, period: int) -> str:
    """Keep final overtime and shootout labels visible on compact cards."""

    if league.startswith("soccer"):
        if re.search(r"\b(?:PENS?|PENALTIES|SHOOTOUT)\b", detail):
            return "FINAL PEN"
        if period >= 3 or re.search(r"\bAET\b|EXTRA TIME", detail):
            return "FINAL AET"
    if league == "nhl":
        if re.search(r"\bS/?O\b|SHOOTOUT", detail):
            return "FINAL S/O"
        if period >= 4:
            return f"FINAL OT{period - 3 if period > 4 else ''}"
    if league == "march_madness" and period > 2:
        return f"FINAL OT{period - 2 if period > 3 else ''}"
    if league in _FOOTBALL | _BASKETBALL and period > 4:
        return f"FINAL OT{period - 4 if period > 5 else ''}"
    return "FINAL"


def _period_status(prefix: str, period: int, clock: str, *, overtime_base: int) -> str:
    if period > overtime_base:
        extra = period - overtime_base
        label = f"OT{extra if extra > 1 else ''}"
    else:
        label = f"{prefix}{period}" if period else prefix
    return f"{label} {clock}".strip()


def _is_zero_clock(value: str) -> bool:
    """Return whether one provider value represents zero seconds remaining."""

    return re.fullmatch(r"0+(?::0+)?(?:\.0+)?", value.strip()) is not None


def _nhl_has_shootout_marker(
    event: Mapping[str, Any], competition: Mapping[str, Any]
) -> bool:
    """Detect explicit NHL shootout markers without treating overtime as a shootout."""

    status = _mapping(event.get("status"))
    status_type = _mapping(status.get("type"))
    competition_situation = _mapping(competition.get("situation"))
    event_situation = _mapping(event.get("situation"))
    sources = (
        status_type,
        event_situation,
        competition_situation,
        _mapping(event_situation.get("lastPlay")),
        _mapping(competition_situation.get("lastPlay")),
        _mapping(event.get("lastPlay")),
    )
    for source in sources:
        for key in ("shootout", "isShootout", "inShootout", "shootoutActive"):
            value = source.get(key)
            if value is True or str(value or "").strip().lower() in {"true", "yes", "active"}:
                return True
        for key in ("shortDetail", "detail", "altDetail", "displayValue", "text"):
            value = str(source.get(key) or "").strip().upper()
            if re.search(r"\bS/?O\b|SHOOTOUT", value):
                return True
        period = _mapping(source.get("period"))
        if str(period.get("displayValue") or "").strip().upper() == "SO":
            return True
        shot_info = _mapping(source.get("shotInfo"))
        if "SHOOTOUT" in str(shot_info.get("text") or "").upper():
            return True
    return False


def _baseball_status(value: str) -> str:
    text = value.replace("Inning", "").replace("inning", "").strip()
    text = re.sub(r"^TOP\s+", "Top ", text, flags=re.IGNORECASE)
    text = re.sub(r"^BOTTOM\s+", "Bottom ", text, flags=re.IGNORECASE)
    return text or "In Progress"


def normalize_soccer_clock(value: object, *, period: int | None = None) -> str:
    """Return one canonical soccer clock label."""

    text = (
        str(value or "")
        .replace("\u200e", "")
        .replace("\u200f", "")
        .replace("\ufffd", "")
        .replace("ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢", "'")
    )
    text = re.sub(r"\s+", "", text).replace("'", "")
    match = re.fullmatch(
        r"(?P<minute>\d+)(?::(?P<seconds>\d{1,2}))?"
        r"(?:\+(?P<added_minute>\d+)(?::(?P<added_seconds>\d{1,2}))?)?",
        text,
    )
    if match is None:
        return ""
    if any(
        int(val) >= 60
        for val in (match.group("seconds"), match.group("added_seconds"))
        if val is not None
    ):
        return ""
    minute = match.group("minute")
    added_minute = match.group("added_minute")
    if added_minute is not None:
        added_seconds = match.group("added_seconds")
        added = added_minute if added_seconds is None else f"{added_minute}:{added_seconds.zfill(2)}"
        return f"{minute}'+{added}'"

    minute_value = int(minute)
    seconds = match.group("seconds")
    if period == 1 and minute_value > 45:
        extra = minute_value - 45
        added = str(extra) if seconds is None else f"{extra}:{seconds.zfill(2)}"
        return f"45'+{added}'"
    if minute_value > 120 or (period is not None and period >= 3 and minute_value > 15):
        extra = minute_value - 120 if minute_value > 120 else minute_value - 15
        added = str(extra) if seconds is None else f"{extra}:{seconds.zfill(2)}"
        return f"120'+{added}'"
    if minute_value > 90:
        extra = minute_value - 90
        added = str(extra) if seconds is None else f"{extra}:{seconds.zfill(2)}"
        return f"90'+{added}'"
    return f"{minute}'"


def _seeds(competition: Mapping[str, Any]) -> dict[str, str]:
    competitors = _competitors(competition.get("competitors"))
    home = _find_side(competitors, "home")
    away = _find_side(competitors, "away")
    return {
        "home_seed": _seed(home),
        "away_seed": _seed(away),
    }


def _football_ranks(
    competition: Mapping[str, Any],
    football_rankings: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Project NCAA college football rankings into the shared display contract."""

    competitors = _competitors(competition.get("competitors"))
    home = _find_side(competitors, "home")
    away = _find_side(competitors, "away")
    return {
        "home_rank": _rank(home, football_rankings),
        "away_rank": _rank(away, football_rankings),
    }


def _seed(competitor: Mapping[str, Any]) -> str:
    value = _mapping(competitor.get("curatedRank")).get("current")
    return "" if value in (None, "", 99, "99") else str(value)


def _rank(
    competitor: Mapping[str, Any],
    football_rankings: Mapping[str, str] | None = None,
) -> str:
    """Return one NCAA ranking, excluding the provider's unranked sentinel."""

    team = _mapping(competitor.get("team"))
    team_id = str(team.get("id") or competitor.get("id") or "").strip()
    return normalize_rank((football_rankings or {}).get(team_id))


def normalize_rank(value: object) -> str:
    """Normalize one ranking value and discard its unranked sentinel."""

    try:
        number = int(float(str(value or "").strip().lstrip("Tt")))
    except (TypeError, ValueError):
        return ""
    return str(number) if 0 < number < 99 else ""


def _possession(value: object, competition: Mapping[str, Any], home_abbr: str, away_abbr: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    folded = text.casefold()
    if folded in {"home", "home_team"}:
        return home_abbr
    if folded in {"away", "away_team"}:
        return away_abbr
    for competitor, abbreviation in ((_find_side(_competitors(competition.get("competitors")), "home"), home_abbr), (_find_side(_competitors(competition.get("competitors")), "away"), away_abbr)):
        team = _mapping(competitor.get("team"))
        if text == str(team.get("id") or "") or folded == abbreviation.casefold():
            return abbreviation
    return ""


def _yard_line(text: str, home_abbr: str, away_abbr: str) -> int | None:
    if " at " not in text:
        return None
    parts = text.split(" at ", 1)[1].strip().split()
    if len(parts) == 1:
        return 50 if _integer_or_none(parts[0]) == 50 else None
    if len(parts) < 2:
        return None
    yard = _integer_or_none(parts[1])
    if yard is None:
        return None
    return yard if parts[0].upper() == home_abbr.upper() else 100 - yard if parts[0].upper() == away_abbr.upper() else None


def _shootout(value: object) -> dict[str, list[str]] | None:
    source = _mapping(value)
    if not source:
        return None
    return {
        "away": _results(source.get("away") or source.get("awayResults")),
        "home": _results(source.get("home") or source.get("homeResults")),
    }


def _results(value: object) -> list[str]:
    result: list[str] = []
    for entry in _sequence(value):
        text = str(_mapping(entry).get("result") or entry).lower()
        result.append("goal" if text in {"goal", "made", "score"} else "miss" if text in {"miss", "failed", "save"} else "pending")
    return result


def _events(value: object, home_abbr: str, away_abbr: str) -> list[dict[str, Any]]:
    """Project provider event records into the soccer renderer contract."""

    result: list[dict[str, Any]] = []
    for entry in _sequence(value):
        source = _mapping(entry)
        team = str(source.get("team") or source.get("teamAbbreviation") or "")
        result.append(soccer_event(
            is_home=team.upper() == home_abbr.upper(),
            player=source.get("displayName") or source.get("athlete") or source.get("name"),
            minute=source.get("clock") or source.get("time"),
            own_goal=bool(source.get("ownGoal") or source.get("isOwnGoal")),
        ))
    return result


def soccer_event(
    *,
    is_home: bool,
    player: object,
    minute: object,
    own_goal: bool = False,
    assist: object = "",
    goal_type: object = "",
    shot_type: object = "",
    expected_goals: object = "",
) -> dict[str, Any]:
    """Project soccer player, assist, clock, and goal facts."""

    name = str(player or "").strip()
    surname = name.split()[-1].upper()[:8] if name else ""
    clock = str(minute or "").strip()
    result = {
        "is_home": bool(is_home),
        "player": surname,
        "time": clock,
        "own_goal": bool(own_goal),
    }
    if name:
        result["alert_player"] = name
    if str(assist or "").strip():
        full_assist = str(assist).strip()
        result["assist"] = full_assist.split()[-1].upper()[:12]
        result["alert_assist"] = full_assist
    if str(goal_type or "").strip():
        result["goal_type"] = str(goal_type).strip().upper()[:12]
    if str(shot_type or "").strip():
        result["shot_type"] = str(shot_type).strip().upper()[:12]
    if expected_goals not in (None, ""):
        result["expected_goals"] = expected_goals
    return result


def _integer(value: object, default: int = 0) -> int:
    result = _integer_or_none(value)
    return default if result is None else result


def _integer_or_none(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _competitors(value: object) -> tuple[Mapping[str, Any], ...]:
    return tuple(item for item in _sequence(value) if isinstance(item, Mapping))


def _find_side(competitors: Sequence[Mapping[str, Any]], side: str) -> Mapping[str, Any]:
    return next((item for item in competitors if str(item.get("homeAway") or "").lower() == side), {})


def _first_mapping(value: object) -> Mapping[str, Any]:
    return _mapping(_sequence(value)[0]) if _sequence(value) else {}


_TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    # NBA
    "NY": ("NY", "NYK", "NYC", "RBNY"),
    "NYK": ("NY", "NYK"),
    "GS": ("GS", "GSW"),
    "GSW": ("GS", "GSW"),
    "NO": ("NO", "NOP"),
    "NOP": ("NO", "NOP"),
    "SA": ("SA", "SAS"),
    "SAS": ("SA", "SAS"),
    "PHX": ("PHX", "PHO"),
    "PHO": ("PHX", "PHO"),
    "UTA": ("UTA", "UTAH"),
    "UTAH": ("UTA", "UTAH"),
    # NFL
    "WAS": ("WAS", "WSH"),
    "WSH": ("WAS", "WSH"),
    "JAC": ("JAC", "JAX"),
    "JAX": ("JAC", "JAX"),
    "TB": ("TB", "TAM"),
    "TAM": ("TB", "TAM"),
    # MLS / Soccer
    "RBNY": ("RBNY", "NYR", "NY"),
    "NYR": ("NYR", "RBNY", "NY"),
    "LAFC": ("LAFC", "LAF"),
    "LAF": ("LAFC", "LAF"),
    "LA": ("LA", "LAG", "LAD", "LAC", "LAR"),
    "LAG": ("LAG", "LA"),
    "SJ": ("SJ", "SJE"),
    "SJE": ("SJ", "SJE"),
    "NE": ("NE", "NER"),
    "NER": ("NE", "NER"),
    "DC": ("DC", "DCU"),
    "DCU": ("DC", "DCU"),
    "WXM": ("WXM", "WRE", "WREXHAM"),
    "WRE": ("WXM", "WRE", "WREXHAM"),
    "ATX": ("ATX", "AUS"),
    "AUS": ("ATX", "AUS"),
    "SKC": ("SKC", "KC"),
    "KC": ("SKC", "KC"),
    "SEA": ("SEA", "SEATTLE"),
    "VAN": ("VAN", "VANCOUVER"),
    "NYC": ("NYC", "NYCF"),
    "BHA": ("BHA", "BRI"),
    "BRI": ("BHA", "BRI"),
    "NFO": ("NFO", "NOT"),
    "NOT": ("NFO", "NOT"),
    "MCI": ("MCI", "MNC"),
    "MNC": ("MCI", "MNC"),
    "MUN": ("MUN", "MAN"),
    "MAN": ("MUN", "MAN"),
}


def baseball_inning_display(data: Mapping[str, Any]) -> dict[str, Any]:
    """Own inning number, half, and phase for every display target."""
    state = str(data.get("state") or "pre").lower()
    result = {"number": 0, "half": "none", "phase": "inactive"}
    if state not in {"in", "crit"}:
        return result
    match = re.match(r"^(TOP|BOTTOM|BOT|MID|MIDDLE|END)(?:\s+OF)?\s*(\d+)", str(data.get("status") or "").strip().upper())
    if match is None or int(match[2]) < 1:
        return {**result, "phase": "paused"}
    half = "top" if match[1] == "TOP" else "bottom" if match[1] in {"BOTTOM", "BOT"} else "break"
    return {"number": int(match[2]), "half": half, "phase": "break" if half == "break" else "playing"}


def project_baseball_display(data: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve inning transitions after provider detail enrichment completes."""
    result = dict(data)
    situation = dict(_mapping(data.get("situation")))
    situation.pop("possession", None)
    inning = baseball_inning_display(result)
    if inning["phase"] == "playing" and _integer(situation.get("outs")) == 3:
        marker = "Mid" if inning["half"] == "top" else "End"
        result["status"] = re.sub(
            r"^(TOP|BOTTOM|BOT)(?:\s+OF)?\s*",
            marker + " ",
            str(result.get("status") or "").strip(),
            flags=re.IGNORECASE,
        )
        inning = baseball_inning_display(result)
    result["baseball_inning"] = inning
    if inning["phase"] == "playing":
        active = str(result.get("away_abbr" if inning["half"] == "top" else "home_abbr") or "")
        if active:
            situation["activeTeam"] = active
        else:
            situation.pop("activeTeam", None)
    else:
        for key in _BASEBALL_AT_BAT_KEYS:
            situation.pop(key, None)
        if inning["phase"] == "break":
            situation.update(balls=0, strikes=0, outs=0, onFirst=False, onSecond=False, onThird=False)
    result["situation"] = situation
    return result


_BASEBALL_AT_BAT_KEYS = frozenset({
    "activeTeam", "possession", "balls", "strikes", "outs", "onFirst", "onSecond", "onThird",
    "batter_name", "batter_h", "batter_ab", "batter_avg", "pitcher_name", "pitcher_pitches", "pitcher_era",
    "last_pitch_speed", "last_pitch_type", "last_pitch_type_abbr", "last_pitch_type_full",
})


def normalize_competition_stage(value: object) -> int:
    """Keep the integer V2 competition stage within its declared values."""
    return value if type(value) is int and value in (0, 1, 2) else 0


def _competition_stage(labels: Sequence[object], *, postseason: bool = False) -> int:
    """Resolve the tournament round independently of the game clock and result."""
    playoff = postseason
    finals = False
    earlier_round = False
    for value in labels:
        label = re.sub(r"[-_]", " ", str(value or "").casefold())
        label = " ".join(label.split())
        if not label:
            continue
        earlier_round = earlier_round or bool(re.search(
            r"\b(?:semi\s?finals?|quarter\s?finals?|conference|division|divisional|afc|nfc|east|west|eastern|western|regional|final four|third place|bronze|(?:1st|2nd|first|second) round)\b",
            label,
        ))
        if re.search(r"\b(?:finals?|super bowl|world series|national championship|fcs championship|championship (?:game|match))\b", label) or label == "championship":
            finals = True
        if earlier_round or re.search(r"\b(?:playoffs?|post\s?season|wild\s?card|knockout|round of \d+|sweet 16|elite (?:8|eight))\b", label):
            playoff = True
    return 1 if earlier_round else 2 if finals else 1 if playoff else 0


def espn_competition_stage(event: Mapping[str, Any]) -> int:
    """Read ESPN season and round metadata without using status text or recaps."""
    competition = _first_mapping(event.get("competitions"))
    season = _mapping(event.get("season"))
    series = _mapping(competition.get("series"))
    kind = _mapping(competition.get("type"))
    labels = [
        season.get("slug"), series.get("type"),
        kind.get("text"), kind.get("name"), kind.get("abbreviation"),
        *(_mapping(note).get("headline") for note in _sequence(competition.get("notes"))),
    ]
    return _competition_stage(labels, postseason=str(season.get("type")) == "3")


def fotmob_competition_stage(
    match: Mapping[str, Any], detail: Mapping[str, Any] | None = None, *, league: str = "",
) -> int:
    """Read FotMob tournament rounds from match and detail metadata."""
    general = _mapping(_mapping(detail).get("general"))
    labels = [match.get("tournamentStage"), general.get("matchRound"), general.get("leagueRoundName")]
    knockout = any(re.fullmatch(r"1/(?:2|4|8|16|32|64)", str(value or "")) for value in labels)
    return _competition_stage(labels, postseason=knockout or league == "soccer_fa_cup")


def golf_competition_stage(event: Mapping[str, Any]) -> int:
    """Identify FedExCup events without treating a final round as a season final."""
    name = re.sub(r"[^a-z0-9]+", " ", str(event.get("name") or "").casefold()).strip()
    if name in {"tour championship", "the tour championship"}:
        return 2
    return 1 if name in {"fedex st jude championship", "bmw championship"} else 0


def nascar_competition_stage(race: Mapping[str, Any]) -> int:
    """Read the official Cup postseason flag and championship race identity."""
    round_number = _integer(race.get("playoff_round"))
    if round_number <= 0:
        return 0
    championship = re.search(r"\bchampionship\b", str(race.get("race_name") or ""), re.IGNORECASE)
    return 2 if round_number == 4 or championship else 1


def nhl_competition_stage(game: Mapping[str, Any]) -> int:
    """Normalize the NHL game type before applying tournament rules."""
    return 1 if _integer(game.get("gameType")) == 3 else 0


def sports_game_phase(data: Mapping[str, Any]) -> str:
    """Resolve display lifecycle without advancing a provider's game clock."""
    state = str(data.get("state") or "").lower()
    status = str(data.get("status") or "").strip().upper()
    if any(word in status for word in ("CANCEL", "POSTPON", "SUSPEND", "DELAY", "ABANDON")):
        return "paused"
    if state in {"post", "final"} or status.startswith(("FINAL", "FT")):
        return "final"
    if state == "pre":
        return "scheduled"
    if state == "half" or status in {"HALF", "HALFTIME", "HT"}:
        return "halftime"
    if sport_family(data.get("sport")) == "baseball":
        return baseball_inning_display(data)["phase"]
    situation = _mapping(data.get("situation"))
    manpower = _mapping(situation.get("manpower"))
    if status in {"S/O", "SO", "PEN", "PEN.", "PENALTIES", "SHOOTOUT"} or (
        manpower.get("phase") == "shootout" or _mapping(situation.get("shootout")).get("state") in {"active", "complete"}
    ):
        return "shootout"
    if "INTERMISSION" in status or manpower.get("phase") == "intermission":
        return "period_break"
    if re.fullmatch(r"(?:Q\d+|P\d+|H\d+|OT\d*) END", status):
        return "period_break"
    return "playing" if state in {"in", "crit"} else "unavailable"


def project_sports_display(data: Mapping[str, Any]) -> dict[str, Any]:
    """Remove stale live facts after every provider enrichment path."""
    family = sport_family(data.get("sport"))
    result = project_baseball_display(data) if family == "baseball" else dict(data)
    result["competition_stage"] = normalize_competition_stage(result.get("competition_stage"))
    phase = sports_game_phase(result)
    result["game_phase"] = phase
    situation = dict(_mapping(result.get("situation")))
    if phase != "playing":
        for key in _FOOTBALL_DOWN_KEYS | {"activeTeam", "possession"}:
            situation.pop(key, None)
        if family == "hockey":
            situation.update(nhl_manpower_situation(
                {"phase": "intermission" if phase == "period_break" else "shootout" if phase == "shootout" else "inactive"},
                home_abbr=str(result.get("home_abbr") or ""), away_abbr=str(result.get("away_abbr") or ""),
            ))
    if family in {"hockey", "soccer"} and phase != "shootout" and not (
        phase == "final" and (re.search(r"\b(?:S/O|SO|PEN)\b", str(result.get("status") or "").upper())
                              or _mapping(situation.get("shootout")).get("state") == "complete")
    ):
        situation.pop("shootout", None)
    if family == "hockey" and phase == "period_break" and not str(result.get("status") or "").endswith("END"):
        label = re.match(r"^(P\d+|OT\d*)\b", str(result.get("status") or ""))
        result["status"] = f"{label[1]} END" if label else "Intermission"
    result["situation"] = situation
    return result


def sport_family(sport: object) -> str:
    """Return the broad sport category for one league identifier."""
    value = str(sport or "").strip().lower()
    if value in {"mlb", "wbc"} or "baseball" in value:
        return "baseball"
    if value in {"nfl"} or value.startswith("ncf") or "football" in value:
        return "football"
    if value in {"nhl"} or "hockey" in value:
        return "hockey"
    if value in {"nba", "wnba", "march_madness"} or value.startswith(("ncb", "ncw")) or "basketball" in value:
        return "basketball"
    if value.startswith("soccer") or value in {"mls", "epl", "championship", "champions_league"}:
        return "soccer"
    return value or "other"


def matches_followed_team(sport: str, team_abbr: str, followed_entries: set[str] | frozenset[str] | Sequence[str]) -> bool:
    """Return whether one team in a sport matches any followed team identifier."""
    sport_str = str(sport or "").strip().lower()
    team_str = str(team_abbr or "").strip().lower()
    if not sport_str or not team_str:
        return False
    followed_set = {str(item).strip().lower() for item in followed_entries if str(item).strip()}
    if not followed_set:
        return False
    family = sport_family(sport_str)
    sport_variants = {sport_str, family}
    if "_" in sport_str:
        sport_variants.add(sport_str.split("_", 1)[1])
        sport_variants.add(sport_str.replace("_", ""))
    team_aliases = _TEAM_ALIASES.get(team_str.upper(), (team_str.upper(),))
    team_variants = {t.lower() for t in team_aliases} | {team_str}
    for s in sport_variants:
        for t in team_variants:
            if f"{s}:{t}" in followed_set or t in followed_set:
                return True
    return False


def _nhl_situation(
    source: Mapping[str, Any],
    possession: str,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Project manpower, power-play ownership, empty-net, and shootout facts."""

    result = nhl_manpower_situation(source, home_abbr=home_abbr, away_abbr=away_abbr)
    result["possession"] = possession
    result["shootout"] = nhl_shootout_display(source)
    return result


def nhl_manpower_situation(
    source: Mapping[str, Any],
    *,
    home_abbr: str,
    away_abbr: str,
) -> dict[str, Any]:
    """Own current NHL counts, badge ownership, and count-label visibility."""

    phase = str(source.get("phase") or "unavailable")
    manpower: dict[str, Any] = {
        "phase": phase,
        "state": "unavailable" if phase == "unavailable" else "inactive",
        "awaySkaters": None,
        "homeSkaters": None,
        "label": "",
        "scrollLabel": "",
        "powerPlayTimeRemaining": "",
        "powerPlayLabel": "",
        "penaltyNumbers": [],
        "penalties": [],
    }
    result: dict[str, Any] = {
        "powerPlay": False,
        "powerPlayTeam": "",
        "emptyNet": False,
        "emptyNetSide": "",
        "manpower": manpower,
    }
    if phase not in {"regulation", "overtime"}:
        return result
    manpower["state"] = "unavailable"
    code = str(source.get("situationCode") or "").strip()
    if not code and source.get("situationOmitted") is True:
        stage = normalize_competition_stage(source.get("competition_stage"))
        code = "1331" if phase == "overtime" and stage == 0 else "1551"
    if not re.fullmatch(r"[01][3-6][3-6][01]", code):
        return result
    away_goalie, away_skaters, home_skaters, home_goalie = map(int, code)
    manpower.update(awaySkaters=away_skaters, homeSkaters=home_skaters)
    away_pp = source.get("awayPowerPlay") is True
    home_pp = source.get("homePowerPlay") is True
    result["powerPlay"] = away_pp != home_pp
    if result["powerPlay"]:
        result["powerPlayTeam"] = away_abbr if away_pp else home_abbr
        advantage = away_skaters if away_pp else home_skaters
        opponent = home_skaters if away_pp else away_skaters
        manpower["powerPlayLabel"] = "PP" if (advantage, opponent) in {(5, 4), (4, 3)} else f"{advantage}v{opponent}"
    result["emptyNet"] = not away_goalie or not home_goalie
    if away_goalie != home_goalie:
        result["emptyNetSide"] = away_abbr if not away_goalie else home_abbr
    if result["emptyNet"]:
        manpower["state"] = "empty_net"
    elif result["powerPlay"]:
        manpower["state"] = "power_play"
    elif away_skaters != home_skaters:
        manpower["state"] = "unequal_strength"
    elif phase == "regulation" and away_skaters < 5:
        manpower["state"] = "reduced_strength"
    else:
        manpower["state"] = "even_strength"
    if manpower["state"] in {"empty_net", "power_play", "unequal_strength", "reduced_strength"}:
        manpower["label"] = f"{away_skaters}v{home_skaters}"
    remaining = source.get("powerPlaySecondsRemaining")
    if result["powerPlay"]:
        if isinstance(remaining, int) and not isinstance(remaining, bool) and 0 <= remaining <= 1200:
            manpower["powerPlayTimeRemaining"] = f"{remaining // 60}:{remaining % 60:02d}"
        short_side = "home" if away_pp else "away"
        advantage_count = (away_skaters - (not away_goalie)) if away_pp else (home_skaters - (not home_goalie))
        short_count = (home_skaters - (not home_goalie)) if away_pp else (away_skaters - (not away_goalie))
        penalty_count = max(0, min(2, advantage_count - short_count))
        candidates = []
        for entry in _sequence(_mapping(source.get("penaltyBox")).get(short_side)):
            penalty = _mapping(entry)
            jersey = _integer_or_none(penalty.get("jerseyNumber"))
            seconds = penalty.get("secondsRemaining")
            kind = str(penalty.get("kind") or "").upper()
            if jersey is None or not 0 <= jersey <= 99:
                continue
            if not isinstance(seconds, int) or isinstance(seconds, bool) or not 0 < seconds <= 1200:
                continue
            if kind not in {"MIN", "MAJ"}:
                continue
            candidates.append({"jerseyNumber": jersey, "secondsRemaining": seconds, "timeRemaining": f"{seconds // 60}:{seconds % 60:02d}"})
        candidates.sort(key=lambda penalty: (penalty["secondsRemaining"] != remaining, penalty["secondsRemaining"], penalty["jerseyNumber"]))
        selected = []
        seen = set()
        for penalty in candidates:
            if penalty["jerseyNumber"] not in seen and len(selected) < penalty_count:
                selected.append(penalty)
                seen.add(penalty["jerseyNumber"])
        selected.sort(key=lambda penalty: (penalty["secondsRemaining"], penalty["jerseyNumber"]))
        manpower["penalties"] = selected
        manpower["penaltyNumbers"] = [penalty["jerseyNumber"] for penalty in selected]
        groups: dict[str, list[str]] = {}
        for penalty in selected:
            groups.setdefault(penalty["timeRemaining"], []).append(f"#{penalty['jerseyNumber']}")
        manpower["scrollLabel"] = " | ".join(f"{clock} {'/'.join(numbers)}" for clock, numbers in groups.items())
        if not groups:
            manpower["scrollLabel"] = manpower["powerPlayTimeRemaining"]
    else:
        manpower["scrollLabel"] = manpower["label"]
    return result


def nhl_goal_display(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build complete goal labels with three surname letters and jersey numbers."""

    goals = []
    for goal in _sequence(source.get("goals")):
        record = _mapping(goal)
        if record.get("side") not in {"away", "home"}:
            continue
        name = unicodedata.normalize("NFKD", str(record.get("lastName") or ""))
        letters = "".join(character for character in name.upper() if character.isascii() and character.isalpha())[:3]
        jersey = _integer_or_none(record.get("jerseyNumber"))
        player_label = letters or "---"
        if jersey is not None:
            player_label = f"{letters}#{jersey}"
        period = _integer(record.get("period"))
        clock = str(record.get("clock") or "")
        goals.append({
            "id": str(record.get("id") or ""),
            "side": record["side"],
            "playerLabel": player_label,
            "label": f"{player_label} {period} {clock}".strip(),
        })
    return goals


def nhl_shootout_display(source: Mapping[str, Any]) -> dict[str, Any] | None:
    """Own NHL shootout lifecycle and one aligned three-round display window."""

    raw = _mapping(source.get("shootout"))
    state = str(raw.get("state") or "")
    if state not in {"active", "complete"}:
        return None
    attempts = {side: _results(raw.get(side)) for side in ("away", "home")}
    current_round = max(1, len(attempts["away"]), len(attempts["home"]))
    first_side = str(raw.get("firstSide") or "")
    next_side = ""
    if state == "active" and first_side in attempts:
        second_side = "home" if first_side == "away" else "away"
        first_count = len(attempts[first_side])
        second_count = len(attempts[second_side])
        if first_count == second_count:
            next_side = first_side
            current_round = first_count + 1
        elif first_count == second_count + 1:
            next_side = second_side
            current_round = first_count
    last_round = max(3, current_round)
    first_round = last_round - 2
    rounds = []
    for number in range(first_round, last_round + 1):
        row: dict[str, Any] = {"round": number, "nextSide": next_side if number == current_round else ""}
        for side, results in attempts.items():
            row[side] = results[number - 1] if number <= len(results) else "pending" if state == "active" else "not_taken"
        rounds.append(row)
    return {
        **attempts,
        "state": state,
        "round": current_round,
        "stage": "sudden_death" if current_round > 3 else "initial",
        "nextSide": next_side,
        "awayGoals": attempts["away"].count("goal"),
        "homeGoals": attempts["home"].count("goal"),
        "roundLabel": f"R{first_round}-{last_round}",
        "displayRounds": rounds,
    }


__all__ = [
    "SportsDisplayProjector",
    "nhl_manpower_situation",
    "nhl_goal_display",
    "nhl_shootout_display",
    "assign_active_team",
    "display_situation",
    "matches_followed_team",
    "normalize_rank",
    "normalize_soccer_clock",
    "soccer_event",
    "sport_family",
    "sports_content_sort_key",
]


def football_name_matches(token: str, name: str) -> bool:
    """Match a full name or ESPN initials without losing the surname."""

    def without_suffix(value):
        return re.sub(r"\s+(?:JR|SR|II|III|IV|V)\.?$", "", value, flags=re.IGNORECASE)

    def key(value):
        return re.sub(r"[\W_]+", "", without_suffix(value).casefold())

    if key(token) == key(name):
        return True
    parts = without_suffix(name).split()
    if not parts:
        return False
    initial = re.fullmatch(r"([A-Za-z.]+)\.\s*(.+)", token)
    if initial:
        return key(initial[2]) == key(parts[-1]) and key(" ".join(parts[:-1])).startswith(key(initial[1]))
    return key(token) == key(parts[-1])


def normalize_football_turnover_play(
    play: Mapping[str, Any],
    *,
    situation: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
    player_catalog: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Normalize one ESPN interception or fumble play for score alerts."""

    play_type = _mapping(play.get("type"))
    text = str(play.get("text") or play.get("shortText") or play.get("description") or "").strip()
    folded = f"{play_type.get('text') or ''} {text}".casefold()
    name_end = r"(?=(?<=[a-z])\.\s+|\s+(?:at|to|for|return(?:ed)?|ran|runs?)\b|[,;()]|$)"
    if re.search(r"\bintercept(?:ion|ed)\b", folded):
        kind = "interception"
        role_words = ("interceptor", "interception", "defender", "returner")
        name_match = re.search(
            r"\b(?:intercepted(?:\s+by)?|interception by)\s+([^,;()]+?)" + name_end,
            text,
            re.IGNORECASE,
        )
    elif re.search(r"\bfumbl(?:e|es|ed|ing)\b", folded):
        kind = "fumble"
        role_words = ("recoverer", "recovery", "fumbler", "rusher", "runner")
        name_match = re.search(
            r"\b(?:recovered by|fumbled by|fumble by)\s+([^,;()]+?)" + name_end,
            text,
            re.IGNORECASE,
        )
    else:
        return {}

    score_value = play.get("scoreValue", play.get("score_value"))
    is_scoring = bool(
        score_value not in (None, "", 0, "0")
        or re.search(r"\b(touchdown|for a td|safety)\b", folded)
    )
    home = home_abbr.upper()
    away = away_abbr.upper()
    play_team = _possession(
        play.get("team") or play.get("teamId") or play.get("possession"),
        competition,
        home_abbr,
        away_abbr,
    )
    role_teams = {
        str(record.get("type") or "").casefold(): _possession(
            record.get("id") or record.get("team"), competition, home_abbr, away_abbr,
        )
        for record in (_mapping(value) for value in _sequence(play.get("teamParticipants")))
    }
    start_team = _possession(_mapping(play.get("start")).get("team"), competition, home_abbr, away_abbr)
    end_team = _possession(_mapping(play.get("end")).get("team"), competition, home_abbr, away_abbr)
    offense = role_teams.get("offense") or start_team or play_team or _possession(
        situation.get("possession"), competition, home_abbr, away_abbr
    )
    active_possession = _possession(
        situation.get("possession"), competition, home_abbr, away_abbr
    )
    athletes = tuple(
        _mapping(value)
        for value in _sequence(play.get("athletesInvolved") or play.get("participants"))
    )
    catalog = {
        str(_mapping(record.get("athlete")).get("id") or ""): record
        for record in player_catalog
    }
    candidates: list[tuple[str, str, str]] = []
    for record in athletes:
        athlete = _mapping(record.get("athlete") or record.get("player") or record)
        catalog_record = _mapping(catalog.get(str(athlete.get("id") or "")))
        athlete = {**_mapping(catalog_record.get("athlete")), **athlete}
        name = str(
            athlete.get("displayName")
            or athlete.get("fullName")
            or athlete.get("shortName")
            or ""
        ).strip()
        team = _possession(
            athlete.get("team") or record.get("team") or catalog_record.get("team"),
            competition,
            home_abbr,
            away_abbr,
        )
        role = " ".join(
            str(record.get(key) or "")
            for key in ("role", "type", "displayRole", "description")
        ).casefold()
        if name:
            candidates.append((name, team, role))

    named_player = name_match.group(1).strip() if name_match else ""
    if not named_player:
        text_prefix = text.split("(", 1)[0].strip()
        player_match = re.match(r"(.+?)\s+\d+\s+(?:yd|yards?)\b", text_prefix, re.IGNORECASE)
        if player_match:
            named_player = player_match.group(1).strip()
    named_player = re.sub(r"^#\d+\s*", "", named_player).strip(" ,.;")
    named_team = ""
    for abbreviation in (home, away):
        for alias in _TEAM_ALIASES.get(abbreviation, (abbreviation,)):
            if named_player.startswith(alias + "-"):
                named_team = abbreviation
                named_player = named_player[len(alias) + 1:]
                break
    catalog_candidates = []
    for record in player_catalog:
        athlete = _mapping(record.get("athlete"))
        name = str(athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "").strip()
        team = _possession(record.get("team") or athlete.get("team"), competition, home_abbr, away_abbr)
        if name:
            catalog_candidates.append((name, team, ""))
    preferred_team = named_team or (role_teams.get("defense") if kind == "interception" else "") or end_team or (play_team if is_scoring else "")
    matches = {
        candidate for candidate in (*candidates, *catalog_candidates)
        if named_player and football_name_matches(named_player, candidate[0])
        and (not preferred_team or not candidate[1] or candidate[1] == preferred_team)
    }
    identities = {(candidate[0], candidate[1]) for candidate in matches}
    actor = next(iter(matches)) if len(identities) == 1 else None
    if actor is None:
        actor = next(
            (
                candidate
                for candidate in candidates
                if any(word in candidate[2] for word in role_words)
            ),
            None,
        )
    if actor is None and kind == "interception":
        actor = next(
            (
                candidate
                for candidate in candidates
                if candidate[1] and candidate[1] != offense
            ),
            None,
        )
    if actor is None and kind == "fumble":
        actor = next(
            (
                candidate
                for candidate in candidates
                if candidate[1] == offense
            ),
            None,
        )

    player = actor[0] if actor else named_player
    actor_team = actor[1] if actor else ""
    if kind == "interception":
        team = actor_team or named_team or role_teams.get("defense") or end_team or (
            play_team if is_scoring else ""
        ) or (active_possession if active_possession and active_possession != offense else "")
        if not team and offense in {home, away}:
            team = away if offense == home else home
    else:
        team = actor_team or named_team or end_team or (play_team if is_scoring else "") or offense or active_possession

    period = _mapping(play.get("period"))
    clock = _mapping(play.get("clock"))
    period_text = str(
        period.get("displayValue") or period.get("number") or ""
    ).strip()
    clock_text = str(
        clock.get("displayValue") or clock.get("value") or ""
    ).strip()
    return_match = re.search(
        r"\b(\d+)\s*(?:yd|yard)s?\s*(?:interception\s*)?return\b|"
        r"\breturn(?:ed)?\s+for\s+(\d+)\s+yards?\b",
        text,
        re.IGNORECASE,
    )
    return_yards = next(
        (int(value) for value in return_match.groups() if value),
        None,
    ) if return_match else None
    source_id = str(play.get("id") or "").strip()
    if not source_id:
        fingerprint = "|".join((period_text, clock_text, text.casefold()))
        source_id = sha1(fingerprint.encode("utf-8")).hexdigest()[:16]

    result: dict[str, Any] = {
        "id": source_id,
        "kind": kind,
        "team": team,
        "player": player,
        "text": text[:180],
        "is_scoring": is_scoring,
    }
    if return_yards is not None:
        result["return_yards"] = return_yards
    if period_text:
        result["period"] = period_text
    if clock_text:
        result["clock"] = clock_text
    if score_value not in (None, ""):
        result["score_value"] = score_value
    down = _integer_or_none(play.get("down") or _mapping(play.get("start")).get("down"))
    distance = _integer_or_none(
        play.get("distance") or _mapping(play.get("start")).get("distance")
    )
    if down is None:
        down = _integer_or_none(situation.get("down"))
    if distance is None:
        distance = _integer_or_none(situation.get("distance"))
    if down is not None:
        result["down"] = down
    if distance is not None:
        result["distance"] = distance
    red_zone = football_red_zone_for_play(
        play,
        situation=situation,
        competition=competition,
        home_abbr=home_abbr,
        away_abbr=away_abbr,
    )
    if red_zone is not None:
        result["is_red_zone"] = red_zone
    return result


def football_red_zone_for_play(
    play: Mapping[str, Any],
    *,
    situation: Mapping[str, Any],
    competition: Mapping[str, Any],
    home_abbr: str,
    away_abbr: str,
) -> bool | None:
    """Resolve red-zone state from one play before using live situation state."""

    contexts = (
        play,
        _mapping(play.get("situation")),
        _mapping(play.get("start")),
    )
    for context in contexts:
        for key in ("isRedZone", "is_red_zone", "redZone"):
            if key in context and context[key] is not None:
                value = context[key]
                if isinstance(value, str):
                    return value.strip().casefold() in {"true", "1", "yes"}
                return bool(value)

    start = _mapping(play.get("start"))
    yards_to_goal = _integer_or_none(start.get("yardsToEndzone"))
    if yards_to_goal is not None:
        return yards_to_goal <= 20
    raw_line = next(
        (
            value for value in (
                start.get("yardLine"),
                start.get("yardLineText"),
                play.get("yardLine"),
                play.get("yardLineText"),
            )
            if value not in (None, "")
        ),
        None,
    )
    if isinstance(raw_line, Mapping):
        raw_line = raw_line.get("text") or raw_line.get("displayValue") or raw_line.get("value")
    if isinstance(raw_line, str) and re.search(r"[A-Z]{2,4}", raw_line, re.IGNORECASE):
        text = raw_line if " at " in raw_line.casefold() else f"at {raw_line}"
        yard_line = _yard_line(text, home_abbr, away_abbr)
    else:
        yard_line = _integer_or_none(raw_line)

    possession = _possession(
        play.get("possession") or play.get("team") or situation.get("possession"),
        competition,
        home_abbr,
        away_abbr,
    )
    if yard_line is not None and possession in {home_abbr, away_abbr}:
        yards_to_goal = yard_line if possession == away_abbr else 100 - yard_line
        return yards_to_goal <= 20

    current = situation.get("isRedZone")
    return bool(current) if current is not None else None
