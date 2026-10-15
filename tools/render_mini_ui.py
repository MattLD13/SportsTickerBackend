"""Render the production Mini sports code beside the main ticker panes."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sports_ticker.assets.mini_service import MiniSpriteService
from sports_ticker.providers.logo_overrides import mini_logo_sources
from tools.render_rewrite import normalize_snapshot, render_snapshot


def cases(snapshot: dict) -> list[dict]:
    """Keep live input and add local sport layout examples."""
    result = [{"name": "production", "game": dict(snapshot["content"]["sports"][0]["data"])}]
    fixture = json.loads((ROOT / "tests/rewrite/debug/v2_render_snapshot.json").read_text())
    for item in fixture["content"]["sports"]:
        result.append({"name": item["id"], "game": item["data"]})
    nfl = next(row for row in result if row["name"] == "nfl-live")
    goal = deepcopy(nfl); goal["name"] = "football-goal"; goal["game"]["situation"]["downDist"] = "1ST & GOAL"; result.append(goal)
    hoops = deepcopy(nfl); hoops["name"] = "basketball-three-digits"
    hoops["game"].update(sport="nba", away_abbr="BOS", home_abbr="NYK", away_score="112", home_score="108", status="Q4 0:15", situation={},
                         away_logo="https://a.espncdn.com/i/teamlogos/nba/500/bos.png", home_logo="https://a.espncdn.com/i/teamlogos/nba/500/ny.png")
    result.append(hoops)
    hockey = deepcopy(nfl); hockey["name"] = "hockey-power-play"
    hockey["game"].update(sport="nhl", away_abbr="NYR", home_abbr="BOS", away_score="2", home_score="1", status="P3 03:21",
                          away_logo="https://a.espncdn.com/i/teamlogos/nhl/500/nyr.png", home_logo="https://a.espncdn.com/i/teamlogos/nhl/500/bos.png",
                          situation={"powerPlay":True, "powerPlayTeam":"BOS", "activeTeam":"BOS", "manpower":{"scrollLabel":"0:45 5v4"}})
    result.append(hockey)
    shootout = deepcopy(hockey); shootout["name"] = "hockey-shootout"
    shootout["game"].update(status="S/O", situation={"shootout":{"state":"active","roundLabel":"R4-6", "displayRounds":[{"away":"goal","home":"miss"},{"away":"miss","home":"goal"},{"away":"pending","home":"pending"}]}})
    result.append(shootout)
    soccer = deepcopy(nfl); soccer["name"] = "soccer-red-cards"
    soccer["game"].update(sport="soccer_epl", away_abbr="ARS", home_abbr="CHE", away_score="1", home_score="2", status="78'",
                          away_logo="https://a.espncdn.com/i/teamlogos/soccer/500/359.png", home_logo="https://a.espncdn.com/i/teamlogos/soccer/500/363.png", situation={"red_cards":[{"is_home":True},{"is_home":True}]})
    result.append(soccer)
    overtime = deepcopy(hockey); overtime["name"] = "hockey-multiple-ot"
    overtime["game"].update(status="2OT 01:23", situation={})
    result.append(overtime)
    period_end = deepcopy(hoops); period_end["name"] = "basketball-period-end"
    period_end["game"].update(status="Q1 END", away_score="22", home_score="20")
    result.append(period_end)
    for row in result:
        for side in ("away", "home"):
            sources = mini_logo_sources(row["game"], side)
            if sources: row["game"][side + "_logo"] = sources[0]
    stock = fixture["content"].get("stock")
    stock_game = stock[0]["data"] if stock else {"type":"stock_ticker", "sport":"stock", "home_abbr":"AAPL", "home_score":"212.48", "away_score":"+1.25%", "situation":{"change":"2.62"}}
    result.append({"name":"stock-example", "mode":"stock", "game":stock_game})
    result.append({"name":"clock", "mode":"clock", "game":{"date":"THU OCT 15", "time":"12:34:27", "seconds":27}})
    return result


def prepare(snapshot: Path, output: Path, native_root: str) -> list[dict]:
    """Prepare assets before either renderer draws a frame."""
    rows = cases(json.loads(snapshot.read_text()))
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "assets"
    service = MiniSpriteService(cache)
    try:
        for row in rows:
            if row.get("mode", "sports") != "sports": continue
            for side in ("away", "home"): service.reference(*mini_logo_sources(row["game"], side))
        service.wait()
        for row in rows:
            for side in ("away", "home"):
                if row.get("mode", "sports") != "sports":
                    row[side + "_sprite"] = ""
                    continue
                ref = service.reference(*mini_logo_sources(row["game"], side))
                row[side + "_sprite"] = f'{native_root}/assets/{ref["asset_id"]}.mts' if ref["state"] == "ready" else ""
            mode = row.get("mode", "sports")
            envelope = {"api_version":"v2", "content":{mode:[{"id":row["name"], "family":mode, "kind":"scoreboard", "data":row["game"]}]}}
            image = render_snapshot(normalize_snapshot(envelope,mode), mode, item_id=row["name"],
                                    now=datetime.fromisoformat("2026-10-15T12:34:27+00:00"), asset_directory=output / "main-assets")
            image.save(output / (row["name"] + "-main.png"))
    finally:
        service.close()
    (output / "input.json").write_text(json.dumps(rows))
    return rows


def remote_render(host: str, key: Path, output: Path, native_root: str) -> None:
    """Compile and run the preview without changing the Pi display service."""
    ssh = ["ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", host]
    scp = ["scp", "-i", str(key), "-o", "IdentitiesOnly=yes"]
    subprocess.run(ssh + [f"mkdir -p {native_root}/src/mini/rendering {native_root}/src/mini/protocol {native_root}/src/mini/assets {native_root}/arduino {native_root}/assets"], check=True)
    headers = list((ROOT / "esp32_hub75/src/mini/rendering").glob("*.h"))
    subprocess.run(scp + [str(p) for p in headers] + [f"{host}:{native_root}/src/mini/rendering/"], check=True)
    subprocess.run(scp + [str(ROOT / "esp32_hub75/src/mini/protocol/panels.h"), f"{host}:{native_root}/src/mini/protocol/"], check=True)
    subprocess.run(scp + [str(ROOT / "esp32_hub75/src/mini/assets/mini_sprite.h"), f"{host}:{native_root}/src/mini/assets/"], check=True)
    subprocess.run(scp + [str(ROOT / "tools/render_mini_ui.cpp"), f"{host}:{native_root}/src/"], check=True)
    library = ROOT / "esp32_hub75/.pio/libdeps/esp32s3/ArduinoJson/src"
    subprocess.run(scp + ["-r", str(library / "ArduinoJson"), str(library / "ArduinoJson.h"), str(library / "ArduinoJson.hpp"), f"{host}:{native_root}/arduino/"], check=True)
    sprites = list((output / "assets").glob("*.mts"))
    if sprites: subprocess.run(scp + [str(p) for p in sprites] + [f"{host}:{native_root}/assets/"], check=True)
    subprocess.run(scp + [str(output / "input.json"), f"{host}:{native_root}/input.json"], check=True)
    subprocess.run(ssh + [f"nice -n 19 taskset -c 0 g++ -std=c++17 -O1 -I{native_root}/src/mini/protocol -I{native_root}/src/mini/assets -I{native_root}/arduino {native_root}/src/render_mini_ui.cpp -o {native_root}/render-mini && nice -n 19 taskset -c 0 {native_root}/render-mini {native_root}/input.json {native_root}/frames"], check=True)
    subprocess.run(scp + ["-r", f"{host}:{native_root}/frames", str(output)], check=True)


def gallery(output: Path, rows: list[dict]) -> None:
    """Place native Mini frames beside full main-ticker frame references."""
    scale = 5
    sheet = Image.new("RGB", (384 * scale + 40, len(rows) * (64 * scale + 54)), (22, 24, 30))
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        y = index * (64 * scale + 54)
        draw.text((10, y + 5), row["name"] + " | MAIN 384x32", fill="white")
        main = Image.open(output / (row["name"] + "-main.png")).convert("RGB")
        mini = Image.open(output / "frames" / (row["name"] + ".ppm")).convert("RGB")
        mini.save(output / (row["name"] + "-mini.png"))
        sheet.paste(main.resize((384 * scale,32 * scale),Image.Resampling.NEAREST),(10,y+23))
        draw.text((10,y+32*scale+27),"MINI 64x32 | production C++ renderer",fill="white")
        sheet.paste(mini.resize((64 * scale,32 * scale),Image.Resampling.NEAREST),(10,y+32*scale+45))
    selected = [row for row in rows if row["name"] in {"nfl-live", "mlb-live", "basketball-three-digits", "hockey-power-play"}]
    compact = Image.new("RGB", (1040, len(selected) * 190 + 28), (22, 24, 30))
    labels = ImageDraw.Draw(compact)
    labels.text((12, 8), "MAIN SCROLLING PANE", fill="white")
    labels.text((710, 8), "MINI 64x32", fill="white")
    for index, row in enumerate(selected):
        y = 30 + index * 190
        labels.text((12, y), row["name"], fill="white")
        main = Image.open(output / (row["name"] + "-main.png")).convert("RGB").crop((0,0,128,32))
        mini = Image.open(output / (row["name"] + "-mini.png")).convert("RGB")
        compact.paste(main.resize((640,160),Image.Resampling.NEAREST),(12,y+18))
        compact.paste(mini.resize((320,160),Image.Resampling.NEAREST),(710,y+18))
    compact.save(output / "sports-comparison.png")
    sheet.save(output / "comparison.png")
    print(output / "comparison.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "previews/mini-ui")
    parser.add_argument("--ssh", required=True)
    parser.add_argument("--identity", type=Path, required=True)
    args = parser.parse_args()
    native_root = "/tmp/mini-ui-preview"
    rows = prepare(args.snapshot, args.output, native_root)
    remote_render(args.ssh, args.identity, args.output, native_root)
    gallery(args.output, rows)
