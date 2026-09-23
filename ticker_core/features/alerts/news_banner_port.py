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

from PIL import Image, ImageDraw

from ticker_core.rendering.fonts import load_monospace_font
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
_NEWS_KIND_STYLES = {
    "TRADE": ((255, 176, 20), "TRADE"),
    "MAJOR": ((255, 145, 35), "MAJOR"),
    "BLOCKBUSTER": ((245, 70, 170), "BLOCK"),
    "SIGNING": ((60, 205, 95), "SIGN"),
    "EXTENSION": ((170, 120, 255), "EXTEND"),
    "INJURY": ((235, 75, 75), "INJURY"),
    "WAIVER": ((70, 190, 255), "WAIVER"),
    "DFA": ((255, 95, 55), "DFA"),
    "RELEASE": ((170, 180, 195), "RELEASE"),
    "OPTION": ((155, 115, 245), "OPTION"),
    "RECALL": ((55, 210, 150), "RECALL"),
    "ACTIVATED": ((50, 200, 205), "ACTIVE"),
    "SUSPENSION": ((235, 55, 75), "SUSPEND"),
    "RETIREMENT": ((225, 225, 235), "RETIRE"),
    "NO_TENDER": ((220, 135, 45), "NON-TEND"),
}

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


def _darken(color, factor=0.38):
    """Keep team colors recognizable while protecting small white header text."""
    return tuple(max(0, min(255, int(channel * factor))) for channel in color)


def _gradient_stops(item, accent):
    """Return real team colors for a compact, multi-stop news header."""
    trade = str(item.get("kind") or "").strip().upper() == "TRADE"
    sides = ("from", "to") if trade else ("to", "from")
    colors = []
    for side in sides:
        for suffix in ("color", "alt_color"):
            raw = item.get(f"{side}_{suffix}")
            if raw:
                colors.append(_hex_rgb(raw))
    if not colors:
        colors.append(accent)
    if len(colors) == 1:
        colors.append(accent)
    colors = [_darken(color) for color in colors[:4]]
    if len(colors) == 2:
        colors.insert(1, _darken(accent, 0.30))
    return colors


def _team_text_color(item, side, fallback):
    """Choose a catalog color that remains visible without a filled chip."""
    primary = _hex_rgb(item.get(f"{side}_color"), fallback)
    alternate = _hex_rgb(item.get(f"{side}_alt_color"), (255, 255, 255))
    luminance = lambda color: 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    if luminance(primary) >= 130:
        return primary
    if luminance(alternate) >= 130:
        return alternate
    return (255, 255, 255)


def _draw_header_gradient(draw, colors, x0=0, x1=BANNER_W - 1, y0=0, y1=10):
    """Draw a smooth, low-profile horizontal gradient across the alert header."""
    span = max(1, x1 - x0)
    segments = max(1, len(colors) - 1)
    for x in range(x0, x1 + 1):
        position = (x - x0) / span * segments
        segment = min(segments - 1, int(position))
        blend = position - segment
        start, end = colors[segment], colors[segment + 1]
        color = tuple(int(start[channel] + (end[channel] - start[channel]) * blend)
                      for channel in range(3))
        draw.line([(x, y0), (x, y1)], fill=color)


def _news_kind_style(item):
    """Return the accent and compact label for one sports news kind."""

    impact_tier = str(item.get("impact_tier") or "").strip().upper()
    kind = impact_tier if impact_tier in _NEWS_KIND_STYLES else str(item.get("kind") or "NEWS").strip().upper()
    return _NEWS_KIND_STYLES.get(kind, ((139, 147, 163), kind[:6]))


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
        """Draw one structured sports news item."""
        img = Image.new("RGBA", (BANNER_W, PANEL_H), (8, 9, 12, 255))
        d = ImageDraw.Draw(img, "RGBA")

        from_color = _readable(_hex_rgb(item.get('from_color')))
        to_color = _readable(_hex_rgb(item.get('to_color')))
        accent, kind = _news_kind_style(item)

        d.rectangle([0, 0, 2, PANEL_H], fill=accent)
        _draw_header_gradient(d, _gradient_stops(item, accent))
        draw_tiny_text(d, 7, 3, kind, (255, 255, 255))

        y = 2
        x = 12 + len(kind) * 5
        from_abbr = str(item.get('from_abbr', ''))[:4]
        to_abbr = str(item.get('to_abbr', ''))[:4]
        if str(item.get("kind") or "").strip().upper() == "TRADE" and from_abbr and to_abbr:
            x = draw_hybrid_text(d, x, y, from_abbr, _team_text_color(item, "from", from_color))
            self._draw_banner_arrow(d, x + 4, y + 2, 13, from_color, to_color)
            team_x = x + 23
        else:
            team_x = x
        team_abbr = to_abbr or from_abbr
        team_side = "to" if to_abbr else "from"
        team_color = _team_text_color(item, team_side, to_color)
        draw_hybrid_text(d, team_x, y, team_abbr, team_color)

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
