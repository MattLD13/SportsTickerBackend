"""IndyCar display modes.

Scroll card (128 × 32):  race name + session on top, top-3 drivers below.
Full screen (384 × 32):  left 1/4 = race info, right 3/4 = scrolling driver list.
"""

import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFilter, ImageOps
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


def _draw_flag(d, x, y, flag, w=15, h=10):
    fill = _ic_flag_color(flag)
    flag_name = str(flag or '').strip().upper()
    d.rectangle([x - 1, y - 1, x + w, y + h], fill=(6, 8, 12), outline=(120, 130, 145))
    if flag_name == 'CHECKERED':
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=(240, 240, 240), outline=(35, 35, 35))
        cell = 2
        for yy in range(y + 1, y + h - 1):
            for xx in range(x + 1, x + w - 1):
                if (((xx - x) // cell) + ((yy - y) // cell)) % 2 == 0:
                    d.point((xx, yy), fill=(45, 45, 45))
    else:
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=fill, outline=(35, 35, 35))


def _ordinal_place(value):
    text = str(value or '').strip()
    try:
        num = int(text.lstrip('T'))
    except Exception:
        return f"{text} place" if text else ''
    if 10 <= (num % 100) <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(num % 10, 'th')
    return f"{num}{suffix} place"


def _text_size(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), str(text), font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        try:
            return draw.textlength(str(text), font=font), 8
        except Exception:
            return len(str(text)) * 6, 8


def _trim_transparent_padding(img):
    if img is None:
        return None
    try:
        rgba = img.convert('RGBA')
        bbox = rgba.getbbox()
        return rgba.crop(bbox) if bbox else rgba
    except Exception:
        return img


def _render_number_badge(text, font, fg=(235, 235, 235), scale=2):
    text = str(text or '').strip()
    if not text:
        return None
    try:
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
    except Exception:
        text_w = max(4, len(text) * 4)
    base_w = max(6, text_w + 1)
    badge = Image.new("RGBA", (base_w, 5), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    draw_tiny_text(bd, max(0, (base_w - text_w) // 2), 0, text, fg)
    if scale > 1:
        badge = badge.resize((base_w * scale, 5 * scale), Image.Resampling.NEAREST)
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


def _key_background(img):
    if img is None:
        return None
    try:
        rgba = img.convert('RGBA')
        pixels = rgba.load()
        width, height = rgba.size
        corners = [pixels[0, 0], pixels[max(0, width - 1), 0], pixels[0, max(0, height - 1)], pixels[max(0, width - 1), max(0, height - 1)]]
        bg = max(corners, key=corners.count)
        for y in range(height):
            for x in range(width):
                r, g, b, a = pixels[x, y]
                if a == 0:
                    continue
                if abs(r - bg[0]) <= 18 and abs(g - bg[1]) <= 18 and abs(b - bg[2]) <= 18:
                    pixels[x, y] = (r, g, b, 0)
        return rgba
    except Exception:
        return img


def _ic_sample_colors(img, fallback=((235, 235, 235), (35, 35, 35))):
    if img is None:
        return fallback
    try:
        rgba = _key_background(img)
        if rgba is None:
            return fallback
        small = rgba.convert('RGBA').resize((18, 18), Image.Resampling.NEAREST)
        colors = small.getcolors(18 * 18) or []
        ranked = sorted(colors, key=lambda item: item[0], reverse=True)
        picked = []
        for _, col in ranked:
            if len(col) == 4:
                r, g, b, a = col
                if a < 40:
                    continue
            else:
                r, g, b = col[:3]
            rgb = (int(r), int(g), int(b))
            if max(rgb) < 24 or min(rgb) > 232:
                continue
            if (max(rgb) - min(rgb)) < 18:
                continue
            if any(sum(abs(rgb[i] - prev[i]) for i in range(3)) < 40 for prev in picked):
                continue
            picked.append(rgb)
            if len(picked) >= 2:
                break
        if len(picked) == 1:
            picked.append(fallback[1])
        return tuple(picked[:2]) if picked else fallback
    except Exception:
        return fallback


def _draw_tiny_text_outline(draw, x, y, text, fill, outline):
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            draw_tiny_text(draw, x + dx, y + dy, text, outline)
    draw_tiny_text(draw, x, y, text, fill)


class IndycarMixin:

    # ── helpers ──────────────────────────────────────────────────────────────

    def _ic_payload(self, game):
        return (game.get('indycar') or {}) if isinstance(game, dict) else {}

    def _ic_load_logo(self, url, size):
        url = str(url or '').strip()
        if not url:
            return None
        logo = self.get_logo(url, size)
        if logo is not None:
            try:
                cleaned = logo.convert('RGBA')
                cleaned = _key_background(cleaned)
                cleaned = ImageOps.autocontrast(cleaned)
                cleaned = cleaned.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.SHARPEN)
                return cleaned
            except Exception:
                return logo
        try:
            self.download_and_process_logo(url, size)
        except Exception:
            pass
        logo = self.get_logo(url, size)
        if logo is None:
            return None
        try:
            cleaned = logo.convert('RGBA')
            cleaned = _key_background(cleaned)
            cleaned = ImageOps.autocontrast(cleaned)
            cleaned = cleaned.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.SHARPEN)
            return cleaned
        except Exception:
            return logo

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
        # Prefer explicit session_name when provided (e.g., "Qualifying - Round 1")
        session = str(ic.get('session_name') or ic.get('session_type') or 'Race').strip()
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
        try:
            print(f"INDYCAR_SCROLL: drivers_count={len(drivers)}")
        except Exception:
            pass

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
            draw_tiny_text(d, 0, y, pos, pos_color)

            # Put the number text to the left of the driver code.
            num_fill, _num_outline = _ic_sample_colors(self._ic_load_logo(team_logo, (18, 18)))
            num_text = car_num or abbr
            num_w = _tiny_text_width(num_text, self.font)
            name_w = _tiny_text_width(abbr, self.font)
            total_w = num_w + 2 + name_w
            # Center the (number + name) group on the DRIVER label's center
            DRIVER_LABEL_X = 34
            driver_label_w = _tiny_text_width('DRIVER', self.font)
            center_x = DRIVER_LABEL_X + (driver_label_w / 2)
            start_x = max(5, int(round(center_x - total_w / 2)))
            draw_tiny_text(d, start_x, y, num_text, num_fill)
            draw_tiny_text(d, start_x + num_w + 2, y, abbr, (255, 255, 255))

            # Right column value
            if right_val:
                val_x = min(82, W - len(right_val) * 4 - 2)
                val_color = (255, 255, 255) if pos == '1' else (180, 210, 255)
                draw_tiny_text(d, val_x, y, right_val, val_color)

        if not top3:
            # Show session starting info when drivers have not yet run
            start_utc = str(game.get('startTimeUTC') or '').strip()
            start_txt = _format_indycar_time(start_utc) if start_utc else ''
            session_label = self._ic_header_label(ic)
            # Draw the session label and starts text centered in the driver area
            draw_tiny_text(d, max(2, int((W - _tiny_text_width(session_label, self.font)) / 2)), 16, session_label, (180, 210, 255))
            if start_txt:
                starts = f"STARTS {start_txt}"
                draw_tiny_text(d, max(2, int((W - _tiny_text_width(starts, self.font)) / 2)), 23, starts, (200, 200, 200))

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
        INFO_W = 84
        RACE_W = W - INFO_W

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

        flag = str(ic.get('flag') or '').upper()

        # ── Left panel: race info ────────────────────────────────────────────
        self._ic_draw_info_panel(d, ic, game, INFO_W, H)

        # ── Right panel: scrolling driver list or session info ─────────────
        if drivers:
            self._ic_draw_driver_panel(img, d, drivers, INFO_W, RACE_W, H, is_qual=is_qual)
        else:
            # No drivers yet: present session label and start time centered
            start_utc = str(game.get('startTimeUTC') or '').strip()
            start_txt = _format_indycar_time(start_utc) if start_utc else ''
            session_label = self._ic_header_label(ic)
            # draw into right panel area
            text_x = INFO_W + max(4, int((RACE_W - _tiny_text_width(session_label, self.font)) / 2))
            draw_tiny_text(d, text_x, 10, session_label, (180, 210, 255))
            if start_txt:
                starts = f"STARTS {start_txt}"
                text_x2 = INFO_W + max(4, int((RACE_W - _tiny_text_width(starts, self.font)) / 2))
                draw_tiny_text(d, text_x2, 18, starts, (200, 200, 200))

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

        # Accent bar: match the displayed flag color.
        bar_color = _ic_flag_color(_display_flag(flag, state))
        d.rectangle([0, 0, 2, H], fill=bar_color)

        flag_name = _display_flag(flag, state)
        show_flag = bool(flag_name)
        if show_flag:
            _draw_flag(d, panel_w - 17, 1, flag_name, w=15, h=10)

        title_w = panel_w - (24 if show_flag else 6)
        max_chars = max(4, title_w // 4)
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
        try:
            print(f"INDYCAR_PANEL: visible_count={len(visible)} panel_w={panel_w}")
        except Exception:
            pass
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

        min_card_w = 132
        card_h = H - 2
        gap = 6
        ticker_sleep = float(getattr(self, 'scroll_sleep', 0.05) or 0.05)
        row_speed = 1.0 / max(0.001, ticker_sleep)

        cache_key = (
            panel_w,
            H,
            bool(is_qual),
            tuple(
                (
                    str(drv.get('pos') or ''),
                    str(drv.get('name') or drv.get('abbr') or ''),
                    str(drv.get('car') or ''),
                    str(drv.get('team_logo') or ''),
                    str(drv.get('car_illustration') or ''),
                    str(drv.get('gap') or ''),
                    str(drv.get('speed') or ''),
                )
                for drv in visible
            ),
        )
        cached = getattr(self, '_ic_driver_strip_cache', None)
        if cached and cached.get('key') == cache_key:
            cards = cached.get('cards') or []
            strip = cached.get('strip')
            strip_w = int(cached.get('strip_w') or 0)
        else:
            cards = []
            for driver in visible:
                pos = str(driver.get('pos') or '')
                name = str(driver.get('name') or driver.get('abbr') or '???').strip()
                car_num = str(driver.get('car') or '').strip()
                place_text = _ordinal_place(pos)
                name_font = self.font
                name_w, _ = _text_size(pd, name, name_font)
                if name_w > 72:
                    name_font = getattr(self, 'tiny', self.font)
                    name_w, _ = _text_size(pd, name, name_font)
                if name_w > 84:
                    name_font = getattr(self, 'tiny_small', name_font)
                    name_w, _ = _text_size(pd, name, name_font)
                place_w, _ = _text_size(pd, place_text, self.font)
                num_w, _ = _text_size(pd, car_num, self.font)
                card_w = max(min_card_w, int(name_w) + 24, int(place_w + num_w) + 18)
                card = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
                cd = ImageDraw.Draw(card)
                team_logo = str(driver.get('team_logo') or '').strip()
                car_image = str(driver.get('car_illustration') or '').strip()
                gap_val = str(driver.get('gap') or '').strip()
                cd.rectangle([0, 0, card_w - 1, card_h - 1], fill=(12, 12, 18))
                cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(60, 60, 72), width=1)
                if pos == '1':
                    cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(255, 215, 0), width=1)

                pos_color = (255, 215, 0) if pos == '1' else (180, 180, 180)
                cd.text((4, 0), place_text, font=self.font, fill=pos_color)

                if car_num:
                    num_fill, _num_outline = _ic_sample_colors(self._ic_load_logo(team_logo, (18, 18)))
                    num_w, _ = _text_size(cd, car_num, self.font)
                    cd.text((card_w - int(num_w) - 5, 0), car_num, font=self.font, fill=num_fill)

                name_w, _ = _text_size(cd, name, name_font)
                name_x = max(4, card_w - int(name_w) - 5)
                cd.text((name_x, 8), name, font=name_font, fill=(255, 255, 255))

                if car_image:
                    car_img = self._ic_load_logo(car_image, (120, 16))
                    if car_img:
                        car_img = _trim_transparent_padding(car_img)
                        car_x = 1
                        car_y = max(14, card_h - car_img.height - 1)
                        card.paste(car_img, (car_x, car_y), car_img)
                elif car_num:
                    draw_tiny_text(cd, 5, 19, car_num, (110, 110, 122))

                if is_qual:
                    right_val = str(driver.get('speed') or driver.get('gap') or '').strip()[:8]
                else:
                    right_val = gap_val[:10]
                if right_val:
                    rv_w = _tiny_text_width(right_val, self.font)
                    draw_tiny_text(cd, max(4, card_w - rv_w - 4), 23, right_val, (140, 190, 255) if pos != '1' else (255, 255, 255))

                cards.append(card)

            strip_w = sum(card.width for card in cards) + gap * len(cards)
            strip = Image.new('RGBA', (strip_w + panel_w, H), (0, 0, 0, 0))
            sx = 0
            i = 0
            while sx < strip.width and cards:
                card = cards[i % len(cards)]
                strip.paste(card, (sx, 1), card)
                sx += card.width + gap
                i += 1
            self._ic_driver_strip_cache = {'key': cache_key, 'cards': cards, 'strip': strip, 'strip_w': strip_w}

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

        view_x = int(self._ic_hscroll_x)
        view = strip.crop((view_x, 0, view_x + panel_w, H))
        panel.alpha_composite(view)
        img.paste(panel, (x_off, 0), panel)
