"""
Standalone test for OpenF1 live data.

Probes every meaningful endpoint / approach to find out exactly what is
accessible for free (no auth) and what requires a subscription.

Run:
    python test_openf1.py
"""

import sys
import json
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is not installed.  Run:  pip install requests")
    sys.exit(1)

BASE = "https://api.openf1.org/v1"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SportsTickerBackend/test"})

DIVIDER = "-" * 60

def get(path_or_url, **params):
    """GET helper ? returns (status_code, json_or_text)."""
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}/{path_or_url.lstrip('/')}"
    try:
        r = SESSION.get(url, params=params or None, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = r.text[:200]
        return r.status_code, body
    except Exception as exc:
        return 0, str(exc)


def show(label, status, body, preview=5):
    ok = "OK" if status == 200 else "!!"
    print(f"\n{ok} [{status}]  {label}")
    if isinstance(body, list):
        print(f"    list of {len(body)} items")
        for item in body[:preview]:
            print(f"      {json.dumps(item, default=str)[:120]}")
        if len(body) > preview:
            print(f"      ... ({len(body) - preview} more)")
    elif isinstance(body, dict):
        print(f"    ? dict: {json.dumps(body, default=str)[:200]}")
    else:
        print(f"    ? {str(body)[:200]}")


# ??? 1. session_key=latest ????????????????????????????????????????????????????
print(DIVIDER)
print("TEST 1 ? session_key=latest  (requires sponsor tier?)")
status, body = get("sessions", session_key="latest")
show("sessions?session_key=latest", status, body)

# ??? 2. Current race weekend by date range ????????????????????????????????????
print(DIVIDER)
print("TEST 2 ? find today's session by date range  (should be free)")
now = datetime.now(timezone.utc)
window_start = (now - timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%SZ')
window_end   = (now + timedelta(hours=48)).strftime('%Y-%m-%dT%H:%M:%SZ')
status, body = get(
    f"sessions?date_start>={window_start}&date_start<={window_end}"
)
show(f"sessions by date window [{window_start} ? {window_end}]", status, body)

# If we got sessions, store the most recent key for subsequent tests
live_sk = None
if status == 200 and isinstance(body, list) and body:
    live_sk = body[-1].get('session_key')
    print(f"\n  ? Will use session_key={live_sk} for follow-up tests")

# ??? 3. Most recent race weekend (any session) ????????????????????????????????
print(DIVIDER)
print("TEST 3 ? last 3 sessions (no filter) ? always returns something")
status, body = get("sessions", limit=3)
# OpenF1 doesn't support limit in older versions; try a date 30 days back
week_ago = (now - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
status2, body2 = get(f"sessions?date_start>={week_ago}")
show(f"sessions in the last 30 days", status2, body2, preview=3)

if status2 == 200 and isinstance(body2, list) and body2:
    # Use the most recent session if we didn't find one above
    if not live_sk:
        live_sk = body2[-1].get('session_key')
        print(f"\n  ? Falling back to session_key={live_sk}")

# ??? 4. Positions for the discovered session key ??????????????????????????????
if live_sk:
    print(DIVIDER)
    print(f"TEST 4 ? positions  (session_key={live_sk})")
    status, body = get("position", session_key=live_sk)
    show(f"position?session_key={live_sk}", status, body, preview=3)

    # Show only the latest position per driver
    if status == 200 and isinstance(body, list):
        latest = {}
        for p in body:
            dn = p.get('driver_number')
            if dn not in latest or p['date'] > latest[dn]['date']:
                latest[dn] = p
        ranked = sorted(latest.values(), key=lambda x: x.get('position', 99))
        print(f"\n  Latest positions ({len(ranked)} drivers):")
        for p in ranked:
            print(f"    P{p.get('position'):>2}  #{p.get('driver_number'):<3}  {p.get('date','')[:19]}")

# ??? 5. Intervals / gaps for the discovered session key ???????????????????????
if live_sk:
    print(DIVIDER)
    print(f"TEST 5 ? intervals / gaps  (session_key={live_sk})")
    status, body = get("intervals", session_key=live_sk)
    show(f"intervals?session_key={live_sk}", status, body, preview=3)

    if status == 200 and isinstance(body, list):
        latest_iv = {}
        for iv in body:
            dn = iv.get('driver_number')
            if dn not in latest_iv or iv.get('date','') > latest_iv[dn].get('date',''):
                latest_iv[dn] = iv
        print(f"\n  Latest intervals ({len(latest_iv)} drivers):")
        for dn, iv in sorted(latest_iv.items(), key=lambda x: x[0]):
            print(f"    #{dn:<3}  gap_to_leader={iv.get('gap_to_leader')!r:<12}  interval_to_ahead={iv.get('interval_to_position_ahead')!r}")

# ??? 6. Driver info for the discovered session key ????????????????????????????
if live_sk:
    print(DIVIDER)
    print(f"TEST 6 ? driver list  (session_key={live_sk})")
    status, body = get("drivers", session_key=live_sk)
    show(f"drivers?session_key={live_sk}", status, body, preview=5)

    if status == 200 and isinstance(body, list):
        print(f"\n  Drivers ({len(body)}):")
        for d in body:
            print(f"    #{d.get('driver_number'):<3}  {d.get('name_acronym','???')}  {d.get('full_name',''):<25}  {d.get('team_name','')}")

# ??? 7. Lap data for qualifying ???????????????????????????????????????????????
if live_sk:
    print(DIVIDER)
    print(f"TEST 7 ? laps  (session_key={live_sk}, driver_number=1)")
    status, body = get("laps", session_key=live_sk, driver_number=1)
    show(f"laps?session_key={live_sk}&driver_number=1", status, body, preview=3)

# ??? 8. Race control (flags, SC, safety car) ?????????????????????????????????
if live_sk:
    print(DIVIDER)
    print(f"TEST 8 ? race control messages  (session_key={live_sk})")
    status, body = get("race_control", session_key=live_sk)
    show(f"race_control?session_key={live_sk}", status, body, preview=5)

# ??? Summary ??????????????????????????????????????????????????????????????????
print(f"\n{DIVIDER}")
print("SUMMARY")
print(f"  Session key used for tests 4-8: {live_sk}")
print(f"  Run again during a live F1 session to test real-time data.")
print(f"  If tests 4-5 return 200 with data, positions+gaps are free.")
print(f"  If 401, a sponsor API key is needed for that endpoint/session_key.")
print(DIVIDER)
