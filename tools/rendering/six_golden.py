"""Record and check the pixels of every Six renderer for a fixed input corpus.

A case is one fresh set of renderers and a sequence of calls. Each call gives one image.
The corpus stores only inputs. The digests file stores one SHA-256 for each image.
Stand-in logos come from the URL text, so no case reads a file or the network.

  python tools/rendering/six_golden.py build --recorded calls.pkl   # write the corpus and the digests
  python tools/rendering/six_golden.py check                         # render the corpus and compare
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import pickle
import sys
from collections.abc import Iterator, Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "tests/fixtures/six_golden/corpus.json.gz"
DIGESTS = ROOT / "tests/fixtures/six_golden/digests.json"
BASE_TIME = datetime(2026, 10, 18, 20, 15, 0)
MODES = ("sports", "stock", "weather", "music", "flights", "airports", "clock")


# Inputs

def encode(value: Any) -> Any:
    """Encode one input as JSON. Tuples, times, images, and dataclasses keep their type."""
    if isinstance(value, Mapping):
        return {"$map": [[str(key), encode(item)] for key, item in value.items()]}
    if isinstance(value, tuple):
        return {"$tuple": [encode(item) for item in value]}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, datetime):
        return {"$time": value.isoformat()}
    if isinstance(value, Image.Image):
        stream = io.BytesIO()
        value.save(stream, format="PNG")
        return {"$image": base64.b64encode(stream.getvalue()).decode("ascii")}
    if is_dataclass(value) and not isinstance(value, type):
        return {"$data": type(value).__name__, "fields": {field.name: encode(getattr(value, field.name)) for field in fields(value)}}
    if isinstance(value, float) and value != value:
        return {"$nan": True}
    return value


def decode(value: Any) -> Any:
    if isinstance(value, list):
        return [decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$map" in value:
        return {key: decode(item) for key, item in value["$map"]}
    if "$tuple" in value:
        return tuple(decode(item) for item in value["$tuple"])
    if "$time" in value:
        return datetime.fromisoformat(value["$time"])
    if "$image" in value:
        image = Image.open(io.BytesIO(base64.b64decode(value["$image"])))
        image.load()
        return image
    if "$nan" in value:
        return float("nan")
    if "$data" in value:
        from ticker_core.platform.wifi import HotspotDetails, WiFiSetupState
        kinds = {"WiFiSetupState": WiFiSetupState, "HotspotDetails": HotspotDetails}
        return kinds[value["$data"]](**{key: decode(item) for key, item in value["fields"].items()})
    raise ValueError(f"unknown encoded value: {sorted(value)}")


# Stand-in logos

class StandInAssets:
    """Return one fixed image for each URL and size. A URL with "missing" has no image."""

    revision = 0

    def __init__(self, present: bool) -> None:
        self.present = present

    def image(self, url: str, processor: str, size: tuple[int, int]) -> Image.Image | None:
        if not self.present or not url or "missing" in url:
            return None
        seed = hashlib.sha256(f"{url}|{processor}".encode()).digest()
        width, height = max(1, int(size[0])), max(1, int(size[1]))
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        inset = max(0, min(width, height) // 6)
        draw.ellipse((inset, inset, width - 1 - inset, height - 1 - inset), fill=(seed[0], seed[1], seed[2], 255),
                     outline=(seed[3] // 4, seed[4] // 4, seed[5] // 4, 255))
        draw.line((inset, height // 2, width - 1 - inset, height // 2), fill=(255 - seed[0], 255 - seed[1], 255 - seed[2], 255))
        return image


def renderers(present: bool) -> dict[str, Any]:
    """Build one fresh set of Six renderers on stand-in logos."""
    from ticker_core.assets import LogoAssetView
    from ticker_core.bootstrap import CachedLogoView
    from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
    from ticker_core.features.clock import ClockRenderer
    from ticker_core.features.flight import FlightRenderer
    from ticker_core.features.golf import GolfRenderer
    from ticker_core.features.music import MusicRenderer
    from ticker_core.features.racing import RacingRenderer
    from ticker_core.features.sports import SportsRenderer
    from ticker_core.features.status import ConnectionLostOverlay
    from ticker_core.features.utility import UtilityRenderer
    from ticker_core.features.weather import WeatherRenderer
    from ticker_core.ui import load_default_font_set

    assets = StandInAssets(present)
    fonts = load_default_font_set()
    logos = CachedLogoView(assets)
    return {
        "sports": SportsRenderer(fonts, LogoAssetView(assets)), "racing": RacingRenderer(fonts, assets),
        "golf": GolfRenderer(fonts), "weather": WeatherRenderer(fonts), "music": MusicRenderer(fonts, logos),
        "flight": FlightRenderer(fonts, logos), "utility": UtilityRenderer(fonts, logos),
        "clock": ClockRenderer(fonts.tiny, fonts.clock), "alert": ScoreAlertRenderer(fonts, logos),
        "news": NewsBannerRenderer(fonts), "connection": ConnectionLostOverlay(),
    }


def call(renderer_set: dict[str, Any], kind: str, method: str, args: dict[str, Any]) -> Image.Image:
    """Run one recorded renderer call and return its image."""
    from ticker_core.context import RenderContext
    from ticker_core.features.clock import ClockScene
    from ticker_core.ui import ContentScene

    renderer = renderer_set[kind]
    if kind == "weather" and method == "detailed":
        return renderer.detailed(RenderContext(args["now"]), args["item"])
    if method == "render" and kind == "clock":
        return renderer.render(RenderContext(args["now"]), ClockScene())
    if method == "render" and "item" in args and kind not in {"news"}:
        rendered = renderer.render(RenderContext(args["now"]), ContentScene(args["item"], args["mode"], args["elapsed"]))
        return rendered.image
    if kind == "alert":
        return renderer.render(args["alert"], args["elapsed"], args["under"])
    if kind == "news":
        return renderer.render(args["item"]) if method == "render" else renderer.apply(args["frame"], args["item"], args["elapsed"])
    if kind == "connection":
        return renderer.apply(args["frame"])
    context = RenderContext(args["now"]) if "now" in args else None
    if method == "update_overlay":
        extra = {key: value for key, value in args.items() if key not in {"frame", "progress", "version"}}
        return renderer.update_overlay(args["frame"], args["progress"], args["version"], **extra)
    if method == "pairing":
        return renderer.pairing(context, args["code"])
    if method == "wifi_setup":
        return renderer.wifi_setup(context, args["state"])
    if method == "offline":
        return renderer.offline(context, args["offline_for"])
    if method == "empty":
        return renderer.empty(context)
    raise ValueError(f"unknown call {kind}.{method}")


def digest(image: Image.Image) -> str:
    return hashlib.sha256(f"{image.mode}:{image.width}x{image.height}:".encode() + image.tobytes()).hexdigest()


def run_case(case: Mapping[str, Any]) -> list[str]:
    """Render one case. A failed call gives its error type, so a changed failure is visible too."""
    renderer_set = renderers(case["logos"])
    results = []
    for kind, method, args in case["calls"]:
        try:
            results.append(digest(call(renderer_set, kind, method, decode(args))))
        except Exception as error:
            results.append(f"error:{type(error).__name__}")
    return results


# Corpus sources

def recorded_cases(path: Path) -> Iterator[dict[str, Any]]:
    """Turn calls that the test suite made into cases, once with logos and once without."""
    for body in pickle.load(path.open("rb")):
        entry = pickle.loads(body)
        if entry[0] == "error":
            continue
        kind, method, args = entry
        for logos in (True, False):
            yield {"source": "tests", "logos": logos, "calls": [[kind, method, encode(_images(args))]]}


def _images(value: Any) -> Any:
    """Rebuild images that the recorder stored as PNG bytes."""
    if isinstance(value, tuple) and len(value) == 3 and value[0] == "__image__":
        image = Image.open(io.BytesIO(value[2]))
        image.load()
        return image
    if isinstance(value, dict):
        return {key: _images(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_images(item) for item in value)
    if isinstance(value, list):
        return [_images(item) for item in value]
    return value


def _kind(item: Mapping[str, Any]) -> str:
    from ticker_core.ui.catalog import content_family
    family = content_family(item)
    return {"scoreboard": "sports", "stock": "utility", "leaderboard": "utility", "empty": "utility"}.get(family, family)


def fixture_items() -> Iterator[tuple[str, dict[str, Any], str]]:
    """Return each content item of each display payload in the fixtures, as the Six runtime prepares it."""
    from ticker_core.app.frame_builder import _content_mapping
    from ticker_core.protocol import TickerResponse
    from ticker_core.runtime.state import _content

    paths = sorted(ROOT.glob("tests/fixtures/**/*.json")) + sorted(ROOT.glob("docs/contracts/fixtures/**/*.json"))
    seen = set()
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for payload in _payloads(data):
            try:
                response = TickerResponse.from_payload(payload)
            except Exception:
                continue
            mode = response.settings.mode
            for content in response.content:
                item = _content_mapping(_content(content))
                key = json.dumps(item, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    yield path.relative_to(ROOT).as_posix(), item, mode


def _payloads(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("content"), dict) and isinstance(value.get("snapshot"), dict):
            yield value
        for item in value.values():
            yield from _payloads(item)
    elif isinstance(value, list):
        for item in value:
            yield from _payloads(item)


def fixture_cases() -> Iterator[dict[str, Any]]:
    """Render each fixture item in its mode and as a pinned item, at three times, with and without logos."""
    for source, item, mode in fixture_items():
        kind = _kind(item)
        variants = [item]
        if kind in {"sports", "golf", "racing"}:
            variants.append({**item, "sports_presentation": "pinned"})
        for variant in variants:
            for logos in (True, False):
                calls = [[kind, "render", encode({"now": BASE_TIME + timedelta(seconds=step), "item": variant,
                                                  "mode": mode, "elapsed": elapsed})]
                         for step, elapsed in ((0, 0.0), (7, 2.5), (31, 9.0), (75, 21.0))]
                yield {"source": source, "logos": logos, "calls": calls}


def gallery_cases() -> Iterator[dict[str, Any]]:
    """Render each public layout example: as a pane, pinned, and as an animation of eight frames."""
    from ticker3.web.preview import project_preview_game

    library = json.loads((ROOT / "docs/contracts/demo-layouts.json").read_text(encoding="utf-8"))
    for row in library["cases"]:
        mode, game = row["mode"], project_preview_game(row["game"])
        source = f"gallery:{row['name']}"
        if mode in {"message", "pairing"}:
            yield from _system_cases(source, game)
            continue
        item = {"id": row["name"], "type": game.get("type") or ("weather" if mode == "weather" else "scoreboard"),
                "sport": game.get("sport") or mode, **game}
        kind = _kind(item)
        variants = [item, {**item, "sports_presentation": "pinned"}] if kind in {"sports", "golf", "racing"} else [item]
        for variant in variants:
            for logos in (True, False):
                calls = [[kind, "render", encode({"now": BASE_TIME + timedelta(seconds=frame / 4), "item": variant,
                                                  "mode": mode, "elapsed": frame / 4})] for frame in range(8)]
                if kind == "weather":
                    calls += [[kind, "detailed", encode({"now": BASE_TIME + timedelta(seconds=frame / 10), "item": variant})]
                              for frame in range(6)]
                yield {"source": source, "logos": logos, "calls": calls}


def _system_cases(source: str, game: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Render the utility screens of one public system example."""
    from ticker_core.platform.wifi import HotspotDetails, WiFiSetupState

    times = [BASE_TIME + timedelta(seconds=step) for step in (0, 0.5, 1.0, 13.0)]
    calls = []
    if "app_code" in game or "wifi_setup" in game:
        if game.get("wifi_setup"):
            state = WiFiSetupState(False, False, HotspotDetails("SportsTicker Setup", ""), setup_code=game.get("wifi_pin", "123456"))
            calls = [["utility", "wifi_setup", encode({"now": now, "state": state})] for now in times]
        else:
            calls = [["utility", "pairing", encode({"now": now, "code": game.get("app_code")})] for now in times]
    kind = game.get("utility_kind")
    base = Image.new("RGB", (384, 32), (20, 60, 110))
    if kind == "offline":
        calls = [["utility", "offline", encode({"now": now, "offline_for": float(game.get("age_seconds", 60))})] for now in times]
        calls.append(["connection", "apply", encode({"frame": base})])
    elif kind == "empty":
        calls = [["utility", "empty", encode({"now": now})] for now in times]
    elif kind == "update_failed":
        calls = [["utility", "update_overlay", encode({"frame": base, "progress": 0.0, "version": "", "failure_status": game.get("update_result", "rolled_back")})]]
    elif kind in {"checking", "downloading", "installing"}:
        total = max(1, int(game.get("total", 1)))
        progress = min(1.0, float(game.get("complete", 0)) / total)
        calls = [["utility", "update_overlay", encode({"frame": base, "progress": value, "version": "DEMO"})] for value in (0.0, progress, 1.0)]
    if calls:
        yield {"source": source, "logos": True, "calls": calls}


