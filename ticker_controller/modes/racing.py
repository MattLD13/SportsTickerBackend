"""IndyCar / endurance racing card renderer for the 384×32 LED matrix."""

import time as _time

from PIL import Image, ImageDraw
from ..config import PANEL_H, PANEL_W, PAGE_HOLD_TIME
from ..fonts import draw_tiny_text


def _hex(h: str) -> tuple:
    """Parse '#RRGGBB' → (r, g, b).  Returns dim grey on any failure."""
    try:
        h = h.strip().lstrip('#')
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (60, 60, 60)


_GOLD   = (255, 215, 0)
_SILVER = (192, 192, 192)
_BRONZE = (205, 127, 50)
_WHITE  = (255, 255, 255)
_DIM    = (100, 110, 120)
_LEAD   = (255, 215, 0)

_TINY_CHAR_W = 5  # each draw_tiny_text character advances 5 px


def _tiny_width(text: str) -> int:
    return len(str(text)) * _TINY_CHAR_W


def _draw_tiny_clipped(img: Image.Image, x: int, y: int, text: str,
                       color: tuple, max_w: int, scroll_pos: float = 0.0):
    """Render bitmap text clipped to max_w pixels.

    When text is wider than max_w and scroll_pos > 0, scrolls horizontally
    in a seamless loop. scroll_pos should be time.time() * speed_px_per_sec.
    """
    text = str(text).upper().strip()
    if not text or max_w <= 0:
        return
    text_w = _tiny_width(text)
    ROW_H = 7  # 5px glyph + 2px gap

    tmp = Image.new('RGBA', (max(_TINY_CHAR_W, text_w * 2 + 40), ROW_H), (0, 0, 0, 0))
    d_tmp = ImageDraw.Draw(tmp)

    if text_w <= max_w or scroll_pos == 0.0:
        draw_tiny_text(d_tmp, 0, 0, text, color)
        crop = tmp.crop((0, 0, min(max_w, tmp.width), ROW_H))
        img.paste(crop, (x, y), crop)
        return

    GAP = 20
    total_loop = text_w + GAP
    offset = int(scroll_pos) % total_loop
    draw_tiny_text(d_tmp, 0, 0, text, color)
    draw_tiny_text(d_tmp, total_loop, 0, text, color)
    crop = tmp.crop((offset, 0, offset + max_w, ROW_H))
    img.paste(crop, (x, y), crop)


_FLAG_COLORS = {
    'green':      ((0,   180,  50),  'GRN'),
    'yellow':     ((220, 190,   0),  'YLW'),
    'safety_car': ((20,   80, 220),  'SC '),
    'vsc':        ((130, 130, 220),  'VSC'),
    'red':        ((220,  20,  20),  'RED'),
    'fcy':        ((200, 140,   0),  'FCY'),
    'chequered':  ((200, 200, 200),  'CHQ'),
    'checkered':  ((200, 200, 200),  'CHQ'),
    'white':      ((240, 240, 240),  'WHT'),
    # Nürburgring-specific (kept for backward compat)
    'code60':     ((0,  180, 220),   'C60'),
    'noz':        ((255, 130,  0),   'NOZ'),
    'caution':    ((220, 190,  0),   'CAU'),
    'pit_closed': ((255, 100,  0),   'PIT'),
    'medical_car':((220,  60, 130),  'MED'),
    'unknown':    ((80,   90, 100),  '???'),
}


def _pos_color(pos_int: int) -> tuple:
    if pos_int == 1: return _GOLD
    if pos_int == 2: return _SILVER
    if pos_int == 3: return _BRONZE
    return _WHITE


