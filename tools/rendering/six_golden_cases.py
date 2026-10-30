"""Synthetic Six golden cases that reach renderer branches that no fixture or test reaches.

Each function returns cases for one card. Each case renders one item at several times, with and without logos.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any

Encode = Callable[[Any], Any]


def cases(encode: Encode, base: datetime) -> Iterator[dict[str, Any]]:
    for source, kind, mode, items, elapsed in (*_golf(), *_racing()):
        for item in items:
            for logos in (True, False):
                calls = [[kind, "render", encode({"now": base + timedelta(seconds=value), "item": item, "mode": mode,
                                                  "elapsed": value})] for value in elapsed]
                yield {"source": source, "logos": logos, "calls": calls}
    yield from _alerts(encode)
    yield from _news(encode)
    yield from _sports(encode, base)
    yield from _ads(encode, base)


def _under():
    """A busy frame under an overlay, so a shutter or a slide shows what it covers."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (384, 32), (12, 30, 60))
    draw = ImageDraw.Draw(image)
    for x in range(0, 384, 24):
        draw.rectangle((x, 4, x + 11, 27), fill=(200, 90 + x % 120, 40))
    return image


def _alerts(encode: Encode) -> Iterator[dict[str, Any]]:
    """Score alerts from the alert gallery, with color, logo, fact, status, and down variants, at each phase."""
    from tools.rendering.render_score_alert_gallery import EXAMPLES

    base = [{key: value for key, value in example.items() if key not in {"title", "source", "url"}} for example in EXAMPLES]
    variants = []
    for alert in base:
        variants.append(alert)
        variants.append({**alert, "team_logo": f"https://logos.example/{alert['team_abbr'].lower()}.png"})
    long_facts = {"player": "Christopher Columbus Alexander-Smith", "data": "47YD PASS FROM Christopher Columbus Alexander-Smith TO THE END ZONE",
                  "primary_assist": "Bartholomew Longname", "secondary_assist": "Maximilian Evenlongername"}
    first = base[0]
    variants += [
        {**base[5], **long_facts},
        {**base[5], "player": "Adam Fox", "primary_assist": "Very Longassistname"},
        {**first, "player": "", "data": "", "primary_assist": "", "secondary_assist": ""},
        {**first, "headline": "A VERY LONG FUTURE SPORT HEADLINE THAT CANNOT FIT"},
        {**first, "headline": "THREE POINTER BUZZER BEATER"},
        {**first, "team_color": "#000000", "team_alt_color": "#000000"},
        {**first, "team_color": "#010101", "team_logo": "https://logos.example/dark.png"},
        {**first, "team_color": "#FFD700", "team_alt_color": "#FFFFFF"},
        {**first, "team_color": "", "team_alt_color": "#FF0000"},
        {**first, "team_color": "nonsense", "team_alt_color": None},
        {**first, "status": "Top 7th"}, {**first, "status": "Mid 5th"}, {**first, "status": "End 8th"},
        {**first, "status": "Final"}, {**first, "status": "Rain Delay 6th"}, {**first, "status": "Bottom"},
        {**first, "sport": "wbc", "status": "^3"},
        {**base[7], "down_distance": "1 & Goal", "is_red_zone": True},
        {**base[7], "down_distance": "3&10"}, {**base[7], "down_distance": "bad"},
        {**base[7], "status": "TOP OF HOUR BOT"},
        {**first, "home_score": None, "away_score": 105, "team_abbr": "MIL"},
        {**first, "team_abbr": "XXX"},
    ]
    timings = (0.0, 0.1, 0.25, 0.39, 0.45, 0.6, 1.0, 1.5, 3.0, 7.7, 7.8, 7.95, 8.0, 9.0)
    under = _under()
    for alert in variants:
        for logos in (True, False):
            for frame in (under, None):
                calls = [["alert", "render", encode({"alert": alert, "elapsed": value, "under": frame})] for value in timings]
                yield {"source": "synthetic:alert", "logos": logos, "calls": calls}


