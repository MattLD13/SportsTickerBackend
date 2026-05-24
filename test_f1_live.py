"""
Standalone test for F1 live data sources.

Tests in order:
  1. OpenF1 API  (free between sessions; 401 during live sessions)
  2. F1 SignalR  (free always, no F1TV needed for basic topics)

Run:
    python test_f1_live.py
"""
import sys
import json
import threading
import time
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run:  pip install requests")
    sys.exit(1)

DIVIDER = "-" * 60

def jdump(obj, limit=200):
    return json.dumps(obj, default=str)[:limit]


# ===========================================================================
# PART 1 — OpenF1 REST API
# ===========================================================================

print(DIVIDER)
print("PART 1: OpenF1 REST API  (https://api.openf1.org/v1)")
print(DIVIDER)

BASE = "https://api.openf1.org/v1"
S = requests.Session()
S.headers.update({"User-Agent": "SportsTickerTest/1.0"})

def of1_get(endpoint, **params):
    url = f"{BASE}/{endpoint}"
    try:
        r = S.get(url, params=params or None, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = r.text[:300]
        return r.status_code, body
    except Exception as exc:
        return 0, str(exc)

now = datetime.now(timezone.utc)

# 1a. session_key=latest
code, body = of1_get("sessions", session_key="latest")
tag = "OK" if code == 200 else "!!"
print(f"\n{tag} [{code}]  sessions?session_key=latest")
if isinstance(body, dict):
    detail = body.get("detail", "")
    print(f"     {detail[:120]}")
    if "stripe" in detail.lower():
        print("     NOTE: OpenF1 requires a PAID API key during live sessions.")
elif isinstance(body, list):
    print(f"     {len(body)} session(s) returned")
    for s in body[:2]:
        print(f"     sk={s.get('session_key')}  {s.get('session_name')}  {s.get('date_start','')[:16]}")

# 1b. Date-range search (last 30 days)
week_ago = (now - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
code2, body2 = of1_get(f"sessions?date_start>={week_ago}")
tag2 = "OK" if code2 == 200 else "!!"
print(f"\n{tag2} [{code2}]  sessions (last 30 days)")
if isinstance(body2, dict):
    print(f"     {body2.get('detail','')[:120]}")
elif isinstance(body2, list):
    print(f"     {len(body2)} session(s) returned")
    live_sk = body2[-1].get('session_key') if body2 else None
    for s in body2[-3:]:
        print(f"     sk={s.get('session_key')}  {s.get('session_name'):<20}  {s.get('date_start','')[:16]}")

    if live_sk:
        # Try positions for the most recent session
        code3, body3 = of1_get("position", session_key=live_sk)
        tag3 = "OK" if code3 == 200 else "!!"
        print(f"\n{tag3} [{code3}]  position?session_key={live_sk}")
        if isinstance(body3, list) and body3:
            latest_pos = {}
            for p in body3:
                dn = p.get('driver_number')
                if dn not in latest_pos or p['date'] > latest_pos[dn]['date']:
                    latest_pos[dn] = p
            ranked = sorted(latest_pos.values(), key=lambda x: x.get('position', 99))
            for p in ranked[:5]:
                print(f"     P{p.get('position'):>2}  #{p.get('driver_number'):<3}  {p.get('date','')[:19]}")
        elif isinstance(body3, dict):
            print(f"     {body3.get('detail','')[:120]}")

        code4, body4 = of1_get("intervals", session_key=live_sk)
        tag4 = "OK" if code4 == 200 else "!!"
        print(f"\n{tag4} [{code4}]  intervals?session_key={live_sk}")
        if isinstance(body4, list) and body4:
            latest_iv = {}
            for iv in body4:
                dn = iv.get('driver_number')
                if dn not in latest_iv or iv.get('date','') > latest_iv[dn].get('date',''):
                    latest_iv[dn] = iv
            for dn, iv in list(sorted(latest_iv.items()))[:5]:
                print(f"     #{dn:<3}  gap_to_leader={str(iv.get('gap_to_leader')):<12}  interval={iv.get('interval_to_position_ahead')}")
        elif isinstance(body4, dict):
            print(f"     {body4.get('detail','')[:120]}")


# ===========================================================================
# PART 2 — F1 Official SignalR Feed  (livetiming.formula1.com)
# ===========================================================================

print(f"\n{DIVIDER}")
print("PART 2: F1 Official SignalR  (livetiming.formula1.com)")
print(DIVIDER)

NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
WS_URL        = "wss://livetiming.formula1.com/signalrcore"

# 2a. Negotiate handshake — use POST (correct for ASP.NET Core SignalR)
print("\n[2a] POST negotiate (get connection token + AWSALBCORS cookie)")
try:
    neg = requests.post(NEGOTIATE_URL, timeout=10,
                        headers={"Content-Type": "text/plain;charset=UTF-8"})
    print(f"     HTTP {neg.status_code}")
    cookie_val = neg.cookies.get("AWSALBCORS", "")
    print(f"     AWSALBCORS cookie: {'present (' + cookie_val[:20] + '...)' if cookie_val else 'MISSING'}")
    try:
        neg_json = neg.json()
        print(f"     connectionToken: {str(neg_json.get('connectionToken',''))[:40]}")
        print(f"     connectionId:    {neg_json.get('connectionId','')}")
    except Exception:
        print(f"     body: {neg.text[:200]}")
    neg_ok = neg.status_code == 200
except Exception as exc:
    print(f"     ERROR: {exc}")
    neg_ok = False
    cookie_val = ""

# 2b. Try signalrcore Python library if available
print("\n[2b] signalrcore Python library connection test (10s)")
try:
    from signalrcore.hub_connection_builder import HubConnectionBuilder
    from signalrcore.messages.completion_message import CompletionMessage
    HAS_SRC = True
except ImportError:
    HAS_SRC = False
    print("     signalrcore not installed.  Run:  pip install signalrcore")

if HAS_SRC:
    received = {"connected": False, "messages": [], "error": None}
    done_event = threading.Event()

    headers = {"Cookie": f"AWSALBCORS={cookie_val}"} if cookie_val else {}

    try:
        conn = (
            HubConnectionBuilder()
            .with_url(WS_URL, options={
                "verify_ssl": True,
                "headers": headers,
            })
            .build()
        )

        def on_open():
            received["connected"] = True
            print("     WebSocket OPEN")
            # Subscribe to free topics
            topics = ["SessionInfo", "DriverList", "TimingData",
                      "TrackStatus", "LapCount", "ExtrapolatedClock"]
            conn.send("Subscribe", [topics], on_invocation=on_msg)

        def on_close(*_):
            print("     WebSocket CLOSED")
            done_event.set()

        def on_msg(msg):
            received["messages"].append(msg)
            if len(received["messages"]) >= 3:
                done_event.set()

        conn.on_open(on_open)
        conn.on_close(on_close)
        conn.on("feed", on_msg)

        conn.start()
        done_event.wait(timeout=10)
        conn.stop()

    except Exception as exc:
        received["error"] = str(exc)

    print(f"     Connected:      {received['connected']}")
    print(f"     Messages rcvd:  {len(received['messages'])}")
    if received["error"]:
        print(f"     Error:          {received['error'][:120]}")

    if received["messages"]:
        for i, msg in enumerate(received["messages"][:3]):
            if isinstance(msg, CompletionMessage):
                keys = list(msg.result.keys()) if isinstance(msg.result, dict) else []
                print(f"     msg[{i}] CompletionMessage  keys={keys}")
            elif isinstance(msg, list):
                print(f"     msg[{i}] feed update  topic={msg[0] if msg else '?'}")
            else:
                print(f"     msg[{i}] {type(msg).__name__}  {str(msg)[:80]}")

# 2c. Check if the existing backend SignalR client is running
print("\n[2c] Check backend SignalR client status")
try:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from sports_ticker.fetchers import f1_signalr
    client = f1_signalr.get_client()
    if client is None:
        print("     signalrcore not installed — SignalR client disabled")
    else:
        time.sleep(2)  # give it a moment
        print(f"     is_connected: {client.is_connected}")
        data = client.get_live_data()
        dl = data.get("driver_list", {})
        tl = data.get("timing_lines", {})
        lc = data.get("lap_count", {})
        ts = data.get("track_status", {})
        print(f"     driver_list entries:  {len(dl)}")
        print(f"     timing_lines entries: {len(tl)}")
        print(f"     lap_count:            {lc}")
        print(f"     track_status:         {ts}")
        if dl:
            for num, d in list(dl.items())[:3]:
                tl_d = tl.get(str(num), {})
                print(f"     #{num}  {d.get('Tla','?')}  pos={tl_d.get('Position','?')}  gap={tl_d.get('GapToLeader','?')}")
except Exception as exc:
    print(f"     ERROR loading backend client: {exc}")

# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{DIVIDER}")
print("RESULT SUMMARY")
print(DIVIDER)
print("  OpenF1  FREE: between sessions and post-race  (historical data)")
print("  OpenF1  PAID: during any live session (Stripe API key required)")
print("  SignalR FREE: always — no F1TV subscription needed for:")
print("    DriverList, TimingData, TrackStatus, LapCount, ExtrapolatedClock")
print()
print("  => If SignalR connected=True above, live data is working for free.")
print("  => If SignalR is 403/blocked, the server IP is being filtered by F1.")
print(DIVIDER)
