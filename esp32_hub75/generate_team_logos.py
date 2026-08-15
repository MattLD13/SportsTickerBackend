"""Download and convert real team marks into small ESP32 flash bitmaps."""

from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image


ROOT = Path(__file__).parent
OUTPUT = ROOT / "src" / "team_logos.h"
SIZE = 14
LOGOS = {
    "BUF": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png",
    "DAL": "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png",
    "GB": "https://a.espncdn.com/i/teamlogos/nfl/500/gb.png",
    "KC": "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png",
    "NE": "https://a.espncdn.com/i/teamlogos/nfl/500/ne.png",
    "NYG": "https://a.espncdn.com/i/teamlogos/nfl/500/nyg.png",
    "PHI": "https://a.espncdn.com/i/teamlogos/nfl/500/phi.png",
    "SF": "https://a.espncdn.com/i/teamlogos/nfl/500/sf.png",
    "BOS": "https://a.espncdn.com/i/teamlogos/mlb/500/bos.png",
    "CHC": "https://a.espncdn.com/i/teamlogos/mlb/500/chc.png",
    "LAD": "https://a.espncdn.com/i/teamlogos/mlb/500/lad.png",
    "NYY": "https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png",
    "TOR": "https://a.espncdn.com/i/teamlogos/mlb/500/tor.png",
    "ATL": "https://a.espncdn.com/i/teamlogos/mlb/500/atl.png",
    "LAL": "https://a.espncdn.com/i/teamlogos/nba/500/lal.png",
    "BKN": "https://a.espncdn.com/i/teamlogos/nba/500/bkn.png",
    "BOS_NBA": "https://a.espncdn.com/i/teamlogos/nba/500/bos.png",
    "GSW": "https://a.espncdn.com/i/teamlogos/nba/500/gs.png",
    "CHI_NBA": "https://a.espncdn.com/i/teamlogos/nba/500/chi.png",
    "NYK": "https://a.espncdn.com/i/teamlogos/nba/500/ny.png",
    "NYR": "https://a.espncdn.com/i/teamlogos/nhl/500/nyr.png",
    "NJD": "https://a.espncdn.com/i/teamlogos/nhl/500/nj.png",
    "BOS_NHL": "https://a.espncdn.com/i/teamlogos/nhl/500/bos.png",
    "TOR_NHL": "https://a.espncdn.com/i/teamlogos/nhl/500/tor.png",
    "TBL": "https://a.espncdn.com/i/teamlogos/nhl/500/tb.png",
}


def rgb565(red: int, green: int, blue: int) -> int:
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


def fetch(url: str) -> Image.Image:
    request = Request(url, headers={"User-Agent": "SportsTicker ESP32 logo cache"})
    with urlopen(request, timeout=20) as response:
        return Image.open(response).convert("RGBA")


def bitmap(name: str, url: str) -> tuple[str, str]:
    source = fetch(url)
    source.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    image.alpha_composite(source, ((SIZE - source.width) // 2, (SIZE - source.height) // 2))
    pixels = []
    mask = []
    for red, green, blue, alpha in image.getdata():
        pixels.append(f"0x{rgb565(red, green, blue):04X}")
        mask.append("1" if alpha >= 24 else "0")
    symbol = name.replace("_", "_")
    return (
        f"static const uint16_t LOGO_{symbol}[{SIZE * SIZE}] PROGMEM = {{" + ", ".join(pixels) + "};",
        f"static const uint8_t MASK_{symbol}[{SIZE * SIZE}] PROGMEM = {{" + ", ".join(mask) + "};",
    )


def main() -> None:
    declarations: list[str] = [
        "#pragma once",
        "#include <Arduino.h>",
        "#include <pgmspace.h>",
        "",
        "static constexpr uint8_t CACHED_LOGO_SIZE = 14;",
        "",
    ]
    entries: list[str] = []
    for name, url in LOGOS.items():
        try:
            pixel_data, mask_data = bitmap(name, url)
        except Exception as error:
            print(f"skip {name}: {error}")
            continue
        declarations.extend((pixel_data, mask_data, ""))
        entries.append(f'  {{"{name}", LOGO_{name}, MASK_{name}}},')
    declarations.extend(
        [
            "struct CachedTeamLogo {",
            "  const char* abbreviation;",
            "  const uint16_t* pixels;",
            "  const uint8_t* mask;",
            "};",
            "",
            "static const CachedTeamLogo CACHED_TEAM_LOGOS[] = {",
            *entries,
            "};",
            "",
            "static constexpr size_t CACHED_TEAM_LOGO_COUNT = sizeof(CACHED_TEAM_LOGOS) / sizeof(CACHED_TEAM_LOGOS[0]);",
            "",
        ]
    )
    OUTPUT.write_text("\n".join(declarations), encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(entries)} real logos")


if __name__ == "__main__":
    main()
