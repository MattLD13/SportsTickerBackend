"""IndyCar display modes.

Scroll card (128 × 32):  race name + session on top, top-3 drivers below.
Full screen (384 × 32):  left 1/4 = race info, right 3/4 = scrolling driver list.
"""

import time
from PIL import Image, ImageDraw
from ..config import PANEL_W, PANEL_H
from ..fonts import draw_tiny_text, draw_hybrid_text


def _hex_to_rgb(h, fallback=(128, 128, 128)):
    try:
        h = str(h or '').strip().lstrip('#')
        if len(h) == 6:
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return fallback


def _ic_flag_color(flag):
    flag = str(flag or '').strip().upper()
    return {
        'GREEN': (55, 190, 90),
        'RED': (230, 70, 70),
        'YELLOW': (255, 215, 0),
        'CHECKERED': (235, 235, 235),
        'WHITE': (230, 230, 230),
    }.get(flag, (0, 80, 180))


def _draw_mini_flag(d, x, y, flag):
    fill = _ic_flag_color(flag)
    flag_name = str(flag or '').strip().upper()
    if flag_name == 'CHECKERED':
        d.rectangle([x, y + 1, x + 6, y + 5], fill=(240, 240, 240), outline=(35, 35, 35))
        for yy in range(1, 5):
            for xx in range(0, 7):
                if (xx + yy) % 2 == 0:
                    d.point((x + xx, y + yy), fill=(45, 45, 45))
    else:
        d.rectangle([x, y + 1, x + 6, y + 5], fill=fill, outline=(35, 35, 35))


def _draw_centered_tiny_text(draw, center_x, y, text, color, font):
    text = str(text or '').strip()
    if not text:
        return
    try:
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
    except Exception:
        text_w = len(text) * 4
    draw_tiny_text(draw, int(round(center_x - (text_w / 2))), y, text, color)


def _tiny_text_width(text, font):
    text = str(text or '').strip()
    if not text:
        return 0
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * 4


