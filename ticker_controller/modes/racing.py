"""Generic racing display mode for LED matrix panels.

All motor-sport series (IndyCar, F1, NASCAR, WEC, MotoGP, …) share the
same two-layout system:

  Scroll card  (128 × 32) — compact strip: race name + top-3 drivers
  Full screen  (384 × 32) — left 1/4 info panel, right 3/4 driver list

Series-specific adapters (indycar.py, f1.py, nascar.py, …) simply map
their payload key into game['indycar'] (the canonical slot used here)
and then delegate to draw_racing_scroll_card / draw_racing_full.
"""

import concurrent.futures
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


# ── Colour helpers ────────────────────────────────────────────────────────────

def _hex_to_rgb(h, fallback=(128, 128, 128)):
    try:
        h = str(h or '').strip().lstrip('#')
        if len(h) == 6:
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return fallback


def racing_flag_color(flag):
    """Map a normalised flag string to an RGB colour for LED display.

    Covers F1, IndyCar, NASCAR, WEC, IMSA, DTM, Formula E, MotoGP,
    Nürburgring / VLN, and any other motor-sport series.
    Unknown flags fall back to dim blue so they stand out visually.
    """
    flag = str(flag or '').strip().upper()
    return {
        # ── Green ──────────────────────────────────────────────────────────
        'GREEN':               (55, 190, 90),
        'CLEAR':               (55, 190, 90),
        'ROLLING START':       (55, 190, 90),
        'FORMATION LAP':       (55, 190, 90),

        # ── Yellow — plain / full-course / local ──────────────────────────
        'YELLOW':              (255, 215, 0),
        'DOUBLE YELLOW':       (255, 215, 0),
        'CAUTION':             (255, 215, 0),   # NASCAR / IndyCar
        'DEBRIS':              (255, 215, 0),   # NASCAR debris caution
        'FCY':                 (255, 215, 0),   # WEC Full Course Yellow
        'FULL COURSE YELLOW':  (255, 215, 0),
        'LOCAL YELLOW':        (255, 215, 0),   # WEC / IMSA local sector
        'SLOW ZONE':           (255, 215, 0),   # WEC slow zone
        'CODE 60':             (255, 215, 0),   # Nürburgring / VLN (60 km/h)
        'CODE60':              (255, 215, 0),
        'WAVE AROUND':         (255, 215, 0),   # NASCAR (free pass lap)
        'LUCKY DOG':           (255, 215, 0),   # NASCAR (free pass recipient)

        # ── Safety Car / VSC / Pace Car — orange (distinct from yellow) ───
        'SAFETY CAR':          (255, 140, 0),
        'SC':                  (255, 140, 0),
        'PACE CAR':            (255, 140, 0),   # NASCAR / IMSA
        'PACE':                (255, 140, 0),
        'VSC':                 (255, 140, 0),   # Virtual Safety Car (F1/WEC)
        'VIRTUAL SAFETY CAR':  (255, 140, 0),
        'VSC ENDING':          (255, 185, 0),   # VSC winding down
        'SC ENDING':           (255, 185, 0),
        'NEUTRALISED':         (255, 140, 0),   # Rallycross / Pikes Peak
        'NEUTRALIZED':         (255, 140, 0),

        # ── Red ────────────────────────────────────────────────────────────
        'RED':                 (230, 70, 70),
        'RED FLAG':            (230, 70, 70),

        # ── White — final lap ──────────────────────────────────────────────
        'WHITE':               (230, 230, 230),
        'OIL FLAG':            (230, 230, 230),   # WEC / MotoGP fluid on track

        # ── Checkered — session end ───────────────────────────────────────
        'CHECKERED':           (235, 235, 235),
        'GWC':                 (55, 190, 90),     # Green-White-Checkered: starts green

        # ── Blue — backmarker / pass instruction ──────────────────────────
        'BLUE':                (60, 100, 235),

        # ── Black — penalty / DSQ ─────────────────────────────────────────
        'BLACK':               (30, 30, 30),
        'MEATBALL':            (30, 30, 30),      # Black flag + orange disc (NASCAR mechanical)
        'BLACK AND WHITE':     (130, 130, 130),   # Warning (unsportsmanlike)
        'BLACK WHITE':         (130, 130, 130),

        # ── MotoGP specific ───────────────────────────────────────────────
        'FLAG TO FLAG':        (55, 190, 90),     # Wet-to-dry bike swap, race continues
        'FTF':                 (55, 190, 90),

    }.get(flag, (0, 80, 180))   # dim blue = unrecognised flag


# Keep the old private name so any code that imported it directly still works.
_ic_flag_color = racing_flag_color


# ── Flag drawing helpers ──────────────────────────────────────────────────────

