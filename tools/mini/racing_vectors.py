"""Export deterministic Mini racing contracts for native renderer checks."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sports_ticker.providers.sports_display import RACING_FLAGS
from sports_ticker.projections.racing_display import racing_cards
from sports_ticker.projections.device_data import project_device_data

TARGET = ROOT / "tests/fixtures/display/mini_racing.json"


def game(sport="imsa", flag="GREEN"):
    members = []
    classes = ("GTP", "LMP2", "GTDPRO", "GTD") if sport == "imsa" else ("HYPERCAR", "LMGT3") if sport == "wec" else ("",)
    for group_index, group in enumerate(classes):
        for position, car in enumerate(("45", "12", "9"), 1):
            members.append({"pos": group_index * 3 + position, "class_pos": position, "class": group,
                            "car": car, "name": ("Tyler Reddick", "Ryan Blaney", "Chase Elliott")[position - 1],
                            "abbr": ("RED", "BLA", "ELL")[position - 1], "manufacturer": "Porsche 963",
                            "livery_primary": "#E8002D", "gap": ("Leader", "+0.801s", "+2.924s")[position - 1]})
    return {"id": "vector", "type": "racing", "sport": sport, "state": "in", "status": "LIVE",
            "startTimeUTC": "2026-10-23T20:00:00Z", sport: {
                "short_name": "Petit Le Mans" if sport == "imsa" else "Barcelona 6h" if sport == "wec" else "Phoenix",
                "session_name": "Race", "flag": flag, "lap": 65, "total_laps": 200, "drivers": members}}


def mini_payload(source):
    data = deepcopy(source)
    data["racing_display"] = {"cards": racing_cards(data)}
    payload = {"api_version": "v2", "settings": {"mode": "sports", "brightness": 100},
               "meta": {"pairing": {"paired": True}}, "content": {
                   "racing": [{"id": data["id"], "family": "racing", "kind": data["sport"], "is_shown": True, "data": data}]}}
    return project_device_data(payload, mini=True)


def vectors():
    result = []
    for code in RACING_FLAGS:
        source = game("nascar", code)
        result.append({"name": "flag-" + code.lower().replace(" ", "-"), "flag": code,
                       "payload": mini_payload(source), "elapsed_ms": 0})
    for sport in ("f1", "indycar", "wec", "imsa"):
        result.append({"name": sport, "flag": "GREEN", "payload": mini_payload(game(sport)), "elapsed_ms": 0})
    target = game("nascar")
    target["nascar"]["signals"] = [{"active": True, "flag": "BLACK", "scope": "car", "car": "45"}]
    result.append({"name": "car-signal", "flag": "GREEN", "payload": mini_payload(target), "elapsed_ms": 2000})
    target = game("wec")
    target["wec"]["signals"] = [{"active": True, "flag": "DOUBLE YELLOW", "scope": "sector", "sector": "2"}]
    result.append({"name": "sector-signal", "flag": "GREEN", "payload": mini_payload(target), "elapsed_ms": 2000})
    target = game("f1")
    target.update(state="pre", status="14:00")
    target["f1"]["drivers"] = []
    result.append({"name": "upcoming", "flag": "NONE", "payload": mini_payload(target), "elapsed_ms": 0})
    target = game("nascar", "YELLOW")
    target["nascar"]["flag_raw"] = "WAVED YELLOW"
    result.append({"name": "motion-waved", "flag": "YELLOW", "payload": mini_payload(target), "elapsed_ms": 350})
    rotation = mini_payload(game("imsa"))
    rotation["content"]["sports"] = [
        {"id": "hidden", "is_shown": False, "data": {"sport": "nhl"}},
        {"id": "hockey", "is_shown": True, "data": {"sport": "nhl"}},
    ]
    rotation["content"]["stock"] = [{"id": "stock", "is_shown": True, "data": {"sport": "stock"}}]
    return {"cases": result, "rotation": rotation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=TARGET)
    args = parser.parse_args()
    expected = json.dumps(vectors(), ensure_ascii=True, indent=2) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != expected:
            raise SystemExit("Mini racing vectors differ from the V2 projection")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(expected, encoding="utf-8")


if __name__ == "__main__":
    main()
