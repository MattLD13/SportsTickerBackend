"""IndyCar display modes.

Scroll card (128 × 32):  race name + session on top, top-3 drivers below.
Full screen (384 × 32):  left 1/4 = race info, right 3/4 = scrolling driver list.
"""

import hashlib
import io
import os
import threading
import time
from datetime import datetime
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from ..config import PANEL_W, PANEL_H, ASSETS_DIR
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


def _flood_remove_background(img, tolerance=35):
    """BFS flood-fill from all four edges to remove the connected background."""
    if img is None:
        return img
    try:
        rgba = img.convert('RGBA')
        w, h = rgba.size
        pixels = rgba.load()

        # Sample the dominant edge color as background reference
        edge_samples = []
        for x in range(w):
            edge_samples.append(pixels[x, 0][:3])
            edge_samples.append(pixels[x, h - 1][:3])
        for y in range(h):
            edge_samples.append(pixels[0, y][:3])
            edge_samples.append(pixels[w - 1, y][:3])
        # Use the most common edge color as background
        bg = max(set(edge_samples), key=edge_samples.count)

        def _similar(px):
            return (abs(int(px[0]) - bg[0]) <= tolerance and
                    abs(int(px[1]) - bg[1]) <= tolerance and
                    abs(int(px[2]) - bg[2]) <= tolerance)

        visited = [[False] * h for _ in range(w)]
        queue = []
        for x in range(w):
            if not visited[x][0] and _similar(pixels[x, 0]):
                queue.append((x, 0))
                visited[x][0] = True
            if not visited[x][h - 1] and _similar(pixels[x, h - 1]):
                queue.append((x, h - 1))
                visited[x][h - 1] = True
        for y in range(h):
            if not visited[0][y] and _similar(pixels[0, y]):
                queue.append((0, y))
                visited[0][y] = True
            if not visited[w - 1][y] and _similar(pixels[w - 1, y]):
                queue.append((w - 1, y))
                visited[w - 1][y] = True

        while queue:
            x, y = queue.pop()
            r, g, b, a = pixels[x, y]
            pixels[x, y] = (r, g, b, 0)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and not visited[nx][ny]:
                    if _similar(pixels[nx, ny]):
                        visited[nx][ny] = True
                        queue.append((nx, ny))

        return rgba
    except Exception:
        return img


_NASCAR_CAR_CACHE: dict = {}   # cache_key → PIL RGBA
_NASCAR_CAR_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Download progress tracking
_nascar_dl_lock    = threading.Lock()
_nascar_dl_total   = 0
_nascar_dl_done    = 0
_nascar_dl_pending: set = set()   # URLs not yet successfully downloaded
_nascar_dl_inflight: set = set()  # URLs currently being downloaded (prevents duplicates)


def nascar_dl_progress():
    """Return (done, total) for the current NASCAR car image download batch."""
    with _nascar_dl_lock:
        return _nascar_dl_done, _nascar_dl_total


