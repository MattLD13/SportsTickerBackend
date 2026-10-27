"""Project class cards and race-control signals before either device renders."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
import re
from typing import Any

from sports_ticker.providers.sports_display import racing_signal, racing_number_style, racing_flag_pixel

_SERIES = {"f1", "indycar", "nascar", "wec", "imsa"}
_CLASS_ORDER = {"HYPERCAR": 0, "LMGT3": 4, "GTP": 0, "LMP2": 1, "GTDPRO": 2, "GTD": 3}
_MAKES = (("PORSCHE", "POR"), ("TOYOTA", "TOY"), ("FERRARI", "FER"), ("ASTON", "AST"),
          ("MCLAREN", "MCL"), ("MERCEDES", "MER"), ("BMW", "BMW"), ("CADILLAC", "CAD"),
          ("ACURA", "ACU"), ("CORVETTE", "COR"), ("CHEVROLET", "CHE"), ("LEXUS", "LEX"))


def _position(driver):
    try:
        return int(driver.get("pos") or 9999)
    except (ValueError, TypeError):
        return 9999


def _name(sport, driver):
    if sport not in {"wec", "imsa"}:
        return str(driver.get("abbr") or re.sub(r"[^A-Za-z]", "", str(driver.get("name") or ""))[:3] or "---").upper()
    if str(driver.get("class")).upper() == "LMP2":
        raw = str(driver.get("team") or "").upper()
        for fragment, label in (("APR", "APR"), ("INTER EUROPOL", "INT"), ("ERA", "ERA"), ("TOWER", "TWR"), ("UNITED", "UNI"), ("TDS", "TDS")):
            if fragment in raw:
                return label
        return re.sub(r"[^A-Z]", "", raw)[:3] or "---"
    raw = str(driver.get("manufacturer") or driver.get("team") or "").upper()
    return next((label for fragment, label in _MAKES if fragment in raw), re.sub(r"[^A-Z]", "", raw)[:3] or "---")


def racing_cards(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one explicit top-three card per class without changing the full field."""
    sport = str(data.get("sport") or "").lower()
    if sport not in _SERIES:
        return []
    payload = data.get(sport) or {}
    state = str(data.get("state") or "pre")
    raw = payload.get("flag")
    raw = "NONE" if state == "pre" else raw or ("CHECKERED" if state == "post" else "UNKNOWN")
    track = racing_signal(raw, sport)
    original = payload.get("flag_raw")
    if original not in (None, ""):
        reported = racing_signal(original, sport)
        if reported["code"] == track["code"]:
            track = reported
        else:
            track["raw"] = str(original)
    reports = [track]
    for signal in payload.get("signals", ()):
        if isinstance(signal, Mapping) and signal.get("active") is True:
            reports.append(racing_signal(signal.get("code") or signal.get("flag"), sport,
                                         scope=str(signal.get("scope") or "track"), car=signal.get("car"), sector=signal.get("sector")))
    groups = defaultdict(list)
    drivers = sorted((d for d in payload.get("drivers", ()) if isinstance(d, Mapping)), key=_position)
    for driver in drivers:
        group = str(driver.get("class") or "").replace(" ", "").upper() if sport in {"wec", "imsa"} else ""
        groups[group].append(driver)
        if state == "in" and driver.get("flag"):
            signal = racing_signal(driver.get("flag_raw") or driver["flag"], sport, scope="car", car=driver.get("car"))
            if signal["code"] not in {"UNKNOWN", "NONE", "GREEN"}:
                reports.append(signal)
    if not groups:
        groups[""] = []
    session = str(payload.get("session_name") or payload.get("session_type") or "Race")
    timed = str(payload.get("qualifying_metric") or "") in {"time", "mph"} or any(word in session.lower() for word in ("qual", "practice", "hyperpole", "warm", "test", "fp"))
    try:
        year = datetime.fromisoformat(str(data.get("startTimeUTC") or "").replace("Z", "+00:00")).year
    except ValueError:
        year = 0
    status = str(data.get("status") or "WAIT")
    if state == "post":
        status = "FINAL"
    elif state == "in":
        lap, total = payload.get("lap"), payload.get("total_laps")
        status = f"{lap}/{total}" if lap and total else str(payload.get("time_to_go") or session)
    if len(status) > 6 and re.fullmatch(r"\d+:\d\d:\d\d", status):
        hours, minutes, _ = status.split(":")
        status = f"{hours}H{minutes}"
    if len(status) > 6 and re.fullmatch(r"\d+/\d+", status):
        status = "L" + status.split("/", 1)[0]
    status = re.sub(r"^(\d{1,2}:\d{2})\s*([AP])M$", r"\1\2", status, flags=re.IGNORECASE)
    if state == "in" and len(status) > 6:
        status = "LIVE"
    session_short = re.sub(r"Practice\s*(\d+)", r"FP\1", session, flags=re.IGNORECASE)
    session_short = re.sub(r"Sprint Qualifying", "SQ", session_short, flags=re.IGNORECASE)
    session_short = re.sub(r"Qualifying", "Q", session_short, flags=re.IGNORECASE)
    session_short = re.sub(r"Warm.?up", "WU", session_short, flags=re.IGNORECASE)
    if sport in {"f1", "indycar"}:
        badge = ("F1 " if sport == "f1" else "INDY ") + (session_short if timed else "")
    else:
        badge = "CUP" if sport == "nascar" else sport.upper()
    result = []
    for group, members in sorted(groups.items(), key=lambda pair: (_CLASS_ORDER.get(pair[0], 99), pair[0])):
        cars = {str(d.get("car")) for d in members}
        signals = [s for s in reports if s["scope"] != "car" or not s["car"] or s["car"] in cars]
        rows = []
        for index, driver in enumerate(members[:3], 1):
            metric = str(driver.get("gap") or driver.get("best_time") or "--")
            compact = "LEAD" if metric.casefold() == "leader" else metric
            if len(compact) > 8 and compact.endswith("s"):
                compact = compact[:-1]
            rows.append({"position": index, "overall_position": _position(driver), "car": str(driver.get("car") or ""),
                         "name": _name(sport, driver), "full_name": str(driver.get("name") or ""),
                         "metric": metric, "compact_metric": compact, "number_style": racing_number_style(sport, driver, year),
                         "position_rgb": list(((255, 215, 0), (192, 192, 192), (205, 127, 50))[index - 1]),
                         "metric_rgb": [255, 215, 0] if index == 1 else [180, 210, 255]})
        result.append({"class_id": group, "class_label": "HY" if group == "HYPERCAR" else "GTD PRO" if group == "GTDPRO" else group or badge.strip(),
                       "race_name": str(payload.get("short_name") or payload.get("event_name") or sport.upper()),
                       "session": session, "status": status.upper(), "state": state, "timed": timed,
                       "metric_type": str(payload.get("qualifying_metric") or ""), "signals": signals, "rows": rows})
    return result


