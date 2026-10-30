"""Build public Mini examples with the current firmware renderer."""
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
import shutil
import subprocess
import sys

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ticker.server.mini_assets.mini_artwork import encode_artwork
from ticker.server.mini_assets.mini_sprite import encode_sprite
from ticker.shared.music_palette import artwork_colors
from ticker.server.web.preview import main_layout, project_preview_game
from ticker.server.projections.racing_display import mini_racing_cards
from ticker.server.providers.logo_overrides import mini_logo_sources
from tools.rendering.render_mini_ui import remote_render
from tools.mini.generate_mini_weather import FRAMES as WEATHER_FRAMES, STEP_MS as WEATHER_FRAME_MS

SOURCE = ROOT / "docs/contracts/demo-layouts.json"
DESTINATION = ROOT / "ticker/server/web/static/layout-gallery.json"
ALBUM = ROOT / "ticker/server/web/static/mr-blue-sky-cover.png"


def encode_image(image: Image.Image) -> str:
    """Encode exact RGB pixels without changing their dimensions."""
    stream = BytesIO()
    image.convert("RGB").save(stream, format="PNG", optimize=True)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def provenance() -> dict:
    """Identify every source that determines public Mini frames."""
    paths = sorted((ROOT / "mini/src/mini/ui").glob("*.h"))
    paths += [ROOT / name for name in (
        "mini/src/mini/protocol/panes.h", "mini/platformio.ini",
        "mini/src/mini/protocol/rotation.h",
        "ticker/server/projections/racing_display.py", "ticker/shared/racing_number_colors.json",
        "ticker/shared/sports_display.py",
        "ticker/shared/images.py", "ticker/server/mini_assets/mini_sprite.py",
        "ticker/server/mini_assets/mini_artwork.py", "ticker/shared/music_palette.py",
        "ticker/server/providers/logo_overrides.py", "tools/rendering/render_mini_ui.cpp", "tools/rendering/build_demo_layouts.py",
    )]
    paths += [SOURCE, ALBUM, *sorted((SOURCE.parent / "demo-assets").glob("*.source"))]
    hashes = {}
    for path in paths:
        body = path.read_bytes()
        if path.suffix in {".h", ".py", ".cpp", ".ini", ".json"}:
            body = body.replace(b"\r\n", b"\n")
        hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(body).hexdigest()
    config = (ROOT / "mini/src/mini/platform/config.h").read_text()
    version = re.search(r'MINI_FIRMWARE_VERSION\[\].*?= "([^"]+)"', config)
    if version is None:
        raise ValueError("Mini firmware version is missing")
    return {"mini_firmware": version[1], "mini_source_hashes": hashes}


def prepare_rows(source: dict, directory: Path, asset_root: str) -> list[dict]:
    """Prepare approved public images before the renderer reads memory pixels."""
    directory.mkdir(parents=True, exist_ok=True)
    cache, rows = {}, []
    identity, cover = encode_artwork(ALBUM.read_bytes())
    (directory / f"{identity}.mta").write_bytes(cover)
    with Image.open(ALBUM) as image:
        accent, _ = artwork_colors(ImageOps.fit(image.convert("RGB"), (42, 42)))
    for example in source["cases"]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", example["name"]):
            raise ValueError("Invalid public example name")
        row = {"name": example["name"], "mode": example["mode"], "game": deepcopy(example["game"])}
        projected = project_preview_game(row["game"])
        if projected.get("racing_display"):
            row["game"] = mini_racing_cards({"id": row["name"], "is_shown": True, "data": projected})[0]["data"]
        background = row["game"].get("background", {})
        asset_mode = background.get("mode", row["mode"])
        asset_game = background.get("game", row["game"])
        for side in ("away", "home"):
            urls = mini_logo_sources(asset_game, side) if asset_mode == "sports" else ()
            if asset_mode == "stock" and side == "home":
                urls = (asset_game["home_logo"],) if asset_game.get("home_logo") else ()
            if not urls:
                continue
            url = urls[0]
            if url not in cache:
                raw = SOURCE.parent / "demo-assets" / (hashlib.sha256(url.encode()).hexdigest() + ".source")
                sprite_id, body = encode_sprite(raw.read_bytes())
                (directory / f"{sprite_id}.mts").write_bytes(body)
                cache[url] = f"{asset_root}/{sprite_id}.mts"
            row[side + "_sprite"] = cache[url]
        row["now_epoch"] = datetime.fromisoformat(example.get("example_time", source["example_time"])).timestamp()
        if row["mode"] == "weather":
            row.update(frame_count=WEATHER_FRAMES, frame_ms=WEATHER_FRAME_MS)
        if row["mode"] == "music":
            row.update(frame_count=200, frame_ms=100)
            if row["game"].get("cover") == "demo:album":
                row["cover_artwork"] = f"{asset_root}/{identity}.mta"
                row["game"]["cover_asset"] = {"accent_rgb": accent}
        if row["mode"] == "airports":
            pages = max(1, min(4, max(len(row["game"].get("arrivals", [])), len(row["game"].get("departures", [])))))
            row.update(frame_count=pages * 40, frame_ms=100)
        if row["mode"] in {"message", "pairing"} or (row["mode"] == "clock" and not row["game"].get("ready", True)):
            row.update(frame_count=80, frame_ms=100)
        rows.append(row)
    return rows