class IndycarMixin:

    # ── helpers ──────────────────────────────────────────────────────────────

    def _ic_payload(self, game):
        return (game.get('indycar') or {}) if isinstance(game, dict) else {}

    def _ic_draw_livery_bar(self, d, x, y, w, h, primary_hex, secondary_hex):
        """Draw a vertical livery bar split primary (top) / secondary (bottom)."""
        pri = _hex_to_rgb(primary_hex, (128, 128, 128))
        sec = _hex_to_rgb(secondary_hex, (64, 64, 64))
        split = max(1, h * 2 // 3)
        if h > 1:
            d.rectangle([x, y, x + w - 1, y + split - 1], fill=pri)
            d.rectangle([x, y + split, x + w - 1, y + h - 1], fill=sec)
        else:
            d.rectangle([x, y, x + w - 1, y], fill=pri)

    def _ic_header_label(self, ic):
        """Build a compact header string: short race name + session."""
        short = str(ic.get('short_name') or ic.get('event_name') or 'IndyCar').strip()
        session = str(ic.get('session_type') or 'Race').strip()
        # Shorten common words so it fits
        short = (short
                 .replace('GRAND PRIX', 'GP')
                 .replace('CHAMPIONSHIP', 'CHAMP')
                 .replace('PRESENTED BY', '')
                 .replace('  ', ' ')
                 .strip())
        # Truncate so "SHORT SESSION" fits in ~22 chars
        if len(short) + 1 + len(session) > 22:
            short = short[:max(4, 22 - 1 - len(session))]
        return f"{short} {session}"

    # ── scroll card (128 × 32) ───────────────────────────────────────────────

    def draw_indycar_scroll_card(self, game):
        """Compact IndyCar card for the sports/live scrolling strip."""
        W = 128
        img = Image.new("RGBA", (W, PANEL_H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)

        ic = self._ic_payload(game)
        drivers = ic.get('drivers', [])
        if not isinstance(drivers, list):
            drivers = []

        # ── Header ──────────────────────────────────────────────────────────
        header = self._ic_header_label(ic)
        # Shadow + text
        draw_hybrid_text(d, 1 + 1, 1 + 1, header, (8, 8, 8, 180))
        draw_hybrid_text(d, 1,     1,     header, (255, 220, 50, 255))

        # Mini flag on the right edge
        _draw_mini_flag(d, W - 9, 0, ic.get('flag'))

        # Separator
        d.line([(0, 7), (W - 1, 7)], fill=(40, 60, 120))

        session = str(ic.get('session_type') or 'Race').lower()
        is_qual = 'qual' in session

        # ── Column labels ────────────────────────────────────────────────────
        LABEL_COL = (70, 90, 140)
        draw_tiny_text(d, 1,  8, 'P',      LABEL_COL)
        draw_tiny_text(d, 34, 8, 'DRIVER', LABEL_COL)
        right_label = 'MPH' if is_qual else 'GAP'
        draw_tiny_text(d, 90, 8, right_label, LABEL_COL)

        # ── Driver rows (top 3) ──────────────────────────────────────────────
        row_ys = [13, 20, 27]
        top3 = drivers[:3]

        for i, driver in enumerate(top3):
            y = row_ys[i]
            pos    = str(driver.get('pos') or i + 1)
            abbr   = str(driver.get('abbr') or '???').upper()[:3]
            car_num = str(driver.get('car') or '').strip()

            # Right column: speed for qualifying, gap for race
            if is_qual:
                right_val = str(driver.get('speed') or driver.get('gap') or '').strip()[:7]
            else:
                right_val = str(driver.get('gap') or '').strip()[:12]

            # Position number
            pos_color = (255, 215, 0) if pos == '1' else (200, 200, 200)
            draw_tiny_text(d, 1, y, pos, pos_color)

            # Inline 3-letter driver code with the car number immediately after it.
            name_x = 26
            draw_tiny_text(d, name_x, y, abbr, (255, 255, 255))
            if car_num:
                car_x = name_x + _tiny_text_width(abbr, self.font) + 2
                draw_tiny_text(d, car_x, y, car_num, (180, 210, 255))

            # Right column value
            if right_val:
                val_x = min(82, W - len(right_val) * 4 - 2)
                val_color = (255, 255, 255) if pos == '1' else (180, 210, 255)
                draw_tiny_text(d, val_x, y, right_val, val_color)

        if not top3:
            draw_tiny_text(d, 18, 18, 'LOADING', (120, 120, 120))

        return img

    # ── full-screen mode (384 × 32) ──────────────────────────────────────────

    def draw_indycar_full(self, game):
        """Full-bleed IndyCar mode: info panel on left 1/4, driver list on right 3/4."""
        if not hasattr(self, '_ic_scroll_idx'):
            self._ic_scroll_idx   = 0
            self._ic_scroll_ts    = time.time()
            self._ic_scroll_batch = 3   # drivers shown per page

        W = PANEL_W   # 384
        H = PANEL_H   # 32
        INFO_W = W // 4          # 96 px
        RACE_W = W - INFO_W      # 288 px

        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        ic      = self._ic_payload(game)
        drivers = ic.get('drivers', [])
        if not isinstance(drivers, list):
            drivers = []
        session = str(ic.get('session_type') or '').lower()
        is_qual = 'qual' in session or 'prac' in session

        # ── Background: subtle dark blue gradient ────────────────────────────
        for x in range(INFO_W):
            alpha = int(30 + 20 * x / INFO_W)
            d.line([(x, 0), (x, H)], fill=(0, 20, 60, alpha))

        # Vertical divider
        flag = str(ic.get('flag') or '').upper()
        div_color = (255, 200, 0) if flag in ('YELLOW', 'RED') else (0, 80, 200)
        d.line([(INFO_W, 0), (INFO_W, H)], fill=div_color)

        # ── Left panel: race info ────────────────────────────────────────────
        self._ic_draw_info_panel(d, ic, game, INFO_W, H)

        # ── Right panel: scrolling driver list ───────────────────────────────
        if drivers:
            self._ic_draw_driver_panel(img, d, drivers, INFO_W, RACE_W, H, is_qual=is_qual)

        return img

    def _ic_draw_info_panel(self, d, ic, game, panel_w, H):
        """Draw race/session information into the left 1/4 panel."""
        short_name = str(ic.get('short_name') or ic.get('event_name') or 'INDYCAR').upper()
        short_name = (short_name
                      .replace('110TH RUNNING OF THE ', '')
                      .replace('GRAND PRIX', 'GP')
                      .replace('CHAMPIONSHIP', 'CHAMP')
                      .replace('PRESENTED BY', '')
                      .replace('  ', ' ')
                      .strip())

        session    = str(ic.get('session_type') or 'RACE').upper()
        lap        = ic.get('lap', 0) or 0
        total      = ic.get('total_laps', 0) or 0
        rem        = ic.get('laps_remaining', 0) or 0
        time_to_go = str(ic.get('time_to_go') or '').strip()
        start_utc  = str(game.get('startTimeUTC') or '').strip()
        flag       = str(ic.get('flag') or '').strip().upper()
        caution    = flag in ('YELLOW', 'RED') or bool(ic.get('caution'))
        state      = str(game.get('state', 'pre')).lower()
        is_qual    = 'qual' in session.lower() or 'prac' in session.lower()

        # Accent bar: flag-aware color
        bar_color = (255, 200, 0) if caution else (0, 80, 200)
        d.rectangle([0, 0, 2, H], fill=bar_color)

        max_chars = (panel_w - 6) // 4
        line1 = short_name[:max_chars]
        line2 = short_name[max_chars:max_chars * 2] if len(short_name) > max_chars else ''

        draw_tiny_text(d, 4, 1, line1, (255, 220, 50))
        if line2:
            draw_tiny_text(d, 4, 7, line2.strip(), (255, 220, 50))

        y_session = 7 if not line2 else 13
        draw_tiny_text(d, 4, y_session, session, (180, 210, 255))

        y_info = y_session + 7
        if state == 'post':
            info_str = 'FINAL'
        elif is_qual and time_to_go:
            # Qualifying: show time remaining
            info_str = time_to_go[:max_chars]
        elif state == 'in' and total > 0:
            info_str = f"L{lap}/{total}"
        elif state == 'in' and lap > 0:
            info_str = f"LAP {lap}"
        elif state == 'pre' and start_utc:
            start_txt = start_utc
            try:
                start_dt = parse_iso(start_utc)
                if start_dt:
                    start_txt = start_dt.strftime('%I:%M %p').lstrip('0')
            except Exception:
                pass
            info_str = f"STARTS {start_txt}"[:max_chars]
        elif time_to_go:
            info_str = time_to_go[:max_chars]
        else:
            info_str = 'STARTS SOON' if state == 'pre' else str(game.get('status', '')).upper()[:max_chars]

        draw_tiny_text(d, 4, y_info, info_str, (255, 255, 255))

        # Flag indicator
        y_flag = y_info + 7
        if y_flag + 5 <= H and flag and flag not in ('GREEN', ''):
            flag_colors = {
                'YELLOW':    (255, 220, 0),
                'RED':       (255, 50, 50),
                'CHECKERED': (255, 255, 255),
                'WHITE':     (255, 255, 255),
            }
            flag_col = flag_colors.get(flag, (180, 180, 180))
            flag_txt = flag[:5]
            d.rectangle([4, y_flag, 7, y_flag + 4], fill=flag_col)
            draw_tiny_text(d, 9, y_flag, flag_txt, flag_col)

    def _ic_draw_driver_panel(self, img, d, drivers, x_off, panel_w, H, is_qual=False):
        """Draw the scrolling driver leaderboard into the right 3/4 panel."""
        SCROLL_INTERVAL = 3.5   # seconds per page

        n_drivers    = len(drivers)
        n_per_page   = 4        # rows that fit in 32px at 8px/row
        n_pages      = max(1, -(-n_drivers // n_per_page))  # ceil division

        now = time.time()
        if now - self._ic_scroll_ts >= SCROLL_INTERVAL:
            self._ic_scroll_idx = (self._ic_scroll_idx + 1) % n_pages
            self._ic_scroll_ts  = now

        start_idx = self._ic_scroll_idx * n_per_page
        page_drivers = drivers[start_idx: start_idx + n_per_page]

        # Column offsets (relative to x_off)
        POS_X   = 3
        LOGO_X  = 14
        LIVERY_X = 25
        ABBR_X  = 30
        CAR_X   = 46    # car number
        GAP_X   = 58

        LOGO_SZ  = 7
        ROW_H    = 8

        for row_i, driver in enumerate(page_drivers):
            y = row_i * ROW_H

            pos   = str(driver.get('pos') or '')
            abbr  = str(driver.get('abbr') or '???').upper()[:3]
            car   = str(driver.get('car') or '').strip()
            gap   = str(driver.get('gap') or '').strip()
            logo_url = driver.get('team_logo') or ''
            pri_hex  = driver.get('livery_primary', '#888888')
            sec_hex  = driver.get('livery_secondary', '#333333')

            # Row background for P1
            if pos == '1':
                d.rectangle([x_off, y, x_off + panel_w - 1, y + ROW_H - 2],
                            fill=(10, 10, 30))

            # Position
            pos_color = (255, 215, 0) if pos == '1' else (180, 180, 180)
            draw_tiny_text(d, x_off + POS_X, y + 1, pos, pos_color)

            # Team logo
            logo_img = self.get_logo(logo_url, (LOGO_SZ, LOGO_SZ))
            if logo_img:
                logo_img = logo_img.resize((LOGO_SZ, LOGO_SZ), Image.LANCZOS)
                img.paste(logo_img, (x_off + LOGO_X, y), logo_img)

            # Livery bar (3 × 5)
            self._ic_draw_livery_bar(d, x_off + LIVERY_X, y + 1, 3, 5, pri_hex, sec_hex)

            # Driver abbreviation
            draw_tiny_text(d, x_off + ABBR_X, y + 1, abbr, (255, 255, 255))

            # Car number (dim)
            if car:
                draw_tiny_text(d, x_off + CAR_X, y + 1, f"#{car}"[:4], (90, 90, 90))

            # Right column: speed for qualifying, gap for race
            if is_qual:
                right_val = str(driver.get('speed') or '').strip()[:8]
            else:
                right_val = str(driver.get('gap') or '').strip()[:16]
            if right_val:
                right_color = (255, 255, 255) if pos == '1' else (140, 190, 255)
                draw_tiny_text(d, x_off + GAP_X, y + 1, right_val, right_color)

            # Row separator
            if row_i < len(page_drivers) - 1:
                d.line([(x_off + 1, y + ROW_H - 1), (x_off + panel_w - 2, y + ROW_H - 1)],
                       fill=(25, 35, 60))

        # Page dots
        if n_pages > 1:
            dot_y   = H - 2
            dot_step = 3
            track_w  = (n_pages - 1) * dot_step + 2
            dot_x0   = x_off + panel_w - track_w - 2
            for i in range(n_pages):
                color = (0, 120, 255) if i == self._ic_scroll_idx else (40, 40, 60)
                d.rectangle([dot_x0 + i * dot_step, dot_y,
                              dot_x0 + i * dot_step + 1, dot_y + 1], fill=color)
