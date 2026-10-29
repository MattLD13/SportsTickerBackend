"""Draw 32 pixel stadium score cards for the Ticker Six scroll."""

from PIL import Image, ImageDraw

from sports_ticker.providers.sports_display import sport_family

from ticker_core.ui.text import HYBRID as HYBRID_FONT_MAP, PANE as PF
from ticker_core.ui.palette import STATUS_TEXT, SCORE_TEXT, PLAY_TEXT, RED_ZONE_TEXT, TOURNAMENT_SEED, sports_rule_color
from ticker_core.ui.layers import ImageTemplates, image_key
from .logo_badge import draw_missing_team_badge
from .logo_visibility import LogoOutlineMode, paste_team_logo
from .logo_rendering import get_prepared_team_logo

H = 32          # card height, always 32px (LED panel height)
LOGO_SZ = 22    # logo square size in pixels
LOGO_PAD = 2    # gap between logo edge and center content zone
ZONE = LOGO_SZ + LOGO_PAD  # space each side takes = 24px
FOOTBALL_RANK_COLOR = (255, 220, 80)
SHOOTOUT_DOT = 5
MISS_RED = (220, 55, 55)


# ── Low-level drawing helpers ─────────────────────────────────────────────────

def _clamp(v):
    return max(0, min(255, int(v)))


def fill_rect(d, x, y, w, h, r, g, b, a=255):
    """Fill an integer rectangle. Skip an empty size."""
    if w <= 0 or h <= 0:
        return
    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=(_clamp(r), _clamp(g), _clamp(b), _clamp(a)))


def hex_to_rgb(hex_str):
    """Convert '#RRGGBB' or 'RRGGBB' to (r, g, b)."""
    h = (hex_str or '').strip().lstrip('#')
    if len(h) == 6:
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    return (80, 80, 80)


# ── Pixel font ────────────────────────────────────────────────────────────────

def pf_char(d, ch, x, y, r, g, b, sc=1):
    """Draw one pixel-font glyph and return its advance."""
    bm = PF.get(ch.upper(), PF[' '])
    col = (_clamp(r), _clamp(g), _clamp(b), 255)
    for row in range(5):
        for col_idx in range(len(bm[row])):
            if bm[row][col_idx]:
                fx, fy = x + col_idx * sc, y + row * sc
                d.rectangle([fx, fy, fx + sc - 1, fy + sc - 1], fill=col)
    return (len(bm[0]) + 1) * sc


def pf_text(d, text, x, y, r, g, b, sc=1):
    """Draw a pixel-font string and return its width."""
    cx = x
    for ch in str(text).upper():
        cx += pf_char(d, ch, cx, y, r, g, b, sc)
    return cx - x


def pf_w(text, sc=1):
    """Measure the pixel-font glyph advances."""
    return sum(len(PF.get(ch.upper(), PF[' '])[0]) + 1 for ch in str(text)) * sc


def _draw_status_glyphs(draw, x, y, text, color):
    """Draw upper-case six-row status glyphs with a 5 pixel advance."""
    for index, char in enumerate(text):
        bitmap = HYBRID_FONT_MAP.get(char.upper(), HYBRID_FONT_MAP.get(' ', [0x0] * 6))
        for row, row_byte in enumerate(bitmap):
            for column, bit in enumerate((0x8, 0x4, 0x2, 0x1)):
                if row_byte & bit:
                    draw.point((x + index * 5 + column, y + row), fill=color)


# ── Sprite helpers ────────────────────────────────────────────────────────────

def draw_football(d, cx, cy):
    """Possession football (9×5 px), sized to read from across the room."""
    brown = (150, 75, 20)
    tip = (110, 54, 14)
    fill_rect(d, cx - 2, cy, 5, 1, *brown)
    fill_rect(d, cx - 3, cy + 1, 7, 1, *brown)
    fill_rect(d, cx - 4, cy + 2, 9, 1, *brown)
    fill_rect(d, cx - 3, cy + 3, 7, 1, *brown)
    fill_rect(d, cx - 2, cy + 4, 5, 1, *brown)
    # Darker points so the ellipse keeps its shape against a bright logo.
    fill_rect(d, cx - 4, cy + 2, 1, 1, *tip)
    fill_rect(d, cx + 4, cy + 2, 1, 1, *tip)
    # Single lace stripe down the long axis — cross-stitches turn into a blur
    # at this size and read as a plus sign rather than a football.
    fill_rect(d, cx - 2, cy + 2, 5, 1, 255, 255, 255)