def _news(encode: Encode) -> Iterator[dict[str, Any]]:
    """News banners of each kind and domain, sliding in, held, and sliding out."""
    kinds = ("TRADE", "MAJOR", "BLOCKBUSTER", "SIGNING", "EXTENSION", "INJURY", "WAIVER", "DFA", "RELEASE", "OPTION", "RECALL",
             "ACTIVATED", "SUSPENSION", "RETIREMENT", "NO_TENDER", "RUMOR", "")
    text = "The Rangers acquire a defenseman and a conditional pick in exchange for two prospects and a fourth round selection"
    items = []
    for kind in kinds:
        items.append({"kind": kind, "text": text, "from_abbr": "NYR", "to_abbr": "PIT", "from_color": "0038A8",
                      "from_alt_color": "C8102E", "to_color": "#000000", "to_alt_color": "FCB514"})
    items += [
        {"kind": "TRADE", "impact_tier": "BLOCKBUSTER", "text": "Short trade", "from_abbr": "LAL", "to_abbr": "BOS"},
        {"kind": "TRADE", "text": "Only one club", "to_abbr": "SEA", "to_color": "002244"},
        {"kind": "SIGNING", "text": "Signs a one year deal", "from_abbr": "TOR", "from_color": "bad"},
        {"kind": "INJURY", "text": ""},
        {"domain": "stocks", "to_abbr": "AAPL", "pct": 2.345, "text": text},
        {"domain": "stocks", "to_abbr": "TSLAXYZ", "pct": -7.1, "text": "Shares fall"},
        {"domain": "stocks", "to_abbr": "MSFT", "pct": None, "text": "Market news without a move"},
        {"domain": "stocks", "to_abbr": "NVDA", "pct": "bad", "text": text + " " + text},
    ]
    under = _under()
    for item in items:
        duration = 0.3 + (7.4 if item.get("domain") == "stocks" else 6.4) + 0.3
        timings = (0.0, 0.1, 0.29, 0.31, 3.0, duration - 0.29, duration - 0.1, duration, duration + 0.5)
        calls = [["news", "render", encode({"item": item})]]
        calls += [["news", "apply", encode({"frame": under, "item": item, "elapsed": value})] for value in timings]
        yield {"source": "synthetic:news", "logos": True, "calls": calls}


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


def _racing() -> Iterator[tuple[str, str, str, list[dict[str, Any]], tuple[float, ...]]]:
    """Racing items in each series and session, projected by the real racing display contract."""
    from ticker3.web.preview import project_preview_game

    def driver(pos, name, car, **values):
        return {"pos": pos, "name": name, "car": car, **values}

    field = [
        driver("1", "Max Verstappen", "1", abbr="VER", team="Red Bull", gap="LEADER", best_time="1:32.110", speed="201.5",
               team_logo="https://logos.example/redbull.png", livery_primary="#1E41FF", livery_secondary="#FFD700"),
        driver("2", "Lando Norris", "4", abbr="NOR", team="McLaren", gap="+1.204", interval="+1.204", best_time="1:32.400",
               car_illustration="https://cars.example/mclaren.png"),
        driver("T3", "Alexander Albon With A Very Long Display Name", "23", team="Williams", gap="+5.9",
               livery_primary="#005AFF", livery_secondary="112233"),
        driver("DNF", "Retired Driver", "88", gap="DNF", livery_primary="#101010"),
        driver("5", "Badge Driver", "7", team_logo="https://logos.example/badge.png", gap="+10.0"),
        driver("6", "Missing Logo Car", "9", team_logo="https://logos.example/missing.png", gap="+11.1", livery_primary="zzzzzz"),
        driver("", "", "", gap=""),
    ]
    classes = [
        driver("1", "Hypercar Leader", "50", **{"class": "HYPERCAR", "class_pos": "1"}, gap="LEADER", team="Ferrari"),
        driver("2", "LMP2 Runner", "22", **{"class": "LMP2", "class_pos": "1"}, gap="+30.2", team="United Autosports"),
        driver("3", "GT Runner", "91", **{"class": "LMGT3", "class_pos": "1"}, gap="+1 LAP", manufacturer="Porsche",
               car_illustration="https://cars.example/porsche.png"),
    ]
    sessions = (
        {"session_type": "Race", "lap": 34, "total_laps": 57},
        {"session_type": "Race", "time_to_go": "01:12:30"},
        {"session_type": "Race", "time_to_go": "00:00:00"},
        {"session_name": "Qualifying", "qualifying_metric": "time"},
        {"session_name": "Qualifying", "qualifying_metric": "mph"},
        {"session_name": "Practice 2"},
        {"session_name": "Sprint Qualifying"},
    )
    flags = (("GREEN", "in", []), ("YELLOW", "in", [{"active": True, "code": "YELLOW", "scope": "sector", "sector": 2}]),
             ("RED", "in", []), ("SC", "in", [{"active": True, "code": "SC"}]), (None, "pre", []), (None, "post", []),
             ("CHECKERED", "post", []))
    weather = {"air_temp": 81.6, "wind_mph": 7.2, "wind_dir": 200}
    items = []
    names = {"f1": "Example Grand Prix", "nascar": "NASCAR Cup Series Example 400 Presented by Sponsor",
             "indycar": "110th Running of the Example 500", "wec": "6 Hours of Example Championship", "imsa": "Example Grand Prix"}
    for sport in ("f1", "nascar", "indycar", "wec", "imsa"):
        drivers = classes if sport in {"wec", "imsa"} else field
        for session in sessions:
            for flag, state, signals in flags:
                payload = {"short_name": names[sport], "flag": flag, "signals": signals, "drivers": drivers, "weather": weather,
                           **session}
                if sport == "nascar":
                    payload = {**payload, "laps_remaining": 0 if state == "post" else 23}
                game = {"sport": sport, "state": state, "status": "SUN 3:30 PM", sport: payload, "type": "racing", "id": f"{sport}-race"}
                items.append(project_preview_game(game))
        for count in (0, 1):
            game = {"sport": sport, "state": "pre", "status": "SUN 3:30 PM", "type": "racing", "id": f"{sport}-{count}",
                    sport: {"short_name": names[sport], "drivers": drivers[:count], "session_type": "Race"}}
            items.append(project_preview_game(game))
            items.append({**game, "racing_display": {"cards": [{"race_name": "WAITING RACE", "signals": [], "rows": []}]}})
    # No projected cards, and a series name with no payload of its own, which reads the IndyCar payload.
    items.append({"sport": "racing", "type": "racing", "id": "no-cards", "state": "in",
                  "indycar": {"short_name": "Fallback 200", "drivers": field[:2], "flag": "GREEN", "session_type": "Race"}})
    elapsed = (0.0, 0.4, 3.0, 9.0, 21.0)
    yield "synthetic:racing", "racing", "sports", items, elapsed
    yield "synthetic:racing-pinned", "racing", "sports", [{**item, "sports_presentation": "pinned"} for item in items], elapsed


