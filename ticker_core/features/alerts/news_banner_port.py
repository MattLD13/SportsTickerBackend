"""Half-width banner for breaking news, drawn beside the live ticker.

A score alert takes the whole panel, because a score is the thing you turned
the board on for. News is not that. The banner holds the left 192 pixels and
lets the strip carry on scrolling in the right 192, so a trade never costs you
the scores.

That is the one real difference from `score_alert.py`. A score alert freezes
the strip and blocks the render loop for its whole duration. This does not: it
is a modifier applied to each ordinary scroll frame, so the scroll cadence is
untouched and the banner simply rides on top of it.

Two kinds of item arrive, and each stays in its own mode. A trade shows both
clubs in the header over two lines of detail. Stock news shows the symbol and
the day's move over three lines of headline.
"""

import re

from PIL import Image, ImageDraw

from ticker_core.rendering.pixels import draw_hybrid_text, draw_tiny_text

PANEL_W = 384
PANEL_H = 32

BANNER_W = 192          # exactly half the panel
SLIDE = 0.30            # seconds to arrive, and to leave
HOLD_TRADE = 6.4
HOLD_NEWS = 7.4         # a headline is three lines, so it needs longer

AMBER = (255, 176, 20)      # sports news
CYAN = (70, 175, 255)       # stock news
UP = (60, 205, 95)
DOWN = (235, 75, 75)

TEXT_COLS = 35          # characters per line at a 5px advance in 178px


def news_banner_duration(item):
    hold = HOLD_NEWS if (item or {}).get('domain') == 'stocks' else HOLD_TRADE
    return SLIDE + hold + SLIDE


def _ease_out(v):
    v = max(0.0, min(1.0, v))
    return 1 - (1 - v) ** 3


def _hex_rgb(value, fallback=(139, 147, 163)):
    try:
        c = str(value).strip().lstrip('#')
        if len(c) == 6:
            return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return fallback


def _readable(color):
    """Lift a dark club colour until it reads on a black banner.

    Scaled, not mixed toward white: Rays navy mixed with white is grey, but the
    same navy scaled up is still navy.
    """
    lum = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    if lum >= 95:
        return color
    factor = 95.0 / max(1.0, lum)
    return tuple(min(255, int(c * factor)) for c in color)


def wrap_lines(text, cols=TEXT_COLS, max_lines=2):
    """Break text on word boundaries into at most ``max_lines`` lines.

    A trade gets two lines, which is all its own words need. A stock headline
    gets three: real headlines run to a median of 65 characters and a maximum
    of 89, and two lines of 35 would cut a quarter of them.
    """
    words = str(text or '').upper().split()
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


