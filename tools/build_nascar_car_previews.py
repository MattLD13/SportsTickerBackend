"""
Download all NASCAR car images for the current live race, save to previews/nascar/cars/,
and report any that are missing (404 or other error).

Usage:
    python tools/build_nascar_car_previews.py
"""

import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
from PIL import Image

from ticker_controller.modes.indycar import (
    _flood_remove_background,
    _trim_transparent_padding,
)
from sports_ticker.fetchers.sports_nascar import (
    _NCS_2026,
    _NASCAR_IMG_BASE,
    _nascar_car_image_url,
    _nascar_car_image_candidates,
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nascar.com/',
}
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'previews', 'nascar', 'cars')
THUMB_SIZE = (200, 62)   # larger for preview, proportional to 922×400 source


def fetch_live_cars():
    r = requests.get('https://cf.nascar.com/cacher/live/live-feed.json', headers=HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()
    race_id = int(data.get('race_id') or 0)
    run_name = data.get('run_name', 'Unknown Race')
    vehicles = sorted(
        [v for v in data.get('vehicles', []) if isinstance(v, dict)],
        key=lambda v: int(v.get('running_position') or 999),
    )
    cars = []
    for v in vehicles:
        pos = int(v.get('running_position') or 999)
        car_num = str(v.get('vehicle_number') or '').strip()
        drv = v.get('driver') or {}
        full_name = str(drv.get('full_name') or '').strip().rstrip(' #').strip()
        cars.append({'pos': pos, 'car': car_num, 'name': full_name, 'race_id': race_id})
    return race_id, run_name, cars


def download_car(race_id, car_num, name, pos):
    candidates = _nascar_car_image_candidates(race_id, car_num)
    if not candidates:
        return None, '', 'no_url'
    for url in candidates:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            full = Image.open(io.BytesIO(r.content)).convert('RGBA')
            full = _flood_remove_background(full, tolerance=40)
            full = _trim_transparent_padding(full)
            full.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
            return full, url, 'ok'
        except Exception:
            continue
    return None, candidates[0], '404'


def main():
    print("Fetching live NASCAR feed...")
    race_id, run_name, cars = fetch_live_cars()
    print(f"Race: {run_name}  (race_id={race_id})")
    print(f"Cars in feed: {len(cars)}")

    entry = _NCS_2026.get(race_id)
    if entry:
        print(f"Map entry: race #{entry[0]} at {entry[1]}  ({entry[2]})")
    else:
        print(f"WARNING: race_id {race_id} is NOT in _NCS_2026 — image URLs will be empty!")

    os.makedirs(OUT_DIR, exist_ok=True)

    ok, missing, no_url = [], [], []

    for car in cars:
        pos, car_num, name = car['pos'], car['car'], car['name']
        img, url, status = download_car(race_id, car_num, name, pos)
        label = f"P{pos:>2} #{car_num:<3} {name}"
        if status == 'ok':
            fname = f"P{pos:02d}_{car_num}_{name.replace(' ', '_')}.png"
            img.save(os.path.join(OUT_DIR, fname))
            print(f"  OK   {label}")
            ok.append(car_num)
        elif status == '404':
            print(f"  404  {label}  {url}")
            missing.append((car_num, name, url))
        elif status == 'no_url':
            print(f"  NOURL {label}  (race_id not in _NCS_2026)")
            no_url.append((car_num, name))
        else:
            print(f"  ERR  {label}  {status}")
            missing.append((car_num, name, url))
        time.sleep(0.1)

    print()
    print("=" * 60)
    print(f"Downloaded: {len(ok)}/{len(cars)}")
    if no_url:
        print(f"\nNO URL (race_id {race_id} not in schedule map): {len(no_url)}")
        for car_num, name in no_url:
            print(f"  #{car_num} {name}")
    if missing:
        print(f"\nMISSING (404 or error): {len(missing)}")
        for car_num, name, url in missing:
            print(f"  #{car_num} {name}")
            print(f"    {url}")
    if not missing and not no_url:
        print("\nAll car images present.")
    print(f"\nPreview images saved to: {os.path.abspath(OUT_DIR)}")


if __name__ == '__main__':
    main()
