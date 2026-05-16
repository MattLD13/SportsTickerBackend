"""Server-side LED strip renderer — serves game frames as a PNG strip."""

import datetime
import io
import os
import sys
import threading

from flask import request, Response
from PIL import Image, ImageDraw
from ..routes_runtime import app
from ..core import (
    state, normalize_mode,
    NON_SCOREBOARD_TYPES, HIDDEN_STATUS_KEYWORDS, _ACTIVE_STATES,
)
from ..workers import fetcher

# ticker_controller lives at the repo root
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_renderer = None
_renderer_lock = threading.Lock()

PANEL_W = 384
PANEL_H = 32
SEP_W   = 2
SEP_COL = (25, 25, 25, 255)

_SPORTS_TYPES = {
    'nfl', 'nba', 'nhl', 'mlb', 'ncf_fbs', 'ncf_fcs',
    'soccer_epl', 'soccer_fa_cup', 'soccer_champ', 'soccer_champions_league',
    'soccer_europa_league', 'soccer_mls', 'soccer_wc', 'golf', 'masters',
}


def _get_renderer():
    global _renderer
    if _renderer is not None:
        return _renderer
    with _renderer_lock:
        if _renderer is not None:
            return _renderer
        try:
            from ticker_controller.stadium import StadiumRenderer
            _renderer = StadiumRenderer()
            print("[preview] StadiumRenderer ready")
        except Exception as e:
            print(f"[preview] StadiumRenderer init failed: {e}")
            _renderer = False
    return _renderer


def _pf(draw, text, x, y, color, sc=2):
    """Draw pixel-font string using the 3×5 PF glyph dict from stadium.py."""
    try:
        from ticker_controller.stadium import PF
    except Exception:
        return x
    r, g, b = color
    cx = x
    for ch in str(text).upper():
        bm = PF.get(ch, PF.get(' ', [[0]*3]*5))
        for row in range(5):
            for ci in range(3):
                if bm[row][ci]:
                    fx, fy = cx + ci * sc, y + row * sc
                    draw.rectangle([fx, fy, fx + sc - 1, fy + sc - 1], fill=(r, g, b, 255))
        cx += 4 * sc
    return cx


def _pw(text, sc=2):
    return len(str(text)) * 4 * sc


def _render_non_game(g: dict) -> Image.Image:
    """Render a non-sports item as a PANEL_W×PANEL_H RGBA PIL image."""
    itype = g.get('type', '').lower()
    sport = g.get('sport', '').lower()

    img  = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    if itype == 'weather':
        city  = (g.get('city') or g.get('location') or 'WEATHER').upper()[:14]
        temp  = g.get('temp')
        cond  = (g.get('condition') or g.get('description') or '').upper()[:14]
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(10, 40, 90, 255))
        _pf(draw, city,  4, 6,  (100, 200, 255), sc=2)
        temp_str = f"{int(round(temp))}F" if temp is not None else '--F'
        x2 = _pf(draw, temp_str, 4, 20, (255, 255, 255), sc=2)
        _pf(draw, cond, x2 + 6, 20, (80, 170, 255), sc=2)

    elif itype == 'stock_ticker':
        symbol = (g.get('symbol') or '???').upper()[:6]
        price  = g.get('price')
        pct    = g.get('change_pct')
        up     = float(pct or 0) >= 0
        price_str = f"${float(price):.2f}" if price is not None else '$--'
        pct_str   = ('+' if up else '') + f"{float(pct):.1f}%" if pct is not None else ''
        clr_pct   = (50, 220, 100) if up else (255, 70, 70)
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=((0, 80, 40) if up else (80, 0, 0)))
        _pf(draw, symbol,    4, 6,  (180, 255, 180) if up else (255, 180, 180), sc=2)
        x2 = _pf(draw, price_str, 4, 20, (255, 255, 255), sc=2)
        arrow = '▲' if up else '▼'
        _pf(draw, arrow + pct_str, x2 + 6, 20, clr_pct, sc=2)

    elif itype == 'music':
        artist = (g.get('artist') or g.get('artist_name') or 'ARTIST').upper()[:18]
        title  = (g.get('title')  or g.get('song') or '').upper()[:22]
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(60, 0, 100, 255))
        _pf(draw, artist, 4, 6,  (200, 100, 255), sc=2)
        _pf(draw, title,  4, 20, (220, 180, 255), sc=2)

    elif itype == 'clock':
        now      = datetime.datetime.now()
        time_str = now.strftime('%I:%M:%S').lstrip('0') or '12:00:00'
        date_str = now.strftime('%a').upper() + ' ' + now.strftime('%b %d').upper()
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(20, 20, 20, 255))
        tw = _pw(time_str, sc=4)
        _pf(draw, time_str, max(4, (PANEL_W - tw) // 2), 5, (180, 180, 180), sc=4)
        _pf(draw, date_str, 4, 27, (70, 70, 70), sc=1)

    elif itype == 'flight_visitor':
        flight = (g.get('flight') or g.get('id') or '').upper()
        origin = (g.get('origin') or '').upper()
        dest   = (g.get('dest')   or '').upper()
        status = (g.get('status') or '').upper()[:10]
        guest  = (g.get('guest_name') or '').upper()[:12]
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(0, 50, 70, 255))
        x2 = _pf(draw, flight, 4, 6, (0, 220, 200), sc=2)
        if origin and dest:
            _pf(draw, origin + '>' + dest, x2 + 6, 6, (160, 160, 160), sc=2)
        lbl = guest if guest else status
        x2 = _pf(draw, lbl, 4, 20, (100, 200, 180), sc=2)
        if guest and status:
            _pf(draw, status, x2 + 6, 20, (200, 200, 80), sc=2)

    elif sport == 'flight' or itype == 'flight':
        airline = (g.get('airline') or '').upper()[:4]
        flnum   = (g.get('flight_number') or g.get('flight') or '').upper()[:8]
        dest    = (g.get('destination') or g.get('dest') or '').upper()[:12]
        status  = (g.get('status') or '').upper()[:12]
        gate    = (g.get('gate') or '').upper()
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(0, 50, 70, 255))
        x2 = _pf(draw, airline + flnum, 4, 6, (0, 220, 200), sc=2)
        _pf(draw, dest, x2 + 6, 6, (160, 160, 160), sc=2)
        clr = (50, 220, 100) if ('ON TIME' in status or 'ONTIME' in status) else \
              (255, 100, 50) if ('DELAY' in status or 'CANCEL' in status) else (180, 180, 80)
        x2 = _pf(draw, status, 4, 20, clr, sc=2)
        if gate:
            gw = _pw('GATE ' + gate, sc=2)
            _pf(draw, 'GATE ' + gate, PANEL_W - gw - 4, 20, (140, 140, 140), sc=2)

    else:
        label = (g.get('label') or itype or 'ITEM').upper()[:20]
        _pf(draw, label, 4, 13, (100, 100, 100), sc=2)

    return img