def local_render(directory: Path, include: Path | None) -> None:
    """Compile the same C++ presenters and drawing functions used by firmware."""
    if include is None:
        include = ROOT / "mini/.pio/libdeps/esp32s3/ArduinoJson/src"
    if not (include / "ArduinoJson.h").is_file():
        version = re.search(r"bblanchon/ArduinoJson\s*@\s*([\d.]+)", (ROOT / "mini/platformio.ini").read_text())
        if version is None:
            raise ValueError("ArduinoJson dependency must specify one exact version")
        dependency = directory / "ArduinoJson"
        if not dependency.exists():
            subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", f"v{version[1]}",
                            "https://github.com/bblanchon/ArduinoJson.git", str(dependency)], check=True)
        include = dependency / "src"
    compiler = shutil.which("g++") or shutil.which("cl")
    if not compiler:
        raise RuntimeError("A native C++ compiler is required. Use --host to render on the physical Pi.")
    executable = directory / ("render-mini.exe" if sys.platform == "win32" else "render-mini")
    if Path(compiler).stem.lower() == "cl":
        arguments = ["/nologo", "/std:c++17", "/EHsc", "/O1", f"/I{ROOT / 'mini/src/mini/protocol'}",
                     f"/I{ROOT / 'mini/src/mini/assets'}", f"/I{include}",
                     str(ROOT / "tools/rendering/render_mini_ui.cpp"), f"/Fe:{executable}", f"/Fo:{directory / 'render-mini.obj'}"]
    else:
        arguments = ["-std=c++17", "-O1", f"-I{ROOT / 'mini/src/mini/protocol'}",
                     f"-I{ROOT / 'mini/src/mini/assets'}", f"-I{include}",
                     str(ROOT / "tools/rendering/render_mini_ui.cpp"), "-o", str(executable)]
    subprocess.run([compiler, *arguments], check=True)
    subprocess.run([str(executable.resolve()), str((directory / "input.json").resolve()), str((directory / "frames").resolve())], check=True)


def build(source_path: Path, output: Path, directory: Path, *, host: str = "", key: Path | None = None,
          include: Path | None = None) -> dict:
    """Build every catalog frame without ticker, account, or fleet access."""
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("schema_version") != 1:
        raise ValueError("Public demo inputs must use schema version 1")
    directory = directory.resolve()
    native_root = "/tmp/ticker-public-demo-build"
    assets = native_root + "/assets" if host else (directory / "assets").as_posix()
    rows = prepare_rows(source, directory / "assets", assets)
    (directory / "input.json").write_text(json.dumps(rows), encoding="utf-8")
    if host:
        if key is None:
            raise ValueError("Remote rendering requires an SSH key path")
        remote_render(host, key, directory, native_root)
    else:
        local_render(directory, include)
    result = []
    for original, prepared in zip(source["cases"], rows, strict=True):
        row = deepcopy(original)
        count = prepared.get("frame_count", 1)
        with Image.open(directory / "frames" / (row["name"] + ".ppm")) as atlas:
            if atlas.size != (64, 32 * count):
                raise ValueError(f"Invalid Mini frame atlas: {row['name']}")
            first = atlas.crop((0, 0, 64, 32))
            row.update(mini=encode_image(first), mini_source="firmware", main=main_layout(row))
            if count > 1:
                row["mini_animation"] = {"image": encode_image(atlas), "frames": count, "frame_ms": prepared["frame_ms"]}
            first.save(directory / f"{row['name']}.png")
        result.append(row)
    payload = {"schema_version": 3, "example_time": source["example_time"], **provenance(), "cases": result}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Built {len(result)} public layouts from {payload['mini_firmware']}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "previews/public-demo-build")
    parser.add_argument("--arduino-json", type=Path)
    parser.add_argument("--host", default="")
    parser.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/ticker2_codex")
    args = parser.parse_args()
    build(args.source, args.output, args.work_dir, host=args.host, key=args.ssh_key, include=args.arduino_json)


if __name__ == "__main__":
    main()
