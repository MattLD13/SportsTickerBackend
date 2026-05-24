"""NASCAR car image download, background removal, and disk/memory cache."""

import concurrent.futures
import hashlib
import io
import os
import threading

import requests
from PIL import Image, ImageChops, ImageDraw, ImageOps

from ..config import ASSETS_DIR

_NASCAR_CAR_CACHE: dict = {}
_NASCAR_CAR_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nascar.com/',
}

_nascar_dl_lock = threading.Lock()
_nascar_dl_total = 0
_nascar_dl_done = 0
_nascar_dl_pending: set = set()
_nascar_dl_inflight: set = set()
_nascar_prefetch_running = False

_NASCAR_RACE_ID_FILE = 'nascar_race_id.txt'


def trim_transparent_padding(img):
    if img is None:
        return None
    try:
        rgba = img.convert('RGBA')
        bbox = rgba.getbbox()
        return rgba.crop(bbox) if bbox else rgba
    except Exception:
        return img


def _flood_remove_background(img, tolerance=35):
    """Remove background from NASCAR car image (numpy fast path, PIL fallback)."""
    if img is None:
        return img
    try:
        import numpy as np
        arr = np.array(img.convert('RGBA'), dtype=np.int16)
        edges = np.concatenate([
            arr[0, :, :3], arr[-1, :, :3],
            arr[:, 0, :3], arr[:, -1, :3],
        ])
        bg = np.median(edges, axis=0).astype(np.int16)
        diff = np.abs(arr[:, :, :3] - bg)
        arr[np.all(diff <= tolerance, axis=2), 3] = 0
        return Image.fromarray(arr.astype(np.uint8), 'RGBA')
    except ImportError:
        pass
    try:
        rgba = img.convert('RGBA')
        w, h = rgba.size
        rgb_before = rgba.convert('RGB')
        rgb_after = rgb_before.copy()
        fill = (1, 2, 3)
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if rgb_after.getpixel(corner) != fill:
                ImageDraw.floodfill(rgb_after, corner, fill, thresh=tolerance)
        diff = ImageChops.difference(rgb_before, rgb_after)
        r, g, b = diff.split()
        changed = ImageChops.lighter(ImageChops.lighter(r, g), b)
        bg_mask = changed.point(lambda v: 255 if v > 0 else 0, 'L')
        rgba.putalpha(ImageOps.invert(bg_mask))
        return rgba
    except Exception:
        return img


def nascar_dl_progress():
    """Return (done, total) for the current NASCAR car image download batch."""
    with _nascar_dl_lock:
        return _nascar_dl_done, _nascar_dl_total


def _nascar_candidates(url):
    import re as _re
    from datetime import date as _date, timedelta as _td
    _m = _re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
    if not _m:
        return [url]
    _base = _date(int(_m.group(1)), int(_m.group(2)), int(_m.group(3)))
    _prefix = url[:_m.start()]
    _fname = url[_m.end():]
    _small = _fname.replace('-922x400.jpg', '-300x130.jpg')
    _offsets = (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, -8, 8, -9, 9, -10, 10)
    out = []
    if _small != _fname:
        for _d in (_base + _td(days=o) for o in _offsets):
            out.append(_prefix + f"/{_d.year}/{_d.month:02d}/{_d.day:02d}/" + _small)
    for _d in (_base + _td(days=o) for o in _offsets):
        out.append(_prefix + f"/{_d.year}/{_d.month:02d}/{_d.day:02d}/" + _fname)
    return out


def _download_nascar_raw(url):
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
                r = requests.get(candidate, headers=_NASCAR_CAR_HEADERS, timeout=12)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                size_lbl = '300x130' if '-300x130' in candidate else '922x400'
                print(f"[NASCAR] downloaded {url.rsplit('/', 1)[-1]} ({size_lbl}, {len(r.content) // 1024}KB)")
                try:
                    os.makedirs(ASSETS_DIR, exist_ok=True)
                    with open(raw_path, 'wb') as fh:
                        fh.write(r.content)
                except Exception as e:
                    print(f"[NASCAR] raw save failed: {e}")
                return r.content, raw_path
            except Exception:
                continue
        print(f"[NASCAR] MISSING {url.rsplit('/', 1)[-1]} — all candidates 404'd")
        return None, None
    finally:
        with _nascar_dl_lock:
            _nascar_dl_inflight.discard(url)


