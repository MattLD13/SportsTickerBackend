"""Server-side LED strip renderer — serves game frames as a PNG strip."""

import datetime
import io
import os
import sys
import threading
import time

from flask import request, Response
from PIL import Image, ImageDraw
from ..routes_runtime import app
from ..core import (
    state, normalize_mode,
    NON_SCOREBOARD_TYPES, HIDDEN_STATUS_KEYWORDS, _ACTIVE_STATES,
)
from ..workers import fetcher
from ticker_controller.controller import TickerStreamer as _PreviewTickerStreamer
from ticker_controller.fonts import load_display_font, load_monospace_font

# ticker_controller lives at the repo root
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_renderer = None
_preview_renderer = None
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

_STATIC_PREVIEW_MODES = {'music', 'weather', 'clock', 'flights', 'flight_tracker', 'golf', 'masters', 'sports_full'}


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


def _get_preview_renderer():
    global _preview_renderer
    if _preview_renderer is not None:
        return _preview_renderer
    with _renderer_lock:
        if _preview_renderer is not None:
            return _preview_renderer
        try:
            renderer = _PreviewTickerStreamer.__new__(_PreviewTickerStreamer)
            renderer.logo_cache = {}
            renderer.stadium = _get_renderer()
            renderer.font = load_monospace_font(10, bold=True)
            renderer.medium_font = load_monospace_font(12, bold=True)
            renderer.big_font = load_monospace_font(14, bold=True)
            renderer.huge_font = load_display_font(20, bold=True)
            renderer.clock_giant = load_display_font(28, bold=True)
            renderer.tiny = load_monospace_font(9)
            renderer.tiny_small = load_monospace_font(8)
            renderer.micro = load_monospace_font(7)
            renderer.nano = load_monospace_font(5)
            renderer.score_default_font = load_display_font(12, bold=True)
            renderer.brightness = 1.0
            renderer.inverted = False
            renderer.VINYL_SIZE = 51
            renderer.COVER_SIZE = 42
            renderer.vinyl_mask = Image.new('L', (renderer.COVER_SIZE, renderer.COVER_SIZE), 0)
            ImageDraw.Draw(renderer.vinyl_mask).ellipse((0, 0, renderer.COVER_SIZE, renderer.COVER_SIZE), fill=255)
            renderer.scratch_layer = Image.new('RGBA', (renderer.VINYL_SIZE, renderer.VINYL_SIZE), (0, 0, 0, 0))
            renderer._init_vinyl_scratch()
            renderer.vinyl_rotation = 0.0
            renderer.text_scroll_pos = 0.0
            renderer.last_frame_time = time.time()
            renderer.dominant_color = (29, 185, 84)
            renderer.spindle_color = 'black'
            renderer.last_cover_url = ''
            renderer.vinyl_cache = None
            renderer.prev_vinyl_cache = None
            renderer.prev_dominant_color = (29, 185, 84)
            renderer.fade_alpha = 1.0
            renderer.transitioning_out = False
            renderer.viz_heights = [2.0] * 16
            renderer.viz_phase = [__import__('random').random() * 10 for _ in range(16)]
            renderer.C_BG = (5, 5, 8)
            renderer.C_AMBER = (255, 170, 0)
            renderer.C_BLUE_TXT = (80, 180, 255)
            renderer.C_WHT = (220, 220, 230)
            renderer.C_GRN = (80, 255, 80)
            renderer.C_RED = (255, 60, 60)
            renderer.C_GRY = (120, 120, 130)
            _preview_renderer = renderer
        except Exception as e:
            print(f"[preview] preview renderer init failed: {e}")
            _preview_renderer = False
    return _preview_renderer


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


