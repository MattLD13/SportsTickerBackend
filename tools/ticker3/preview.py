"""Render Ticker 3 screens from recorded payloads into PNG previews.

Run: python tools/ticker3/preview.py [--scale 4] [--output previews/ticker3]
The tool runs the real feature code on tests/fixtures/ticker3 and composes the
screens with the real hub. Logos come from their URLs and are kept in the output folder.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from ticker3.contract.records import validate_record  # noqa: E402
from ticker3.contract.settings import subscription_key  # noqa: E402
from ticker3.core.builtin import BUILTINS  # noqa: E402
from ticker3.core.hub import App, Hub  # noqa: E402
from ticker3.features import racing, sports, weather  # noqa: E402
from ticker3.player import draw_frame  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "ticker3"
NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc).timestamp()


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class LogoCache:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        bundle = os.environ.get("TICKER3_CA_BUNDLE")
        self.context = ssl.create_default_context(cafile=bundle) if bundle else None

    def __call__(self, url: str, size: int):
        path = self.directory / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".png")
        if not path.exists():
            try:
                with urlopen(url, timeout=10, context=self.context) as response:
                    path.write_bytes(response.read())
            except OSError:
                return None
        logo = Image.open(path).convert("RGBA")
        logo.thumbnail((size, size), Image.LANCZOS)
        square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        square.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
        return square


def live_examples():
    """Return a live football game and a live baseball game made from the recorded payloads."""
    nfl = load("espn_nfl_2026-10-29.json")
    event = nfl["events"][1]
    event["status"] = {"period": 3, "displayClock": "8:12", "type": {"state": "in"}}
    away = next(team for team in event["competitions"][0]["competitors"] if team["homeAway"] == "away")
    for team in event["competitions"][0]["competitors"]:
        team["score"] = "17" if team is away else "14"
    event["competitions"][0]["situation"] = {"possession": away["id"], "shortDownDistanceText": "3rd & 4", "isRedZone": True}
    nfl["events"] = [event]
    mlb = load("espn_mlb_2026-10-29.json")
    mlb["events"][0]["status"] = {"period": 7, "type": {"state": "in", "shortDetail": "Bot 7th"}}
    mlb["events"][0]["competitions"][0]["situation"] = {"onFirst": True, "onSecond": False, "onThird": True, "outs": 1}
    return sports.records(nfl, "nfl") + sports.records(mlb, "mlb")


def build_hub() -> Hub:
    hub = Hub(clock=lambda: NOW)
    for module in (weather, sports, racing):
        hub.register(module.MANIFEST)
    hub.register(BUILTINS["clock"].manifest, builtin=BUILTINS["clock"])
    apps = {
        "weather": [App("w", "weather", {"latitude": 40.7128, "longitude": -74.006, "label": "NEW YORK"})],
        "nfl": [App("s", "sports", {"leagues": ["nfl"]})],
        "nba": [App("s", "sports", {"leagues": ["nba"]})],
        "live": [App("s", "sports", {"leagues": ["nfl", "mlb"]})],
        "racing": [App("r", "racing", {})],
        "clock": [App("c", "clock", {})],
    }
    for ticker, playlist in apps.items():
        hub.set_ticker_values(ticker, {"tz": "America/New_York"})
        hub.set_playlist(ticker, playlist)

    def sync(feature, config, records):
        hub.apply(feature, {"t": "sync", "sub": subscription_key(config), "records": [validate_record(record) for record in records]})

    nyc = weather.records(load("openmeteo_nyc_2026-10-29.json"), {"units": "f"})
    sync("weather", {"latitude": 40.7128, "longitude": -74.006, "units": "f"}, nyc)
    sync("sports", {"league": "nfl"}, sports.records(load("espn_nfl_2026-10-29.json"), "nfl"))
    sync("sports", {"league": "nba"}, sports.records(load("espn_nba_2026-10-29.json"), "nba"))
    live = live_examples()
    sync("sports", {"league": "nfl"}, [record for record in live if record["id"].startswith("nfl")]
         + sports.records(load("espn_nfl_2026-10-29.json"), "nfl")[2:4])
    sync("sports", {"league": "mlb"}, [record for record in live if record["id"].startswith("mlb")])
    session = racing.records(load("jolpica_f1_2026.json"), datetime.fromtimestamp(NOW, timezone.utc))
    sync("racing", {"series": "f1"}, session)
    # The track weather is the New York record moved to the track, so the preview needs no network.
    track = session[0]["values"]["weather"]["$ref"]["config"]
    sync("weather", {**track, "units": "f"}, copy.deepcopy(nyc))
    return hub


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT / "previews" / "ticker3")
    args = parser.parse_args()
    hub = build_hub()
    logos = LogoCache(args.output / "logos")
    templates = hub.templates()
    args.output.mkdir(parents=True, exist_ok=True)
    for ticker in hub.playlists:
        composition = hub.composition(ticker)
        for panel in ("w384h32", "w64h32"):
            blocks = [(templates[screen["template"]]["panels"][panel], screen["values"]) for screen in composition.screens
                      if panel in templates[screen["template"]]["panels"]]
            frames = [blocks] if not blocks or blocks[0][0]["flow"] == "scroll" else [[block] for block in blocks[:3]]
            for index, chosen in enumerate(frames):
                frame = draw_frame(panel, chosen, now=NOW, logos=logos)
                name = f"{ticker}-{panel}" + (f"-{index}" if len(frames) > 1 else "")
                frame.save(args.output / f"{name}.png")
                frame.resize((frame.width * args.scale, frame.height * args.scale), Image.NEAREST).save(args.output / f"{name}-x{args.scale}.png")
                print(args.output / f"{name}.png", frame.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
