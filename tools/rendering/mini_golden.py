"""Record and check the pixels of every Mini pane for a fixed input corpus.

A case is one row of `render_mini_ui.cpp`: a mode, the pane data, and a frame sequence. The tool
compiles the production drawing code natively and prints one FNV-1a digest over all frames of
each case. The corpus stores only inputs. Stand-in sprites and artwork come from a seed, so no
case reads a file or the network.

  python tools/rendering/mini_golden.py build    # write the corpus and the digests
  python tools/rendering/mini_golden.py check    # render the corpus and compare
  python tools/rendering/mini_golden.py accept   # keep the corpus and write new digests

Use "accept" only after a pixel change on purpose, and inspect real 64x32 frames of the changed cases first.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
import sys
import tempfile
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [os.path.join(str(ROOT), name) for name in ("shared", "server", "six", "")]
CORPUS = ROOT / "tests/fixtures/mini_golden/corpus.json.gz"
DIGESTS = ROOT / "tests/fixtures/mini_golden/digests.json"
LIBRARY = ROOT / "docs/contracts/demo-layouts.json"
SIX_CORPUS = ROOT / "tests/fixtures/six_golden/corpus.json.gz"
ANIMATED = {"weather": (60, 350), "music": (60, 300), "airports": (60, 300), "message": (60, 150), "pairing": (12, 250)}


def _seed(text: str) -> str:
    return "standin:" + str(int(hashlib.sha256(text.encode()).hexdigest()[:6], 16))


def _row(name: str, mode: str, game: dict[str, Any], *, logos: bool = True, frames: tuple[int, int] | None = None,
         **extra: Any) -> dict[str, Any]:
    """Return one renderer row. Sports and stock rows get stand-in sprites for the logos they name."""
    from ticker.server.providers.logo_overrides import mini_logo_sources

    row = {"name": name, "mode": mode, "game": game, **extra}
    background = game.get("background") or {} if mode == "message" else {}
    asset_mode, asset_game = background.get("mode", mode), background.get("game", game)
    for side in ("away", "home"):
        urls = mini_logo_sources(asset_game, side) if asset_mode == "sports" else ()
        if asset_mode == "stock" and side == "home" and asset_game.get("home_logo"):
            urls = (asset_game["home_logo"],)
        if logos and urls:
            row[side + "_sprite"] = _seed(urls[0])
    count, step = frames or ANIMATED.get(mode, (1, 100))
    if count > 1:
        row.update(frame_count=count, frame_ms=step)
    return row


def _mini_game(game: dict[str, Any], name: str) -> dict[str, Any]:
    """Turn a projected racing item into its Mini card. Keep every other game as given."""
    from ticker.server.projections.racing_display import mini_racing_cards
    from ticker.server.web.preview import project_preview_game

    projected = project_preview_game(game)
    if projected.get("racing_display"):
        return mini_racing_cards({"id": name, "is_shown": True, "data": projected})[0]["data"]
    return game


def library_cases() -> Iterator[dict[str, Any]]:
    """Each case of the public layout library, with logos and, for sports, without logos."""
    source = json.loads(LIBRARY.read_text(encoding="utf-8"))
    from datetime import datetime

    for example in source["cases"]:
        game = _mini_game(deepcopy(example["game"]), example["name"])
        now = datetime.fromisoformat(example.get("example_time", source["example_time"])).timestamp()
        extra: dict[str, Any] = {"now_epoch": now}
        if example["mode"] == "music" and game.get("cover") == "demo:album":
            extra["cover_artwork"] = _seed("album")
            game["cover_asset"] = {"accent_rgb": [214, 120, 64]}
        yield _row("library-" + example["name"], example["mode"], game, **extra)
        if example["mode"] in {"sports", "stock"}:
            yield _row("library-" + example["name"] + "-no-logos", example["mode"], game, logos=False, **extra)


def six_sports_cases() -> Iterator[dict[str, Any]]:
    """Each distinct sports item of the Six golden corpus, drawn as a Mini pane."""
    from tools.rendering.six_golden import decode

    seen = set()
    for case in json.loads(gzip.decompress(SIX_CORPUS.read_bytes())):
        for kind, method, args in case["calls"]:
            if kind not in {"sports", "racing"} or method != "render":
                continue
            item = dict(decode(args)["item"])
            item.pop("sports_presentation", None)
            key = json.dumps(item, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            name = f"six-{len(seen):04d}"
            yield _row(name, "sports", _mini_game(json.loads(key), name), logos=case["logos"])


def fixture_cases() -> Iterator[dict[str, Any]]:
    """The Mini hockey and racing fixtures, and the local sports examples of the Mini preview tool."""
    from tools.rendering.render_mini_ui import cases as preview_cases

    for row in json.loads((ROOT / "tests/fixtures/display/mini_hockey_panes.json").read_text(encoding="utf-8")):
        yield _row("hockey-" + row["name"], "sports", row["game"])
    racing = json.loads((ROOT / "tests/fixtures/display/mini_racing.json").read_text(encoding="utf-8"))
    for row in racing["cases"]:
        for index, item in enumerate(row["payload"]["content"]["racing"]):
            for elapsed in (0, 1600, 9000):
                yield _row(f"racing-{row['name']}-{index}-{elapsed}", "sports", item["data"], elapsed_ms=elapsed,
                           signal_ms=elapsed, frame_count=12, frame_ms=350)
    snapshot = json.loads((ROOT / "tests/fixtures/display/render_snapshot.json").read_text(encoding="utf-8"))
    for row in preview_cases(snapshot):
        yield _row("preview-" + row["name"], row.get("mode", "sports"), row["game"])


def synthetic_cases() -> Iterator[dict[str, Any]]:
    """Variations that reach each branch of the non-sports panes."""
    for icon in ("sun", "cloud", "rain", "snow", "fog", "storm", "unknown"):
        for is_day in (0, 1):
            for temperature in (-4, 34, 54, 74, 89, 104, None):
                for city in ("NYC", "BETHLEHEM PENNSYLVANIA UNITED STATES"):
                    game = {"city": city, "temperature": temperature, "icon": icon, "is_day": is_day,
                            "feels": temperature, "wind": 7, "humidity": 41, "aqi": None if temperature is None else 33}
                    yield _row(f"weather-{icon}-{is_day}-{temperature}-{len(city)}", "weather", game)
    for title, artist in (("SHORT", "BAND"), ("A VERY LONG SONG TITLE THAT SCROLLS", "AN ARTIST WITH A LONG NAME")):
        for playing in (True, False):
            for cover in (True, False):
                for status in ("", "idle"):
                    game = {"name": title, "artist": artist, "is_playing": playing, "progress": 61, "duration": 245,
                            "fetch_ts": 1800000000.0, "status": status}
                    extra: dict[str, Any] = {"now_epoch": 1800000004.0, "scroll_ms": 1000}
                    if cover:
                        game["cover_asset"] = {"accent_rgb": [40, 200, 120]}
                        extra["cover_artwork"] = _seed(title)
                    yield _row(f"music-{len(title)}-{playing}-{cover}-{status or 'live'}", "music", game, **extra)
    yield _row("music-no-duration", "music", {"name": "RADIO", "artist": "LIVE", "is_playing": True})
    base = json.loads(LIBRARY.read_text(encoding="utf-8"))
    flight = next(case["game"] for case in base["cases"] if case["mode"] == "flights")
    for status, live, delayed, extra_fields in (("EN ROUTE", True, False, {}), ("LANDED", False, False, {}),
                                                ("DIVERTED", False, False, {}), ("CANCELLED", False, False, {}),
                                                ("SCHEDULED", False, True, {"delay_min": 45}), ("ARRIVED", False, False, {"progress": 100}),
                                                ("BOARDING", False, False, {"origin_iata": "", "dest_iata": "", "progress": 0})):
        yield _row(f"flight-{status}-{delayed}", "flights", {**flight, "status": status, "is_live": live, "is_delayed": delayed, **extra_fields})
    yield _row("flight-blank", "flights", {"id": "FLIGHT_BLANK"})
    airport = next(case["game"] for case in base["cases"] if case["mode"] == "airports")
    rows = [{"flight_number": f"AA{index}", "airport_code": "BOS", "status": "ON TIME", "is_delayed": index % 2 == 1, "delay_min": 15 * index}
            for index in range(5)]
    for arrivals, departures in ((rows, rows[:2]), ([], rows), ([], [])):
        yield _row(f"airport-{len(arrivals)}-{len(departures)}", "airports", {**airport, "arrivals": arrivals, "departures": departures})
    for symbol, price, percent, logo in (("AAPL", "212.48", "+1.25%", True), ("BRK.B", "$412.10", "-0.88%", False),
                                         ("VERYLONGSYM", "12345.6789", "--", True), ("", None, None, False)):
        game = {"symbol": symbol, "home_score": price, "away_score": percent, "home_logo": f"https://logos.example/{symbol}.png" if logo else ""}
        yield _row(f"stock-{symbol or 'empty'}", "stock", game)
    for ready in (True, False):
        for seconds in (0, 29, 59):
            yield _row(f"clock-{ready}-{seconds}", "clock", {"ready": ready, "date": "FRI OCT 30", "time": "12:34:56", "seconds": seconds},
                       frame_count=20 if not ready else 1, frame_ms=150)
    kinds = ("startup", "connecting", "registering", "offline", "error", "empty", "assets", "checking", "downloading",
             "installing", "update_failed", "time_sync", "device_key")
    background = {"mode": "sports", "game": next(case["game"] for case in base["cases"] if case["mode"] == "sports")}
    for kind in kinds:
        for detail in ("", "SHORT", "A VERY LONG DETAIL THAT MUST SCROLL ACROSS"):
            for complete, total in ((0, 0), (3, 7), (9, 9)):
                game = {"utility_kind": kind, "detail": detail, "complete": complete, "total": total,
                        "clock": "9:04", "date": "FRI OCT 30", "age_seconds": 4000 if complete else 42}
                yield _row(f"message-{kind}-{len(detail)}-{complete}", "message", game)
            yield _row(f"message-{kind}-{len(detail)}-over", "message", {"utility_kind": kind, "detail": detail, "background": background})
    shootout = {"state": "complete", "roundLabel": "FINAL S/O", "displayRounds": [{"away": "goal", "home": "miss"}] * 3}
    yield _row("sports-wide-shootout", "sports", {"sport": "nhl", "state": "in", "status": "S/O", "away_abbr": "SEA", "home_abbr": "PHI",
                                                  "away_score": "112", "home_score": "108", "situation": {"shootout": shootout, "activeTeam": "XYZ"}})
    racing = next(case["game"] for case in base["cases"] if case["game"].get("racing_display") or case["game"].get("type") == "racing")
    card = _mini_game(deepcopy(racing), "racing-no-signals")
    card["racing_display"].pop("signals", None)
    yield _row("racing-no-signals", "sports", card)
    for wifi in (True, False):
        for code in ("123456", ""):
            yield _row(f"pairing-{wifi}-{code or 'wait'}", "pairing", {"wifi_setup": wifi, "wifi_pin": code, "app_code": code})


def corpus() -> list[dict[str, Any]]:
    cases = [*library_cases(), *six_sports_cases(), *fixture_cases(), *synthetic_cases()]
    names = [case["name"] for case in cases]
    if len(names) != len(set(names)):
        raise ValueError("Golden case names must be unique")
    return cases


def renderer(arduinojson: Path | None) -> Path:
    """Compile the production drawing code for this host. Return the executable."""
    compiler = shutil.which("g++")
    if compiler is None:
        raise RuntimeError("Install g++ to render Mini golden cases")
    if arduinojson is None:
        arduinojson = ROOT / "mini/.pio/libdeps/esp32s3/ArduinoJson/src"
    if not (arduinojson / "ArduinoJson.h").is_file():
        raise RuntimeError(f"ArduinoJson headers are missing. Build the firmware or pass --arduinojson: {arduinojson}")
    output = Path(tempfile.mkdtemp(prefix="mini-golden-")) / "render-mini"
    subprocess.run([compiler, "-std=c++17", "-O1", "-Imini/src/mini/protocol", "-Imini/src/mini/assets",
                    f"-I{arduinojson}", "tools/rendering/render_mini_ui.cpp", "-o", str(output)], cwd=ROOT, check=True)
    return output


def digests(executable: Path, cases: list[dict[str, Any]]) -> list[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(cases, handle)
    try:
        output = subprocess.run([str(executable), handle.name, "--digest"], check=True, capture_output=True, text=True).stdout
    finally:
        Path(handle.name).unlink()
    result = output.split()
    if len(result) != len(cases):
        raise RuntimeError(f"The renderer returned {len(result)} digests for {len(cases)} cases")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("build", "check", "accept"))
    parser.add_argument("--arduinojson", type=Path, help="The ArduinoJson src directory. The default is the PlatformIO copy.")
    args = parser.parse_args()
    executable = renderer(args.arduinojson)
    if args.action == "build":
        cases = corpus()
        CORPUS.parent.mkdir(parents=True, exist_ok=True)
        CORPUS.write_bytes(gzip.compress(json.dumps(cases, separators=(",", ":")).encode(), mtime=0))
    else:
        cases = json.loads(gzip.decompress(CORPUS.read_bytes()))
    actual = digests(executable, cases)
    failed = sum(value == "0000000000000000" for value in actual)
    if args.action == "check":
        expected = json.loads(DIGESTS.read_text(encoding="utf-8"))
        changed = [index for index, value in enumerate(actual) if index >= len(expected) or expected[index] != value]
        print(f"{len(cases)} cases, {len(changed)} changed")
        for index in changed[:20]:
            print("changed:", cases[index]["name"])
        return 1 if changed or len(expected) != len(actual) else 0
    if args.action == "accept":
        before = json.loads(DIGESTS.read_text(encoding="utf-8"))
        changed = [cases[index]["name"] for index, value in enumerate(actual) if index >= len(before) or before[index] != value]
        print(f"{len(changed)} changed:", ", ".join(changed[:20]))
    DIGESTS.write_text(json.dumps(actual, indent=0) + "\n", encoding="utf-8")
    print(f"{len(cases)} cases, {sum(case.get('frame_count', 1) for case in cases)} frames, {failed} unknown modes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