def _placeholder_item_for_mode(mode: str) -> dict | None:
    mode = str(mode or '').lower()
    if mode == 'music':
        return {
            'type': 'music',
            'sport': 'music',
            'id': 'spotify_idle',
            'status': 'IDLE',
            'state': 'paused',
            'is_shown': True,
            'home_abbr': 'MUSIC',
            'away_abbr': 'NO SONG DATA',
            'home_logo': '',
            'next_logos': [],
            'situation': {
                'progress': 0,
                'duration': 1,
                'is_playing': False,
                'fetch_ts': time.time(),
            },
        }
    if mode == 'flight_tracker':
        return {
            'type': 'flight_visitor',
            'sport': 'flight',
            'id': 'flight_tracker_blank',
            'guest_name': 'NO FLIGHT SELECTED',
            'origin_city': 'TRACKER',
            'dest_city': 'SETUP',
            'alt': 0,
            'dist': 0,
            'eta_str': '--',
            'speed': 0,
            'progress': 0,
            'status': 'ADD FLIGHT',
            'delay_min': 0,
            'is_delayed': False,
            'is_live': False,
            'aircraft_type': '',
            'aircraft_code': '',
            'is_shown': True,
        }
    if mode == 'clock':
        return {'type': 'clock', 'sport': 'clock', 'id': 'clk', 'is_shown': True}
    if mode == 'weather':
        return {
            'type': 'weather', 'sport': 'weather', 'id': 'weather_blank', 'is_shown': True,
            'away_abbr': 'NO CITY SET', 'home_abbr': '--', 'status': 'SET A CITY',
            'situation': {'icon': 'cloud', 'stats': {}, 'forecast': []},
        }
    if mode in ('flights', 'flight_tracker'):
        return {
            'type': 'flight_airport_hud', 'sport': 'flight', 'id': 'airport_hud_blank', 'is_shown': True,
            '_weather_item': None, '_arrivals': [], '_departures': [],
        }
    return None


