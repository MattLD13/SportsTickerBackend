"""IndyCar display modes.

Scroll card (128 × 32):  race name + session on top, top-3 drivers below.
Full screen (384 × 32):  left 1/4 = race info, right 3/4 = scrolling driver list.
"""

import time
from datetime import datetime
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
        d.rectangle([x, y + 1, x + 8, y + 6], fill=(240, 240, 240), outline=(35, 35, 35))
        for yy in range(1, 6):
            for xx in range(0, 9):
                if (xx + yy) % 2 == 0:
                    d.point((x + xx, y + yy), fill=(45, 45, 45))
    else:
        d.rectangle([x, y + 1, x + 8, y + 6], fill=fill, outline=(35, 35, 35))


def _render_number_badge(text, font, fg=(235, 235, 235), scale=2):
    text = str(text or '').strip()
    if not text:
        return None
    try:
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
    except Exception:
        text_w = max(4, len(text) * 4)
    base_w = max(8, text_w + 2)
    badge = Image.new("RGBA", (base_w, 7), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    draw_tiny_text(bd, max(0, (base_w - text_w) // 2), 0, text, fg)
    if scale > 1:
        badge = badge.resize((base_w * scale, 7 * scale), Image.Resampling.NEAREST)
    return badge


def _format_indycar_time(value):
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        cleaned = text.replace('Z', '+00:00')
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime('%I:%M %p').lstrip('0')
    except Exception:
        return text


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


def _group_width(text, badge_text, font, badge_scale=2):
    txt = str(text or '').strip()
    badge = _render_number_badge(badge_text, font, scale=badge_scale)
    return _tiny_text_width(txt, font) + (2 if badge else 0) + (badge.width if badge else 0)


def _tiny_text_width(text, font):
    text = str(text or '').strip()
    if not text:
        return 0
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * 4


def _display_flag(flag, state):
    state = str(state or '').lower()
    if state in ('pre', 'post'):
        return 'CHECKERED'
    return str(flag or '').strip().upper() or 'GREEN'


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
        state = str(game.get('state', 'pre')).lower()
        _draw_mini_flag(d, W - 12, 0, _display_flag(ic.get('flag'), state))

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
            team_logo = str(driver.get('team_logo') or '').strip()

            # Right column: speed for qualifying, gap for race
            if is_qual:
                right_val = str(driver.get('speed') or driver.get('gap') or '').strip()[:7]
            else:
                right_val = str(driver.get('gap') or '').strip()[:12]

            # Position number
            pos_color = (255, 215, 0) if pos == '1' else (200, 200, 200)
            draw_tiny_text(d, 1, y, pos, pos_color)

            # Center the 3-letter code and number image as one unit.
            badge = self.get_logo(team_logo, (10, 10)) if team_logo else _render_number_badge(car_num, self.font, fg=(180, 210, 255), scale=2)
            group_w = _tiny_text_width(abbr, self.font) + (2 if badge else 0) + (badge.width if badge else 0)
            start_x = max(24, int(round(58 - group_w / 2)))
            draw_tiny_text(d, start_x, y, abbr, (255, 255, 255))
            if badge:
                badge_x = start_x + _tiny_text_width(abbr, self.font) + 2
                badge_y = max(0, y - 1)
                img.paste(badge, (badge_x, badge_y), badge)

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
            start_txt = _format_indycar_time(start_utc)
            info_str = f"STARTS {start_txt}"[:max_chars]
        elif time_to_go:
            info_str = time_to_go[:max_chars]
        else:
            info_str = 'STARTS SOON' if state == 'pre' else str(game.get('status', '')).upper()[:max_chars]

        draw_tiny_text(d, 4, y_info, info_str, (255, 255, 255))

        # Flag indicator
        y_flag = y_info + 7
        if y_flag + 5 <= H and flag and flag not in ('GREEN', ''):
            _draw_mini_flag(d, 0, y_flag, _display_flag(flag, state))

    def _ic_draw_driver_panel(self, img, d, drivers, x_off, panel_w, H, is_qual=False):
        """Draw the scrolling driver leaderboard into the right 3/4 panel."""
        now = time.time()
        if not hasattr(self, '_ic_hscroll_x'):
            self._ic_hscroll_x = 0.0
            self._ic_hscroll_ts = now

        elapsed = max(0.0, now - self._ic_hscroll_ts)
        self._ic_hscroll_ts = now

        panel = Image.new('RGBA', (panel_w, H), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)

        visible = [dict(drv) for drv in drivers if isinstance(drv, dict)]
        if not visible:
            pd.rectangle([0, 0, panel_w - 1, H - 1], fill=(8, 8, 16))
            draw_tiny_text(pd, 8, 12, 'LOADING', (120, 120, 120))
            img.paste(panel, (x_off, 0), panel)
            return

        # Sort by race position when available.
        def _pos_sort_key(drv):
            try:
                return int(str(drv.get('pos') or 999).lstrip('T'))
            except Exception:
                return 999

        visible.sort(key=_pos_sort_key)

        card_w = 88
        card_h = H - 2
        gap = 4
        row_speed = 16.0 if len(visible) > 6 else 12.0

        cards = []
        for driver in visible:
            card = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
            cd = ImageDraw.Draw(card)
            pos = str(driver.get('pos') or '')
            name = str(driver.get('name') or driver.get('abbr') or '???').strip()
            car_num = str(driver.get('car') or '').strip()
            team_logo = str(driver.get('team_logo') or '').strip()
            car_image = str(driver.get('car_illustration') or '').strip()
            gap_val = str(driver.get('gap') or '').strip()
            cd.rectangle([0, 0, card_w - 1, card_h - 1], fill=(12, 12, 18))
            cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(60, 60, 72), width=1)
            if pos == '1':
                cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(255, 215, 0), width=1)

            pos_color = (255, 215, 0) if pos == '1' else (180, 180, 180)
            draw_tiny_text(cd, 3, 2, pos, pos_color)

            name = name[:18]
            name_width = _tiny_text_width(name, self.font)
            badge = self.get_logo(team_logo, (11, 11)) if team_logo else _render_number_badge(car_num, self.font, fg=(205, 225, 255), scale=3)
            badge_w = badge.width if badge else 0
            group_w = name_width + (2 if badge else 0) + badge_w
            group_x = max(5, int((card_w - group_w) / 2))
            draw_tiny_text(cd, group_x, 2, name, (255, 255, 255))
            if badge:
                card.paste(badge, (group_x + name_width + 2, 1), badge)

            if car_image:
                car_img = self.get_logo(car_image, (36, 12))
                if car_img:
                    car_x = max(4, int((card_w - car_img.width) / 2))
                    card.paste(car_img, (car_x, 12), car_img)
            elif car_num:
                draw_tiny_text(cd, 6, 13, car_num, (110, 110, 122))

            if is_qual:
                right_val = str(driver.get('speed') or driver.get('gap') or '').strip()[:8]
            else:
                right_val = gap_val[:10]
            if right_val:
                rv_w = _tiny_text_width(right_val, self.font)
                draw_tiny_text(cd, max(4, card_w - rv_w - 4), 22, right_val, (140, 190, 255) if pos != '1' else (255, 255, 255))

            cards.append(card)

        strip_w = sum(card.width for card in cards) + gap * len(cards)
        if strip_w <= 0:
            img.paste(panel, (x_off, 0), panel)
            return

        if len(cards) == 1:
            # Keep a single card centered instead of scrolling pointlessly.
            x = max(0, (panel_w - cards[0].width) // 2)
            panel.paste(cards[0], (x, 1), cards[0])
            img.paste(panel, (x_off, 0), panel)
            return

        # Advance the horizontal scroll and crop a continuous strip.
        self._ic_hscroll_x = (self._ic_hscroll_x + elapsed * row_speed) % strip_w

        strip = Image.new('RGBA', (strip_w + panel_w, H), (0, 0, 0, 0))
        sx = 0
        i = 0
        while sx < strip.width:
            card = cards[i % len(cards)]
            strip.paste(card, (sx, 1), card)
            sx += card.width + gap
            i += 1

        view_x = int(self._ic_hscroll_x)
        view = strip.crop((view_x, 0, view_x + panel_w, H))
        panel.alpha_composite(view)
        img.paste(panel, (x_off, 0), panel)