def _sports(encode: Encode, base: datetime) -> Iterator[dict[str, Any]]:
    """Real gallery games with one fact changed, as a pane and pinned, at four hockey page times."""
    import json
    from copy import deepcopy

    from ticker3.web.preview import project_preview_game

    library = json.loads(open("docs/contracts/demo-layouts.json", encoding="utf-8").read())
    games = [project_preview_game(row["game"]) for row in library["cases"] if row["mode"] == "sports"]
    games = [game for game in games if game.get("sport") not in {"f1", "nascar", "indycar", "wec", "imsa", "golf"}]

    def family(game):
        sport = str(game.get("sport", "")).lower()
        return ("football" if any(word in sport for word in ("nfl", "ncf", "football")) else "baseball" if "mlb" in sport or "baseball" in sport
                else "hockey" if "nhl" in sport or "hockey" in sport else "soccer" if "soccer" in sport else "basketball")

    def situation(**values):
        return lambda game: {**game, "situation": {**(game.get("situation") or {}), **values}}

    def field(**values):
        return lambda game: {**game, **values}

    def goals(count):
        return lambda game: {**game, "situation": {**(game.get("situation") or {}), "hockeyGoals": [
            {"side": "away" if index % 4 else "home", "player": f"Player Number{index}", "time": f"P{index % 3 + 1} {index}:0{index % 10}",
             "assists": ["A One", "B Two"][: index % 3]} for index in range(count)]}}

    def soccer_events(count):
        events = [{"player": f"Longplayername{index}", "time": f"{10 + index}'", "own_goal": index == 2, "is_home": index % 3 != 1}
                  for index in range(count)]
        cards = [{"is_home": True, "player": "Sent Off", "time": "77'"}, {"is_home": False, "player": "", "time": ""}]
        return lambda game: {**game, "situation": {**(game.get("situation") or {}), "goal_events": events, "red_cards": cards}}

    common = [
        field(home_logo_rendering={"method": "new", "outline": "inner"}, away_logo_rendering={"outline": "auto", "cutoff": 90}),
        field(home_logo_rendering={"outline": "off"}, away_logo_rendering={"method": "old", "outline": "auto", "cutoff": "bad"}),
        field(home_logo="https://logos.example/missing-home.png", away_logo="https://logos.example/missing-away.png"),
        field(home_logo="", away_logo="", home_color="", away_color=""),
        field(home_color="#000000", home_alt_color="#FFFFFF", away_color="#808080", away_alt_color="#FF2200"),
        field(home_color="zzz", away_color="#FFFFFF", away_alt_color="#FFFFFF"),
        field(home_score=None, away_score="", status=""),
        field(home_score="104", away_score="99", status="FINAL/2OT"),
        field(home_rank=5, away_seed=12, competition_stage=1),
        field(competition_stage=2, home_seed=1, away_rank=25),
        field(state="pre", status="SAT 7:30 PM"),
    ]
    by_family = {
        "football": [
            situation(yardLine=None, downDistFull="1st & 10 at CAR 33", downDist="1st & 10", possession="CAR"),
            situation(yardLine=None, downDistFull="3rd & 4 at 50", downDist="3rd & 4"),
            situation(yardLine=None, downDistFull="2nd & 7 at XYZ 20", downDist="2nd & 7"),
            situation(yardLine=None, downDistFull="4th & 1 at CAR x", downDist="4th & 1"),
            situation(yardLine=None, downDistFull="Kickoff", downDist=""),
            situation(yardsToGo=None, downDist="3rd & Goal", isGoalToGo=True, yardLine=8),
            situation(yardsToGo=None, downDist="2nd & inches", yardLine=40),
            situation(yardsToGo=None, downDist="4th & 1.", yardLine=60),
            situation(isRedZone=True, yardLine=15),
            lambda game: {**game, "situation": {**(game.get("situation") or {}), "isRedZone": True,
                                                "possession": game.get("home_abbr"), "yardLine": 85}},
            lambda game: {**game, "situation": {**(game.get("situation") or {}), "isRedZone": True,
                                                "possession": game.get("away_abbr"), "yardLine": 12}},
            situation(possession=""),
        ],
        "baseball": [
            situation(batter_name="Juan Soto Jr.", batter_avg="0.312", batter_h="2", batter_ab="", pitcher_pitches=""),
            situation(batter_avg="", batter_h="", batter_ab="", last_pitch_speed=0, last_pitch_type_full="", pitcher_era="3.12"),
            situation(last_pitch_speed=97, last_pitch_type_full="Four-Seam Fastball (FF)", pitcher_name="Gerrit Cole"),
            situation(last_pitch_speed="88", last_pitch_type_full="Knuckle Curve/Slurve", last_pitch_type_abbr="KC"),
            situation(last_pitch_speed=84, last_pitch_type_full="Changeup Splitter Combination Pitch"),
            situation(last_pitch_speed=0, last_pitch_type_full="", last_pitch_type_abbr="", pitcher_era="-.--"),
            situation(last_pitch_speed=91, last_pitch_type_full="", last_pitch_type_abbr="", last_pitch_type=""),
            situation(onFirst=True, onSecond=True, onThird=True, balls=3, strikes=2, outs=2),
            field(home_challenges_used=2, away_challenges=0, home_challenges=None, away_challenges_used=None),
            field(home_challenges_used="bad", home_challenges=1, away_challenges_used=1),
            situation(batter_name="Christopher Bartholomew Longlastname-Hyphenated III", pitcher_name="A Verylongpitchername Sr"),
        ],
        "hockey": [goals(3), goals(7), goals(12), situation(emptyNet=True, emptyNetSide="home"),
                   situation(powerPlay=True, powerPlayTeam="home"), situation(shootout={"away": ["goal", "miss"], "home": ["miss"]})],
        "soccer": [soccer_events(2), soccer_events(4), soccer_events(7), soccer_events(0)],
        "basketball": [],
    }
    items = []
    seen = {}
    for game in games:
        kind = family(game)
        if seen.get(kind, 0) >= 2:
            continue
        seen[kind] = seen.get(kind, 0) + 1
        for mutation in common + by_family[kind]:
            item = mutation(deepcopy(game))
            item.setdefault("type", "scoreboard")
            item.setdefault("id", f"{kind}-{len(items)}")
            items.append(item)
    for item in items:
        for presentation in (None, "pinned"):
            shown = {**item, "sports_presentation": presentation} if presentation else item
            for logos in (True, False):
                calls = [["sports", "render", encode({"now": base + timedelta(seconds=step), "item": shown, "mode": "sports",
                                                      "elapsed": float(step)})] for step in (0, 5, 10, 15)]
                yield {"source": "synthetic:sports", "logos": logos, "calls": calls}