class NewsBannerMixin:

    def _banner_fonts(self):
        fonts = getattr(self, '_news_banner_fonts', None)
        if fonts is None:
            fonts = {size: load_monospace_font(size, bold=True) for size in (14, 16)}
            self._news_banner_fonts = fonts
        return fonts

    # ── pieces ───────────────────────────────────────────────────────────────
    def _draw_banner_arrow(self, d, x, y, length, start_color, end_color):
        """A shaft that fades from the old club's colour into the new one."""
        for i in range(length):
            t = i / max(1, length - 1)
            shade = tuple(int(start_color[k] + (end_color[k] - start_color[k]) * t)
                          for k in range(3))
            d.point((x + i, y), fill=shade)
            d.point((x + i, y + 1), fill=shade)
        tip = x + length
        d.polygon([(tip, y - 2), (tip, y + 3), (tip + 3, y + 1)], fill=end_color)

    def _draw_trade_banner(self, item):
        """A trade: both clubs in the header, the detail underneath."""
        img = Image.new("RGBA", (BANNER_W, PANEL_H), (8, 9, 12, 255))
        d = ImageDraw.Draw(img, "RGBA")

        from_color = _readable(_hex_rgb(item.get('from_color')))
        to_color = _readable(_hex_rgb(item.get('to_color')))
        kind = str(item.get('kind') or 'TRADE')[:6]

        d.rectangle([0, 0, 2, PANEL_H], fill=AMBER)
        d.rectangle([4, 0, BANNER_W, 10], fill=(22, 24, 30))
        d.rectangle([6, 1, 8 + len(kind) * 5, 9], fill=AMBER)
        draw_tiny_text(d, 8, 3, kind, (10, 10, 12))

        # The old club is plain coloured text. The new club sits in a filled
        # chip. Two clubs often share a colour family, and VAN to NYR is navy on
        # navy: an arrow between two identical blues says nothing. The chip
        # carries the destination colour as a block, so the move reads even then.
        y = 2
        x = draw_hybrid_text(d, 14 + len(kind) * 5, y, str(item.get('from_abbr', ''))[:4], from_color)
        self._draw_banner_arrow(d, x + 4, y + 2, 13, from_color, to_color)
        chip_x = x + 23
        to_abbr = str(item.get('to_abbr', ''))[:4]
        chip_w = len(to_abbr) * 5 + 5
        d.rectangle([chip_x, y - 1, chip_x + chip_w, y + 8], fill=to_color)
        lum = 0.2126 * to_color[0] + 0.7152 * to_color[1] + 0.0722 * to_color[2]
        draw_hybrid_text(d, chip_x + 3, y, to_abbr,
                         (10, 10, 12) if lum > 150 else (255, 255, 255))

        d.line([(4, 11), (BANNER_W, 11)], fill=(52, 56, 66))

        lines = wrap_lines(item.get('text'), max_lines=2)
        if len(lines) == 1:
            # A short trade centres instead of hanging from the rule with an
            # empty line under it.
            draw_hybrid_text(d, 7, 20, lines[0], (255, 255, 255))
        else:
            draw_hybrid_text(d, 7, 15, lines[0], (255, 255, 255))
            draw_hybrid_text(d, 7, 24, lines[1], (206, 211, 222))
        return img

    def _draw_stock_banner(self, item):
        """Company or market news: the symbol and the move, then the headline."""
        img = Image.new("RGBA", (BANNER_W, PANEL_H), (8, 9, 12, 255))
        d = ImageDraw.Draw(img, "RGBA")

        try:
            pct = float(item.get('pct') or 0.0)
        except (TypeError, ValueError):
            pct = 0.0
        accent = UP if pct >= 0 else DOWN

        d.rectangle([0, 0, 2, PANEL_H], fill=accent)
        d.rectangle([4, 0, BANNER_W, 9], fill=(22, 24, 30))
        d.rectangle([6, 1, 34, 8], fill=CYAN)
        draw_tiny_text(d, 8, 2, "NEWS", (8, 10, 14))
        draw_hybrid_text(d, 40, 1, str(item.get('to_abbr', ''))[:6], (255, 255, 255))

        if item.get('pct') is not None:
            label = f"{pct:+.1f}%"
            draw_tiny_text(d, BANNER_W - 5 - len(label) * 5, 2, label, accent)
        d.line([(4, 10), (BANNER_W, 10)], fill=(52, 56, 66))

        # Rows 12 to 31 hold exactly three 6px lines with one row between. Any
        # lower and the last line loses its bottom row off the panel.
        for i, line in enumerate(wrap_lines(item.get('text'), max_lines=3)):
            draw_hybrid_text(d, 7, 12 + i * 7, line,
                             (255, 255, 255) if i == 0 else (203, 209, 220))
        return img

    # ── frame ────────────────────────────────────────────────────────────────
    def draw_news_banner(self, item):
        if str(item.get('domain')) == 'stocks':
            return self._draw_stock_banner(item)
        return self._draw_trade_banner(item)

    def apply_news_banner(self, frame, item, elapsed):
        """Lay the banner over the left half of an ordinary scroll frame.

        ``frame`` is the panel-wide view the strip would have shown anyway, so
        the right half keeps scrolling underneath and nothing is lost while the
        banner is up.
        """
        total = news_banner_duration(item)
        if elapsed < SLIDE:
            travel = int(BANNER_W * (1 - _ease_out(elapsed / SLIDE)))
        elif elapsed > total - SLIDE:
            travel = int(BANNER_W * _ease_out((elapsed - (total - SLIDE)) / SLIDE))
        else:
            travel = 0

        out = frame.convert("RGBA")
        out.alpha_composite(self.draw_news_banner(item), (-travel, 0))
        ImageDraw.Draw(out).line(
            [(BANNER_W - travel, 0), (BANNER_W - travel, PANEL_H)], fill=(70, 76, 88))
        return out.convert("RGB")


class PreparedNewsBannerRenderer(NewsBannerMixin):
    """Expose the ported news banner without controller inheritance."""
