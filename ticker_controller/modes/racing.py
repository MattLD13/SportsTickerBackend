"""N24 / endurance racing card renderer for the 384×32 LED matrix."""

from PIL import Image, ImageDraw
from ..config import PANEL_H
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
_LEAD   = (255, 215, 0)   # gap colour for the race leader


_FLAG_COLORS = {
    'green':      ((0,   180,  50),  'GRN'),
    'yellow':     ((220, 190,   0),  'YLW'),
    'safety_car': ((20,   80, 220),  'SC '),
    'vsc':        ((130, 130, 220),  'VSC'),
    'red':        ((220,  20,  20),  'RED'),
    'fcy':        ((200, 140,   0),  'FCY'),
    'chequered':  ((200, 200, 200),  'CHQ'),
    # Nürburgring-specific
    'code60':     ((0,  180, 220),   'C60'),  # Code 60 slow zone
    'noz':        ((255, 130,  0),   'NOZ'),  # No Overtaking Zone
    'caution':    ((220, 190,  0),   'CAU'),
    'pit_closed': ((255, 100,  0),   'PIT'),  # Pit lane closed
    'medical_car':((220,  60, 130),  'MED'),
    'unknown':    ((80,   90, 100),  '???'),
}


class RacingMixin:
    """Provides N24 card renderers for the LED matrix strip."""

    # ------------------------------------------------------------------
    # Race-control / track-state card  (192 × 32 px)
    # ------------------------------------------------------------------

    def draw_n24_racecontrol_card(self, game: dict) -> Image.Image:
        """192×32 race-control card showing track state + latest message.

        Layout:
          y=0-4   thick colored flag-status bar
          y=6-12  [FLAG badge] track state name
          y=14    separator
          y=16-22 latest race control message text (truncated)
          y=24-30 second message line if text wraps
        """
        W = 192
        img = Image.new('RGBA', (W, PANEL_H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        try:
            ts_key   = game.get('track_state_key', 'green')
            ts_name  = game.get('track_state_name', 'GREEN FLAG')
            ts_color_hex = game.get('track_state_color', '#00C040')
            flag_rgb, flag_abbr = _FLAG_COLORS.get(ts_key, ((80, 80, 80), '???'))

            # ── Thick status bar across top ──────────────────────────────
            for py in range(5):
                d.line([(0, py), (W - 1, py)], fill=flag_rgb)

            # ── Flag badge + state name ──────────────────────────────────
            bw = len(flag_abbr) * 5 + 6
            d.rectangle((2, 6, 2 + bw, 14), fill=flag_rgb)
            draw_tiny_text(d, 4, 7, flag_abbr, (0, 0, 0))

            state_text = ts_name[:24]
            draw_tiny_text(d, 2 + bw + 4, 7, state_text, flag_rgb)

            # ── Separator ────────────────────────────────────────────────
            d.line([(0, 15), (W - 1, 15)], fill=(30, 40, 50))

            # ── Latest RC message (wrapped into 2 lines) ─────────────────
            msg = str(game.get('latest_message', '') or '').strip()
            if not msg:
                msgs = game.get('messages', [])
                msg  = msgs[0] if msgs else 'NO RECENT MESSAGES'

            max_chars = (W - 4) // 6  # ~5px per char + 1px spacing
            line1 = msg[:max_chars]
            line2 = msg[max_chars: max_chars * 2] if len(msg) > max_chars else ''

            draw_tiny_text(d, 2, 17, line1, (190, 200, 210))
            if line2:
                draw_tiny_text(d, 2, 25, line2, (130, 145, 160))

        except Exception as exc:
            print(f'[N24 RC render] {exc}')

        return img

    # ------------------------------------------------------------------
    # Compact card  (96 × 32 px) — used in sports / live feed
    # ------------------------------------------------------------------

    def draw_n24_car_compact(self, game: dict) -> Image.Image:
        """96×32 compact card for N24 entries scrolling in the sports feed.

        Layout:
          y=0-1   2-px livery stripe
          y=3-9   pos · #NUM badge · team (truncated)          laps right
          y=10    dim separator
          y=12-18 class badge · driver acronym · gap right
          y=20-26 car / mfr name (very dim)
        """
        W = 96
        img = Image.new('RGBA', (W, PANEL_H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        try:
            mc  = game.get('manufacturer_colors') or {}
            cc  = game.get('class_colors')        or {}
            pri = _hex(mc.get('primary',   '#2A3A4A'))
            sec = _hex(mc.get('secondary', '#4A6A8A'))
            acc = _hex(mc.get('accent',    '#AABBCC'))

            # Livery stripe — 2 px
            seg = W // 3
            for px in range(0, seg):
                d.point((px, 0), fill=pri); d.point((px, 1), fill=pri)
            for px in range(seg, seg * 2):
                d.point((px, 0), fill=sec); d.point((px, 1), fill=sec)
            for px in range(seg * 2, W):
                d.point((px, 0), fill=acc); d.point((px, 1), fill=acc)

            # Row 1: pos · #NUM badge · team · laps
            pos_str = str(game.get('pos', '?'))
            try:
                pos_int = int(pos_str)
            except ValueError:
                pos_int = 99
            pos_col = _GOLD if pos_int == 1 else _SILVER if pos_int == 2 else _BRONZE if pos_int == 3 else _WHITE
            draw_tiny_text(d, max(1, 8 - len(pos_str) * 5), 3, pos_str, pos_col)

            car_num = str(game.get('car_num', '?'))[:3]
            nw = len(car_num) * 5 + 4
            d.rectangle((10, 2, 10 + nw, 10), fill=pri)
            draw_tiny_text(d, 12, 3, car_num, _hex(mc.get('text', '#FFFFFF')))

            laps    = str(game.get('laps', 0))
            laps_w  = len(laps) * 5 + 2
            team_x  = 10 + nw + 3
            team    = str(game.get('team', game.get('car', ''))).upper()
            t_chars = max(0, (W - laps_w - team_x - 4) // 6)
            draw_tiny_text(d, team_x, 3, team[:t_chars], (200, 210, 215))
            draw_tiny_text(d, W - laps_w, 3, laps, (140, 165, 185))

            # Separator
            d.line([(0, 11), (W - 1, 11)], fill=(30, 40, 50))

            # Row 2: class badge · driver acronym · gap
            class_label = str(cc.get('label', game.get('class_name', '?')))[:5]
            class_bg    = _hex(cc.get('bg',   '#333344'))
            class_fg    = _hex(cc.get('text', '#CCCCDD'))
            cw = len(class_label) * 5 + 4
            d.rectangle((0, 12, cw, 20), fill=class_bg)
            draw_tiny_text(d, 2, 13, class_label, class_fg)

            acronym = str(game.get('current_driver_acronym', '???'))[:3]
            draw_tiny_text(d, cw + 4, 13, acronym, (190, 215, 255))

            gap = str(game.get('gap', '')).strip()
            if not gap:
                gap_str, gap_col = 'LDR', _LEAD
            else:
                gap_str, gap_col = gap[:8], (150, 170, 190)
            gw = len(gap_str) * 5
            draw_tiny_text(d, W - gw - 1, 13, gap_str, gap_col)

            # Row 3: car / mfr name (dim)
            car_name = str(game.get('car', game.get('manufacturer', ''))).upper()[:15]
            draw_tiny_text(d, 2, 21, car_name, (45, 60, 75))

        except Exception as exc:
            print(f'[N24 compact render] {exc}')

        return img

    # ------------------------------------------------------------------
    # Full card  (128 × 32 px) — used in n24 mode or when pinned
    # ------------------------------------------------------------------

    def draw_n24_car_card(self, game: dict) -> Image.Image:
        """Render a 128×32 car card for one N24 entry.

        Layout (128 px wide × 32 px tall):
          y=0-2   3-colour livery stripe   primary | secondary | accent
          y=4-10  Row 1  pos · car# badge · team name · laps
          y=11    dim separator
          y=13-19 Row 2  class badge · current-driver acronym · gap
          y=21-27 Row 3  manufacturer / car name (dim)
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

            # ── Livery stripe (3 equal segments across top 3 px) ────────
            seg = W // 3
            for px in range(0, seg):
                d.point((px, 0), fill=pri); d.point((px, 1), fill=pri); d.point((px, 2), fill=pri)
            for px in range(seg, seg * 2):
                d.point((px, 0), fill=sec); d.point((px, 1), fill=sec); d.point((px, 2), fill=sec)
            for px in range(seg * 2, W):
                d.point((px, 0), fill=acc); d.point((px, 1), fill=acc); d.point((px, 2), fill=acc)

            # ── Row 1: pos · car# · team · laps ─────────────────────────
            pos_str = str(game.get('pos', '?'))
            try:
                pos_int = int(pos_str)
            except ValueError:
                pos_int = 99
            pos_col = _GOLD if pos_int == 1 else _SILVER if pos_int == 2 else _BRONZE if pos_int == 3 else _WHITE

            # Position (right-aligned in a 10px slot)
            draw_tiny_text(d, max(1, 10 - len(pos_str) * 5), 4, pos_str, pos_col)

            # Car number coloured badge (background = primary colour)
            car_num = str(game.get('car_num', '?'))[:3]
            nw = len(car_num) * 5 + 4
            d.rectangle((12, 3, 12 + nw, 11), fill=pri)
            num_text_col = _hex(mc.get('text', '#FFFFFF'))
            draw_tiny_text(d, 14, 4, car_num, num_text_col)

            # Team name (truncated, left of laps)
            team = str(game.get('team', game.get('car', ''))).upper()[:14]
            team_x = 12 + nw + 3
            laps   = str(game.get('laps', 0))
            laps_w = len(laps) * 5 + 2
            team_max = W - laps_w - team_x - 4
            team_chars = max(0, team_max // 6)
            draw_tiny_text(d, team_x, 4, team[:team_chars], (210, 215, 220))

            # Laps right-aligned
            draw_tiny_text(d, W - laps_w, 4, laps, (160, 180, 200))

            # ── Separator ───────────────────────────────────────────────
            d.line([(0, 12), (W - 1, 12)], fill=(35, 45, 55))

            # ── Row 2: class badge · current driver acronym · gap ───────
            class_label = str(cc.get('label', game.get('class_name', '?')))[:5]
            class_bg    = _hex(cc.get('bg',   '#333344'))
            class_fg    = _hex(cc.get('text', '#CCCCDD'))
            cw = len(class_label) * 5 + 4
            d.rectangle((0, 13, cw, 21), fill=class_bg)
            draw_tiny_text(d, 2, 14, class_label, class_fg)

            # Current driver acronym  (3-letter, highlighted)
            acronym  = str(game.get('current_driver_acronym', '???'))[:3]
            acr_x    = cw + 4
            draw_tiny_text(d, acr_x, 14, acronym, (200, 220, 255))

            # All driver acronyms (dim, space-separated, what fits)
            all_acr = ' '.join(game.get('driver_acronyms', []))
            acr2_x  = acr_x + 22
            avail   = W - acr2_x - 30
            acr2_chars = max(0, avail // 6)
            if all_acr:
                draw_tiny_text(d, acr2_x, 14, all_acr[:acr2_chars], _DIM)

            # Gap right-aligned
            gap = str(game.get('gap', '')).strip()
            if not gap:
                gap_str = 'LDR'; gap_col = _LEAD
            else:
                gap_str = gap[:9]; gap_col = (160, 180, 200)
            gw = len(gap_str) * 5
            draw_tiny_text(d, W - gw - 1, 14, gap_str, gap_col)

            # ── Row 3: manufacturer / car name (dim) ────────────────────
            car_name = str(game.get('car', game.get('manufacturer', ''))).upper()[:21]
            draw_tiny_text(d, 2, 22, car_name, (55, 70, 85))

        except Exception as exc:
            print(f'[N24 render] {exc}')

        return img