def _ads(encode: Encode, base: datetime) -> Iterator[dict[str, Any]]:
    """Every April Fools campaign card in the strip, with and without its logo."""
    from ticker_core.features.sports.ads import SPORTS_ADS

    for index, ad in enumerate(SPORTS_ADS):
        for spot in ad["spots"]:
            item = {"id": f"ad-{index}", "type": "fan_duel_joke_ad", "kind": "fan_duel_joke_ad", "sport": "sports", "family": "sports",
                    "state": "pre", "status": "SPORTS AD", "headline": ad["brand"], "tagline": spot["copy"], "detail": "PARODY",
                    "logo": ad["logo"], "logo_plate": ad.get("logo_plate"), "background": ad["background"], "accent": ad["accent"]}
            for logos in (True, False):
                call = ["sports", "render", encode({"now": base, "item": item, "mode": "sports", "elapsed": 0.0})]
                yield {"source": "synthetic:ad", "logos": logos, "calls": [call]}
    plain = {"type": "fan_duel_joke_ad", "sport": "sports", "logo": "https://logos.example/missing.png", "logo_plate": "#FFFFFF",
             "background": "bad", "accent": ""}
    yield {"source": "synthetic:ad", "logos": True, "calls": [["sports", "render", encode({"now": base, "item": plain, "mode": "sports", "elapsed": 0.0})]]}
