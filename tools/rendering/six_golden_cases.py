"""Synthetic Six golden cases that reach renderer branches that no fixture or test reaches.

Each function returns cases for one card. Each case renders one item at several times, with and without logos.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any

Encode = Callable[[Any], Any]


def cases(encode: Encode, base: datetime) -> Iterator[dict[str, Any]]:
    for source, kind, mode, items, elapsed in (*_golf(),):
        for item in items:
            for logos in (True, False):
                calls = [[kind, "render", encode({"now": base + timedelta(seconds=value), "item": item, "mode": mode,
                                                  "elapsed": value})] for value in elapsed]
                yield {"source": source, "logos": logos, "calls": calls}


def _golf() -> Iterator[tuple[str, str, str, list[dict[str, Any]], tuple[float, ...]]]:
    pars = [4, 5, 3, 4, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 5, 3, 4, 4]

    def player(name, pos, total, today=None, thru=0, holes=()):
        return {"name": name, "pos": pos, "total": total, "today": today, "thru": thru, "holes": list(holes)}

    full_round = [1, 3, 2, 4, 5, 6, 4, 7, 3, 4, 3, 4, 5, 4, 5, 3, 4, 4]
    stroke = [
        player("Scottie Scheffler", "1", -12, -5, 18, full_round),
        player("Rory McIlroy", "T2", -10, None, 9, [4, 4, 3, 3, 4, 2, 4, 4, 4]),
        player("Xander Schauffele", "T2", -10, "E", "F", full_round),
        player("Ludvig Aberg", "4", "E", "--", 0),
        player("Withdrawn Player", "WD", 5),
        player("Cut Player", "CUT", 8, 2, 18, full_round),
        player("Tommy Fleetwood", "6", "+3", "+1", "F"),
        player("Single", "7", "even"),
        player("Collin Morikawa", "8", 4, 1, 12, [5, 6, 4, 5]),
        player("Hideki Matsuyama", "9", 6, 3, 18, full_round),
        player("Jon Rahm", "10", 7, None, 4, [None, 5, None, 6]),
        player("Viktor Hovland", "11", 9, 4, 18, full_round),
        player("Patrick Cantlay", "12", 10, 5, 18, full_round),
        player("Justin Thomas", "13", 11, 6, 18, full_round),
        player("Max Homa", "14", 12, 7, 18, full_round),
        player("Sam Burns", "15", 13, 8, 18, full_round),
    ]
    unranked = [player("Alpha Bravo", "-", 3), player("Charlie Delta", "", -2), player("Echo Foxtrot", "-", 3)]
    items = []
    for brand in ("pga", "masters"):
        for players in (stroke, stroke[:2], unranked, []):
            for event in ({"event_name": "The Open", "round": "Round 3"}, {"round": "FINAL"}, {}):
                golf = {"brand": brand, "pars": pars, "players": players, **event}
                items.append({"id": f"golf-{brand}-{len(players)}", "type": "golf", "sport": "golf", "status": "R4",
                              "away_abbr": "PGA", "golf": golf})
    items.append({"id": "masters-key", "type": "masters", "sport": "masters", "masters": {"brand": "masters", "players": stroke[:3]}})
    items.append({"id": "golf-bad", "type": "golf", "sport": "golf", "golf": {"players": "none", "pars": "none"}})
    items.append({"id": "golf-empty", "type": "golf", "sport": "golf"})
    sides = (
        ({"team": "USA", "player": "Scottie Scheffler", "score": "3&2"}, {"team": "INTL", "player": "Hideki Matsuyama", "score": ""}),
        ({"team": "USA", "player": "Xander", "score": ""}, {"team": "INTL", "score": "2 UP"}),
        ({"team": "USA", "score": "AS"}, {"team": "INTL", "score": ""}),
        ({"team": "UNITED STATES", "score": "Halved"}, {"team": "INTERNATIONAL", "score": ""}),
        ({"team": "USA", "score": ""}, {"team": "INTL", "score": ""}),
        ({"player": "Tony Finau"}, {"player": "Adam Scott", "score": "1 UP"}),
        ({}, {}),
    )
    matches = [{"sides": list(pair)} for pair in sides]
    for count in (0, 2, 3, 7):
        for teams in ([{"abbr": "USA", "score": "11.5"}, {"abbr": "INTL", "score": "6.5"}], [{"abbr": "United States"}], []):
            for event in ({"event_name": "Presidents Cup"}, {}):
                golf = {"format": "match_play", "teams": teams, "matches": matches[:count] + (["bad"] if count == 7 else []), **event}
                items.append({"id": f"match-{count}-{len(teams)}", "type": "golf", "sport": "golf", "golf": golf})
    items.append({"id": "match-bad", "type": "golf", "sport": "golf",
                  "golf": {"format": "match_play", "teams": "none", "matches": [{"sides": "none"}]}})
    elapsed = (0.0, 4.0, 8.5, 12.0, 16.0, 30.0)
    yield "synthetic:golf", "golf", "sports", items, elapsed
    yield "synthetic:golf-pinned", "golf", "sports", [{**item, "sports_presentation": "pinned"} for item in items], elapsed