def _process_nascar_raw(url, target_size):
    global _nascar_dl_done
    cache_key = f"{url}_{target_size[0]}x{target_size[1]}"
    if cache_key in _NASCAR_CAR_CACHE:
        return _NASCAR_CAR_CACHE[cache_key]
    raw_name = f"nascar_raw_{hashlib.md5(url.encode()).hexdigest()}.jpg"
    raw_path = os.path.join(ASSETS_DIR, raw_name)
    disk_name = f"nascar_{hashlib.md5(url.encode()).hexdigest()}_{target_size[0]}x{target_size[1]}.png"
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
        print(f"[NASCAR] SKIP {url.rsplit('/', 1)[-1]} — raw file missing (404'd earlier)")
        return None
    try:
        full = Image.open(io.BytesIO(raw)).convert('RGBA')
        full.thumbnail(target_size, Image.Resampling.LANCZOS)
        full = _flood_remove_background(full, tolerance=40)
        full = trim_transparent_padding(full)
        _NASCAR_CAR_CACHE[cache_key] = full
        print(f"[NASCAR] processed {url.rsplit('/', 1)[-1]} → {full.size}")
        try:
            full.save(disk_path, 'PNG')
        except Exception as e:
            print(f"[NASCAR] PNG save failed ({disk_path}): {e}")
        with _nascar_dl_lock:
            _nascar_dl_pending.discard(url)
            _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
        return full
    except Exception as e:
        print(f"[NASCAR] process failed {url.rsplit('/', 1)[-1]}: {e}")
        _NASCAR_CAR_CACHE[cache_key] = None
        return None


def load_nascar_car(url, target_size):
    """Return processed NASCAR car image from memory/disk cache, or None if not ready."""
    if not url:
        return None
    cache_key = f"{url}_{target_size[0]}x{target_size[1]}"
    if cache_key in _NASCAR_CAR_CACHE:
        return _NASCAR_CAR_CACHE[cache_key]
    disk_name = f"nascar_{hashlib.md5(url.encode()).hexdigest()}_{target_size[0]}x{target_size[1]}.png"
    disk_path = os.path.join(ASSETS_DIR, disk_name)
    if os.path.exists(disk_path):
        try:
            img = Image.open(disk_path).convert('RGBA')
            _NASCAR_CAR_CACHE[cache_key] = img
            with _nascar_dl_lock:
                _nascar_dl_pending.discard(url)
                global _nascar_dl_done
                _nascar_dl_done = min(_nascar_dl_total, _nascar_dl_done + 1)
            return img
        except Exception:
            pass
    return None


def nascar_submit_downloads(urls, target_size, executor=None):
    """Two-phase prefetch: download raw JPEGs, then process to PNG."""
    global _nascar_dl_total, _nascar_dl_done, _nascar_prefetch_running
    urls = [u for u in urls if u]
    if not urls:
        return
    with _nascar_dl_lock:
        new_urls = [
            u for u in urls
            if f"{u}_{target_size[0]}x{target_size[1]}" not in _NASCAR_CAR_CACHE
        ]
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
            with concurrent.futures.ThreadPoolExecutor(max_workers=download_workers) as download_pool:
                dl_futs = [download_pool.submit(_download_nascar_raw, u) for u in new_urls]
                concurrent.futures.wait(dl_futs)
            print(f"[NASCAR] all {len(new_urls)} downloads complete — processing in background...")
            process_workers = min(2, max(1, len(new_urls)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=process_workers) as process_pool:
                proc_futs = [process_pool.submit(_process_nascar_raw, u, target_size) for u in new_urls]
                concurrent.futures.wait(proc_futs)
            done, total = nascar_dl_progress()
            print(f"[NASCAR] prefetch done: {done}/{total} cars ready")
        finally:
            with _nascar_dl_lock:
                _nascar_prefetch_running = False

    threading.Thread(target=_run_phases, daemon=True).start()


def nascar_retry_pending(executor, target_size=(120, 14)):
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


def nascar_purge_old_cars(assets_dir, race_id):
    """Delete disk-cached car images when race_id changes (new race week)."""
    global _nascar_dl_total, _nascar_dl_done
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
