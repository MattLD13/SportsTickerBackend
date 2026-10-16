"""Build public layout examples with the production ticker renderers.

Mini images come from the native firmware renderer or verified hardware captures.
This tool never connects to a ticker or changes its settings.
"""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ticker_core.bootstrap import create_default_content_catalog
from ticker_core.assets import AssetPlanner
from ticker_core.context import RenderContext
from ticker_core.features.utility import UtilityRenderer
from ticker_core.platform import AssetCoordinator
from ticker_core.platform.wifi import HotspotDetails, WiFiSetupState
from ticker_core.rendering import ContentScene, load_default_font_set
from tools.render_rewrite import panel_image

DESTINATION = ROOT / "sports_ticker/dashboard_v2/static/layout-gallery.json"
EXAMPLE_TIME = "2026-10-16T12:34:27-04:00"


def encode_image(image: Image.Image) -> str:
    """Encode exact pixels for the public static gallery."""
    stream = BytesIO()
    image.convert("RGB").save(stream, format="PNG", optimize=True)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def main_images(row: dict, assets: AssetCoordinator) -> dict:
    """Draw a sample through the same catalog that the Pi uses."""
    game = deepcopy(row["game"])
    mode = row["mode"]
    context = RenderContext(datetime.fromisoformat(row.get("example_time", EXAMPLE_TIME)))
    utility = UtilityRenderer(load_default_font_set())
    if mode == "pairing":
        if game["wifi_setup"]:
            state = WiFiSetupState(False, False, HotspotDetails("SportsTicker Setup", ""), setup_code=game["wifi_pin"])
            image = utility.wifi_setup(context, state)
        else:
            image = utility.pairing(context, game["app_code"])
    elif mode == "message":
        if game["message"] == "NO SPORTS":
            image = utility.empty(context)
        elif game["message"] == "WIFI LOST":
            image = utility.offline(context, 60)
        else:
            return {"note": "The big ticker keeps its last valid frame after an invalid data response."}
    elif mode == "clock" and not game.get("ready", True):
        return {"note": "The big ticker uses its system clock. This Mini time-sync screen has no matching big ticker screen."}
    else:
        catalog = create_default_content_catalog(assets)
        pane = catalog.render(context, ContentScene(game, mode)).image
        game["sports_presentation"] = "pinned"
        image = catalog.render(context, ContentScene(game, mode)).image if mode == "sports" else pane
        frames = {"pinned": encode_image(panel_image(image))}
        if mode in {"sports", "stock"}:
            frames.update(pane=encode_image(pane), pane_width=pane.width)
        return frames
    return {"pinned": encode_image(panel_image(image))}


def build(manifest: list[dict], mini_frames: Path | None, output: Path, asset_directory: Path, provenance: dict | None = None) -> None:
    """Package synthetic examples without reading fleet or controller state."""
    assets = AssetCoordinator(asset_directory)
    result = []
    try:
        requests = AssetPlanner().plan({"items": [row["game"] for row in manifest]}).requests
        for future in assets.prefetch(requests):
            future.result(timeout=30)
        for original in manifest:
            row = {key: deepcopy(original[key]) for key in ("name", "group", "title", "mode", "game")}
            for key in ("example_time", "note", "mini_source"):
                if key in original:
                    row[key] = original[key]
            if mini_frames is not None:
                with Image.open(mini_frames / (row["name"] + ".png")) as image:
                    if image.size != (64, 32):
                        raise ValueError(f"Invalid Mini frame size: {row['name']}")
                    row["mini"] = encode_image(image)
            else:
                row["mini"] = original["mini"]
            row["main"] = main_images(row, assets)
            result.append(row)
            print(row["name"], row["title"], flush=True)
    finally:
        assets.close()
    renderer_paths = sorted((ROOT / "esp32_hub75/src/mini/rendering").glob("*.h"))
    renderer_paths += [ROOT / "esp32_hub75/src/mini/protocol/panels.h", ROOT / "esp32_hub75/src/mini/features/renderers.inc"]
    if mini_frames is not None:
        version = re.search(r'MINI_FIRMWARE_VERSION\[\].*?= "([^"]+)"', (ROOT / "esp32_hub75/src/mini/platform/config.h").read_text())
        if version is None:
            raise ValueError("The Mini firmware version is missing.")
        provenance = {
            "mini_firmware": version[1],
            "mini_source_hashes": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in renderer_paths},
        }
    if not provenance:
        raise ValueError("Mini frames must include capture provenance.")
    payload = {
        "schema_version": 1,
        "example_time": EXAMPLE_TIME,
        **provenance,
        "cases": result,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Saved {len(result)} public examples to {output}")


def main() -> None:
    """Read a reviewed manifest or refresh the published main frames."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DESTINATION)
    parser.add_argument("--mini-frames", type=Path)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    parser.add_argument("--assets", type=Path, default=ROOT / "previews/demo-layouts/main-assets")
    args = parser.parse_args()
    source = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = source["cases"] if isinstance(source, dict) else source
    provenance = {key: source[key] for key in ("mini_firmware", "mini_source_hashes")} if isinstance(source, dict) else None
    build(manifest, args.mini_frames, args.output, args.assets, provenance)


if __name__ == "__main__":
    main()
