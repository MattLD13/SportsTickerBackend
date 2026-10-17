"""Package public sample inputs and verified Mini captures.

Mini images come from the native firmware renderer or verified hardware captures.
This tool never connects to a ticker or changes its settings.
"""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sports_ticker.dashboard_v2.preview import main_layout

DESTINATION = ROOT / "sports_ticker/dashboard_v2/static/layout-gallery.json"
EXAMPLE_TIME = "2026-10-16T12:34:27-04:00"


def encode_image(image: Image.Image) -> str:
    """Encode exact pixels for the public static gallery."""
    stream = BytesIO()
    image.convert("RGB").save(stream, format="PNG", optimize=True)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def build(manifest: list[dict], mini_frames: Path | None, output: Path, provenance: dict | None = None) -> None:
    """Package synthetic examples without reading fleet or controller state."""
    result = []
    for original in manifest:
        row = {key: deepcopy(original[key]) for key in ("name", "group", "title", "mode", "game")}
        for key in ("example_time", "note", "mini_source", "mini_firmware", "mini_source_hashes"):
            if key in original:
                row[key] = original[key]
        if mini_frames is not None:
            with Image.open(mini_frames / (row["name"] + ".png")) as image:
                if image.size != (64, 32):
                    raise ValueError(f"Invalid Mini frame size: {row['name']}")
                row["mini"] = encode_image(image)
        else:
            row["mini"] = original["mini"]
        row["main"] = main_layout(row)
        result.append(row)
        print(row["name"], row["title"], flush=True)
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
        "schema_version": 2,
        "example_time": EXAMPLE_TIME,
        **provenance,
        "cases": result,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Saved {len(result)} public examples to {output}")


def main() -> None:
    """Read a reviewed manifest and package its public sample catalog."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DESTINATION)
    parser.add_argument("--mini-frames", type=Path)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    args = parser.parse_args()
    source = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = source["cases"] if isinstance(source, dict) else source
    provenance = {key: source[key] for key in ("mini_firmware", "mini_source_hashes")} if isinstance(source, dict) else None
    build(manifest, args.mini_frames, args.output, provenance)


if __name__ == "__main__":
    main()