def _load_nascar_car(url, target_size):
    """Download NASCAR car image. Tries 300x130 thumbnail first (6KB) then full 922x400 (36KB).
    Checks all date offsets (±2 days) before giving up. Disk-cached."""
    global _nascar_dl_done
    if not url:
        return None
    cache_key = f"{url}_{target_size[0]}x{target_size[1]}"
    if cache_key in _NASCAR_CAR_CACHE:
        return _NASCAR_CAR_CACHE[cache_key]

    # Deduplicate: don't download the same URL twice concurrently
    with _nascar_dl_lock:
        if url in _nascar_dl_inflight:
            return None
        _nascar_dl_inflight.add(url)

    try:
        disk_name = f"nascar_{hashlib.md5(url.encode()).hexdigest()}_{target_size[0]}x{target_size[1]}.png"
        disk_path = os.path.join(ASSETS_DIR, disk_name)
        try:
            if os.path.exists(disk_path):
                img = Image.open(disk_path).convert('RGBA')
                _NASCAR_CAR_CACHE[cache_key] = img
                with _nascar_dl_lock:
                    _nascar_dl_pending.discard(url)
                    _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
                return img
        except Exception:
            pass

        # Build candidate list: 300x130 (fast, ~6KB) at each date offset, then 922x400 fallback
        import re as _re
        from datetime import date as _date, timedelta as _td
        _m = _re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
        if _m:
            _base = _date(int(_m.group(1)), int(_m.group(2)), int(_m.group(3)))
            _prefix = url[:_m.start()]
            _fname  = url[_m.end():]                         # e.g. 26_NCS_14Dover_5-922x400.jpg
            _small  = _fname.replace('-922x400.jpg', '-300x130.jpg')
            _offsets = (0, -1, 1, -2, 2)
            # Try 300x130 at every offset first, then 922x400 at every offset
            candidates = []
            if _small != _fname:
                for _d in (_base + _td(days=o) for o in _offsets):
                    candidates.append(_prefix + f"/{_d.year}/{_d.month:02d}/{_d.day:02d}/" + _small)
            for _d in (_base + _td(days=o) for o in _offsets):
                candidates.append(_prefix + f"/{_d.year}/{_d.month:02d}/{_d.day:02d}/" + _fname)
        else:
            candidates = [url]

        raw_content = None
        used = None
        for candidate in candidates:
            try:
                r = requests.get(candidate, headers=_NASCAR_CAR_HEADERS, timeout=12)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                raw_content = r.content
                used = candidate
                break
            except Exception:
                continue

        car_id = url.rsplit('/', 1)[-1]
        if raw_content is None:
            print(f"[NASCAR] MISSING {car_id} — all {len(candidates)} candidates 404'd")
            return None

        full = Image.open(io.BytesIO(raw_content)).convert('RGBA')
        full = _flood_remove_background(full, tolerance=40)
        full = _trim_transparent_padding(full)
        full.thumbnail(target_size, Image.Resampling.LANCZOS)
        _NASCAR_CAR_CACHE[cache_key] = full
        size_used = '300x130' if '-300x130' in (used or '') else '922x400'
        print(f"[NASCAR] OK {car_id} ({size_used}, {len(raw_content)//1024}KB → {full.size})")
        try:
            os.makedirs(ASSETS_DIR, exist_ok=True)
            full.save(disk_path, 'PNG')
        except Exception:
            pass
        with _nascar_dl_lock:
            _nascar_dl_pending.discard(url)
            _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
        return full

    except Exception as _exc:
        print(f"[NASCAR] ERROR {url.rsplit('/',1)[-1]}: {_exc}")
        return None
    finally:
        with _nascar_dl_lock:
            _nascar_dl_inflight.discard(url)


def nascar_submit_downloads(urls, target_size, executor):
    """Register a batch of NASCAR car URLs and submit them to the thread pool."""
    global _nascar_dl_total, _nascar_dl_done
    urls = [u for u in urls if u]
    if not urls:
        return
    with _nascar_dl_lock:
        # Only queue URLs whose processed cache key isn't already present
        new_urls = [u for u in urls
                    if f"{u}_{target_size[0]}x{target_size[1]}" not in _NASCAR_CAR_CACHE]
        _nascar_dl_pending.update(new_urls)
        _nascar_dl_total = len(_nascar_dl_pending) + _nascar_dl_done
    for u in new_urls:
        executor.submit(_load_nascar_car, u, target_size)


def nascar_retry_pending(executor, target_size=(120, 14)):
    """Re-submit any URLs that haven't successfully downloaded yet."""
    with _nascar_dl_lock:
        pending = list(_nascar_dl_pending)
    for u in pending:
        executor.submit(_load_nascar_car, u, target_size)


_NASCAR_RACE_ID_FILE = 'nascar_race_id.txt'


