"""Diagnose why NASCAR car images aren't loading."""
import io
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
from PIL import Image

# Replicate the URL builder from sports_nascar.py
from datetime import date, timedelta

_NASCAR_IMG_BASE = "https://www.nascar.com/wp-content/uploads/sites/7"
_NCS_2026 = {
    5593: (1,  'Bowmangray',  '2026-02-04'),
    5596: (2,  'Daytona',     '2026-02-15'),
    5610: (15, 'Charlotte',   '2026-05-24'),
    # All-Star race (use whatever race_id was in the live feed — try a few)
    5621: (13, 'Watkinsglen', '2026-05-10'),
    5609: (14, 'Dover',       '2026-05-17'),
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nascar.com/',
}

def build_url(race_id, car_number, year=2026):
    entry = _NCS_2026.get(int(race_id or 0))
    if not entry:
        return None
    race_num, track_slug, race_date_iso = entry
    race_day = date.fromisoformat(race_date_iso)
    upload_day = race_day - timedelta(days=5)
    yy  = str(year)[-2:]
    mon = f"{upload_day.month:02d}"
    day = f"{upload_day.day:02d}"
    car = str(car_number).strip()
    return f"{_NASCAR_IMG_BASE}/{year}/{mon}/{day}/{yy}_NCS_{race_num}{track_slug}_{car}-922x400.jpg"

print("=== NASCAR Car Image Diagnostic ===\n")

# Test a known URL from the live feed
# The All-Star race was May 17 2026 at North Wilkesboro — check what race_id it has
# Try a few race IDs and car numbers
test_cases = [
    (5609, '5',   'Dover race car #5'),
    (5609, '48',  'Dover race car #48'),
    (5610, '24',  'Charlotte race car #24'),
    (5618, '5',   'NWB car #5'),   # 5618 = Northwilkesboro
]

for race_id, car, label in test_cases:
    url = build_url(race_id, car)
    if not url:
        print(f"[{label}] No URL built (race_id {race_id} not in map)")
        continue
    print(f"[{label}]")
    print(f"  URL: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"  HTTP status: {r.status_code}")
        if r.status_code == 200:
            ct = r.headers.get('Content-Type', '')
            print(f"  Content-Type: {ct}")
            print(f"  Content-Length: {len(r.content)} bytes")
            try:
                img = Image.open(io.BytesIO(r.content))
                print(f"  Image size: {img.size}, mode: {img.mode}")
                print(f"  SUCCESS - image loaded OK")
            except Exception as e:
                print(f"  PIL ERROR: {e}")
        else:
            print(f"  FAILED - {r.status_code} {r.reason}")
    except Exception as e:
        print(f"  REQUEST ERROR: {e}")
    print()

# Also print what URL the live feed would have produced
print("\n=== Live feed URL test ===")
print("Enter the race_id and a car number from the live JSON to test:")
print("(Ctrl+C to skip)")
try:
    race_id_in = int(input("race_id: ").strip())
    car_in = input("car number: ").strip()
    url = build_url(race_id_in, car_in)
    print(f"URL: {url}")
    if url:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"HTTP {r.status_code}")
        if r.status_code == 200:
            img = Image.open(io.BytesIO(r.content))
            print(f"Image: {img.size} {img.mode} - OK")
        else:
            # Show redirect location if any
            print(f"Reason: {r.reason}")
            if r.history:
                print(f"Redirects: {[resp.url for resp in r.history]}")
    else:
        print("race_id not in map — add it to _NCS_2026")
except (KeyboardInterrupt, EOFError):
    print("(skipped)")