def _is_sports_game(g: dict) -> bool:
    itype = (g.get('type') or '').lower()
    sport = (g.get('sport') or '').lower()
    if itype in ('weather', 'stock_ticker', 'music', 'clock', 'flight_visitor'):
        return False
    if sport == 'flight' or itype == 'flight':
        return False
    # If it has home/away teams it's a sports game
    if g.get('home') or g.get('away') or g.get('home_name') or g.get('away_name'):
        return True
    if sport in _SPORTS_TYPES:
        return True
    return False


def _sport_for_preview(sport_name: str) -> str:
    sport_norm = str(sport_name or '').lower()
    return 'mlb' if sport_norm == 'wbc' else sport_norm


def _filter_preview_games(games: list, mode: str) -> list:
    """Apply the same visible-mode filtering the web dashboard detail panel uses."""
    active_sports = state.get('active_sports', {})
    saved_teams = set(state.get('my_teams', []))
    collision_abbrs = {'LV'}
    visible = []

    for g in games:
        game = g.copy()
        sport = _sport_for_preview(game.get('sport', ''))
        g_type = game.get('type', '')
        game['sport'] = sport
        should_show = True

        if mode in ('sports', 'live', 'my_teams'):
            should_show = active_sports.get(sport, True)

        if mode == 'my_teams':
            h_ab = str(game.get('home_abbr', '')).upper()
            a_ab = str(game.get('away_abbr', '')).upper()
            in_home = f"{sport}:{h_ab}" in saved_teams or (h_ab in saved_teams and h_ab not in collision_abbrs)
            in_away = f"{sport}:{a_ab}" in saved_teams or (a_ab in saved_teams and a_ab not in collision_abbrs)
            should_show = should_show and (in_home or in_away)
        elif mode == 'live':
            should_show = should_show and game.get('state') in _ACTIVE_STATES
        elif mode == 'sports':
            if g_type in NON_SCOREBOARD_TYPES:
                should_show = False
            status_lower = str(game.get('status', '')).lower()
            if any(k in status_lower for k in HIDDEN_STATUS_KEYWORDS):
                should_show = False
        elif mode == 'soccer_full':
            should_show = str(sport).startswith('soccer_')
        elif mode == 'masters':
            should_show = g_type == 'masters' or sport == 'masters'

        if should_show:
            game['is_shown'] = True
            visible.append(game)

    return visible


def _empty_png():
    img = Image.new('RGB', (PANEL_W, PANEL_H), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    r = Response(buf.getvalue(), mimetype='image/png')
    r.headers['Cache-Control'] = 'no-store'
    r.headers['X-Strip-Width'] = str(PANEL_W)
    return r


@app.route('/api/preview/strip.png')
def preview_strip():
    mode_str = request.args.get('mode', state.get('mode', 'sports'))
    try:
        current_mode = normalize_mode(mode_str)
        games = fetcher.get_mode_snapshot(current_mode, 0)[:30]
    except Exception:
        games = []

    games = _filter_preview_games(games, current_mode)

    renderer = _get_renderer()

    if not games:
        return _empty_png()

    cards = []
    for g in games:
        try:
            if _is_sports_game(g) and renderer:
                result = renderer.render(g)
                card = result[0] if isinstance(result, tuple) else result
                if card is None:
                    continue
            else:
                card = _render_non_game(g)

            if card.mode != 'RGBA':
                card = card.convert('RGBA')
            cards.append(card)
        except Exception as e:
            print(f"[preview] render error for {g.get('id','?')}: {e}")

    if not cards:
        return _empty_png()

    total_w = sum(c.width for c in cards) + (len(cards) - 1) * SEP_W
    strip   = Image.new('RGBA', (total_w, PANEL_H), (0, 0, 0, 255))
    sd      = ImageDraw.Draw(strip)
    x = 0
    for i, card in enumerate(cards):
        if i > 0:
            sd.line([(x, 0), (x, PANEL_H - 1)], fill=SEP_COL)
            x += SEP_W
        strip.paste(card, (x, 0), card)
        x += card.width

    img = strip.convert('RGB')
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    r = Response(buf.getvalue(), mimetype='image/png')
    r.headers['Cache-Control'] = 'no-store'
    r.headers['X-Strip-Width'] = str(img.width)
    return r