def _draw_mini_flag(d, x, y, flag):
    """Draw a small flag indicator (9 × 6 px visible area).

    Custom patterns for flags with distinct visual designs; solid fill
    from racing_flag_color() for everything else.
    """
    flag_name = str(flag or '').strip().upper()
    # Bounding box
    bx0, by0, bx1, by1 = x, y + 1, x + 8, y + 6
    OL = (35, 35, 35)

    if flag_name == 'CHECKERED':
        d.rectangle([bx0, by0, bx1, by1], fill=(240, 240, 240))
        for yy in range(by0, by1 + 1):
            for xx in range(bx0, bx1 + 1):
                if (xx + yy) % 2 == 0:
                    d.point((xx, yy), fill=(45, 45, 45))

    elif flag_name == 'GWC':
        # Green-White-Checkered: full checker with green replacing black
        d.rectangle([bx0, by0, bx1, by1], fill=(240, 240, 240))
        for yy in range(by0, by1 + 1):
            for xx in range(bx0, bx1 + 1):
                if (xx + yy) % 2 == 0:
                    d.point((xx, yy), fill=(55, 190, 90))

    elif flag_name == 'MEATBALL':
        # NASCAR black flag with central orange disc
        d.rectangle([bx0, by0, bx1, by1], fill=(20, 20, 20))
        cx, cy = (bx0 + bx1) // 2, (by0 + by1) // 2
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(255, 120, 0))

    elif flag_name in ('BLACK AND WHITE', 'BLACK WHITE'):
        # NASCAR warning flag: white base, black upper-left triangle
        d.rectangle([bx0, by0, bx1, by1], fill=(240, 240, 240))
        d.polygon([(bx0, by0), (bx1, by0), (bx0, by1)], fill=(20, 20, 20))

    elif flag_name == 'DOUBLE YELLOW':
        # Dark background with two yellow bands (top + bottom)
        d.rectangle([bx0, by0, bx1, by1], fill=(20, 15, 0))
        mid = (by0 + by1) // 2
        d.rectangle([bx0, by0, bx1, mid - 1], fill=(255, 215, 0))
        d.rectangle([bx0, mid + 1, bx1, by1], fill=(255, 215, 0))

    elif flag_name == 'BLUE':
        # Blue flag with diagonal yellow stripe (lower-left → upper-right)
        d.rectangle([bx0, by0, bx1, by1], fill=(60, 100, 235))
        d.line([(bx0 + 1, by1), (bx1, by0 + 1)], fill=(255, 215, 0))
        d.line([(bx0 + 2, by1), (bx1, by0 + 2)], fill=(255, 215, 0))

    elif flag_name in ('VSC ENDING', 'SC ENDING'):
        # Left orange (still SC), right green (about to go green)
        mid = (bx0 + bx1) // 2
        d.rectangle([bx0, by0, mid, by1], fill=(255, 140, 0))
        d.rectangle([mid + 1, by0, bx1, by1], fill=(55, 190, 90))

    elif flag_name in ('FLAG TO FLAG', 'FTF'):
        # Left sky-blue (wet/rain), right green (dry)
        mid = (bx0 + bx1) // 2
        d.rectangle([bx0, by0, mid, by1], fill=(100, 160, 220))
        d.rectangle([mid + 1, by0, bx1, by1], fill=(55, 190, 90))

    else:
        d.rectangle([bx0, by0, bx1, by1], fill=racing_flag_color(flag_name))

    d.rectangle([bx0, by0, bx1, by1], outline=OL)