def _nascar_purge_old_cars(assets_dir, race_id):
    """Delete disk-cached car images when race_id changes (new race week)."""
    race_id = str(race_id or '').strip()
    if not race_id or not assets_dir:
        return
    id_file = os.path.join(assets_dir, _NASCAR_RACE_ID_FILE)
    try:
        stored = open(id_file).read().strip() if os.path.exists(id_file) else ''
    except Exception:
        stored = ''
    if stored == race_id:
        return
    # Race week changed — purge stale car PNGs and all counters
    import logging
    logging.getLogger(__name__).info("[NASCAR] race_id changed %s→%s, purging car cache", stored, race_id)
    try:
        for fname in os.listdir(assets_dir):
            if fname.startswith('nascar_') and fname.endswith('.png'):
                try:
                    os.remove(os.path.join(assets_dir, fname))
                except Exception:
                    pass
        _NASCAR_CAR_CACHE.clear()
        global _nascar_dl_total, _nascar_dl_done
        with _nascar_dl_lock:
            _nascar_dl_total = 0
            _nascar_dl_done = 0
            _nascar_dl_pending.clear()
            _nascar_dl_inflight.clear()
        os.makedirs(assets_dir, exist_ok=True)
        with open(id_file, 'w') as f:
            f.write(race_id)
    except Exception:
        pass


