"""Stadium-style game card renderer (Python port of ticker_playground.html)."""

import io
import re

import requests
from PIL import Image, ImageDraw, ImageStat, ImageFilter, ImageChops, ImageEnhance

from .fonts import HYBRID_FONT_MAP

# ── Canvas constants ──────────────────────────────────────────────────────────
H = 32          # card height, always 32px (LED panel height)
LOGO_SZ = 22    # logo square size in pixels
LOGO_PAD = 2    # gap between logo edge and center content zone
ZONE = LOGO_SZ + LOGO_PAD  # space each side takes = 24px

# ── 3×5 pixel font ────────────────────────────────────────────────────────────
PF = {
    '0':[[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    '1':[[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    '2':[[1,1,1],[0,0,1],[1,1,1],[1,0,0],[1,1,1]],
    '3':[[1,1,1],[0,0,1],[0,1,1],[0,0,1],[1,1,1]],
    '4':[[1,0,1],[1,0,1],[1,1,1],[0,0,1],[0,0,1]],
    '5':[[1,1,1],[1,0,0],[1,1,1],[0,0,1],[1,1,1]],
    '6':[[1,1,1],[1,0,0],[1,1,1],[1,0,1],[1,1,1]],
    '7':[[1,1,1],[0,0,1],[0,1,0],[0,1,0],[0,1,0]],
    '8':[[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,1,1]],
    '9':[[1,1,1],[1,0,1],[1,1,1],[0,0,1],[1,1,1]],
    'A':[[0,1,0],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'B':[[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,1,0]],
    'C':[[0,1,1],[1,0,0],[1,0,0],[1,0,0],[0,1,1]],
    'D':[[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]],
    'E':[[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,1,1]],
    'F':[[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,0,0]],
    'G':[[0,1,1],[1,0,0],[1,0,1],[1,0,1],[0,1,1]],
    'H':[[1,0,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'I':[[1,1,1],[0,1,0],[0,1,0],[0,1,0],[1,1,1]],
    'J':[[0,0,1],[0,0,1],[0,0,1],[1,0,1],[0,1,1]],
    'K':[[1,0,1],[1,1,0],[1,0,0],[1,1,0],[1,0,1]],
    'L':[[1,0,0],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    'M':[[1,0,1],[1,1,1],[1,0,1],[1,0,1],[1,0,1]],
    'N':[[1,0,1],[1,1,1],[1,1,1],[1,0,1],[1,0,1]],
    'O':[[0,1,0],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'P':[[1,1,0],[1,0,1],[1,1,0],[1,0,0],[1,0,0]],
    'Q':[[0,1,0],[1,0,1],[1,0,1],[1,1,1],[0,1,1]],
    'R':[[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    'S':[[0,1,1],[1,0,0],[0,1,0],[0,0,1],[1,1,0]],
    'T':[[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    'U':[[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,1]],
    'V':[[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'W':[[1,0,1],[1,0,1],[1,0,1],[1,1,1],[1,0,1]],
    'X':[[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    'Y':[[1,0,1],[1,0,1],[0,1,0],[0,1,0],[0,1,0]],
    'Z':[[1,1,1],[0,0,1],[0,1,0],[1,0,0],[1,1,1]],
    '-':[[0,0,0],[0,0,0],[1,1,1],[0,0,0],[0,0,0]],
    ':':[[0,0,0],[0,1,0],[0,0,0],[0,1,0],[0,0,0]],
    '.':[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,1,0]],
    "'":[[0,1,0],[0,1,0],[0,0,0],[0,0,0],[0,0,0]],
    '/':[[0,0,1],[0,0,1],[0,1,0],[1,0,0],[1,0,0]],
    '+':[[0,0,0],[0,1,0],[1,1,1],[0,1,0],[0,0,0]],
    '&':[[0,1,0],[1,0,1],[0,1,0],[1,0,1],[0,1,1]],
    '#':[[1,0,1],[1,1,1],[1,0,1],[1,1,1],[1,0,1]],
    '▲':[[0,1,0],[1,1,1],[1,1,1],[0,0,0],[0,0,0]],
    '▼':[[0,0,0],[0,0,0],[1,1,1],[1,1,1],[0,1,0]],
    ' ':[[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]],
}

# ── Low-level drawing helpers ─────────────────────────────────────────────────

def _clamp(v): return max(0, min(255, int(v)))

def fi(d, x, y, w, h, r, g, b, a=255):
    """Fill integer rectangle."""
    if w <= 0 or h <= 0:
        return
    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=(_clamp(r), _clamp(g), _clamp(b), _clamp(a)))

def li(c, f=0.4):
    """Lighten colour tuple."""
    return tuple(min(255, int(v + (255 - v) * f)) for v in c)

def da(c, f=0.5):
    """Darken colour tuple."""
    return tuple(int(v * (1 - f)) for v in c)

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
    """Draw one pixel-font glyph; returns width consumed."""
    bm = PF.get(ch.upper(), PF[' '])
    col = (_clamp(r), _clamp(g), _clamp(b), 255)
    for row in range(5):
        for col_idx in range(3):
            if bm[row][col_idx]:
                fx, fy = x + col_idx * sc, y + row * sc
                d.rectangle([fx, fy, fx + sc - 1, fy + sc - 1], fill=col)
    return 4 * sc

def pf_text(d, text, x, y, r, g, b, sc=1):
    """Draw pixel-font string; returns total width."""
    cx = x
    for ch in str(text).upper():
        cx += pf_char(d, ch, cx, y, r, g, b, sc)
    return cx - x

def pf_w(text, sc=1):
    """Width of pixel-font string."""
    return len(str(text)) * 4 * sc


def draw_hybrid_text(draw, x, y, text_str, color):
    """Old renderer style from flights.py: 4px glyph width, 6 rows high."""
    text_str = str(text_str).upper()
    x_cursor = x
    for char in text_str:
        bitmap = HYBRID_FONT_MAP.get(char, HYBRID_FONT_MAP.get(' ', [0x0] * 6))
        for r, row_byte in enumerate(bitmap):
            if row_byte & 0x8:
                draw.point((x_cursor + 0, y + r), fill=color)
            if row_byte & 0x4:
                draw.point((x_cursor + 1, y + r), fill=color)
            if row_byte & 0x2:
                draw.point((x_cursor + 2, y + r), fill=color)
            if row_byte & 0x1:
                draw.point((x_cursor + 3, y + r), fill=color)
        x_cursor += 5
    return x_cursor - x


# ── Sprite helpers ────────────────────────────────────────────────────────────

def draw_football(d, cx, cy):
    """Tiny football icon (7×3 px)."""
    brown = (139, 69, 19, 255)
    fi(d, cx - 2, cy,     5, 1, *brown[:3])
    fi(d, cx - 3, cy + 1, 7, 1, *brown[:3])
    fi(d, cx - 2, cy + 2, 5, 1, *brown[:3])
    fi(d, cx - 1, cy + 1, 1, 1, 255, 255, 255)
    fi(d, cx,     cy + 1, 1, 1, 255, 255, 255)
    fi(d, cx + 1, cy + 1, 1, 1, 255, 255, 255)

def draw_base_diamond(d, cx, ty, on1, on2, on3):
    """
    Baseball base diamond.
    cx=center x, ty=top y.
    on2=2B(top), on1=1B(right), on3=3B(left).
    """
    bases = [
        (cx,     ty,     on2),   # 2B top
        (cx + 4, ty + 4, on1),   # 1B right
        (cx - 4, ty + 4, on3),   # 3B left
    ]
    for bx, by, on in bases:
        c = (255, 200, 0) if on else (55, 55, 55)
        fi(d, bx - 2, by,     5, 1, *c)
        fi(d, bx - 1, by + 1, 3, 1, *c)
        fi(d, bx,     by + 2, 1, 1, *c)
        fi(d, bx - 2, by,     1, 1, *c)
        fi(d, bx + 2, by,     1, 1, *c)

def draw_shootout_dot(d, x, y, result, size=5, stride=7):
    """
    Draw one shootout indicator at pixel position (x, y).
    result: 'goal' | 'miss' | 'pending'
    size:   dot pixel size (5 for NHL, 3 for soccer)
    """
    if result == 'goal':
        fi(d, x, y, size, size, 50, 200, 70)
    elif result == 'miss':
        # Red X scaled to size
        if size >= 4:
            fi(d, x,          y,          2, 2, 220, 55, 55)
            fi(d, x + size-2, y,          2, 2, 220, 55, 55)
            fi(d, x + 1,      y + size//2, size - 2, 1, 220, 55, 55)
            fi(d, x,          y + size-2, 2, 2, 220, 55, 55)
            fi(d, x + size-2, y + size-2, 2, 2, 220, 55, 55)
        else:  # 3px version
            fi(d, x,     y,     2, 1, 220, 55, 55)
            fi(d, x + 1, y + 1, 1, 1, 220, 55, 55)
            fi(d, x,     y + 2, 2, 1, 220, 55, 55)
            fi(d, x + 2, y,     1, 1, 220, 55, 55)
            fi(d, x + 2, y + 2, 1, 1, 220, 55, 55)
    else:
        # Pending: grey filled square with dark inner
        fi(d, x, y, size, size, 55, 55, 55)
        fi(d, x + 1, y + 1, size - 2, size - 2, 10, 10, 14)

def draw_so_column(d, x, y, results, vertical=True, size=5, stride=7, max_show=5):
    """Draw a column (or row) of shootout dots, always showing at least 3 slots."""
    n_show = min(max(len(results), 3), max_show)
    for i in range(n_show):
        r = results[i] if i < len(results) else 'pending'
        dx = x if vertical else x + i * stride
        dy = y + i * stride if vertical else y
        draw_shootout_dot(d, dx, dy, r, size=size, stride=stride)


# ── Logo loading ──────────────────────────────────────────────────────────────

def _download_logo(url, size=(22, 22)):
    """Fetch and resize a logo from URL; returns RGBA PIL Image or None."""
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            img = Image.open(io.BytesIO(r.content)).convert('RGBA')
            img.thumbnail(size, Image.Resampling.LANCZOS)
            out = Image.new('RGBA', size, (0, 0, 0, 0))
            out.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
            return _enhance_logo_visibility(out)
    except Exception:
        pass
    return None


def _enhance_logo_visibility(img):
    """Only outline logos that are overwhelmingly dark."""
    try:
        if not img or img.mode != 'RGBA':
            return img

        rgba = img.copy()
        alpha = rgba.split()[3]
        px = list(rgba.getdata())

        # Only sample fully opaque pixels to ignore dark anti-aliased edges
        core_pixels = [p for p in px if p[3] > 200]
        if not core_pixels:
            core_pixels = [p for p in px if p[3] > 20]
            if not core_pixels:
                return rgba

        dark = 0
        for r, g, b, _ in core_pixels:
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if lum < 40:
                dark += 1

        dark_ratio = dark / len(core_pixels)

        # If the logo isn't at least 92% very dark, skip the outline.
        if dark_ratio < 0.92:
            return rgba

        edge = alpha.filter(ImageFilter.MaxFilter(3))
        ring = ImageChops.subtract(edge, alpha)
        ring_layer = Image.new('RGBA', rgba.size, (245, 245, 245, 230))
        outlined = Image.new('RGBA', rgba.size, (0, 0, 0, 0))
        outlined.paste(ring_layer, (0, 0), ring)
        outlined.alpha_composite(rgba)
        return outlined
    except Exception:
        return img

def _fallback_logo(color, size=(22, 22)):
    """Coloured square with highlight border when no real logo available."""
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r, g, b = color
    dc = da(color)
    d.rectangle([0, 0, size[0]-1, size[1]-1], fill=(*dc, 255))
    d.rectangle([2, 2, size[0]-3, size[1]-3], fill=(*da(color, 0.1), 255))
    d.rectangle([0, 0, size[0]-1, 0], fill=(r, g, b, 255))
    d.rectangle([0, size[1]-1, size[0]-1, size[1]-1], fill=(r, g, b, 255))
    d.rectangle([0, 0, 0, size[1]-1], fill=(r, g, b, 255))
    d.rectangle([size[0]-1, 0, size[0]-1, size[1]-1], fill=(r, g, b, 255))
    li_c = li(color, 0.25)
    d.rectangle([1, 1, size[0]-2, 1], fill=(*li_c, 255))
    d.rectangle([1, 1, 1, size[1]-2], fill=(*li_c, 255))
    return img


# ── Card width calculator ─────────────────────────────────────────────────────

def calc_card_width(g):
    """
    Returns the minimum canvas width (px) so content never overlaps logos.
    Mirrors calcCardWidth() in the JS playground exactly.
    """
    sport = g.get('sport', '').lower()
    state = g.get('state', '')
    is_active = state == 'in'
    is_mlb = 'baseball' in sport or 'mlb' in sport
    is_nfl = 'football' in sport or 'nfl' in sport
    is_nhl = 'hockey'   in sport or 'nhl' in sport
    sit = g.get('situation', {}) or {}
    shootout = sit.get('shootout') or (g.get('so') if 'so' in g else None)
    is_so = bool(shootout)
    dd = sit.get('downDist', '') or g.get('dd', '') or ''

    a_score = str(g.get('away_score', g.get('as', 0)))
    h_score = str(g.get('home_score', g.get('hs', 0)))
    status = str(g.get('status', ''))

    a_score_w = pf_w(a_score, sc=2)
    h_score_w = pf_w(h_score, sc=2)
    score_w = a_score_w + pf_w('-', sc=2) + h_score_w
    center = score_w

    if is_mlb and is_active:
        center = max(center, score_w + 2)
    else:
        center = max(center, pf_w(status))

    if is_nfl and is_active and dd:
        center = max(center, pf_w(dd))

    if (is_nhl or sport == 'soccer') and is_so:
        center = max(center, score_w + 14)

    total = ZONE + 4 + center + 4 + ZONE
    return min(160, int((total + 1) // 2 * 2))


# ── Main renderer ─────────────────────────────────────────────────────────────

class StadiumRenderer:
    """
    Renders a single game card in the Stadium style.

    Parameters
    ----------
    logo_cache : dict
        Shared logo cache dict (same one TickerStreamer uses).
        Values are PIL RGBA images already sized to (LOGO_SZ, LOGO_SZ).
        If the logo is not in cache, this renderer will try to fetch it.
    """

    LOGO_SIZE = (LOGO_SZ, LOGO_SZ)

    def __init__(self, logo_cache=None):
        self._cache = logo_cache if logo_cache is not None else {}

    def _get_logo(self, url):
        """Return RGBA PIL image at LOGO_SIZE, or None."""
        if not url:
            return None
        key = f"{url}_{LOGO_SZ}x{LOGO_SZ}"
        if key not in self._cache:
            img = _download_logo(url, self.LOGO_SIZE)
            if img:
                self._cache[key] = img
        return self._cache.get(key)

    def _paste_logo(self, img, logo, x, y):
        """Paste RGBA logo onto img at (x, y), using alpha as mask."""
        if logo:
            img.paste(logo, (int(x), int(y)), logo)

    def render(self, g):
        """
        Render game dict g.  Returns (PIL.Image RGBA, card_width_px).

        Accepts both ticker_streamer field names (home_score, away_score, etc.)
        and compact playground field names (hs, as, ac, hc).
        """
        g = self._normalise(g)

        CW = calc_card_width(g)
        img = Image.new('RGBA', (CW, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img, 'RGBA')

        sport = g['sport'].lower()
        is_active = g['state'] == 'in'
        is_mlb  = 'baseball' in sport or 'mlb'    in sport
        is_nfl  = 'football' in sport or 'nfl'    in sport
        is_nhl  = 'hockey'   in sport or 'nhl'    in sport
        is_soc  = 'soccer'   in sport
        is_march = 'march' in sport
        sit     = g.get('sit', {})
        shootout = sit.get('shootout')
        is_so   = bool(shootout)

        ac = g['ac']
        hc = g['hc']
        a_score = str(g['as'])
        h_score = str(g['hs'])
        status = g['status']

        def _side_from_value(val):
            if val is None:
                return None
            s = str(val).strip().upper()
            if not s:
                return None
            home_tokens = {
                str(g.get('home', '')).strip().upper(),
                str(g.get('home_abbr', '')).strip().upper(),
                str(g.get('home_id', '')).strip().upper(),
                'HOME', 'H',
            }
            away_tokens = {
                str(g.get('away', '')).strip().upper(),
                str(g.get('away_abbr', '')).strip().upper(),
                str(g.get('away_id', '')).strip().upper(),
                'AWAY', 'A',
            }
            home_tokens.discard('')
            away_tokens.discard('')
            if s in home_tokens:
                return 'home'
            if s in away_tokens:
                return 'away'
            return None

        # ── Background + header line ──────────────────────────────────────────
        fi(d, 0, 0, CW, H,  0, 0, 0)
        fi(d, 0, 7, CW, 1,  55, 76, 130)

        st = status[:12]
        if not (is_mlb and is_active):
            self._draw_header_text(img, CW, st)
            fi(d, 0, 7, CW, 1, 55, 76, 130)

        # ── Logos ─────────────────────────────────────────────────────────────
        a_logo_x = 1
        h_logo_x = CW - LOGO_SZ - 1
        logo_y   = H - LOGO_SZ - 1

        a_logo = self._get_logo(g.get('away_logo'))
        h_logo = self._get_logo(g.get('home_logo'))

        if a_logo:
            self._paste_logo(img, a_logo, a_logo_x, logo_y)
        else:
            self._draw_fallback_logo(d, a_logo_x, logo_y, ac)

        if h_logo:
            self._paste_logo(img, h_logo, h_logo_x, logo_y)
        else:
            self._draw_fallback_logo(d, h_logo_x, logo_y, hc)

        # ── Content safe zone ─────────────────────────────────────────────────
        cL  = a_logo_x + LOGO_SZ + LOGO_PAD
        cR  = h_logo_x - LOGO_PAD
        cCX = (cL + cR) // 2
        center_x = (cL + cR) / 2.0

        # ── Score ─────────────────────────────────────────────────────────────
        if not (is_mlb and is_active):
            a_sw = pf_w(a_score, sc=2)
            h_sw = pf_w(h_score, sc=2)
            dash_sw = pf_w('-', sc=2)
            total_sw = a_sw + dash_sw + h_sw
            score_layer = Image.new('RGBA', (total_sw, 10), (0, 0, 0, 0))
            score_draw = ImageDraw.Draw(score_layer, 'RGBA')
            pf_text(score_draw, a_score, 0,                0, 255, 255, 255, sc=2)
            pf_text(score_draw, '-',     a_sw,             0, 255, 255, 255, sc=2)
            pf_text(score_draw, h_score, a_sw + dash_sw,   0, 255, 255, 255, sc=2)
            score_layer = score_layer.resize((total_sw, 11), Image.Resampling.NEAREST)
            layer_x = int(round(center_x - total_sw / 2.0))
            img.alpha_composite(score_layer, (layer_x, 9))

        # ══ NFL ══════════════════════════════════════════════════════════════
        if is_nfl and is_active:
            poss    = sit.get('possession', '') or g.get('poss', '')
            dd      = sit.get('downDist',   '') or g.get('dd',   '')
            rz      = sit.get('isRedZone',  False) or g.get('rz', False)
            poss_side = _side_from_value(poss)
            is_poss_home = poss_side == 'home'
            is_poss_away = poss_side == 'away'

            if is_poss_home or is_poss_away:
                hdr_cx = (h_logo_x + LOGO_SZ // 2 - 1) if is_poss_home \
                         else (a_logo_x + LOGO_SZ // 2 - 1)
                draw_football(d, hdr_cx, 2)

            if rz:
                d.rectangle([0, 0, CW - 1, H - 1], outline=(255, 40, 40, 153), width=1)

            if dd:
                dd_color = (235, 70, 70) if rz else (0, 200, 60)
                pf_text(d, dd, cCX - pf_w(dd) // 2, 23, *dd_color)

        # ══ NHL ══════════════════════════════════════════════════════════════
        if is_nhl and is_active and not is_so:
            poss        = sit.get('possession', '') or g.get('poss', '')
            is_pp       = sit.get('powerPlay',  False) or g.get('pp', False)
            is_en       = sit.get('emptyNet',   False) or g.get('en', False)
            en_team     = sit.get('emptyNetSide', '') or g.get('enTeam', '')
            poss_side = _side_from_value(poss)
            is_poss_home = poss_side == 'home'
            is_poss_away = poss_side == 'away'

            poss_hdr_x = (h_logo_x + LOGO_SZ // 2) if is_poss_home \
                         else (a_logo_x + LOGO_SZ // 2)

            if is_en:
                en_is_home = (poss_side == 'home')
                en_hdr_x = (h_logo_x + LOGO_SZ // 2) if en_is_home \
                           else (a_logo_x + LOGO_SZ // 2)
                pf_text(d, 'EN', en_hdr_x - pf_w('EN') // 2, 2, 255, 100, 100)
            elif is_pp and (is_poss_home or is_poss_away):
                pf_text(d, 'PP', poss_hdr_x - pf_w('PP') // 2, 2, 255, 220, 0)

        if is_nhl and is_so:
            so_a = shootout.get('away', [])
            so_h = shootout.get('home', [])
            draw_so_column(d, a_logo_x + LOGO_SZ + 2, 9, so_a,
                           vertical=True, size=5, stride=7, max_show=3)
            draw_so_column(d, h_logo_x - 7, 9, so_h,
                           vertical=True, size=5, stride=7, max_show=3)

        # ══ MLB ══════════════════════════════════════════════════════════════
        if is_mlb and is_active:
            balls   = int(sit.get('balls',   g.get('balls',   0)) or 0)
            strikes = int(sit.get('strikes', g.get('strikes', 0)) or 0)
            outs    = int(sit.get('outs',    g.get('outs',    0)) or 0)
            on1     = bool(sit.get('onFirst',  g.get('on1', False)))
            on2     = bool(sit.get('onSecond', g.get('on2', False)))
            on3     = bool(sit.get('onThird',  g.get('on3', False)))

            status_up = status.upper()
            is_top = 'TOP' in status_up or 'T ' in status_up
            if 'isTop' in g:
                is_top = bool(g['isTop'])

            fi(d, 0, 0, CW, 8, 0, 0, 0)
            fi(d, 0, 7, CW, 1, 55, 76, 130)

            inn_match = re.search(r'\d+', status)
            inn_num = inn_match.group() if inn_match else ''
            arrow_glyph = '▲' if is_top else '▼'
            arrow_w = pf_w(arrow_glyph)
            num_w = pf_w(inn_num)
            total_w = arrow_w + num_w
            hx = max(1, (CW - total_w) // 2)
            pf_text(d, arrow_glyph, hx + 1, 2, 8, 8, 8)
            pf_text(d, inn_num, hx + arrow_w + 1, 2, 8, 8, 8)
            pf_text(d, arrow_glyph, hx, 1, 255, 220, 105)
            pf_text(d, inn_num, hx + arrow_w, 1, 255, 240, 150)

            b_glyph, s_glyph = str(balls), str(strikes)
            bs_w = pf_w(b_glyph) + pf_w('-') + pf_w(s_glyph)
            batting_side = _side_from_value(sit.get('possession', '') or g.get('poss', ''))
            if batting_side is None:
                batting_side = 'away' if is_top else 'home'
            bs_hdr_x = (h_logo_x + LOGO_SZ // 2 - bs_w // 2) if batting_side == 'home' \
                       else (a_logo_x + LOGO_SZ // 2 - bs_w // 2)
            bsx = bs_hdr_x
            bsx += pf_text(d, b_glyph, bsx, 2,  60, 200,  60)
            bsx += pf_text(d, '-',     bsx, 2, 160, 160, 160)
            pf_text(d,     s_glyph, bsx, 2, 255, 140,  40)

            a_sw   = pf_w(a_score, sc=2)
            h_sw   = pf_w(h_score, sc=2)
            dash_sw = pf_w('-', sc=2)
            total_sw = a_sw + dash_sw + h_sw
            score_x = int(round(center_x - total_sw / 2.0))
            dash_x = score_x + a_sw
            pf_text(d, a_score, score_x,          8, 255, 255, 255, sc=2)
            pf_text(d, '-',     dash_x,           8, 255, 255, 255, sc=2)
            pf_text(d, h_score, dash_x + dash_sw, 8, 255, 255, 255, sc=2)

            draw_base_diamond(d, dash_x + 3, 19, on1, on2, on3)

            out_y = 28
            out_total_w = 3 * 5 - 1
            ox = (dash_x + 3) - out_total_w // 2
            for i in range(3):
                col = (210, 70, 70) if i < outs else (45, 45, 45)
                fi(d, ox + i * 5, out_y, 4, 3, *col)

        # ══ Soccer shootout ══════════════════════════════════════════════════
        if is_soc and is_so:
            so_a = shootout.get('away', [])
            so_h = shootout.get('home', [])
            self._draw_soccer_so_col(d, a_logo_x + LOGO_SZ + 2, 8, so_a)
            self._draw_soccer_so_col(d, h_logo_x - 5, 8, so_h)

        # ══ March Madness ════════════════════════════════════════════════════
        if is_march:
            seed_a = g.get('seed_a', g.get('away_seed', ''))
            seed_h = g.get('seed_h', g.get('home_seed', ''))
            won_a  = g['state'] == 'post' and g['as'] > g['hs']
            won_h  = g['state'] == 'post' and g['hs'] > g['as']
            sa, sh = str(seed_a), str(seed_h)
            a_col = (100, 210, 100) if won_a else (170, 70, 70) if won_h else (66, 117, 199)
            h_col = (100, 210, 100) if won_h else (170, 70, 70) if won_a else (66, 117, 199)
            pf_text(d, sa, 2,                    2, *a_col)
            pf_text(d, sh, CW - pf_w(sh) - 2,   2, *h_col)

        return img, CW

    def _draw_header_text(self, img, card_w, text):
        """Draw header with the hybrid bitmap renderer style."""
        label = str(text or '')[:9].upper()
        if not label:
            return
        d = ImageDraw.Draw(img, 'RGBA')
        tw = len(label) * 5
        tx = max(1, (card_w - tw) // 2)
        ty = 1
        draw_hybrid_text(d, tx + 1, ty + 1, label, (8, 8, 8, 180))
        draw_hybrid_text(d, tx, ty, label, (255, 240, 150, 255))

    def _draw_soccer_so_col(self, d, x, y, results):
        n_show = 5
        for i in range(n_show):
            r = results[i] if i < len(results) else 'pending'
            dy = y + i * 5
            if r == 'goal':
                fi(d, x, dy, 3, 3, 50, 200, 70)
            elif r == 'miss':
                fi(d, x, dy, 3, 3, 220, 55, 55)
            else:
                fi(d, x, dy, 3, 3, 80, 80, 80)

    def _draw_fallback_logo(self, d, x, y, color):
        r, g, b = color
        dc = da(color)
        fi(d, x, y, LOGO_SZ, LOGO_SZ, *dc)
        fi(d, x + 2, y + 2, LOGO_SZ - 4, LOGO_SZ - 4, *da(color, 0.1))
        fi(d, x, y, LOGO_SZ, 1, r, g, b)
        fi(d, x, y + LOGO_SZ - 1, LOGO_SZ, 1, r, g, b)
        fi(d, x, y, 1, LOGO_SZ, r, g, b)
        fi(d, x + LOGO_SZ - 1, y, 1, LOGO_SZ, r, g, b)
        lc = li(color, 0.25)
        fi(d, x + 1, y + 1, LOGO_SZ - 2, 1, *lc)
        fi(d, x + 1, y + 1, 1, LOGO_SZ - 2, *lc)

    @staticmethod
    def _normalise(g):
        """Accept both ticker_streamer field names and compact playground names."""
        out = dict(g)

        if 'as' not in out:
            out['as'] = int(out.get('away_score', 0) or 0)
        if 'hs' not in out:
            out['hs'] = int(out.get('home_score', 0) or 0)
        else:
            out['as'] = int(out['as'])
            out['hs'] = int(out['hs'])

        if 'away' not in out:
            out['away'] = out.get('away_abbr', '???')
        if 'home' not in out:
            out['home'] = out.get('home_abbr', '???')

        if 'sport' not in out:
            out['sport'] = 'unknown'

        def _col(key_hex, key_rgb, fallback):
            if key_rgb in out and isinstance(out[key_rgb], (list, tuple)):
                return tuple(int(v) for v in out[key_rgb][:3])
            return hex_to_rgb(out.get(key_hex, '')) or fallback

        out['ac'] = _col('away_color', 'ac', (80, 80, 80))
        out['hc'] = _col('home_color', 'hc', (80, 80, 80))

        if 'state' not in out:
            s = str(out.get('game_state', out.get('status', ''))).lower()
            if 'final' in s or 'post' in s:
                out['state'] = 'post'
            elif any(x in s for x in ('q', 'p', 'h', 'inning', 'top', 'bot', "'", 'live')):
                out['state'] = 'in'
            else:
                out['state'] = 'pre'

        sit = out.get('situation', {}) or {}
        out['sit'] = sit

        so = sit.get('shootout')
        if so and isinstance(so, dict):
            out.setdefault('so', so)

        return out


# ── Convenience: render strip of all games ────────────────────────────────────

def build_strip(games, logo_cache=None, repeat=1):
    """
    Render a horizontal strip of game cards (optionally repeated for looping).
    Returns a single PIL RGBA image.
    """
    renderer = StadiumRenderer(logo_cache=logo_cache)
    cards = []
    for g in games:
        img, _ = renderer.render(g)
        cards.append(img)

    if not cards:
        return Image.new('RGBA', (1, H), (0, 0, 0, 255))

    all_cards = cards * repeat
    total_w = sum(c.width for c in all_cards)
    strip = Image.new('RGBA', (total_w, H), (0, 0, 0, 255))
    x = 0
    for c in all_cards:
        strip.paste(c, (x, 0), c)
        x += c.width
    return strip
