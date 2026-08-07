#!/usr/bin/env python3
"""Concept studies for the my-teams score alert takeover.

Five different visual treatments of the same scoring play, so the look can be
chosen from renders rather than from description. Concept 1 is what currently
ships; the rest are alternatives.

    python tools/render_score_alert_concepts.py            # stills + GIFs
    python tools/render_score_alert_concepts.py --no-gif   # stills only

Nothing here is imported by the controller. Once a concept is picked, it gets
rewritten into ticker_controller/modes/score_alert.py properly.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, save_image  # noqa: E402
from ticker_controller.config import PANEL_W, PANEL_H  # noqa: E402
from ticker_controller.fonts import draw_tiny_text  # noqa: E402
from ticker_controller.modes.score_alert import _mix, _scale  # noqa: E402

OUT_DIR = "previews/score_alert_concepts"
FPS = 30
TOTAL = 6.0          # seconds per concept, so the GIFs are comparable
STILL_AT = 2.0       # mid-hold, for the comparison sheet

SAMPLE = {
    "id": "concept",
    "sport": "mlb",
    "kind": "grand_slam",
    "headline": "GRAND SLAM",
    "detail": "JUDGE",
    "points": 4,
    "big": True,
    "status": "BOT 7",
    "team_abbr": "NYY",
    "team_color": "#132448",
    "team_alt_color": "#C4CED3",
    "opp_abbr": "BOS",
    "home_abbr": "NYY",
    "away_abbr": "BOS",
    "home_score": 9,
    "away_score": 3,
    "team_logo": "https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png",
}


# ── easing ───────────────────────────────────────────────────────────────────

def clamp01(v):
    return max(0.0, min(1.0, v))


def smooth(v):
    v = clamp01(v)
    return v * v * (3 - 2 * v)


def ease_out(v):
    v = clamp01(v)
    return 1 - (1 - v) ** 3


def text_layer(text, font, color, alpha=1.0):
    """Draw text on its own transparent layer, tight to the glyphs."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = probe.textbbox((0, 0), text, font=font)
    layer = Image.new("RGBA", (max(1, box[2] - box[0] + 4), max(1, box[3] - box[1] + 4)), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((2 - box[0], 2 - box[1]), text, font=font,
                               fill=color + (int(255 * clamp01(alpha)),))
    return layer


def outline_text(d, x, y, text, font, fill, anchor="mm"):
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                d.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0), anchor=anchor)
    d.text((x, y), text, font=font, fill=fill, anchor=anchor)


def score_column(d, alert, x0, color_scorer=(255, 255, 255), color_other=(115, 115, 122),
                 color_status=(165, 165, 175)):
    scorer = str(alert["team_abbr"]).upper()
    for i, (abbr, score) in enumerate((
        (alert["away_abbr"], alert["away_score"]),
        (alert["home_abbr"], alert["home_score"]),
    )):
        y = 3 + i * 9
        c = color_scorer if str(abbr).upper() == scorer else color_other
        draw_tiny_text(d, x0 + 2, y, str(abbr)[:3], c)
        text = str(score)
        draw_tiny_text(d, PANEL_W - 3 - len(text) * 5, y, text, c)
    draw_tiny_text(d, x0 + 2, 22, str(alert["status"])[:16], color_status)


def slide_off(img, t, out_start, out_len, direction=-1):
    """Shift a finished frame off-panel for the exit."""
    if t < out_start:
        return img
    k = ease_out((t - out_start) / out_len)
    shifted = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
    shifted.paste(img, (int(direction * PANEL_W * k), 0))
    return shifted


# ── concept 1 · chevron slam (shipping) ──────────────────────────────────────

def concept_chevron(r, alert, t):
    """Team-colour field with sweeping chevrons; shutters open from the centre."""
    from ticker_controller.modes.score_alert import score_alert_duration
    # Re-timed onto the shared 6s budget so the GIFs line up.
    return r.draw_score_alert(alert, t * score_alert_duration(alert) / TOTAL).convert("RGBA")


# ── concept 2 · broadcast bug ────────────────────────────────────────────────