def _draw_flag(d, x, y, flag, w=15, h=10):
    """Draw a flag icon (w × h px, default 15 × 10).

    Custom patterns for flags with distinct visual designs; solid fill
    from racing_flag_color() for everything else.
    """
    flag_name = str(flag or '').strip().upper()

    # Drop-shadow / background halo
    d.rectangle([x - 1, y - 1, x + w, y + h], fill=(6, 8, 12), outline=(120, 130, 145))

    # Flag outer bounds and inner area (inside 1 px outline)
    x0, y0, x1, y1 = x, y, x + w - 1, y + h - 1
    ix0, iy0, ix1, iy1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1
    OL = (35, 35, 35)

    if flag_name == 'CHECKERED':
        d.rectangle([x0, y0, x1, y1], fill=(240, 240, 240), outline=OL)
        cell = 2
        for yy in range(iy0, iy1 + 1):
            for xx in range(ix0, ix1 + 1):
                if (((xx - ix0) // cell) + ((yy - iy0) // cell)) % 2 == 0:
                    d.point((xx, yy), fill=(45, 45, 45))

    elif flag_name == 'GWC':
        # Green-White-Checkered: full checker with green replacing black
        d.rectangle([x0, y0, x1, y1], fill=(240, 240, 240), outline=OL)
        cell = 2
        for yy in range(iy0, iy1 + 1):
            for xx in range(ix0, ix1 + 1):
                if (((xx - ix0) // cell) + ((yy - iy0) // cell)) % 2 == 0:
                    d.point((xx, yy), fill=(55, 190, 90))

    elif flag_name == 'MEATBALL':
        # NASCAR mechanical: black flag with central orange disc
        d.rectangle([x0, y0, x1, y1], fill=(20, 20, 20), outline=OL)
        cx = (x0 + x1) // 2
        cy = (y0 + y1) // 2
        r  = max(2, min(w, h) // 3)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 120, 0))

    elif flag_name in ('BLACK AND WHITE', 'BLACK WHITE'):
        # NASCAR warning flag: white base, black upper-left triangle
        d.rectangle([x0, y0, x1, y1], fill=(240, 240, 240), outline=OL)
        d.polygon([(ix0, iy0), (ix1, iy0), (ix0, iy1)], fill=(20, 20, 20))
        d.rectangle([x0, y0, x1, y1], outline=OL)

    elif flag_name == 'DOUBLE YELLOW':
        # Dark background with two yellow bands (top + bottom)
        d.rectangle([x0, y0, x1, y1], fill=(20, 15, 0), outline=OL)
        stripe_h = max(2, (iy1 - iy0 + 1) // 3)
        d.rectangle([ix0, iy0, ix1, iy0 + stripe_h - 1], fill=(255, 215, 0))
        d.rectangle([ix0, iy1 - stripe_h + 1, ix1, iy1], fill=(255, 215, 0))

    elif flag_name == 'BLUE':
        # Blue flag with diagonal yellow stripe (lower-left → upper-right)
        d.rectangle([x0, y0, x1, y1], fill=(60, 100, 235), outline=OL)
        for i in range(3):
            d.line([(ix0 + i, iy1), (ix1, iy0 + i)], fill=(255, 215, 0))

    elif flag_name in ('VSC ENDING', 'SC ENDING'):
        # Left orange (still under SC), right green (restart imminent)
        mid = (x0 + x1) // 2
        d.rectangle([x0, y0, mid, y1], fill=(255, 140, 0))
        d.rectangle([mid + 1, y0, x1, y1], fill=(55, 190, 90))
        d.rectangle([x0, y0, x1, y1], outline=OL)

    elif flag_name in ('FLAG TO FLAG', 'FTF'):
        # Left sky-blue (wet/rain track), right green (dry/slick)
        mid = (x0 + x1) // 2
        d.rectangle([x0, y0, mid, y1], fill=(100, 160, 220))
        d.rectangle([mid + 1, y0, x1, y1], fill=(55, 190, 90))
        d.rectangle([x0, y0, x1, y1], outline=OL)

    else:
        d.rectangle([x0, y0, x1, y1], fill=racing_flag_color(flag_name), outline=OL)


# ── Misc helpers ──────────────────────────────────────────────────────────────

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


def _flood_remove_background(img, tolerance=20):
    """Remove background from a racing car image via connected flood fill.

    Only pixels reachable from the image border AND within *tolerance* of
    pure white are made transparent.  White regions on the car itself that
    aren't connected to the border are preserved.

    At thumbnail sizes (typically 40–120 × 14–30 px) the numpy path
    converges in < 10 iterations and completes in < 2 ms.
    Falls back to pure-Python BFS when numpy is unavailable.
    """
    if img is None:
        return img

    # ── numpy path (fast) ────────────────────────────────────────────────────
    try:
        import numpy as np
        rgba = img.convert('RGBA')
        arr  = np.array(rgba, dtype=np.uint8)
        h, w = arr.shape[:2]

        # Candidate background: every channel is close to white
        bg = np.all(arr[:, :, :3] >= (255 - tolerance), axis=2)

        # Seed the connected set from all four edges
        conn = np.zeros((h, w), dtype=bool)
        conn[0, :]  = bg[0, :]
        conn[-1, :] = bg[-1, :]
        conn[:, 0]  = bg[:, 0]
        conn[:, -1] = bg[:, -1]

        # Iterative 4-connected expansion — no wrap-around (unlike np.roll).
        # Converges in ≈ (white border thickness) iterations.
        for _ in range(max(h, w)):
            exp = np.zeros_like(conn)
            exp[1:,  :]  |= conn[:-1, :]   # expand down
            exp[:-1, :]  |= conn[1:,  :]   # expand up
            exp[:,  1:]  |= conn[:, :-1]    # expand right
            exp[:, :-1]  |= conn[:,  1:]    # expand left
            new = conn | (exp & bg)
            if np.array_equal(new, conn):
                break
            conn = new

        arr[conn, 3] = 0
        return Image.fromarray(arr, 'RGBA')

    except ImportError:
        pass

    # ── Pure-Python BFS fallback (no numpy) ──────────────────────────────────
    from collections import deque
    rgba   = img.convert('RGBA')
    pixels = rgba.load()
    w, h   = rgba.size
    thresh = 255 - tolerance

    def _is_bg(x, y):
        r, g, b, _ = pixels[x, y]
        return r >= thresh and g >= thresh and b >= thresh

    visited = [[False] * w for _ in range(h)]
    queue   = deque()
    for x in range(w):
        for y in (0, h - 1):
            if _is_bg(x, y) and not visited[y][x]:
                visited[y][x] = True
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if _is_bg(x, y) and not visited[y][x]:
                visited[y][x] = True
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx] and _is_bg(nx, ny):
                visited[ny][nx] = True
                queue.append((nx, ny))
    for y in range(h):
        for x in range(w):
            if visited[y][x]:
                r, g, b, a = pixels[x, y]
                pixels[x, y] = (r, g, b, 0)
    return rgba


# ── NASCAR car image download / cache ─────────────────────────────────────────

_NASCAR_CAR_CACHE: dict = {}
_NASCAR_CAR_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
# Shared session for connection reuse — avoids TLS re-handshake per candidate URL.
_nascar_http = requests.Session()
_nascar_http.headers.update(_NASCAR_CAR_HEADERS)

_nascar_dl_lock      = threading.Lock()
_nascar_dl_total     = 0
_nascar_dl_done      = 0
_nascar_dl_pending: set   = set()
_nascar_dl_inflight: set  = set()
_nascar_prefetch_running  = False


def nascar_dl_progress():
    """Return (done, total) for the current NASCAR car image download batch."""
    with _nascar_dl_lock:
        return _nascar_dl_done, _nascar_dl_total


def _nascar_candidates(url):
    """Return candidate URLs to try: 300x130 (fast) at each date offset, then 922x400.

    Ordered most-likely first: primary offset (0) in both sizes, then ±1 day,
    then ±2 days.  Caps at 6 candidates to keep total timeout bounded.
    """
    import re as _re
    from datetime import date as _date, timedelta as _td
    _m = _re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
    if not _m:
        return [url]
    _base   = _date(int(_m.group(1)), int(_m.group(2)), int(_m.group(3)))
    _prefix = url[:_m.start()]
    _fname  = url[_m.end():]
    _small  = _fname.replace('-922x400.jpg', '-300x130.jpg')
    # Interleave small/large per offset so a hit at the right date is found quickly.
    _offsets = (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, -8, 8, -9, 9, -10, 10)
    out = []
    for _d in (_base + _td(days=o) for o in _offsets):
        dated = f"/{_d.year}/{_d.month:02d}/{_d.day:02d}/"
        if _small != _fname:
            out.append(_prefix + dated + _small)
        out.append(_prefix + dated + _fname)
    return out


def _download_nascar_raw(url):
    """Phase 1 — download raw JPEG to disk cache.

    Returns (raw_bytes, raw_path) or (None, None) on total failure.
    """
    raw_name = f"nascar_raw_{hashlib.md5(url.encode()).hexdigest()}.jpg"
    raw_path = os.path.join(ASSETS_DIR, raw_name)
    with _nascar_dl_lock:
        _nascar_dl_inflight.add(url)
    try:
        if os.path.exists(raw_path):
            try:
                with open(raw_path, 'rb') as fh:
                    return fh.read(), raw_path
            except Exception:
                pass
        for candidate in _nascar_candidates(url):
            try:
                r = _nascar_http.get(candidate, timeout=(3, 8))
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                size_lbl = '300x130' if '-300x130' in candidate else '922x400'
                print(f"[NASCAR] downloaded {url.rsplit('/',1)[-1]} ({size_lbl}, {len(r.content)//1024}KB)")
                try:
                    os.makedirs(ASSETS_DIR, exist_ok=True)
                    with open(raw_path, 'wb') as fh:
                        fh.write(r.content)
                except Exception as e:
                    print(f"[NASCAR] raw save failed: {e}")
                return r.content, raw_path
            except Exception:
                continue
        print(f"[NASCAR] MISSING {url.rsplit('/',1)[-1]} — all candidates 404'd")
        return None, None
    finally:
        with _nascar_dl_lock:
            _nascar_dl_inflight.discard(url)


def _process_nascar_raw(url, target_size):
    """Phase 2 — load raw JPEG from disk, thumbnail, remove BG, save PNG."""
    global _nascar_dl_done
    cache_key = f"{url}_{target_size[0]}x{target_size[1]}"
    if cache_key in _NASCAR_CAR_CACHE:
        return _NASCAR_CAR_CACHE[cache_key]
    raw_name  = f"nascar_raw_{hashlib.md5(url.encode()).hexdigest()}.jpg"
    raw_path  = os.path.join(ASSETS_DIR, raw_name)
    disk_name = f"nascar_{hashlib.md5(url.encode()).hexdigest()}_{target_size[0]}x{target_size[1]}_v4.png"
    disk_path = os.path.join(ASSETS_DIR, disk_name)
    if os.path.exists(disk_path):
        try:
            img = Image.open(disk_path).convert('RGBA')
            _NASCAR_CAR_CACHE[cache_key] = img
            with _nascar_dl_lock:
                _nascar_dl_pending.discard(url)
                _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
            return img
        except Exception:
            pass
    try:
        with open(raw_path, 'rb') as fh:
            raw = fh.read()
    except Exception:
        _NASCAR_CAR_CACHE[cache_key] = None
        with _nascar_dl_lock:
            _nascar_dl_pending.discard(url)
            _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
        print(f"[NASCAR] SKIP {url.rsplit('/',1)[-1]} — raw file missing (404'd earlier)")
        return None
    try:
        full = Image.open(io.BytesIO(raw)).convert('RGBA')

        # Pre-crop: remove the white border at full resolution before
        # thumbnailing so the car fills the tile rather than being surrounded
        # by empty space that just shrinks it further.
        try:
            import numpy as np
            rgb = np.array(full)[:, :, :3]
            car = ~np.all(rgb >= 240, axis=2)
            if car.any():
                ys, xs = np.where(car)
                pad  = 8
                full = full.crop((
                    max(0,           xs.min() - pad),
                    max(0,           ys.min() - pad),
                    min(full.width,  xs.max() + pad + 1),
                    min(full.height, ys.max() + pad + 1),
                ))
        except Exception:
            pass

        # 1) Generous intermediate resize for high-quality bg removal
        full.thumbnail((200, 28), Image.Resampling.LANCZOS)
        # 2) Remove background, then trim transparent padding so the
        #    visible car starts at pixel 0 (flush left)
        full = _flood_remove_background(full, tolerance=20)
        full = _trim_transparent_padding(full)
        # 3) Fit within target box preserving aspect ratio
        if full.width > 0 and full.height > 0:
            full.thumbnail(target_size, Image.Resampling.LANCZOS)
        _NASCAR_CAR_CACHE[cache_key] = full
        print(f"[NASCAR] processed {url.rsplit('/',1)[-1]} -> {full.size}")
        try:
            full.save(disk_path, 'PNG')
        except Exception as e:
            print(f"[NASCAR] PNG save failed ({disk_path}): {e}")
        with _nascar_dl_lock:
            _nascar_dl_pending.discard(url)
            _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
        return full
    except Exception as e:
        print(f"[NASCAR] process failed {url.rsplit('/',1)[-1]}: {e}")
        _NASCAR_CAR_CACHE[cache_key] = None
        with _nascar_dl_lock:
            _nascar_dl_pending.discard(url)
            _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
        return None


def _load_nascar_car(url, target_size):
    """Render-thread helper: return processed image from memory/disk cache.

    If not yet processed, triggers processing from the raw download
    (non-blocking on miss — returns None until the image is ready).
    """
    global _nascar_dl_done
    if not url:
        return None
    cache_key = f"{url}_{target_size[0]}x{target_size[1]}"
    if cache_key in _NASCAR_CAR_CACHE:
        return _NASCAR_CAR_CACHE[cache_key]
    disk_name = f"nascar_{hashlib.md5(url.encode()).hexdigest()}_{target_size[0]}x{target_size[1]}_v4.png"
    disk_path = os.path.join(ASSETS_DIR, disk_name)
    if os.path.exists(disk_path):
        try:
            img = Image.open(disk_path).convert('RGBA')
            _NASCAR_CAR_CACHE[cache_key] = img
            with _nascar_dl_lock:
                _nascar_dl_pending.discard(url)
                _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
            return img
        except Exception:
            pass
    return None


def nascar_submit_downloads(urls, target_size, executor):
    """Two-phase prefetch: download ALL raw JPEGs first, then process them all."""
    global _nascar_dl_total, _nascar_dl_done, _nascar_prefetch_running
    urls = [u for u in urls if u]
    if not urls:
        return
    with _nascar_dl_lock:
        new_urls = [u for u in urls
                    if f"{u}_{target_size[0]}x{target_size[1]}" not in _NASCAR_CAR_CACHE]
        _nascar_dl_pending.update(new_urls)
        _nascar_dl_total = len(_nascar_dl_pending) + _nascar_dl_done
        if _nascar_prefetch_running:
            return
        _nascar_prefetch_running = True
    if not new_urls:
        with _nascar_dl_lock:
            _nascar_prefetch_running = False
        return

    def _run_phases():
        try:
            download_workers = min(4, max(1, len(new_urls)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=download_workers) as dl_pool:
                concurrent.futures.wait([dl_pool.submit(_download_nascar_raw, u) for u in new_urls])
            print(f"[NASCAR] all {len(new_urls)} downloads complete — processing in background...")
            process_workers = min(2, max(1, len(new_urls)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=process_workers) as proc_pool:
                concurrent.futures.wait([proc_pool.submit(_process_nascar_raw, u, target_size) for u in new_urls])
            done, total = nascar_dl_progress()
            print(f"[NASCAR] prefetch done: {done}/{total} cars ready")
        finally:
            with _nascar_dl_lock:
                _nascar_prefetch_running = False

    threading.Thread(target=_run_phases, daemon=True).start()


def nascar_retry_pending(executor, target_size=(80, 14)):
    """Re-submit any URLs that haven't successfully downloaded yet."""
    with _nascar_dl_lock:
        pending = [u for u in _nascar_dl_pending if u not in _nascar_dl_inflight]
    if not pending:
        return

    def _run_retry():
        dl_futs = [executor.submit(_download_nascar_raw, u) for u in pending]
        concurrent.futures.wait(dl_futs)
        proc_futs = [executor.submit(_process_nascar_raw, u, target_size) for u in pending]
        concurrent.futures.wait(proc_futs)

    threading.Thread(target=_run_retry, daemon=True).start()


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
            _nascar_dl_done  = 0
            _nascar_dl_pending.clear()
            _nascar_dl_inflight.clear()
        os.makedirs(assets_dir, exist_ok=True)
        with open(id_file, 'w') as f:
            f.write(race_id)
    except Exception:
        pass


# ── Drawing helpers (module-level, shared by RacingMixin methods) ─────────────

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


def _format_racing_time(value):
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        cleaned = text.replace('Z', '+00:00')
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime('%I:%M %p').lstrip('0')
    except Exception:
        return text


# Keep the old name as an alias.
_format_indycar_time = _format_racing_time


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
    f = str(flag or '').strip().upper()
    if f:
        return f
    state = str(state or '').lower()
    if state == 'post':
        return 'CHECKERED'
    if state == 'pre':
        return 'WHITE'
    return 'GREEN'


def _key_background(img, tolerance=18):
    """Remove the background colour from a logo image.

    Uses a global colour-threshold approach keyed on the dominant corner
    colour.  For small logo thumbnails this is accurate and fast.  The numpy
    path is ~100× faster than the pure-Python pixel loop and runs in a few
    microseconds at 18×18, making it safe to call on a Pi Zero 2W.
    """
    if img is None:
        return None
    try:
        import numpy as np
        rgba = img.convert('RGBA')
        arr  = np.array(rgba, dtype=np.uint8)
        h, w = arr.shape[:2]
        # Sample all four corners to find the most common background colour.
        corners = [tuple(arr[0,   0,   :3].tolist()),
                   tuple(arr[0,   w-1, :3].tolist()),
                   tuple(arr[h-1, 0,   :3].tolist()),
                   tuple(arr[h-1, w-1, :3].tolist())]
        counts  = {}
        for c in corners:
            counts[c] = counts.get(c, 0) + 1
        bg_rgb = max(counts, key=counts.get)
        bg_arr = np.array(bg_rgb, dtype=np.int16)
        diff   = np.abs(arr[:, :, :3].astype(np.int16) - bg_arr)
        mask   = np.all(diff <= tolerance, axis=2) & (arr[:, :, 3] > 0)
        arr[mask, 3] = 0
        return Image.fromarray(arr, 'RGBA')
    except ImportError:
        pass
    # ── Pure-Python fallback (no numpy) ──────────────────────────────────────
    try:
        rgba   = img.convert('RGBA')
        pixels = rgba.load()
        width, height = rgba.size
        corners = [pixels[0, 0], pixels[max(0, width - 1), 0],
                   pixels[0, max(0, height - 1)], pixels[max(0, width - 1), max(0, height - 1)]]
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


# ── RacingMixin ───────────────────────────────────────────────────────────────

class RacingMixin:
    """Shared rendering mixin for all motor-sport series.

    Reads race data from game['indycar'] (the canonical payload key).
    Series adapters (IndycarMixin, F1Mixin, NascarMixin, …) remap their
    own key into game['indycar'] before calling draw_racing_*.
    """

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
        """Return a processed (keyed + sharpened) logo image.

        Results are cached per (url, size, tolerance) so the expensive PIL
        pipeline (MedianFilter, SHARPEN, key_background) only runs once per
        unique logo, not on every render frame.  None results are NOT cached
        so a pending download is retried next call.
        """
        url = str(url or '').strip()
        if not url:
            return None

        size_t    = size if isinstance(size, tuple) else (int(size), int(size))
        cache_key = (url, size_t, bg_tolerance)
        if not hasattr(self, '_ic_logo_proc_cache'):
            self._ic_logo_proc_cache = {}
        if cache_key in self._ic_logo_proc_cache:
            return self._ic_logo_proc_cache[cache_key]

        # Fetch raw logo (trigger download if needed).
        logo = self.get_logo(url, size)
        if logo is None:
            try:
                self.download_and_process_logo(url, size)
            except Exception:
                pass
            logo = self.get_logo(url, size)
        if logo is None:
            return None   # don't cache — allow retry next frame

        try:
            cleaned = logo.convert('RGBA')
            cleaned = _key_background(cleaned, bg_tolerance)
            cleaned = ImageOps.autocontrast(cleaned)
            cleaned = cleaned.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.SHARPEN)
        except Exception:
            cleaned = logo

        self._ic_logo_proc_cache[cache_key] = cleaned
        return cleaned

    def _ic_logo_colors(self, url, size=(18, 18)):
        """Return (primary_rgb, secondary_rgb) for a team logo URL, cached.

        Combines _ic_load_logo (already cached) + _ic_sample_colors so colour
        quantization only ever runs once per unique logo URL+size pair.
        """
        if not hasattr(self, '_ic_color_cache'):
            self._ic_color_cache = {}
        size_t = size if isinstance(size, tuple) else (int(size), int(size))
        key    = (url, size_t)
        if key not in self._ic_color_cache:
            logo = self._ic_load_logo(url, size)
            if logo is not None:
                self._ic_color_cache[key] = _ic_sample_colors(logo)
        return self._ic_color_cache.get(key, ((180, 180, 180), (80, 80, 80)))

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
        short   = str(ic.get('short_name') or ic.get('event_name') or 'Racing').strip()
        session = str(ic.get('session_name') or ic.get('session_type') or 'Race').strip()
        short = (short.upper()
                 .replace('GRAND PRIX', 'GP')
                 .replace('CHAMPIONSHIP', 'CHAMP')
                 .replace('PRESENTED BY', '')
                 .replace('  ', ' ')
                 .strip())
        session = (session
                   .replace('Sprint Qualifying', 'Sprint Quali')
                   .replace('Qualifying', 'Quali'))
        if len(short) + 1 + len(session) > 24:
            short = short[:max(4, 24 - 1 - len(session))]
        return f"{short} {session}"

    # ── scroll card (128 × 32) ───────────────────────────────────────────────

    def draw_racing_scroll_card(self, game):
        """Compact racing card for the sports/live scrolling strip."""
        W = 128
        img = Image.new("RGBA", (W, PANEL_H), (0, 0, 0, 255))
        d   = ImageDraw.Draw(img)

        ic      = self._ic_payload(game)
        drivers = ic.get('drivers', [])
        if not isinstance(drivers, list):
            drivers = []
        # ── Header ──────────────────────────────────────────────────────────
        header = self._ic_header_label(ic)
        draw_hybrid_text(d, 1 + 1, 1 + 1, header, (8, 8, 8, 180))
        draw_hybrid_text(d, 1,     1,     header, (255, 240, 150, 255))

        state = str(game.get('state', 'pre')).lower()
        _draw_mini_flag(d, W - 12, 0, _display_flag(ic.get('flag'), state))

        d.line([(0, 7), (W - 1, 7)], fill=(55, 76, 130))

        session  = str(ic.get('session_type') or 'Race').lower()
        is_qual  = 'qual' in session
        is_f1    = game.get('sport') == 'f1'

        # ── Column labels ────────────────────────────────────────────────────
        LABEL_COL = (70, 90, 140)
        draw_tiny_text(d, 1,  8, 'P',      LABEL_COL)
        draw_tiny_text(d, 34, 8, 'DRIVER', LABEL_COL)
        if is_qual:
            right_label = 'TIME' if is_f1 else 'MPH'
        else:
            right_label = 'GAP'
        draw_tiny_text(d, 90, 8, right_label, LABEL_COL)

        # ── Driver rows (top 3) ──────────────────────────────────────────────
        row_ys = [13, 20, 27]
        top3   = drivers[:3]

        for i, driver in enumerate(top3):
            y       = row_ys[i]
            pos     = str(driver.get('pos') or i + 1)
            abbr    = str(driver.get('abbr') or '???').upper()[:3]
            car_num = str(driver.get('car') or '').strip()
            team_logo = str(driver.get('team_logo') or '').strip()

            if is_qual:
                if is_f1:
                    right_val = str(driver.get('gap') or '').strip()[:12]
                else:
                    right_val = str(driver.get('speed') or driver.get('gap') or '').strip()[:7]
            else:
                right_val = str(driver.get('gap') or '').strip()[:12]

            pos_color = (255, 215, 0) if pos == '1' else (200, 200, 200)
            draw_tiny_text(d, 0, y, pos, pos_color)

            if team_logo:
                num_fill, _ = self._ic_logo_colors(team_logo, (18, 18))
            else:
                livery_hex = str(driver.get('livery_primary') or '').strip()
                num_fill = _hex_to_rgb(livery_hex, (128, 128, 128)) if livery_hex else (180, 180, 180)

            num_text = car_num or abbr
            num_w    = _tiny_text_width(num_text, self.font)
            name_w   = _tiny_text_width(abbr, self.font)
            total_w  = num_w + 2 + name_w
            DRIVER_LABEL_X  = 34
            driver_label_w  = _tiny_text_width('DRIVER', self.font)
            center_x = DRIVER_LABEL_X + (driver_label_w / 2)
            start_x  = max(5, int(round(center_x - total_w / 2)))

            r_c, g_c, b_c = num_fill[:3]
            luma = 0.299 * r_c + 0.587 * g_c + 0.114 * b_c
            if luma < 80:
                outline = (255, 255, 255, 200)
                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    draw_tiny_text(d, start_x + ox, y + oy, num_text, outline)
            draw_tiny_text(d, start_x, y, num_text, num_fill)
            draw_tiny_text(d, start_x + num_w + 2, y, abbr, (255, 255, 255))

            if right_val:
                val_x = min(82, W - len(right_val) * 4 - 2)
                val_color = (255, 255, 255) if pos == '1' else (180, 210, 255)
                draw_tiny_text(d, val_x, y, right_val, val_color)

        if not top3:
            g_state    = str(game.get('state') or '').lower()
            start_txt  = str(game.get('status') or '').strip() if g_state == 'pre' else ''
            session_label = self._ic_header_label(ic)
            draw_tiny_text(d, max(2, int((W - _tiny_text_width(session_label, self.font)) / 2)),
                           16, session_label, (180, 210, 255))
            if start_txt:
                starts = f"STARTS {start_txt}"
                draw_tiny_text(d, max(2, int((W - _tiny_text_width(starts, self.font)) / 2)),
                               23, starts, (200, 200, 200))

        return img

    # ── full-screen mode (384 × 32) ──────────────────────────────────────────

    def draw_racing_full(self, game):
        """Full-bleed racing mode: info panel on left 1/4, driver list on right 3/4."""
        if not hasattr(self, '_ic_scroll_idx'):
            self._ic_scroll_idx   = 0
            self._ic_scroll_ts    = time.time()
            self._ic_scroll_batch = 3

        W      = PANEL_W    # 384
        H      = PANEL_H    # 32
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

        for x in range(INFO_W):
            alpha = int(30 + 20 * x / INFO_W)
            d.line([(x, 0), (x, H)], fill=(0, 20, 60, alpha))

        self._ic_draw_info_panel(d, ic, game, INFO_W, H)

        if drivers:
            self._ic_draw_driver_panel(img, d, drivers, INFO_W, RACE_W, H, is_qual=is_qual)
        else:
            g_state    = str(game.get('state') or '').lower()
            start_txt  = str(game.get('status') or '').strip() if g_state == 'pre' else ''
            session_label = self._ic_header_label(ic)
            text_x = INFO_W + max(4, int((RACE_W - _tiny_text_width(session_label, self.font)) / 2))
            draw_tiny_text(d, text_x, 10, session_label, (180, 210, 255))
            if start_txt:
                starts  = f"STARTS {start_txt}"
                text_x2 = INFO_W + max(4, int((RACE_W - _tiny_text_width(starts, self.font)) / 2))
                draw_tiny_text(d, text_x2, 18, starts, (200, 200, 200))

        return img

    def _ic_draw_info_panel(self, d, ic, game, panel_w, H):
        """Draw race/session information into the left 1/4 panel."""
        short_name = str(ic.get('short_name') or ic.get('event_name') or 'RACING').upper()
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
        _final_suffix = ''
        for _fs in (' - FINAL SEGMENT', ' - FINAL', ' FINAL SEGMENT', ' FINAL'):
            if short_name.endswith(_fs):
                short_name = short_name[:-len(_fs)].strip()
                _final_suffix = 'FINAL'
                break

        session    = str(ic.get('session_type') or 'RACE').upper()
        lap        = ic.get('lap', 0) or 0
        total      = ic.get('total_laps', 0) or 0
        time_to_go = str(ic.get('time_to_go') or '').strip()
        start_utc  = str(game.get('startTimeUTC') or '').strip()
        flag       = str(ic.get('flag') or '').strip().upper()
        caution    = flag in (
            'YELLOW', 'DOUBLE YELLOW', 'FCY', 'FULL COURSE YELLOW', 'CAUTION',
            'SAFETY CAR', 'SC', 'VSC', 'VSC ENDING', 'SC ENDING',
            'RED', 'RED FLAG',
        ) or bool(ic.get('caution'))
        state      = str(game.get('state', 'pre')).lower()
        is_qual    = 'qual' in session.lower() or 'prac' in session.lower()

        bar_color = racing_flag_color(_display_flag(flag, state))
        d.rectangle([0, 0, 2, H], fill=bar_color)

        flag_name = _display_flag(flag, state)
        show_flag = bool(flag_name)
        if show_flag:
            _draw_flag(d, panel_w - 17, 1, flag_name, w=15, h=10)

        avail_w = panel_w - (21 if show_flag else 5) - 4
        name_px  = _tiny_text_width(short_name, self.font)

        if name_px <= avail_w:
            draw_tiny_text(d, 4, 1, short_name, (255, 240, 150))
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
            draw_tiny_text(td, 0,             0, short_name, (255, 240, 150))
            draw_tiny_text(td, name_px + GAP, 0, short_name, (255, 240, 150))
            clip = tmp.crop((offset, 0, offset + avail_w, 7))
            d._image.paste(clip, (4, 1), clip)

        variant = str(os.environ.get('INDYCAR_INFO_VARIANT') or 'conditions').strip().lower()
        if variant in ('track_map', 'conditions'):
            weather  = self._ic_conditions_weather(ic.get('weather'))
            air      = str(weather.get('air_temp') or '--').strip()
            wind     = str(weather.get('wind_mph') or '--').strip()
            wind_dir = _wind_compass(weather.get('wind_dir')) or '--'
            draw_tiny_text(d, 4, 8, session[:11], (180, 210, 255))
            _draw_condition_icon(d, 5, 17, 'air', (255, 220, 50))
            draw_tiny_text(d, 15, 16, f"{air}F", (255, 255, 255))
            _draw_condition_icon(d, 5, 26, 'wind', (115, 190, 255))
            draw_tiny_text(d, 15, 25, f"{wind}-{wind_dir}", (180, 210, 255))
            return
        if variant == 'leader':
            drivers  = ic.get('drivers', [])
            leader   = next((drv for drv in drivers if isinstance(drv, dict) and str(drv.get('pos') or '') == '1'), None)
            if not leader and isinstance(drivers, list) and drivers:
                leader = next((drv for drv in drivers if isinstance(drv, dict)), None)
            lead_car   = str((leader or {}).get('car') or '').strip()
            lead_abbr  = str((leader or {}).get('abbr') or '').strip().upper()
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

        y_info    = y_session + 7
        max_chars = max(4, avail_w // 5)
        if state == 'post' or _final_suffix:
            info_str = 'FINAL'
        elif is_qual and time_to_go:
            info_str = time_to_go[:max_chars]
        elif state == 'in' and total > 0:
            info_str = f"L{lap}/{total}"
        elif state == 'in' and lap > 0:
            info_str = f"LAP {lap}"
        elif state == 'pre':
            start_txt = str(game.get('status') or '').strip() or _format_racing_time(start_utc)
            info_str  = f"STARTS {start_txt}"[:max_chars]
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
            self._ic_hscroll_x  = 0.0
            self._ic_hscroll_ts = now

        elapsed = max(0.0, now - self._ic_hscroll_ts)
        self._ic_hscroll_ts = now

        panel = Image.new('RGBA', (panel_w, H), (0, 0, 0, 0))
        pd    = ImageDraw.Draw(panel)

        visible = [dict(drv) for drv in drivers if isinstance(drv, dict)]
        if not visible:
            pd.rectangle([0, 0, panel_w - 1, H - 1], fill=(8, 8, 16))
            draw_tiny_text(pd, 8, 12, 'LOADING', (120, 120, 120))
            img.paste(panel, (x_off, 0), panel)
            return

        def _pos_sort_key(drv):
            try:
                return int(str(drv.get('pos') or 999).lstrip('T'))
            except Exception:
                return 999

        visible.sort(key=_pos_sort_key)

        min_card_w   = 132
        card_h       = H - 2
        gap          = 6
        ticker_sleep = float(getattr(self, 'scroll_sleep', 0.05) or 0.05)
        row_speed    = 1.0 / max(0.001, ticker_sleep)

        cache_key = (
            panel_w,
            H,
            bool(is_qual),
            nascar_dl_progress(),   # invalidates strip once all car downloads finish
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
            cards   = cached.get('cards') or []
            strip   = cached.get('strip')
            strip_w = int(cached.get('strip_w') or 0)
        else:
            cards = []
            for driver in visible:
                pos       = str(driver.get('pos') or '')
                name      = str(driver.get('name') or driver.get('abbr') or '???').strip()
                car_num   = str(driver.get('car') or '').strip()
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
                num_w,   _ = _text_size(pd, car_num, self.font)
                card_w = max(min_card_w, int(name_w) + 24, int(place_w + num_w) + 18)
                card = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
                cd = ImageDraw.Draw(card)
                team_logo  = str(driver.get('team_logo') or '').strip()
                car_image  = str(driver.get('car_illustration') or '').strip()
                gap_val    = str(driver.get('gap') or '').strip()
                primary    = _hex_to_rgb(driver.get('livery_primary'), (120, 120, 130))
                secondary  = _hex_to_rgb(driver.get('livery_secondary'), (20, 20, 24))
                cd.rectangle([0, 0, card_w - 1, card_h - 1], fill=(12, 12, 18))
                cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(60, 60, 72), width=1)
                if pos == '1':
                    cd.rectangle([0, 0, card_w - 1, card_h - 1], outline=(255, 215, 0), width=1)

                drew_car = False
                if car_image:
                    is_nascar_img = 'nascar.com' in car_image
                    if is_nascar_img:
                        car_img = _load_nascar_car(car_image, (80, 14))
                    else:
                        car_img = None
                        for ext in ('webp', 'png', 'jpg', 'jpeg'):
                            if car_image.endswith(f'.{ext}'):
                                car_img = self._ic_load_logo(car_image, (120, 19))
                                if car_img:
                                    break
                            else:
                                alt = car_image.rsplit('.', 1)[0] + f'.{ext}'
                                car_img = self._ic_load_logo(alt, (120, 19))
                                if car_img:
                                    break
                        if not car_img:
                            car_img = self._ic_load_logo(car_image, (120, 19))
                    if car_img:
                        # Only trim non-NASCAR; NASCAR cars are already at a
                        # consistent size from _process_nascar_raw.
                        if not is_nascar_img:
                            car_img = _trim_transparent_padding(car_img)
                        car_x   = 0
                        car_y   = max(0, card_h - car_img.height - 1)
                        card.paste(car_img, (car_x, car_y), car_img)
                        drew_car = True
                if not drew_car and hasattr(self, '_draw_f1_generated_car') and str(driver.get('team') or ''):
                    fallback_w = min(120, card_w - 2)
                    self._draw_f1_generated_car(card, 1, 14, fallback_w, 15,
                                                primary + (255,), secondary + (255,))
                    drew_car = True
                if not drew_car and car_num:
                    draw_tiny_text(cd, 5, 19, car_num, (110, 110, 122))

                pos_color = (255, 215, 0) if pos == '1' else (180, 180, 180)
                cd.text((4, 0), place_text, font=self.font, fill=pos_color)

                if car_num:
                    if team_logo:
                        num_fill, _num_outline = self._ic_logo_colors(team_logo, (18, 18))
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
                name_x    = max(4, card_w - int(name_w) - 5)
                cd.text((name_x, 10), name, font=name_font, fill=(255, 255, 255))

                if is_qual:
                    right_val = str(driver.get('speed') or driver.get('gap') or '').strip()[:8]
                else:
                    right_val = gap_val[:10]
                if right_val:
                    rv_w = _tiny_text_width(right_val, self.font)
                    draw_tiny_text(cd, max(4, card_w - rv_w - 4), 23,
                                   right_val,
                                   (140, 190, 255) if pos != '1' else (255, 255, 255))

                cards.append(card)

            strip_w = sum(card.width for card in cards) + gap * len(cards)
            strip   = Image.new('RGBA', (strip_w + panel_w, H), (0, 0, 0, 0))
            sx = 0
            i  = 0
            while sx < strip.width and cards:
                card = cards[i % len(cards)]
                strip.paste(card, (sx, 1), card)
                sx += card.width + gap
                i  += 1
            self._ic_driver_strip_cache = {
                'key': cache_key, 'cards': cards, 'strip': strip, 'strip_w': strip_w,
            }

        if strip_w <= 0:
            img.paste(panel, (x_off, 0), panel)
            return

        if len(cards) == 1:
            x = max(0, (panel_w - cards[0].width) // 2)
            panel.paste(cards[0], (x, 1), cards[0])
            img.paste(panel, (x_off, 0), panel)
            return

        self._ic_hscroll_x = (self._ic_hscroll_x + elapsed * row_speed) % strip_w
        view_x = int(self._ic_hscroll_x)
        view   = strip.crop((view_x, 0, view_x + panel_w, H))
        panel.alpha_composite(view)
        img.paste(panel, (x_off, 0), panel)
