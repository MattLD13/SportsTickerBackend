"""Compare production frames with fixed inputs, fonts, and verified logo bytes."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import os
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [os.path.join(str(ROOT), name) for name in ("shared", "server", "six", "")]
from PIL import __version__ as pillow_version, features
from ticker.panel.assets import AssetPlanner
from ticker.panel.bootstrap import create_default_content_catalog
from ticker.panel.frame import RenderContext
from ticker.panel.assets.storage import AssetCoordinator
from ticker.panel import ContentScene
from tools.rendering.render_frame import content_items, normalize_snapshot, panel_image
from tools.benchmarks.pi_viewport_baseline import fonts_manifest

FIXTURE = ROOT / "tests/fixtures/render_baseline"


def run(output: Path, *, record: bool = False, repeats: int = 100) -> dict:
    snapshot = json.loads((FIXTURE / "snapshot.json").read_text(encoding="utf-8"))
    manifest = json.loads((FIXTURE / "assets.json").read_text(encoding="utf-8"))
    originals = {}
    for url, asset in manifest.items():
        raw = (FIXTURE / asset["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
            raise ValueError("A frozen logo differs from its recorded identity")
        originals[url] = raw
    runtime = {"pillow": pillow_version, "freetype": features.version_module("freetype2"), "fonts": fonts_manifest()}
    runtime = json.loads(json.dumps(runtime))
    profile = hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest()[:16]
    context = RenderContext(datetime.fromisoformat("2026-08-13T00:00:00+00:00"))
    output.mkdir(parents=True, exist_ok=True)
    cases = {}
    with tempfile.TemporaryDirectory(prefix="ticker-render-") as temporary:
        assets = AssetCoordinator(temporary, fetch=lambda url: originals[url])
        try:
            requests = AssetPlanner().plan(snapshot).requests
            if not requests:
                raise ValueError("The baseline has no real logo requests")
            for future in assets.prefetch(requests):
                if future.result() is None:
                    raise ValueError("A frozen asset failed preparation")
            catalog = create_default_content_catalog(assets)
            for item in content_items(normalize_snapshot(snapshot, "sports"), "sports"):
                for presentation in ("pane", "pinned"):
                    game = dict(item)
                    if presentation == "pinned":
                        game["sports_presentation"] = "pinned"
                    scene = ContentScene(game, "sports")
                    name = str(item["id"]) + "-" + presentation
                    frame = panel_image(catalog.render(context, scene).image)
                    digest = hashlib.sha256(frame.tobytes()).hexdigest()
                    timings = []
                    for _ in range(repeats):
                        started = time.perf_counter_ns()
                        measured = panel_image(catalog.render(context, scene).image)
                        timings.append((time.perf_counter_ns() - started) / 1_000_000)
                        if hashlib.sha256(measured.tobytes()).hexdigest() != digest:
                            raise ValueError("Fixed-input rendering changed between repetitions")
                    frame.save(output / (name + ".png"))
                    cases[name] = {"sha256": digest, "median_ms": statistics.median(timings),
                                   "p95_ms": sorted(timings)[max(0, int(len(timings) * .95) - 1)]}
        finally:
            assets.close()
    baseline = FIXTURE / "pixels.json"
    hashes = {name: case["sha256"] for name, case in cases.items()}
    expected = json.loads(baseline.read_text(encoding="utf-8")) if baseline.exists() else {"profiles": {}}
    if record:
        expected["profiles"][profile] = runtime
        expected["pixels"] = hashes
        baseline.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    if expected.get("pixels") != hashes:
        raise ValueError("Production render pixels differ from the reviewed baseline")
    result = {"profile": profile, "runtime": runtime, "cases": cases, "network_requests": 0,
              "frozen_logos": len(originals), "fixed_input_repetitions": repeats, "pixels_match": True}
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("previews/render-baseline"))
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--repeats", type=int, default=100)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("Repeats must be positive")
    result = run(args.output, record=args.record, repeats=args.repeats)
    print(json.dumps({key: result[key] for key in ("profile", "frozen_logos", "network_requests", "pixels_match", "cases")}))


if __name__ == "__main__":
    main()
