"""Render Mini weather with live provider data and production drawing code."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ticker.shared.domain import DisplaySettings
from ticker.server.providers.weather import HybridWeatherProvider
from ticker.server.projections.data_api import _content_item
from tools.rendering.render_mini_ui import remote_render
from tools.rendering.render_frame import normalize_snapshot, render_snapshot


def render(output: Path, weather: dict, host: str, key: Path) -> None:
    """Draw current weather, condition examples, and both statistic pages."""
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(120):
        rows.append({"name": f"live-{index:03}", "mode": "weather", "game": weather, "elapsed_ms": index * 100})
    examples = (
        ("sunny", "sun", 1, 72, 70), ("clear-night", "sun", 0, 55, 53),
        ("cloudy", "cloud", 1, 64, 62), ("rain", "rain", 1, 61, 57),
        ("snow", "snow", 1, -12, -24), ("fog", "fog", 0, 51, 49),
        ("storm", "storm", 1, 83, 87), ("hot", "sun", 1, 105, 112),
    )
    for name, icon, day, temperature, feels in examples:
        game = deepcopy(weather)
        game.update(city="BETHLEHEM", icon=icon, is_day=day, temperature=temperature, feels=feels, wind=8, humidity=53, aqi=31)
        for page in (0, 5000):
            rows.append({"name": f"{name}-{page}", "mode": "weather", "game": game, "elapsed_ms": page})
        if name in {"sunny", "rain"}:
            for index in range(40):
                rows.append({"name": f"{name}-motion-{index:03}", "mode": "weather", "game": game, "elapsed_ms": index * 100})
    missing = {"city": "WEATHER", "icon": "unknown", "temperature": None}
    rows.append({"name": "missing", "mode": "weather", "game": missing})
    long_city = {**weather, "city": "SAN FRANCISCO BAY AREA"}
    for index in range(120):
        rows.append({"name": f"long-city-{index:03}", "mode": "weather", "game": long_city, "elapsed_ms": index * 100})
    (output / "input.json").write_text(json.dumps(rows), encoding="utf-8")
    remote_render(host, key, output, "/tmp/mini-weather-preview")
    envelope = {"content": {"weather": [{"id": "weather_main", "family": "weather", "kind": "weather", "data": weather}]}}
    six = render_snapshot(normalize_snapshot(envelope, "weather"), "weather", prefetch=False, asset_directory=output / "six-assets")
    assert six.size == (384, 32)
    six.save(output / "live-six.png")
    names = [("live-000", "Live provider: feels / wind"), ("live-050", "Live provider: humidity / AQI")]
    names += [(f"{name}-0", f"Example: {name}") for name, *_ in examples]
    sheet = Image.new("RGB", (960, len(names) // 2 * 242 + 12), (22, 24, 30))
    draw = ImageDraw.Draw(sheet)
    for index, (name, label) in enumerate(names):
        frame = Image.open(output / "frames" / f"{name}.ppm").convert("RGB")
        frame.save(output / f"{name}.png")
        x, y = index % 2 * 480 + 12, index // 2 * 242 + 10
        draw.text((x, y), label, fill="white")
        sheet.paste(frame.resize((448, 224), Image.Resampling.NEAREST), (x, y + 15))
    sheet.save(output / "preview.png")
    for prefix, count in (("live", 120), ("long-city", 120), ("sunny-motion", 40), ("rain-motion", 40)):
        frames = [Image.open(output / "frames" / f"{prefix}-{index:03}.ppm").convert("RGB").resize((640, 320), Image.Resampling.NEAREST) for index in range(count)]
        frames[0].save(output / f"{prefix}.gif", save_all=True, append_images=frames[1:], duration=100, loop=0)
    print(output / "preview.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, default=Path("previews/mini-weather"))
    parser.add_argument("--host", default="mld@ticker2.local")
    parser.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/ticker2_codex")
    parser.add_argument("--city", default="Bethlehem")
    parser.add_argument("--latitude", type=float, default=40.6259)
    parser.add_argument("--longitude", type=float, default=-75.3705)
    args = parser.parse_args()
    if args.snapshot:
        weather = json.loads(args.snapshot.read_text(encoding="utf-8"))
    else:
        settings = DisplaySettings(mode="weather", weather_city=args.city, weather_lat=args.latitude, weather_lon=args.longitude)
        result = HybridWeatherProvider(timeout=5).fetch(settings)
        if not result.health.healthy or not result.content:
            raise RuntimeError(f"Live weather fetch failed: {result.health.error}")
        weather = _content_item(result.content[0])["data"]
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "live-weather.json").write_text(json.dumps(weather, indent=2), encoding="utf-8")
    render(args.output, weather, args.host, args.ssh_key)


if __name__ == "__main__":
    main()