def _render_non_game(g: dict, mode: str = 'sports') -> Image.Image:
    """Render a non-sports item using the real controller mixins."""
    renderer = _get_preview_renderer()
    if renderer:
        try:
            itype = str(g.get('type', '')).lower()
            sport = str(g.get('sport', '')).lower()
            renderer.mode = str(mode or 'sports')
            if itype == 'weather':
                return renderer.draw_weather_detailed(g)
            if itype == 'stock_ticker' or sport.startswith('stock'):
                logo_url = g.get('home_logo')
                if logo_url:
                    renderer.download_and_process_logo(logo_url, (24, 24))
                return renderer.draw_stock_card(g)
            if itype == 'music' or sport == 'music':
                return renderer.draw_music_card(g)
            if itype == 'clock' or sport.startswith('clock'):
                return renderer.draw_clock_modern()
            if itype == 'flight_visitor':
                return renderer.draw_flight_visitor(g)
            if itype == 'flight_airport_hud':
                return renderer.draw_flight_airport(
                    g.get('_weather_item'),
                    g.get('_arrivals', []),
                    g.get('_departures', []),
                )
            if sport == 'flight' or itype == 'flight':
                return renderer.draw_flight_visitor(g)
            if itype == 'racing' or sport == 'indycar':
                if renderer.mode in ('indycar', 'indycar_full', 'sports_full'):
                    return renderer.draw_indycar_full(g)
                return renderer.draw_indycar_scroll_card(g)
            if itype in ('golf', 'masters') or sport in ('golf', 'masters'):
                if renderer.mode in ('golf', 'masters', 'sports_full'):
                    return renderer.draw_golf_mode(g)
                return renderer.draw_golf_scroll_card(g)
            if itype == 'leaderboard':
                return renderer.draw_leaderboard_card(g)
        except Exception as e:
            print(f"[preview] real non-sports render failed for {g.get('id','?')}: {e}")

    # Last-resort fallback: compact but still mode-aware.
    itype = str(g.get('type', '')).lower()
    sport = str(g.get('sport', '')).lower()
    img = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    if itype == 'weather':
        city = (g.get('city') or g.get('location') or 'WEATHER').upper()[:14]
        temp = g.get('temp')
        cond = (g.get('condition') or g.get('description') or '').upper()[:14]
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(10, 40, 90, 255))
        _pf(draw, city, 4, 6, (100, 200, 255), sc=2)
        temp_str = f"{int(round(temp))}F" if temp is not None else '--F'
        x2 = _pf(draw, temp_str, 4, 20, (255, 255, 255), sc=2)
        _pf(draw, cond, x2 + 6, 20, (80, 170, 255), sc=2)
    elif itype == 'stock_ticker':
        symbol = (g.get('symbol') or '???').upper()[:6]
        price = g.get('price')
        pct = g.get('change_pct')
        up = float(pct or 0) >= 0
        price_str = f"${float(price):.2f}" if price is not None else '$--'
        pct_str = ('+' if up else '') + f"{float(pct):.1f}%" if pct is not None else ''
        clr_pct = (50, 220, 100) if up else (255, 70, 70)
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=((0, 80, 40) if up else (80, 0, 0)))
        _pf(draw, symbol, 4, 6, (180, 255, 180) if up else (255, 180, 180), sc=2)
        x2 = _pf(draw, price_str, 4, 20, (255, 255, 255), sc=2)
        arrow = '▲' if up else '▼'
        _pf(draw, arrow + pct_str, x2 + 6, 20, clr_pct, sc=2)
    elif itype == 'music':
        artist = (g.get('artist') or g.get('artist_name') or g.get('home_abbr') or 'ARTIST').upper()[:18]
        title = (g.get('title') or g.get('song') or g.get('away_abbr') or '').upper()[:22]
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(60, 0, 100, 255))
        _pf(draw, artist, 4, 6, (200, 100, 255), sc=2)
        _pf(draw, title, 4, 20, (220, 180, 255), sc=2)
    elif itype == 'clock':
        now = datetime.datetime.now()
        time_str = now.strftime('%I:%M:%S').lstrip('0') or '12:00:00'
        date_str = now.strftime('%a').upper() + ' ' + now.strftime('%b %d').upper()
        draw.rectangle([0, 0, PANEL_W - 1, 3], fill=(20, 20, 20, 255))
        tw = _pw(time_str, sc=4)
        _pf(draw, time_str, max(4, (PANEL_W - tw) // 2), 5, (180, 180, 180), sc=4)
        _pf(draw, date_str, 4, 27, (70, 70, 70), sc=1)
    elif itype == 'flight_visitor':
        flight = (g.get('flight') or g.get('id') or '').upper()
        origin = (g.get('origin') or '').upper()
        dest = (g.get('dest') or '').upper()
        status = (g.get('status') or '').upper()[:10]
        guest = (g.get('guest_name') or '').upper()[:12]
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
        flnum = (g.get('flight_number') or g.get('flight') or '').upper()[:8]
        dest = (g.get('destination') or g.get('dest') or '').upper()[:12]
        status = (g.get('status') or '').upper()[:12]
        gate = (g.get('gate') or '').upper()
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


def _collapse_flight_airport_items(games: list) -> list:
    """Match the controller/browser grouping for airport weather/arrival/departure rows."""
    flight_weather = None
    flight_arrivals = []
    flight_departures = []
    other_games = []

    for g in games:
        if not isinstance(g, dict):
            continue
        item_type = str(g.get('type', ''))
        if item_type == 'flight_weather':
            flight_weather = g
        elif item_type == 'flight_arrival':
            flight_arrivals.append(g)
        elif item_type == 'flight_departure':
            flight_departures.append(g)
        else:
            other_games.append(g)

    if flight_weather or flight_arrivals or flight_departures:
        other_games.append({
            'type': 'flight_airport_hud',
            'sport': 'flight',
            'id': 'airport_hud',
            'is_shown': True,
            '_weather_item': flight_weather,
            '_arrivals': flight_arrivals,
            '_departures': flight_departures,
        })

    return other_games


def _is_sports_game(g: dict) -> bool:
    itype = (g.get('type') or '').lower()
    sport = (g.get('sport') or '').lower()
    if itype in ('weather', 'stock_ticker', 'music', 'clock', 'flight_visitor', 'flight_airport_hud', 'golf', 'masters', 'racing'):
        return False
    if sport in ('golf', 'masters', 'indycar'):
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


def _single_card_png(card: Image.Image):
    if card.mode != 'RGB':
        card = card.convert('RGB')
    buf = io.BytesIO()
    card.save(buf, 'PNG')
    buf.seek(0)
    r = Response(buf.getvalue(), mimetype='image/png')
    r.headers['Cache-Control'] = 'no-store'
    r.headers['X-Strip-Width'] = str(card.width)
    return r


@app.route('/api/preview/strip.png')
def preview_strip():
    mode_str = request.args.get('mode', state.get('mode', 'sports'))
    pin_id   = request.args.get('pin_id', '')
    try:
        current_mode = normalize_mode(mode_str)
        # sports_full uses the sports snapshot — just filter to a single pinned game
        fetch_mode = 'sports' if current_mode == 'sports_full' else current_mode
        games = fetcher.get_mode_snapshot(fetch_mode, 0)[:30]
    except Exception:
        games = []

    # sports_full: render the pinned game fullscreen
    if current_mode == 'sports_full' and pin_id:
        all_games = games
        # pin_id from JS is "sport:raw_id" (e.g. "nfl:401548409")
        if ':' in pin_id:
            pin_sport, _, pin_raw_id = pin_id.partition(':')
        else:
            pin_sport, pin_raw_id = '', pin_id

        def _matches(g):
            g_id = str(g.get('id', ''))
            if pin_sport:
                return g_id == pin_raw_id and str(g.get('sport', '')).lower() == pin_sport
            return g_id == pin_id

        pinned = next((g for g in all_games if _matches(g)), None)
        if pinned is None:
            # fallback: any sports game
            pinned = next((g for g in all_games if _is_sports_game(g)), None)
        if pinned:
            preview = _get_preview_renderer()
            if preview:
                try:
                    # Pre-warm the logo cache so get_logo() finds them
                    for logo_url in (pinned.get('home_logo'), pinned.get('away_logo')):
                        if logo_url:
                            preview.download_and_process_logo(logo_url, (24, 24))
                    sport = str(pinned.get('sport', '')).lower()
                    g_type = str(pinned.get('type', '')).lower()
                    if g_type == 'racing' or sport == 'indycar':
                        card = preview.draw_indycar_full(pinned)
                    else:
                        card = preview.draw_sport_full_bleed(pinned)
                    return _single_card_png(card)
                except Exception as e:
                    print(f"[preview] draw_sport_full_bleed failed: {e}")
            # fallback to stadium renderer
            renderer = _get_renderer()
            if renderer:
                try:
                    result = renderer.render(pinned)
                    card = result[0] if isinstance(result, tuple) else result
                    if card:
                        return _single_card_png(card)
                except Exception as e:
                    print(f"[preview] stadium fallback failed: {e}")
        return _empty_png()

    games = _filter_preview_games(games, current_mode)
    games = _collapse_flight_airport_items(games)
    if not games:
        placeholder = _placeholder_item_for_mode(current_mode)
        if placeholder:
            games = [placeholder]

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
                card = _render_non_game(g, current_mode)

            if card.mode != 'RGBA':
                card = card.convert('RGBA')
            cards.append(card)
        except Exception as e:
            print(f"[preview] render error for {g.get('id','?')}: {e}")

    if not cards:
        placeholder = _placeholder_item_for_mode(current_mode)
        if placeholder:
            return _single_card_png(_render_non_game(placeholder, current_mode))
        return _empty_png()

    if current_mode in _STATIC_PREVIEW_MODES:
        return _single_card_png(cards[0])

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