def draw_base_diamond(d, cx, ty, on1, on2, on3):
    """Draw second base at the top, first base on the right, and third base on the left."""
    for bx, by, on in ((cx, ty, on2), (cx + 4, ty + 4, on1), (cx - 4, ty + 4, on3)):
        c = (255, 200, 0) if on else (55, 55, 55)
        fill_rect(d, bx - 2, by, 5, 1, *c)
        fill_rect(d, bx - 1, by + 1, 3, 1, *c)
        fill_rect(d, bx, by + 2, 1, 1, *c)
        fill_rect(d, bx - 2, by, 1, 1, *c)
        fill_rect(d, bx + 2, by, 1, 1, *c)


def draw_shootout_dot(d, x, y, result):
    """Draw one 5 pixel shootout result: a green goal, a red cross, or an open slot."""
    size = SHOOTOUT_DOT
    if result == 'goal':
        fill_rect(d, x, y, size, size, 50, 200, 70)
    elif result == 'miss':
        fill_rect(d, x, y, 2, 2, *MISS_RED)
        fill_rect(d, x + size - 2, y, 2, 2, *MISS_RED)
        fill_rect(d, x + 1, y + size // 2, size - 2, 1, *MISS_RED)
        fill_rect(d, x, y + size - 2, 2, 2, *MISS_RED)
        fill_rect(d, x + size - 2, y + size - 2, 2, 2, *MISS_RED)
    else:
        fill_rect(d, x, y, size, size, 55, 55, 55)
        fill_rect(d, x + 1, y + 1, size - 2, size - 2, 10, 10, 14)


def draw_hockey_so_column(draw, x, y, shootout, side):
    """Draw the backend's three NHL rounds without changing their order."""
    for index, row in enumerate(shootout.get('displayRounds', ())):
        dy = y + index * 7
        result = row[side]
        if result == 'not_taken':
            fill_rect(draw, x, dy, 5, 5, 20, 25, 32)
            fill_rect(draw, x + 1, dy + 2, 3, 1, 65, 70, 80)
        else:
            draw_shootout_dot(draw, x, dy, result)
        if row.get('nextSide') == side:
            draw.rectangle((x - 1, dy - 1, x + 5, dy + 5), outline=(90, 190, 255))


# ── Card width ────────────────────────────────────────────────────────────────

def calc_card_width(g):
    """Return the smallest even card width that keeps content clear of both logos."""
    family = sport_family(g.get('sport'))
    is_mlb = family == 'baseball'
    is_nfl = family == 'football'
    is_nhl = family == 'hockey'
    sit = g.get('situation', {}) or {}
    dd = sit.get('downDist', '') or ''

    score_w = pf_w(str(g.get('away_score', g['as'])), sc=2) + pf_w('-', sc=2) + pf_w(str(g.get('home_score', g['hs'])), sc=2)
    show_inning = (g.get('baseball_inning') or {}).get('phase') in {'playing', 'break'}
    if is_mlb and show_inning:
        center = score_w + 2
    else:
        center = max(score_w, pf_w(str(g.get('status', ''))))
    if is_nfl and g.get('state', '') == 'in' and dd:
        center = max(center, pf_w(dd))
    if (is_nhl or family == 'soccer') and sit.get('shootout'):
        center = max(center, score_w + 14)
    if is_nhl:
        center = max(center, pf_w(str(sit.get('manpower', {}).get('scrollLabel') or '')))
    total = ZONE + 4 + center + 4 + ZONE
    return min(160, int((total + 1) // 2 * 2))


def _normalise(g):
    """Add integer scores, team codes, colours, a state, and the situation to one game."""
    out = dict(g)
    out['as'] = int(out.get('away_score', 0) or 0)
    out['hs'] = int(out.get('home_score', 0) or 0)
    if 'away' not in out:
        out['away'] = out.get('away_abbr', '???')
    if 'home' not in out:
        out['home'] = out.get('home_abbr', '???')
    if 'sport' not in out:
        out['sport'] = 'unknown'
    out['ac'] = hex_to_rgb(out.get('away_color', ''))
    out['hc'] = hex_to_rgb(out.get('home_color', ''))
    if 'state' not in out:
        s = str(out.get('game_state', out.get('status', ''))).lower()
        if 'final' in s or 'post' in s:
            out['state'] = 'post'
        elif any(x in s for x in ('q', 'p', 'h', 'inning', 'top', 'bot', "'", 'live')):
            out['state'] = 'in'
        else:
            out['state'] = 'pre'
    out['sit'] = out.get('situation', {}) or {}
    return out


def _team_side(g, value):
    """Return 'home' or 'away' for a team code, team id, or side name."""
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    for side, short in (('home', 'H'), ('away', 'A')):
        tokens = {str(g.get(key, '')).strip().upper() for key in (side, f'{side}_abbr', f'{side}_id')} | {side.upper(), short}
        tokens.discard('')
        if s in tokens:
            return side
    return None


# ── Renderer ──────────────────────────────────────────────────────────────────

class PreparedStadiumRenderer:
    """Render one stadium card from prepared logos. Rendering never fetches."""

    LOGO_SIZE = (LOGO_SZ, LOGO_SZ)

    def __init__(self, logos):
        self._logos = logos
        self._card_templates = ImageTemplates(max_bytes=4 * 1024 * 1024)

    def render(self, g):
        """Render one game. Return the RGBA card and its width."""
        g = _normalise(g)
        rule_color = sports_rule_color(g.get('competition_stage'))
        width = calc_card_width(g)
        sport = g['sport'].lower()
        sit = g.get('sit', {})
        inning = g.get('baseball_inning') or {}
        show_inning = inning.get('phase') in {'playing', 'break'}
        family = sport_family(sport)

        layout = _CardLayout(width)
        away_logo = self._get_logo(g.get('away_logo'), g.get('away_logo_rendering'))
        home_logo = self._get_logo(g.get('home_logo'), g.get('home_logo_rendering'))
        img = self._card_base(g, width, rule_color, away_logo, home_logo)
        d = ImageDraw.Draw(img, 'RGBA')
        if not (family == 'baseball' and show_inning):
            self._draw_header_text(img, width, g['status'][:12])
            fill_rect(d, 0, 7, width, 1, *rule_color)
            self._draw_score(img, layout, str(g['as']), str(g['hs']))

        if family == 'football' and g['state'] == 'in':
            self._draw_football_overlay(d, g, sit, layout)
        if family == 'hockey':
            self._draw_hockey_overlay(d, g, sit, layout)
        if family == 'baseball' and show_inning:
            self._draw_baseball_overlay(d, g, sit, inning, layout, rule_color)
        if family == 'soccer':
            self._draw_soccer_overlay(d, sit, layout)
        if 'march' in sport:
            self._draw_seed_overlay(d, g, width)
        return img, width

    # ── Sport overlays ───────────────────────────────────────────────────────

    @staticmethod
    def _draw_score(img, layout, away_score, home_score):
        """Draw the double-size score, stretched one row taller, at the content center."""
        away_w = pf_w(away_score, sc=2)
        dash_w = pf_w('-', sc=2)
        total_w = away_w + dash_w + pf_w(home_score, sc=2)
        layer = Image.new('RGBA', (total_w, 10), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer, 'RGBA')
        pf_text(layer_draw, away_score, 0, 0, *SCORE_TEXT, sc=2)
        pf_text(layer_draw, '-', away_w, 0, *SCORE_TEXT, sc=2)
        pf_text(layer_draw, home_score, away_w + dash_w, 0, *SCORE_TEXT, sc=2)
        layer = layer.resize((total_w, 11), Image.Resampling.NEAREST)
        img.alpha_composite(layer, (int(round(layout.center_x - total_w / 2.0)), 9))

    @staticmethod
    def _draw_football_overlay(d, g, sit, layout):
        side = _team_side(g, sit.get('activeTeam', ''))
        if side in ('home', 'away'):
            # The 5px ball stays clear of the y=7 rule.
            draw_football(d, layout.logo_center(side) - 1, 1)
        red_zone = sit.get('isRedZone', False)
        if red_zone:
            d.rectangle([0, 0, layout.width - 1, H - 1], outline=(255, 40, 40, 153), width=1)
        down = sit.get('downDist', '')
        if down:
            pf_text(d, down, layout.center - pf_w(down) // 2, 23, *(RED_ZONE_TEXT if red_zone else PLAY_TEXT))

    @staticmethod
    def _draw_hockey_overlay(d, g, sit, layout):
        shootout = sit.get('shootout')
        if shootout:
            draw_hockey_so_column(d, layout.away_logo_x + LOGO_SZ + 2, 9, shootout, 'away')
            draw_hockey_so_column(d, layout.home_logo_x - 7, 9, shootout, 'home')
            round_label = str(shootout.get('roundLabel') or '')
            pf_text(d, round_label, layout.center - pf_w(round_label) // 2, 23, 200, 210, 225)
            return
        if g['state'] not in {'in', 'crit'}:
            return
        is_pp = bool(sit.get('powerPlay'))
        is_en = bool(sit.get('emptyNet'))
        if is_en:
            side = _team_side(g, sit.get('emptyNetSide'))
            if side:
                pf_text(d, 'EN', layout.logo_center(side) - pf_w('EN') // 2, 2, 255, 100, 100)
        elif is_pp:
            side = _team_side(g, sit.get('powerPlayTeam'))
            if side:
                label = str(sit.get('manpower', {}).get('powerPlayLabel') or '')
                pf_text(d, label, layout.logo_center(side) - pf_w(label) // 2, 2, 255, 220, 0)
        label = str(sit.get('manpower', {}).get('scrollLabel') or '')
        if label:
            color = (255, 220, 0) if is_pp else (255, 100, 100) if is_en else (200, 210, 225)
            pf_text(d, label, layout.center - pf_w(label) // 2, 23, *color)

    @staticmethod
    def _draw_baseball_overlay(d, g, sit, inning, layout, rule_color):
        width = layout.width
        fill_rect(d, 0, 0, width, 8, 0, 0, 0)
        fill_rect(d, 0, 7, width, 1, *rule_color)

        # Between halves there is no half to point at, so a dash says
        # "inning break" instead of guessing a direction.
        half = inning.get('half', 'none')
        arrow = '▲' if half == 'top' else ('▼' if half == 'bottom' else '-')
        number = str(inning['number']) if inning.get('number') else ''
        arrow_w = pf_w(arrow)
        hx = max(1, (width - (arrow_w + pf_w(number))) // 2)
        pf_text(d, arrow, hx + 1, 2, 8, 8, 8)
        pf_text(d, number, hx + arrow_w + 1, 2, 8, 8, 8)
        pf_text(d, arrow, hx, 1, 255, 220, 105)
        pf_text(d, number, hx + arrow_w, 1, 255, 240, 150)

        balls = str(int(sit.get('balls', 0) or 0))
        strikes = str(int(sit.get('strikes', 0) or 0))
        outs = int(sit.get('outs', 0) or 0)
        side = _team_side(g, sit.get('activeTeam', ''))
        if side is not None:
            x = layout.logo_center(side) - (pf_w(balls) + pf_w('-') + pf_w(strikes)) // 2
            x += pf_text(d, balls, x, 2, 60, 200, 60)
            x += pf_text(d, '-', x, 2, 160, 160, 160)
            pf_text(d, strikes, x, 2, 255, 140, 40)

        away_score, home_score = str(g['as']), str(g['hs'])
        away_w = pf_w(away_score, sc=2)
        dash_w = pf_w('-', sc=2)
        score_x = int(round(layout.center_x - (away_w + dash_w + pf_w(home_score, sc=2)) / 2.0))
        dash_x = score_x + away_w
        pf_text(d, away_score, score_x, 8, 255, 255, 255, sc=2)
        pf_text(d, '-', dash_x, 8, 255, 255, 255, sc=2)
        pf_text(d, home_score, dash_x + dash_w, 8, 255, 255, 255, sc=2)
        draw_base_diamond(d, dash_x + 3, 19, bool(sit.get('onFirst', False)),
                          bool(sit.get('onSecond', False)), bool(sit.get('onThird', False)))
        out_x = (dash_x + 3) - (3 * 5 - 1) // 2
        for i in range(3):
            fill_rect(d, out_x + i * 5, 28, 4, 3, *((210, 70, 70) if i < outs else (45, 45, 45)))

    @staticmethod
    def _draw_soccer_overlay(d, sit, layout):
        shootout = sit.get('shootout')
        if shootout:
            PreparedStadiumRenderer._draw_soccer_so_col(d, layout.away_logo_x + LOGO_SZ + 2, 8, shootout.get('away', []))
            PreparedStadiumRenderer._draw_soccer_so_col(d, layout.home_logo_x - 5, 8, shootout.get('home', []))
        # A 5×7 red card sits above the inner edge of the logo. A count above
        # one shows as a digit inside the card.
        red_cards = sit.get('red_cards') or []
        counts = (sum(1 for c in red_cards if not c.get('is_home')), sum(1 for c in red_cards if c.get('is_home')))
        card_w, card_h = 5, 7
        for count, rx in zip(counts, (layout.away_logo_x + 2, layout.home_logo_x + LOGO_SZ - card_w - 2)):
            if count <= 0:
                continue
            d.rectangle([rx, 0, rx + card_w - 1, card_h - 1], fill=(210, 30, 30))
            if count > 1:
                pf_text(d, str(min(count, 9)), rx + 1, 1, 255, 255, 255)

    @staticmethod
    def _draw_seed_overlay(d, g, width):
        """Draw tournament seeds. A final shows the winner in green and the loser in red."""
        away_won = g['state'] == 'post' and g['as'] > g['hs']
        home_won = g['state'] == 'post' and g['hs'] > g['as']
        away_seed, home_seed = str(g.get('away_seed', '')), str(g.get('home_seed', ''))
        away_color = (100, 210, 100) if away_won else (170, 70, 70) if home_won else TOURNAMENT_SEED
        home_color = (100, 210, 100) if home_won else (170, 70, 70) if away_won else TOURNAMENT_SEED
        pf_text(d, away_seed, 2, 2, *away_color)
        pf_text(d, home_seed, width - pf_w(home_seed) - 2, 2, *home_color)

    @staticmethod
    def _draw_soccer_so_col(d, x, y, results):
        for i in range(5):
            r = results[i] if i < len(results) else 'pending'
            color = (50, 200, 70) if r == 'goal' else MISS_RED if r == 'miss' else (80, 80, 80)
            fill_rect(d, x, y + i * 5, 3, 3, *color)

    # ── Static card layer ────────────────────────────────────────────────────

    def _card_base(self, game, width, rule_color, away_logo, home_logo):
        """Return the cached team-mark, ranking, and rule layer for this card."""
        key = (width, rule_color, game['sport'].lower(), tuple(game['ac']), tuple(game['hc']),
               str(game.get('away_abbr') or game.get('away', '')), str(game.get('home_abbr') or game.get('home', '')),
               str(game.get('away_rank') or ''), str(game.get('home_rank') or ''), image_key(away_logo), image_key(home_logo))
        return self._card_templates.render(key, lambda: self._build_base(game, width, rule_color, away_logo, home_logo))

    def _build_base(self, game, width, rule_color, away_logo, home_logo):
        image = Image.new('RGBA', (width, H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image, 'RGBA')
        fill_rect(draw, 0, 0, width, H, 0, 0, 0)
        fill_rect(draw, 0, 7, width, 1, *rule_color)
        away_x, home_x, logo_y = 1, width - LOGO_SZ - 1, H - LOGO_SZ - 1
        for side, x, logo, color in (('away', away_x, away_logo, game['ac']), ('home', home_x, home_logo, game['hc'])):
            if logo:
                paste_team_logo(image, logo, (int(x), int(logo_y)), outline_mode=LogoOutlineMode.SCROLL)
            else:
                draw_missing_team_badge(image, (x, logo_y), LOGO_SZ, color,
                                        game.get(f'{side}_abbr') or game.get(side, ''))
        if game['sport'].lower() in {'ncf_fbs', 'ncf_fcs'}:
            for rank, logo_x, right_aligned in ((game.get('away_rank'), away_x, False), (game.get('home_rank'), home_x, True)):
                label = str(rank or '').strip()
                if not label:
                    continue
                rank_x = logo_x + LOGO_SZ - pf_w(label) - 1 if right_aligned else logo_x + 1
                rank_y = logo_y + LOGO_SZ - 6
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    pf_text(draw, label, rank_x + dx, rank_y + dy, 0, 0, 0)
                pf_text(draw, label, rank_x, rank_y, *FOOTBALL_RANK_COLOR)
        return image

    @staticmethod
    def _draw_header_text(img, card_w, text):
        """Draw the status header with a dark one-pixel drop shadow."""
        label = str(text or '')[:12].upper()
        if not label:
            return
        d = ImageDraw.Draw(img, 'RGBA')
        tx = max(1, (card_w - len(label) * 5) // 2)
        _draw_status_glyphs(d, tx + 1, 2, label, (8, 8, 8, 180))
        _draw_status_glyphs(d, tx, 1, label, (*STATUS_TEXT, 255))

    def _get_logo(self, url, rendering=None):
        """Return one prepared logo from the injected source."""
        return get_prepared_team_logo(self._logos, str(url) if url else None, self.LOGO_SIZE, rendering)


class _CardLayout:
    """Hold the logo and content-zone positions for one card width."""

    def __init__(self, width):
        self.width = width
        self.away_logo_x = 1
        self.home_logo_x = width - LOGO_SZ - 1
        left = self.away_logo_x + LOGO_SZ + LOGO_PAD
        right = self.home_logo_x - LOGO_PAD
        self.center = (left + right) // 2
        self.center_x = (left + right) / 2.0

    def logo_center(self, side):
        return (self.home_logo_x if side == 'home' else self.away_logo_x) + LOGO_SZ // 2