def mini_racing_cards(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = item.get("data") or {}
    result = []
    for card in data.get("racing_display", {}).get("cards", ()):
        signals = []
        for signal in card["signals"]:
            pixels = []
            for y in range(5):
                for x in range(5):
                    r, g, b = racing_flag_pixel(signal, x, y, 5, 5)
                    pixels.append(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
            label = signal["label"]
            if signal["car"]:
                label = label[:2] + signal["car"]
            elif signal["sector"]:
                label = label[:1] + " S" + signal["sector"]
            signals.append({"code": signal["code"], "label": label, "pixels": pixels,
                            "flashing": signal["motion"] == "waved",
                            "show_label": signal["code"] not in {"GREEN", "NONE", "CHECKERED"}})
        view = {key: card[key] for key in ("race_name", "class_label", "status", "state")}
        view["rows"] = [{**{key: row[key] for key in ("position", "car", "name", "compact_metric", "position_rgb", "metric_rgb")},
                         "number_style": {key: row["number_style"][key] for key in ("color_rgb", "outline_rgb")}}
                        for row in card["rows"]]
        view["signals"] = signals
        result.append({**item, "id": str(item["id"]) + ":" + (card["class_id"] or "overall"),
                       "data": {**{key: data[key] for key in ("sport", "state", "status", "game_phase", "competition_stage", "situation",
                                                              "away_abbr", "home_abbr", "away_score", "home_score", "startTimeUTC") if key in data},
                                "racing_display": view}})
    return result