def concept_broadcast(r, alert, t):
    """Clean lower-third: colour block, headline slides in, rule draws across.

    The most restrained of the five and by far the cheapest to light — almost
    the whole panel stays black, which is where the LED panels are happiest.
    """
    base, accent = r._score_alert_palette(alert)
    img = Image.new("RGBA", (PANEL_W, PANEL_H), (6, 6, 9, 255))
    d = ImageDraw.Draw(img, "RGBA")

    block_w = 44
    fill_h = int(PANEL_H * ease_out(t / 0.28))
    d.rectangle([0, PANEL_H - fill_h, block_w - 2, PANEL_H], fill=_scale(base, 0.95))
    d.line([(block_w - 1, PANEL_H - fill_h), (block_w - 1, PANEL_H)], fill=accent)
    if fill_h >= PANEL_H:
        logo = r.get_logo(alert.get("team_logo"), (24, 24))
        if logo is not None:
            img.paste(logo, ((block_w - 24) // 2, 4), logo)

    left = block_w + 9
    p = smooth((t - 0.22) / 0.38)
    if p > 0:
        layer = text_layer(alert["headline"], r.huge_font, (255, 255, 255), p)
        img.alpha_composite(layer, (left + int(22 * (1 - p)), -1))

    # A rule that draws itself is the cheapest possible motion cue.
    rule = smooth((t - 0.34) / 0.55)
    if rule > 0:
        end = left + int((PANEL_W - left - 96) * rule)
        d.line([(left, 22), (end, 22)], fill=accent)

    detail = smooth((t - 0.6) / 0.3)
    if detail > 0:
        draw_tiny_text(d, left + 1, 25, alert["detail"], _mix(accent, (255, 255, 255), 0.4))

    if t > 0.7:
        score_column(d, alert, PANEL_W - 86)

    return slide_off(img, t, TOTAL - 0.45, 0.45)


# ── concept 3 · jumbotron bulbs ──────────────────────────────────────────────

def concept_jumbotron(r, alert, t):
    """Ballpark marquee: chasing bulbs around the frame, headline strobes in."""
    base, accent = r._score_alert_palette(alert)
    img = Image.new("RGBA", (PANEL_W, PANEL_H), (5, 5, 8, 255))
    d = ImageDraw.Draw(img, "RGBA")

    # Soft team-colour glow behind the headline so the frame isn't just black.
    center = PANEL_W // 2
    glow = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    for x in range(PANEL_W):
        falloff = max(0.0, 1 - abs(x - center) / 170.0)
        gd.line([(x, 0), (x, PANEL_H)], fill=_scale(base, 0.55) + (int(150 * falloff ** 2),))
    img.alpha_composite(glow)

    # Bulbs. Three-phase chase, which reads as movement without ever lighting
    # more than a third of them at once.
    step = int(t * 14)
    on = (255, 226, 150)
    off = _scale(base, 0.5)
    for i, x in enumerate(range(3, PANEL_W - 2, 7)):
        lit = (i + step) % 3 == 0
        c = on if lit else off
        d.rectangle([x, 0, x + 1, 1], fill=c)
        d.rectangle([x, PANEL_H - 2, x + 1, PANEL_H - 1], fill=c)

    logo = r.get_logo(alert.get("team_logo"), (24, 24))
    if logo is not None:
        img.paste(logo, (5, 4), logo)

    # Strobe the headline for the first beat, then hold it steady.
    text_center = (34 + (PANEL_W - 82)) // 2
    visible = True if t > 0.95 else (int(t * 9) % 2 == 0)
    if visible:
        outline_text(d, text_center, 12, alert["headline"], r.huge_font, (255, 250, 235))
    if t > 0.95:
        detail = alert["detail"]
        draw_tiny_text(d, text_center - len(detail) * 5 // 2, 25, detail, (255, 214, 130))

    if t > 0.6:
        score_column(d, alert, PANEL_W - 82, color_status=(190, 165, 110))

    if t > TOTAL - 0.4:
        k = 1 - smooth((t - (TOTAL - 0.4)) / 0.4)
        img = Image.blend(Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255)), img, k)
    return img


# ── concept 4 · split-flap board ─────────────────────────────────────────────

_FLAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def concept_splitflap(r, alert, t):
    """Departure-board flaps: letters scramble, then settle one at a time.

    Amber on black, monospaced, seams every few rows — reads as a mechanical
    board rather than a screen, and costs almost nothing in current.
    """
    base, accent = r._score_alert_palette(alert)
    img = Image.new("RGBA", (PANEL_W, PANEL_H), (9, 9, 10, 255))
    d = ImageDraw.Draw(img, "RGBA")

    amber = (255, 172, 20)
    for y in range(0, PANEL_H, 8):
        d.line([(0, y), (PANEL_W, y)], fill=(24, 24, 26))

    logo = r.get_logo(alert.get("team_logo"), (16, 16))
    if logo is not None:
        img.paste(logo, (6, 8), logo)
    d.line([(30, 3), (30, PANEL_H - 4)], fill=(46, 46, 50))

    headline = alert["headline"]
    text_x = 40
    settled = int(max(0.0, t - 0.15) / 0.075)
    rng = random.Random(int(t * 22))
    shown = "".join(
        ch if (i < settled or ch == " ") else rng.choice(_FLAP_CHARS)
        for i, ch in enumerate(headline)
    )
    # Blank the flaps out again on the way off, same mechanism in reverse.
    if t > TOTAL - 0.7:
        gone = int((t - (TOTAL - 0.7)) / 0.055)
        shown = "".join(" " if i < gone else c for i, c in enumerate(shown))

    d.text((text_x, 4), shown, font=r.huge_font, fill=amber)

    if settled >= len(headline) and t < TOTAL - 0.7:
        draw_tiny_text(d, text_x + 1, 25, alert["detail"], _scale(amber, 0.8))
        score_column(d, alert, PANEL_W - 82,
                     color_scorer=amber, color_other=(120, 82, 12),
                     color_status=(150, 102, 16))
    return img


# ── concept 5 · knockout bar ─────────────────────────────────────────────────

def concept_knockout(r, alert, t):
    """Headline reversed out of a solid accent bar that wipes across.

    The boldest of the five, and the most expensive: a near-white bar 18 rows
    tall across most of the panel is several thousand lit pixels, which is
    exactly the wide-bright-content case the panels brown out on. Included
    because it is the strongest read at distance — the trade is real.
    """
    base, accent = r._score_alert_palette(alert)
    img = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, PANEL_W, PANEL_H], fill=_scale(base, 0.42))
    for y in range(0, PANEL_H, 2):
        d.line([(0, y), (PANEL_W, y)], fill=(0, 0, 0, 60))

    logo = r.get_logo(alert.get("team_logo"), (24, 24))
    if logo is not None:
        img.paste(logo, (5, 4), logo)

    bar_left, bar_right = 36, PANEL_W - 84
    wipe = ease_out(t / 0.4)
    if t > TOTAL - 0.45:
        # Exits the same way it arrived: the left edge chases the right one out.
        bar_left += int((bar_right - bar_left) * smooth((t - (TOTAL - 0.45)) / 0.45))
    end = bar_left + int((bar_right - bar_left) * wipe)

    if end > bar_left:
        d.rectangle([bar_left, 5, end, 22], fill=accent)
        d.line([(end, 5), (end, 22)], fill=(255, 255, 255))

        # The headline is a hole in the bar, so it is clipped by the wipe for
        # free and never floats outside it.
        knock = text_layer(alert["headline"], r.huge_font, _scale(base, 0.55))
        clip = Image.new("RGBA", (end - bar_left, PANEL_H), (0, 0, 0, 0))
        clip.alpha_composite(knock, (8, 13 - knock.height // 2))
        img.alpha_composite(clip, (bar_left, 0))

    if wipe >= 1.0 and t < TOTAL - 0.45:
        draw_tiny_text(d, bar_left + 9, 25, alert["detail"], (255, 255, 255))
        score_column(d, alert, PANEL_W - 82)
    return img


CONCEPTS = [
    ("1_chevron_slam", concept_chevron),
    ("2_broadcast_bug", concept_broadcast),
    ("3_jumbotron", concept_jumbotron),
    ("4_split_flap", concept_splitflap),
    ("5_knockout_bar", concept_knockout),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--no-gif", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    r = make_renderer("sports")
    for size in ((24, 24), (16, 16)):
        r.download_and_process_logo(SAMPLE["team_logo"], size)

    stills = []
    for name, fn in CONCEPTS:
        still = fn(r, SAMPLE, STILL_AT).convert("RGB")
        save_image(still, os.path.join(args.out_dir, f"{name}.png"))
        stills.append(still)

        if args.no_gif:
            continue
        frames = []
        for i in range(int(TOTAL * FPS)):
            frame = fn(r, SAMPLE, i / FPS).convert("RGB")
            frames.append(frame.resize(
                (PANEL_W * args.scale, PANEL_H * args.scale), Image.Resampling.NEAREST))
        path = os.path.join(args.out_dir, f"{name}.gif")
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=int(1000 / FPS), loop=0)
        print(f"Saved {path} ({len(frames)} frames)")

    # Comparison sheet: same play, same instant, five treatments.
    s = args.scale
    sheet = Image.new("RGB", (PANEL_W * s, (PANEL_H * s + 8) * len(stills)), (18, 18, 20))
    for i, still in enumerate(stills):
        sheet.paste(still.resize((PANEL_W * s, PANEL_H * s), Image.Resampling.NEAREST),
                    (0, i * (PANEL_H * s + 8)))
    save_image(sheet, os.path.join(args.out_dir, "_concepts.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