class RacingMixin:
    """Provides IndyCar card renderers for the LED matrix strip."""

    # ------------------------------------------------------------------
    # Race-control / track-state card  (192 × 32 px)
    # ------------------------------------------------------------------

    def draw_indycar_racecontrol_card(self, game: dict) -> Image.Image:
        """192×32 race-control card: flag state, session, latest message.

        Layout:
          y=0-3   colored flag-status bar
          y=5-11  [FLAG badge]  session · track state name
          y=13    separator
          y=15-21 latest message (scrolling if long)
          y=23-29 second info line
        """
        W = 192
        img = Image.new('RGBA', (W, PANEL_H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        try:
            ts_key   = game.get('track_state_key', 'green')
            ts_name  = game.get('track_state_name', 'GREEN')
            flag_rgb, flag_abbr = _FLAG_COLORS.get(ts_key, _FLAG_COLORS['unknown'])

            # Flag bar (top 4px)
            for py in range(4):
                d.line([(0, py), (W - 1, py)], fill=flag_rgb)

            # Flag badge + state name
            bw = len(flag_abbr) * _TINY_CHAR_W + 6
            d.rectangle((2, 5, 2 + bw, 13), fill=flag_rgb)
            draw_tiny_text(d, 4, 6, flag_abbr, (0, 0, 0))

            session_label = str(game.get('session_label', 'RACE'))
            state_text = f'{session_label} {ts_name}'[:24]
            draw_tiny_text(d, 2 + bw + 4, 6, state_text, flag_rgb)

            # Separator
            d.line([(0, 14), (W - 1, 14)], fill=(30, 40, 50))

            # Latest message (scrolling)
            msg = str(game.get('latest_message', '') or '').strip()
            if not msg:
                msgs = game.get('messages', [])
                msg = msgs[0] if msgs else 'NO MESSAGES'
            scroll_pos = _time.time() * 18.0
            _draw_tiny_clipped(img, 2, 16, msg, (190, 200, 210), W - 4, scroll_pos)

            # Second line: leader laps or event name
            laps = game.get('leader_laps', 0)
            event = str(game.get('event_name', 'IndyCar')).upper()[:20]
            if laps:
                draw_tiny_text(d, 2, 24, f'LAP {laps}', (120, 140, 160))
            else:
                draw_tiny_text(d, 2, 24, event, (80, 90, 100))

        except Exception as exc:
            print(f'[IndyCar RC render] {exc}')

        return img

    # Backward-compatible alias
    draw_n24_racecontrol_card = draw_indycar_racecontrol_card

    # ------------------------------------------------------------------
    # Compact card  (96 × 32 px) — used in sports / live feed
    # ------------------------------------------------------------------

    def draw_indycar_car_compact(self, game: dict) -> Image.Image:
        """96×32 compact IndyCar card for the sports feed.

        Layout:
          y=0-1   2-px engine-color livery stripe
          y=3-9   pos · #NUM badge · driver name (scrolling) · laps right
          y=10    separator
          y=12-18 engine badge · driver acronym · gap right
          y=20-26 team name (dim)
        """
        W = 96
        img = Image.new('RGBA', (W, PANEL_H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        try:
            mc  = game.get('manufacturer_colors') or {}
            pri = _hex(mc.get('primary',   '#2A3A4A'))
            sec = _hex(mc.get('secondary', '#4A6A8A'))
            acc = _hex(mc.get('accent',    '#AABBCC'))

            # Livery stripe 2px
            seg = W // 3
            for px in range(0, seg):
                d.point((px, 0), fill=pri); d.point((px, 1), fill=pri)
            for px in range(seg, seg * 2):
                d.point((px, 0), fill=sec); d.point((px, 1), fill=sec)
            for px in range(seg * 2, W):
                d.point((px, 0), fill=acc); d.point((px, 1), fill=acc)

            # Row 1: pos · #NUM · driver name · laps
            pos_str = str(game.get('pos', '?'))
            try:
                pos_int = int(pos_str)
            except ValueError:
                pos_int = 99
            draw_tiny_text(d, max(1, 8 - len(pos_str) * 5), 3, pos_str, _pos_color(pos_int))

            car_num = str(game.get('car_num', '?'))[:3]
            nw = len(car_num) * _TINY_CHAR_W + 4
            d.rectangle((10, 2, 10 + nw, 10), fill=pri)
            draw_tiny_text(d, 12, 3, car_num, _hex(mc.get('text', '#FFFFFF')))

            laps   = str(game.get('laps', 0))
            laps_w = _tiny_width(laps) + 2
            driver = str(game.get('current_driver', game.get('driver', ''))).upper()
            team_x = 10 + nw + 3
            avail  = W - laps_w - team_x - 4
            scroll_pos = _time.time() * 18.0
            _draw_tiny_clipped(img, team_x, 3, driver, (200, 210, 215), avail, scroll_pos)
            draw_tiny_text(d, W - laps_w, 3, laps, (140, 165, 185))

            # Separator
            d.line([(0, 11), (W - 1, 11)], fill=(30, 40, 50))

            # Row 2: engine badge · driver acronym · gap
            cc  = game.get('class_colors') or {}
            class_label = str(cc.get('label', game.get('class_name', '?')))[:5]
            class_bg    = _hex(cc.get('bg',   '#333344'))
            class_fg    = _hex(cc.get('text', '#CCCCDD'))
            cw = len(class_label) * _TINY_CHAR_W + 4
            d.rectangle((0, 12, cw, 20), fill=class_bg)
            draw_tiny_text(d, 2, 13, class_label, class_fg)

            acronym = str(game.get('current_driver_acronym', '???'))[:3]
            draw_tiny_text(d, cw + 4, 13, acronym, (190, 215, 255))

            gap = str(game.get('gap', '')).strip()
            gap_str, gap_col = ('LDR', _LEAD) if not gap else (gap[:8], (150, 170, 190))
            gw = _tiny_width(gap_str)
            draw_tiny_text(d, W - gw - 1, 13, gap_str, gap_col)

            # Row 3: team name (dim)
            team = str(game.get('team', '')).upper()[:15]
            draw_tiny_text(d, 2, 21, team, (45, 60, 75))

        except Exception as exc:
            print(f'[IndyCar compact render] {exc}')

        return img

    # Backward-compatible alias
    draw_n24_car_compact = draw_indycar_car_compact

    # ------------------------------------------------------------------
    # Full card  (128 × 32 px) — used in indycar mode or when pinned
    # ------------------------------------------------------------------

    def draw_indycar_car_card(self, game: dict) -> Image.Image:
        """128×32 IndyCar car card.

        Layout:
          y=0-2   3-colour livery stripe
          y=4-10  pos · car# badge · driver name (scrolling) · laps
          y=11    separator
          y=13-19 engine badge · all driver acronyms · gap
          y=21-27 team name (dim, scrolling if long)
        """
        W = 128
        img = Image.new('RGBA', (W, PANEL_H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        try:
            mc  = game.get('manufacturer_colors') or {}
            cc  = game.get('class_colors')        or {}
            pri = _hex(mc.get('primary',   '#2A3A4A'))
            sec = _hex(mc.get('secondary', '#4A6A8A'))
            acc = _hex(mc.get('accent',    '#AABBCC'))

            # Livery stripe (3 equal segments, 3 px tall)
            seg = W // 3
            for px in range(0, seg):
                d.point((px, 0), fill=pri); d.point((px, 1), fill=pri); d.point((px, 2), fill=pri)
            for px in range(seg, seg * 2):
                d.point((px, 0), fill=sec); d.point((px, 1), fill=sec); d.point((px, 2), fill=sec)
            for px in range(seg * 2, W):
                d.point((px, 0), fill=acc); d.point((px, 1), fill=acc); d.point((px, 2), fill=acc)

            # Row 1: pos · car# · driver · laps
            pos_str = str(game.get('pos', '?'))
            try:
                pos_int = int(pos_str)
            except ValueError:
                pos_int = 99
            draw_tiny_text(d, max(1, 10 - len(pos_str) * 5), 4, pos_str, _pos_color(pos_int))

            car_num = str(game.get('car_num', '?'))[:3]
            nw = len(car_num) * _TINY_CHAR_W + 4
            d.rectangle((12, 3, 12 + nw, 11), fill=pri)
            draw_tiny_text(d, 14, 4, car_num, _hex(mc.get('text', '#FFFFFF')))

            driver = str(game.get('current_driver', game.get('driver', ''))).upper()
            team_x = 12 + nw + 3
            laps   = str(game.get('laps', 0))
            laps_w = _tiny_width(laps) + 2
            avail  = W - laps_w - team_x - 4
            scroll_pos = _time.time() * 18.0
            _draw_tiny_clipped(img, team_x, 4, driver, (210, 215, 220), avail, scroll_pos)
            draw_tiny_text(d, W - laps_w, 4, laps, (160, 180, 200))

            # Separator
            d.line([(0, 12), (W - 1, 12)], fill=(35, 45, 55))

            # Row 2: engine badge · driver acronym · gap
            class_label = str(cc.get('label', game.get('class_name', '?')))[:5]
            class_bg    = _hex(cc.get('bg',   '#333344'))
            class_fg    = _hex(cc.get('text', '#CCCCDD'))
            cw = len(class_label) * _TINY_CHAR_W + 4
            d.rectangle((0, 13, cw, 21), fill=class_bg)
            draw_tiny_text(d, 2, 14, class_label, class_fg)

            acronym = str(game.get('current_driver_acronym', '???'))[:3]
            draw_tiny_text(d, cw + 4, 14, acronym, (200, 220, 255))

            all_acr = ' '.join(game.get('driver_acronyms', []))
            acr2_x  = cw + 25
            avail2  = W - acr2_x - 30
            if all_acr and avail2 > 5:
                draw_tiny_text(d, acr2_x, 14, all_acr[:avail2 // _TINY_CHAR_W], _DIM)

            gap = str(game.get('gap', '')).strip()
            gap_str, gap_col = ('LDR', _LEAD) if not gap else (gap[:9], (160, 180, 200))
            gw = _tiny_width(gap_str)
            draw_tiny_text(d, W - gw - 1, 14, gap_str, gap_col)

            # Row 3: team name (dim, scrolling)
            team = str(game.get('team', '')).upper()
            scroll_team = _time.time() * 14.0
            _draw_tiny_clipped(img, 2, 22, team, (55, 70, 85), W - 4, scroll_team)

        except Exception as exc:
            print(f'[IndyCar car render] {exc}')

        return img

    # Backward-compatible alias
    draw_n24_car_card = draw_indycar_car_card

    # ------------------------------------------------------------------
    # Fullscreen dashboard  (384 × 32 px) — used in indycar mode
    # ------------------------------------------------------------------

    def draw_indycar_fullscreen(self, game: dict) -> Image.Image:
        """384×32 full-screen IndyCar race dashboard.

        Shows 4 cars at a time. Page auto-advances every PAGE_HOLD_TIME
        seconds so the display cycles through the full field.

        Layout per row (7 px tall, 4 rows, y=4/11/18/25):
          x=0-12    POS (right-aligned 2-3 chars)
          x=13-30   #NUM badge (engine primary color)
          x=31-52   ENGINE badge (CHV / HON)
          x=53-212  DRIVER full name (scrolling)
          x=213-252 LAPS / SPEED (race: laps, practice/quali: speed)
          x=253-383 GAP / BEST TIME (race: gap, other: best lap)

        Top 3px: flag-state color bar.
        """
        W = PANEL_W  # 384
        H = PANEL_H  # 32
        img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        try:
            entries = game.get('entries', [])
            session_type  = game.get('session_type', 'race')
            ts_key        = game.get('track_state_key', 'green')
            flag_rgb, flag_abbr = _FLAG_COLORS.get(ts_key, _FLAG_COLORS['unknown'])

            # ── Flag bar (top 3 px) ──────────────────────────────────────
            for py in range(3):
                d.line([(0, py), (W - 1, py)], fill=flag_rgb)

            if not entries:
                draw_tiny_text(d, 4, 13, 'AWAITING INDYCAR TIMING DATA', (70, 80, 90))
                return img

            n = len(entries)
            ROWS = 4
            ROW_H = 7  # 5px glyph + 2px gap
            ROW_STARTS = [4, 11, 18, 25]  # y positions for each row

            # ── Page offset (advances every PAGE_HOLD_TIME seconds) ──────
            page   = int(_time.time() / PAGE_HOLD_TIME)
            offset = (page * ROWS) % n

            # ── Scroll position for long driver names ────────────────────
            scroll_pos = _time.time() * 18.0

            # ── Column bounds ────────────────────────────────────────────
            X_POS     = 0
            X_NUM     = 13
            X_ENG     = 31
            X_DRIVER  = 53
            W_DRIVER  = 160
            X_LAPS    = 213
            W_LAPS    = 40
            X_GAP     = 253
            W_GAP     = W - X_GAP - 2  # ~129px

            # Column header (topmost row if space — show just a 1px dim header line)
            d.line([(X_NUM, 3), (W - 1, 3)], fill=(20, 30, 40))

            for row_idx in range(ROWS):
                entry = entries[(offset + row_idx) % n]
                y = ROW_STARTS[row_idx]

                mc  = entry.get('manufacturer_colors') or {}
                cc  = entry.get('class_colors') or {}
                pri = _hex(mc.get('primary',   '#2A3A4A'))
                txt_col = _hex(mc.get('text', '#FFFFFF'))

                pos_str = str(entry.get('pos', '?'))
                try:
                    pos_int = int(pos_str)
                except ValueError:
                    pos_int = 99

                car_num = str(entry.get('car_num', '?'))[:3]
                driver  = str(entry.get('current_driver', entry.get('driver', ''))).upper()
                engine_label = str(cc.get('label', entry.get('class_name', '?')))[:3]
                engine_bg    = _hex(cc.get('bg',   '#333344'))
                engine_fg    = _hex(cc.get('text', '#CCCCDD'))

                laps = str(entry.get('laps', 0))
                if session_type in ('practice', 'qualifying', 'qualifying2'):
                    speed = str(entry.get('best_speed', '')).strip()
                    display_right = speed[:6] if speed else laps
                    right_col = (200, 220, 180) if speed else (140, 165, 185)
                else:
                    display_right = laps
                    right_col = (140, 165, 185)

                gap = str(entry.get('gap', '')).strip()
                if session_type in ('practice', 'qualifying', 'qualifying2'):
                    best = str(entry.get('best_lap', '')).strip()
                    display_gap = best[:10] if best else gap
                    gap_col = (180, 200, 220)
                elif not gap:
                    display_gap = 'LEADER'
                    gap_col = _LEAD
                else:
                    display_gap = gap[:12]
                    gap_col = (150, 170, 190)

                # POS
                px = X_POS + max(0, 12 - len(pos_str) * _TINY_CHAR_W)
                draw_tiny_text(d, px, y, pos_str, _pos_color(pos_int))

                # Car number badge
                nw = len(car_num) * _TINY_CHAR_W + 3
                d.rectangle((X_NUM, y - 1, X_NUM + nw, y + 5), fill=pri)
                draw_tiny_text(d, X_NUM + 2, y, car_num, txt_col)

                # Engine badge
                ew = len(engine_label) * _TINY_CHAR_W + 3
                d.rectangle((X_ENG, y - 1, X_ENG + ew, y + 5), fill=engine_bg)
                draw_tiny_text(d, X_ENG + 2, y, engine_label, engine_fg)

                # Driver name (scrolling)
                _draw_tiny_clipped(img, X_DRIVER, y, driver, (210, 215, 220),
                                   W_DRIVER, scroll_pos)

                # Laps / speed (right-aligned in zone)
                lw = _tiny_width(display_right)
                lx = X_LAPS + max(0, W_LAPS - lw)
                draw_tiny_text(d, lx, y, display_right, right_col)

                # Gap / best time (right-aligned in zone)
                gw = _tiny_width(display_gap)
                gx = W - gw - 2
                draw_tiny_text(d, gx, y, display_gap, gap_col)

                # Row separator (dim line between rows)
                if row_idx < ROWS - 1:
                    sep_y = y + ROW_H - 1
                    d.line([(X_NUM, sep_y), (W - 1, sep_y)], fill=(22, 30, 38))

        except Exception as exc:
            print(f'[IndyCar fullscreen render] {exc}')

        return img
