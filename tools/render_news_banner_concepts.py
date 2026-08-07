#!/usr/bin/env python3
"""Concept study: a half-width news banner that runs beside the live ticker.

A score alert takes the whole panel because a score is the thing you turned the
board on for. News is not that. It takes the left half and lets the strip keep
scrolling in the right half, so nothing is lost while it is up.

Each banner stays in its own mode. Stock news appears only while the ticker is
in stocks mode. A trade appears only in a sports mode. Neither one crosses over.
There is no banner for a price move on its own.

The text stacks instead of running as one long marquee line. A trade reads as
the two teams in the header, drawn in their own colours with an arrow between,
over two lines of detail. Stock news reads as the symbol in the header over
three lines of headline.

Nothing here is imported by the controller, and nothing here touches
ticker_controller/modes/score_alert.py. Scoring graphics are unchanged.

    python tools/render_news_banner_concepts.py
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.fetch_and_render import make_renderer, prefetch_logos, render_scroll, save_image  # noqa: E402
from tools.render_score_alert_overlay import STRIP_GAMES  # noqa: E402
from ticker_controller.config import PANEL_W, PANEL_H  # noqa: E402
from ticker_controller.fonts import draw_hybrid_text, draw_tiny_text, load_monospace_font  # noqa: E402

OUT_DIR = "previews/news_banner_concepts"
FPS = 25
BANNER_W = 192          # exactly half the panel
SLIDE = 0.30            # seconds for the banner to arrive and to leave
SCROLL_PX = 1.3

AMBER = (255, 176, 20)      # sports news
CYAN = (70, 175, 255)       # stock news
UP = (60, 205, 95)
DOWN = (235, 75, 75)

TEXT_COLS = 35              # characters per line at a 5px advance in 178px


def clamp01(v):
    return max(0.0, min(1.0, v))


def ease_out(v):
    return 1 - (1 - clamp01(v)) ** 3


def hex_rgb(value):
    c = str(value).lstrip('#')
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def readable(color):
    """Lift a dark team colour until it reads on a black banner.

    Scaled, not mixed toward white: Rays navy mixed with white is grey, but the
    same navy scaled up is still navy.
    """
    lum = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    if lum >= 95:
        return color
    factor = 95.0 / max(1.0, lum)
    return tuple(min(255, int(c * factor)) for c in color)


def draw_arrow(d, x, y, length, start_color, end_color):
    """A shaft that fades from the old team's colour into the new team's."""
    for i in range(length):
        t = i / max(1, length - 1)
        shade = tuple(int(start_color[k] + (end_color[k] - start_color[k]) * t) for k in range(3))
        d.point((x + i, y), fill=shade)
        d.point((x + i, y + 1), fill=shade)
    tip = x + length
    d.polygon([(tip, y - 2), (tip, y + 3), (tip + 3, y + 1)], fill=end_color)


def wrap_lines(text, cols=TEXT_COLS, max_lines=2):
    """Break text on word boundaries into at most ``max_lines`` lines.

    A trade gets two lines, which is all its own words need. A stock headline
    gets three: a sample of real headlines runs to a median of 65 characters
    and a maximum of 89, and two lines of 35 would cut a quarter of them.
    """
    words = str(text).upper().split()
    lines = ['']
    for word in words:
        candidate = f"{lines[-1]} {word}".strip()
        if len(candidate) <= cols:
            lines[-1] = candidate
        elif len(lines) < max_lines:
            lines.append(word)
        else:
            # Out of room. Cut the last line rather than drop it in silence.
            lines[-1] = lines[-1][:cols - 1] + '.'
            break
    return lines


# ── stocks mode only ─────────────────────────────────────────────────────────

def draw_stock_news_banner(fonts, item, t):
    """Company or market news. Stocks mode only.

    A price move is a number and needs no words. News is words, so this one
    borrows the trade layout: the header says which symbol and how it is
    trading today, and the headline sits underneath. The day's move stays in
    the header because a headline without the move is only half the story.
    """
    img = Image.new("RGBA", (BANNER_W, PANEL_H), (8, 9, 12, 255))
    d = ImageDraw.Draw(img, "RGBA")
    accent = UP if item["pct"] >= 0 else DOWN

    d.rectangle([0, 0, 2, PANEL_H], fill=accent)
    d.rectangle([4, 0, BANNER_W, 9], fill=(22, 24, 30))
    d.rectangle([6, 1, 34, 8], fill=CYAN)
    draw_tiny_text(d, 8, 2, "NEWS", (8, 10, 14))

    draw_hybrid_text(d, 40, 1, item["symbol"], (255, 255, 255))
    pct = f"{item['pct']:+.1f}%"
    draw_tiny_text(d, BANNER_W - 5 - len(pct) * 5, 2, pct, accent)
    d.line([(4, 10), (BANNER_W, 10)], fill=(52, 56, 66))

    # Three lines, because real headlines need them. Rows 12 to 31 hold exactly
    # three 6px lines with a single row between: any lower and the last line
    # loses its bottom row off the panel.
    for i, line in enumerate(wrap_lines(item["headline"], max_lines=3)):
        draw_hybrid_text(d, 7, 12 + i * 7, line,
                         (255, 255, 255) if i == 0 else (203, 209, 220))
    return img


# ── sports modes only ────────────────────────────────────────────────────────

def draw_trade_banner(fonts, item, t):
    """A trade: the two teams in the header, the detail underneath.

    The header answers the question the eye asks first, which is who is
    involved. The two lines below carry the rest. Nothing scrolls, so the whole
    thing can be read from one glance instead of from a marquee pass.
    """
    img = Image.new("RGBA", (BANNER_W, PANEL_H), (8, 9, 12, 255))
    d = ImageDraw.Draw(img, "RGBA")

    from_color = readable(hex_rgb(item["from_color"]))
    to_color = readable(hex_rgb(item["to_color"]))

    d.rectangle([0, 0, 2, PANEL_H], fill=AMBER)

    # ── header bar: kind, then both teams ────────────────────────────────
    d.rectangle([4, 0, BANNER_W, 10], fill=(22, 24, 30))
    d.rectangle([6, 1, 36, 9], fill=AMBER)
    draw_tiny_text(d, 8, 3, item["kind"], (10, 10, 12))

    # The old team is plain coloured text. The new team sits in a filled chip.
    # Two clubs often share a colour family, and VAN to NYR is navy on navy: an
    # arrow between two identical blues says nothing. The chip carries the
    # destination colour as a block, so the move reads even then.
    y = 2
    x = draw_hybrid_text(d, 44, y, item["from_abbr"], from_color)
    draw_arrow(d, x + 4, y + 2, 13, from_color, to_color)
    chip_x = x + 23
    chip_w = len(item["to_abbr"]) * 5 + 5
    d.rectangle([chip_x, y - 1, chip_x + chip_w, y + 8], fill=to_color)
    lum = 0.2126 * to_color[0] + 0.7152 * to_color[1] + 0.0722 * to_color[2]
    draw_hybrid_text(d, chip_x + 3, y, item["to_abbr"],
                     (10, 10, 12) if lum > 150 else (255, 255, 255))

    d.line([(4, 11), (BANNER_W, 11)], fill=(52, 56, 66))

    # ── two lines of detail ──────────────────────────────────────────────
    lines = wrap_lines(item["text"], max_lines=2)
    if len(lines) == 1:
        # A short trade centres in the space instead of hanging from the rule
        # with an empty line under it.
        draw_hybrid_text(d, 7, 20, lines[0], (255, 255, 255))
    else:
        draw_hybrid_text(d, 7, 15, lines[0], (255, 255, 255))
        draw_hybrid_text(d, 7, 24, lines[1], (206, 211, 222))
    return img


def compose(strip, banner, offset, t, total):
    """Banner on the left, the strip still running on the right."""
    span = max(1, strip.width - PANEL_W)
    frame = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))

    # The scrolling half keeps its own window on the strip. Items slide left and
    # pass under the banner edge, the way a broadcast lower third behaves.
    x = int(offset) % span
    frame.paste(strip.crop((x, 0, x + BANNER_W, PANEL_H)).convert("RGBA"), (BANNER_W, 0))

    if t < SLIDE:
        travel = int(BANNER_W * (1 - ease_out(t / SLIDE)))
    elif t > total - SLIDE:
        travel = int(BANNER_W * ease_out((t - (total - SLIDE)) / SLIDE))
    else:
        travel = 0

    frame.alpha_composite(banner, (-travel, 0))
    d = ImageDraw.Draw(frame)
    d.line([(BANNER_W - travel, 0), (BANNER_W - travel, PANEL_H)], fill=(70, 76, 88))
    return frame.convert("RGB")


# Mock stock cards, so the stocks-mode banner is shown over a stocks strip and
# not over a sports one. Shape copied from StockFetcher.get_stock_obj.
def stock_card(symbol, price, pct, change):
    return {
        'type': 'stock_ticker', 'sport': 'stock', 'id': f'stk_{symbol}',
        'status': 'MARKET', 'tourney_name': 'MARKET', 'state': 'in', 'is_shown': True,
        'home_abbr': symbol, 'home_score': price, 'away_score': pct,
        'home_logo': '', 'situation': {'change': change},
        'home_color': '#FFFFFF', 'away_color': '#FFFFFF',
    }


STOCK_STRIP = [
    stock_card('AAPL', '241.18', '+0.84%', '+2.01'),
    stock_card('NVDA', '182.40', '+4.20%', '+7.35'),
    stock_card('MSFT', '511.06', '-0.42%', '-2.16'),
    stock_card('TSLA', '291.05', '-3.80%', '-11.49'),
    stock_card('AMZN', '224.77', '+1.12%', '+2.49'),
]

CONCEPTS = [
    # Real headlines, pulled from a live feed. Lengths 66, 68 and 89, which is
    # the longest in the sample and the case that proves the third line.
    ('2a_news_tsla', 'stocks', draw_stock_news_banner, 8.0,
     {'symbol': 'TSLA', 'pct': -3.8,
      'headline': "Musk's SpaceX, Tesla to build $16.8B Terafab chip factory in Texas"}),
    ('2b_news_aapl', 'stocks', draw_stock_news_banner, 8.0,
     {'symbol': 'AAPL', 'pct': 1.4,
      'headline': "Apple Stock Surged On An Upgrade Cycle Its Own Reports Flagged Early"}),
    ('2c_news_long', 'stocks', draw_stock_news_banner, 8.0,
     {'symbol': 'DDOG', 'pct': 6.1,
      'headline': "Datadog Posts Q2 Beat as Observability, AI Demand Remain Strong, RBC Capital Markets Says"}),
    ('3_trade_stl',  'sports', draw_trade_banner, 7.0,
     {'kind': 'TRADE',
      'text': 'RHP Ryan Helsley for two prospects',
      'from_abbr': 'TB',  'from_color': '#092C5C',
      'to_abbr':   'STL', 'to_color':   '#C41E3A'}),
    ('4_trade_nyr',  'sports', draw_trade_banner, 7.0,
     {'kind': 'TRADE',
      'text': 'J.T. Miller for Kakko, a 2027 first and a conditional third',
      'from_abbr': 'VAN', 'from_color': '#00205B',
      'to_abbr':   'NYR', 'to_color':   '#0038A8'}),
    ('5_signing',    'sports', draw_trade_banner, 7.0,
     {'kind': 'SIGNS',
      'text': 'Saquon Barkley to a three-year deal worth 37.75M',
      'from_abbr': 'FA',  'from_color': '#8B93A3',
      'to_abbr':   'NYG', 'to_color':   '#0B2265'}),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', default=OUT_DIR)
    parser.add_argument('--scale', type=int, default=3)
    parser.add_argument('--no-gif', action='store_true')
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    r = make_renderer('sports')
    prefetch_logos(r, STRIP_GAMES)
    sports_strip = render_scroll(r, STRIP_GAMES)
    stocks_strip = render_scroll(r, STOCK_STRIP)
    strips = {'sports': sports_strip, 'stocks': stocks_strip}
    fonts = {s: load_monospace_font(s, bold=True) for s in (13, 14, 16)}

    stills = []
    for name, mode, fn, total, item in CONCEPTS:
        strip = strips[mode]
        frames = []
        offset = 120.0
        for i in range(int(total * FPS)):
            t = i / FPS
            frames.append(compose(strip, fn(fonts, item, t), offset, t, total))
            offset += SCROLL_PX

        still = frames[int(2.5 * FPS)]
        save_image(still, os.path.join(args.out_dir, f'{name}.png'))
        stills.append(still)

        if args.no_gif:
            continue
        scaled = [f.resize((PANEL_W * args.scale, PANEL_H * args.scale),
                           Image.Resampling.NEAREST) for f in frames]
        path = os.path.join(args.out_dir, f'{name}.gif')
        scaled[0].save(path, save_all=True, append_images=scaled[1:],
                       duration=int(1000 / FPS), loop=0)
        print(f'Saved {path} ({len(scaled)} frames)')

    s = args.scale
    sheet = Image.new('RGB', (PANEL_W * s, (PANEL_H * s + 8) * len(stills)), (18, 18, 20))
    for i, still in enumerate(stills):
        sheet.paste(still.resize((PANEL_W * s, PANEL_H * s), Image.Resampling.NEAREST),
                    (0, i * (PANEL_H * s + 8)))
    save_image(sheet, os.path.join(args.out_dir, '_banners.png'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