def _wind_compass(value):
    try:
        deg = float(value)
    except Exception:
        return ''
    labels = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')
    return labels[int((deg + 22.5) // 45) % 8]


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


def _tiny_text_width(text, font=None):
    from ..fonts import normalize_special_chars
    text = normalize_special_chars(str(text or '').strip()).upper()
    if not text:
        return 0
    return sum(2 if ch == '~' else 5 for ch in text)


def _display_flag(flag, state):
    state = str(state or '').lower()
    if state in ('pre', 'post'):
        return 'CHECKERED'
    return str(flag or '').strip().upper() or 'GREEN'


def _key_background(img, tolerance=18):
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
                if abs(r - bg[0]) <= tolerance and abs(g - bg[1]) <= tolerance and abs(b - bg[2]) <= tolerance:
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


def _draw_condition_icon(draw, x, y, kind, color):
    kind = str(kind or '').lower()
    if kind == 'track':
        draw.line([(x, y + 4), (x + 6, y + 1)], fill=color)
        draw.line([(x, y + 5), (x + 6, y + 2)], fill=(95, 105, 120))
        draw.point((x + 3, y + 3), fill=(235, 235, 235))
    elif kind == 'air':
        draw.ellipse([x + 1, y + 1, x + 5, y + 5], outline=color)
        draw.point((x + 3, y), fill=color)
        draw.point((x + 3, y + 6), fill=color)
        draw.point((x, y + 3), fill=color)
        draw.point((x + 6, y + 3), fill=color)
    elif kind == 'wind':
        soft = (75, 130, 185)
        draw.line([(x, y + 1), (x + 5, y + 1)], fill=color)
        draw.point((x + 6, y + 2), fill=color)
        draw.point((x + 5, y + 3), fill=color)
        draw.line([(x + 1, y + 3), (x + 8, y + 3)], fill=soft)
        draw.line([(x, y + 5), (x + 4, y + 5)], fill=color)
        draw.point((x + 5, y + 4), fill=color)
        draw.point((x + 6, y + 5), fill=color)
        draw.point((x + 5, y + 6), fill=color)


def _round_weather_value(value):
    try:
        return str(int(round(float(value))))
    except Exception:
        return ''


class IndycarMixin:

    # ── helpers ──────────────────────────────────────────────────────────────

    def _ic_payload(self, game):
        return (game.get('indycar') or {}) if isinstance(game, dict) else {}

    def _ic_conditions_weather(self, provided=None):
        if isinstance(provided, dict) and (provided.get('air_temp') or provided.get('wind_mph')):
            return provided
        now = time.time()
        cached = getattr(self, '_ic_render_weather_cache', {'ts': 0.0, 'data': {}})
        if (now - cached.get('ts', 0.0)) < 300:
            return cached.get('data') or {}
        try:
            url = (
                "https://api.open-meteo.com/v1/forecast"
                "?latitude=39.7950&longitude=-86.2340"
                "&current=temperature_2m,wind_speed_10m,wind_direction_10m"
                "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
            )
            current = (requests.get(url, timeout=3).json().get('current') or {})
            data = {
                'air_temp': _round_weather_value(current.get('temperature_2m')),
                'wind_mph': _round_weather_value(current.get('wind_speed_10m')),
                'wind_dir': _round_weather_value(current.get('wind_direction_10m')),
            }
            self._ic_render_weather_cache = {'ts': now, 'data': data}
            return data
        except Exception:
            self._ic_render_weather_cache = {'ts': now, 'data': {}}
            return {}

    def _ic_load_logo(self, url, size, bg_tolerance=18):
        url = str(url or '').strip()
        if not url:
            return None
        logo = self.get_logo(url, size)
        if logo is not None:
            try:
                cleaned = logo.convert('RGBA')
                cleaned = _key_background(cleaned, bg_tolerance)
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
            cleaned = _key_background(cleaned, bg_tolerance)
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

            # Number color: badge image takes priority (team-specific), then livery_primary (F1), then grey
            if team_logo:
                num_fill, _ = _ic_sample_colors(self._ic_load_logo(team_logo, (18, 18)))
            else:
                livery_hex = str(driver.get('livery_primary') or '').strip()
                num_fill = _hex_to_rgb(livery_hex, (128, 128, 128)) if livery_hex else (180, 180, 180)

            num_text = car_num or abbr
            num_w = _tiny_text_width(num_text, self.font)
            name_w = _tiny_text_width(abbr, self.font)
            total_w = num_w + 2 + name_w
            DRIVER_LABEL_X = 34
            driver_label_w = _tiny_text_width('DRIVER', self.font)
            center_x = DRIVER_LABEL_X + (driver_label_w / 2)
            start_x = max(5, int(round(center_x - total_w / 2)))

            # White outline on dark colors (luminance < 80)
            r_c, g_c, b_c = num_fill[:3]
            luma = 0.299 * r_c + 0.587 * g_c + 0.114 * b_c
            if luma < 80:
                outline = (255, 255, 255, 200)
                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    draw_tiny_text(d, start_x + ox, y + oy, num_text, outline)
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
                      .replace('NASCAR CUP SERIES', '')
                      .replace('NASCAR XFINITY SERIES', '')
                      .replace('NASCAR CRAFTSMAN TRUCK SERIES', '')
                      .replace('NASCAR ', '')
                      .replace('  ', ' ')
                      .strip())
        # Pull " - FINAL SEGMENT" / " - FINAL" out of the name so it can be placed separately
        _final_suffix = ''
        for _fs in (' - FINAL SEGMENT', ' - FINAL', ' FINAL SEGMENT', ' FINAL'):
            if short_name.endswith(_fs):
                short_name = short_name[:-len(_fs)].strip()
                _final_suffix = 'FINAL'
                break

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

        # Available width: leave gap before the flag (or right edge)
        avail_w = panel_w - (21 if show_flag else 5) - 4   # 4px left margin
        name_px  = _tiny_text_width(short_name, self.font)

        # Draw race name at y=1 — scroll if too wide, static if it fits
        if name_px <= avail_w:
            draw_tiny_text(d, 4, 1, short_name, (255, 220, 50))
        else:
            now_t = time.time()
            if not hasattr(self, '_ic_info_scroll_x'):
                self._ic_info_scroll_x  = 0.0
                self._ic_info_scroll_ts = now_t
            dt = max(0.0, now_t - self._ic_info_scroll_ts)
            self._ic_info_scroll_ts = now_t
            GAP = 18
            total_loop = name_px + GAP
            self._ic_info_scroll_x = (self._ic_info_scroll_x + dt * 14.0) % total_loop
            offset = int(self._ic_info_scroll_x)
            tmp = Image.new('RGBA', (name_px * 2 + GAP + avail_w, 7), (0, 0, 0, 0))
            td  = ImageDraw.Draw(tmp)
            draw_tiny_text(td, 0,             0, short_name, (255, 220, 50))
            draw_tiny_text(td, name_px + GAP, 0, short_name, (255, 220, 50))
            clip = tmp.crop((offset, 0, offset + avail_w, 7))
            d._image.paste(clip, (4, 1), clip)

        variant = str(os.environ.get('INDYCAR_INFO_VARIANT') or 'conditions').strip().lower()
        if variant in ('track_map', 'conditions'):
            weather = self._ic_conditions_weather(ic.get('weather'))
            air = str(weather.get('air_temp') or '--').strip()
            wind = str(weather.get('wind_mph') or '--').strip()
            wind_dir = _wind_compass(weather.get('wind_dir')) or '--'
            draw_tiny_text(d, 4, 8, session[:11], (180, 210, 255))
            _draw_condition_icon(d, 5, 17, 'air', (255, 220, 50))
            draw_tiny_text(d, 15, 16, f"{air}F", (255, 255, 255))
            _draw_condition_icon(d, 5, 26, 'wind', (115, 190, 255))
            draw_tiny_text(d, 15, 25, f"{wind}-{wind_dir}", (180, 210, 255))
            return
        if variant == 'leader':
            drivers = ic.get('drivers', [])
            leader = next((drv for drv in drivers if isinstance(drv, dict) and str(drv.get('pos') or '') == '1'), None)
            if not leader and isinstance(drivers, list) and drivers:
                leader = next((drv for drv in drivers if isinstance(drv, dict)), None)
            lead_car = str((leader or {}).get('car') or '').strip()
            lead_abbr = str((leader or {}).get('abbr') or '').strip().upper()
            lead_speed = str((leader or {}).get('speed') or (leader or {}).get('gap') or '').strip()
            draw_tiny_text(d, 4, 8, 'P1', (255, 220, 50))
            if lead_car:
                d.text((4, 13), lead_car, font=getattr(self, 'medium_font', self.font), fill=(255, 255, 255))
            if lead_abbr:
                draw_tiny_text(d, 37, 15, lead_abbr[:3], (180, 210, 255))
            metric = lead_speed[:10] if lead_speed else session[:10]
            draw_tiny_text(d, 4, 24, metric, (255, 255, 255))
            return

        y_session = 7
        draw_tiny_text(d, 4, y_session, session, (180, 210, 255))

        y_info = y_session + 7
        max_chars = max(4, avail_w // 5)
        if state == 'post' or _final_suffix:
            info_str = 'FINAL'
        elif is_qual and time_to_go:
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

        if info_str:
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
                primary = _hex_to_rgb(driver.get('livery_primary'), (120, 120, 130))
                secondary = _hex_to_rgb(driver.get('livery_secondary'), (20, 20, 24))
                cd.rectangle([0, 0, card_w - 1, card_h - 1], fill=(12, 12, 18))
                cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(60, 60, 72), width=1)
                if pos == '1':
                    cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(255, 215, 0), width=1)

                if car_image:
                    is_nascar_img = 'nascar.com' in car_image
                    if is_nascar_img:
                        # Use the same size as the pre-fetch so _NASCAR_CAR_CACHE hits
                        car_img = _load_nascar_car(car_image, (120, 14))
                    else:
                        car_img = self._ic_load_logo(car_image, (120, 19))
                    if car_img:
                        car_img = _trim_transparent_padding(car_img)
                        car_x = 1
                        car_y = max(0, card_h - car_img.height - 1)
                        card.paste(car_img, (car_x, car_y), car_img)
                elif hasattr(self, '_draw_f1_generated_car') and str(driver.get('team') or ''):
                    fallback_w = min(120, card_w - 2)
                    self._draw_f1_generated_car(card, 1, 14, fallback_w, 15, primary + (255,), secondary + (255,))
                elif car_num:
                    draw_tiny_text(cd, 5, 19, car_num, (110, 110, 122))

                pos_color = (255, 215, 0) if pos == '1' else (180, 180, 180)
                cd.text((4, 0), place_text, font=self.font, fill=pos_color)

                if car_num:
                    if team_logo:
                        num_fill, _num_outline = _ic_sample_colors(self._ic_load_logo(team_logo, (18, 18)))
                    else:
                        num_fill = primary
                    num_w, _ = _text_size(cd, car_num, self.font)
                    num_x = card_w - int(num_w) - 5
                    r_c, g_c, b_c = num_fill[:3]
                    if 0.299 * r_c + 0.587 * g_c + 0.114 * b_c < 80:
                        outline_col = (255, 255, 255, 200)
                        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            cd.text((num_x + ox, oy), car_num, font=self.font, fill=outline_col)
                    cd.text((num_x, 0), car_num, font=self.font, fill=num_fill)

                name_w, _ = _text_size(cd, name, name_font)
                name_x = max(4, card_w - int(name_w) - 5)
                cd.text((name_x, 10), name, font=name_font, fill=(255, 255, 255))

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