def corpus(recorded: Path | None) -> list[dict[str, Any]]:
    cases = list(fixture_cases()) + list(gallery_cases())
    if recorded is not None:
        cases.extend(recorded_cases(recorded))
    from tools.rendering import six_golden_cases
    cases.extend(six_golden_cases.cases(encode, BASE_TIME))
    unique, seen = [], set()
    for case in cases:
        key = json.dumps([case["logos"], case["calls"]], sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(case)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("build", "check"))
    parser.add_argument("--recorded", type=Path, help="A pickle of renderer calls from the test suite recorder.")
    args = parser.parse_args()
    if args.action == "build":
        cases = corpus(args.recorded)
        if args.recorded is None and CORPUS.exists():
            # Keep recorded cases from an earlier build when no new recording is given.
            old = json.loads(gzip.decompress(CORPUS.read_bytes()))
            cases.extend(case for case in old if case["source"] == "tests")
            cases = list({json.dumps([c["logos"], c["calls"]], sort_keys=True): c for c in cases}.values())
        digests = [run_case(case) for case in cases]
        CORPUS.parent.mkdir(parents=True, exist_ok=True)
        CORPUS.write_bytes(gzip.compress(json.dumps(cases, separators=(",", ":")).encode(), mtime=0))
        DIGESTS.write_text(json.dumps(digests, indent=0) + "\n", encoding="utf-8")
        errors = sum(value.startswith("error:") for values in digests for value in values)
        print(f"{len(cases)} cases, {sum(map(len, digests))} images, {errors} errors")
        return 0
    cases = json.loads(gzip.decompress(CORPUS.read_bytes()))
    expected = json.loads(DIGESTS.read_text(encoding="utf-8"))
    changed = [index for index, case in enumerate(cases) if run_case(case) != expected[index]]
    print(f"{len(cases)} cases, {len(changed)} changed")
    for index in changed[:20]:
        print("changed:", index, cases[index]["source"], [call[0] + "." + call[1] for call in cases[index]["calls"]])
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
