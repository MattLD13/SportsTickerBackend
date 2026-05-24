"""Background SignalR Core client for F1 Live Timing (livetiming.formula1.com).

Uses the /signalrcore endpoint (ASP.NET Core SignalR), matching the approach
of the FastF1 library. A cookie-based negotiate handshake obtains the
AWSALBCORS token needed for the WebSocket upgrade. TimingData, DriverList,
LapCount, TrackStatus, ExtrapolatedClock, and SessionInfo are all free and
require no F1TV subscription.
"""

import asyncio
import json
import logging
import os
import threading
import time

import requests

try:
    from signalrcore.hub_connection_builder import HubConnectionBuilder
    from signalrcore.messages.completion_message import CompletionMessage
    _HAS_SIGNALRCORE = True
except ImportError:
    _HAS_SIGNALRCORE = False

try:
    import websockets.asyncio.client as _ws_client
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False

# ASP.NET Core SignalR uses Record Separator (0x1E) as message delimiter.
_SIGNALR_SEP = '\x1e'

# Set F1_SIGNALR_PROXY_HOST to route through a Cloudflare Worker (or any
# reverse-proxy) when the server IP is blocked by F1's CDN.
# Example: F1_SIGNALR_PROXY_HOST=f1-signalr-proxy.yourname.workers.dev
_PROXY_HOST    = os.getenv("F1_SIGNALR_PROXY_HOST", "").strip()
_NEGOTIATE_URL = (
    f"https://{_PROXY_HOST}/signalrcore/negotiate?negotiateVersion=1"
    if _PROXY_HOST else
    "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
)
_WS_URL = (
    f"wss://{_PROXY_HOST}/signalrcore"
    if _PROXY_HOST else
    "wss://livetiming.formula1.com/signalrcore"
)
# Default retry delay after a 403.  Keep short — F1's CDN blocks by IP and
# may unblock after a few minutes.  Override with the env var if needed.
_FORBIDDEN_COOLDOWN_SECONDS = int(os.getenv("F1_SIGNALR_403_COOLDOWN_SECONDS", "300"))

# Headers that make the negotiate request look like a browser visiting
# formula1.com — CDNs / WAFs commonly check Origin and Referer.
_BROWSER_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36",
    "Origin":          "https://www.formula1.com",
    "Referer":         "https://www.formula1.com/",
    "Accept":          "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_TOPICS = [
    "SessionInfo",
    "DriverList",
    "TimingData",
    "TrackStatus",
    "SessionStatus",
    "LapCount",
    "ExtrapolatedClock",
    "RaceControlMessages",
]


class F1LiveTimingClient:
    """Persistent SignalR Core client for F1 live timing.

    Started once at module load via the singleton.  Call get_live_data() from
    any thread to read the latest snapshot.
    """

    def __init__(self):
        self._lock          = threading.Lock()
        self._connection    = None
        self._running       = False
        self._connected     = False
        self._blocked_until = 0.0

        # Live data store
        self._driver_list        = {}
        self._timing_lines       = {}
        self._track_status       = {}
        self._session_status     = ''
        self._session_info       = {}
        self._lap_count          = {}
        self._extrapolated_clock = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if self._running or not _HAS_SIGNALRCORE:
            return
        self._running = True
        t = threading.Thread(target=self._run_loop, name='f1_signalr', daemon=True)
        t.start()

    def stop(self):
        self._running = False
        conn = self._connection
        if conn:
            try:
                conn.stop()
            except Exception:
                pass

    @property
    def is_connected(self):
        return self._connected

    def get_live_data(self):
        """Return a snapshot of the latest timing data (thread-safe)."""
        with self._lock:
            return {
                'driver_list':        dict(self._driver_list),
                'timing_lines':       dict(self._timing_lines),
                'track_status':       dict(self._track_status),
                'session_status':     self._session_status,
                'session_info':       dict(self._session_info),
                'lap_count':          dict(self._lap_count),
                'extrapolated_clock': dict(self._extrapolated_clock),
            }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply_topic(self, topic, data):
        if not isinstance(data, dict):
            return
        with self._lock:
            if topic == 'SessionInfo':
                self._merge_nested(self._session_info, data)
            elif topic == 'DriverList':
                self._merge_nested(self._driver_list, data)
            elif topic == 'TimingData':
                lines = data.get('Lines', {})
                if isinstance(lines, dict):
                    self._merge_nested(self._timing_lines, lines)
            elif topic == 'TrackStatus':
                self._track_status.update(data)
            elif topic == 'SessionStatus':
                status = data.get('Status')
                if status:
                    self._session_status = str(status)
            elif topic == 'LapCount':
                self._lap_count.update(data)
            elif topic == 'ExtrapolatedClock':
                self._extrapolated_clock.update(data)

    def _on_message(self, msg):
        """Handle messages from signalrcore hub.

        CompletionMessage = initial state bulk-dump after Subscribe.
        list              = incremental feed: [topic, data] or [topic, data, ''].
        """
        try:
            if isinstance(msg, CompletionMessage):
                if isinstance(msg.result, dict):
                    for topic, data in msg.result.items():
                        self._apply_topic(topic, data)
                    self._connected = True
            elif isinstance(msg, list) and len(msg) >= 2:
                self._apply_topic(msg[0], msg[1])
        except Exception as exc:
            print(f"[F1 SignalR] message parse error: {exc}")

    def _run_loop(self):
        logging.getLogger('signalrcore').setLevel(logging.WARNING)

        # When a proxy host is configured, Cloudflare's Browser Integrity Check
        # blocks urllib (used by signalrcore internally for negotiate).
        # Use our own async SignalR implementation that drives everything with
        # requests + websockets — both send headers we can control.
        if _PROXY_HOST and _HAS_WEBSOCKETS:
            asyncio.run(self._run_loop_proxy())
            return

        while self._running:
            now = time.time()
            if self._blocked_until > now:
                time.sleep(min(self._blocked_until - now, 60))
                continue

            open_event  = threading.Event()
            close_event = threading.Event()

            try:
                # 1. POST negotiate to obtain the AWSALBCORS load-balancer cookie.
                #    Browser-like headers (Origin, Referer, UA) help bypass CDN
                #    rules that block plain server/bot requests.
                neg_headers = {
                    **_BROWSER_HEADERS,
                    "Content-Type": "text/plain;charset=UTF-8",
                }
                r = requests.post(_NEGOTIATE_URL, timeout=10, headers=neg_headers)
                if r.status_code == 403:
                    self._blocked_until = time.time() + _FORBIDDEN_COOLDOWN_SECONDS
                    print(f"[F1 SignalR] 403 at negotiate; retrying in {_FORBIDDEN_COOLDOWN_SECONDS}s")
                    continue
                if not r.ok:
                    print(f"[F1 SignalR] negotiate HTTP {r.status_code}; retrying in 30s")
                    time.sleep(30)
                    continue

                cookie_val = r.cookies.get("AWSALBCORS", "")
                ws_headers = {**_BROWSER_HEADERS}
                if cookie_val:
                    ws_headers["Cookie"] = f"AWSALBCORS={cookie_val}"

                # 2. Build SignalR Core connection (no F1TV auth — free topics only).
                #    Pass the same browser headers to the WebSocket upgrade so the
                #    CDN sees a consistent request fingerprint.
                #    Do NOT pass access_token_factory=None — signalrcore requires
                #    it to be a callable or absent entirely.
                conn = (
                    HubConnectionBuilder()
                    .with_url(_WS_URL, options={
                        "verify_ssl": True,
                        "headers":    ws_headers,
                    })
                    .build()
                )

                def _on_open():
                    open_event.set()
                    print("[F1 SignalR] connected")

                def _on_close(*_):
                    self._connected = False
                    close_event.set()
                    print("[F1 SignalR] disconnected")

                conn.on_open(_on_open)
                conn.on_close(_on_close)
                conn.on("feed", self._on_message)

                self._connection = conn
                conn.start()

                # 3. Wait for WebSocket to open before subscribing
                if not open_event.wait(timeout=15):
                    print("[F1 SignalR] connection timed out")
                    conn.stop()
                    time.sleep(10)
                    continue

                conn.send("Subscribe", [_TOPICS], on_invocation=self._on_message)

                # 4. Stay alive until the server closes the connection
                while self._running and not close_event.wait(timeout=5):
                    pass

            except Exception as exc:
                err = str(exc)
                if '403' in err or 'Forbidden' in err:
                    self._blocked_until = time.time() + _FORBIDDEN_COOLDOWN_SECONDS
                    print(f"[F1 SignalR] 403 Forbidden; retrying in {_FORBIDDEN_COOLDOWN_SECONDS}s")
                else:
                    print(f"[F1 SignalR] connection error: {exc}")
            finally:
                self._connected = False

            if self._running:
                time.sleep(10)

    async def _run_loop_proxy(self):
        """Async SignalR client for proxy mode.

        Cloudflare's Browser Integrity Check blocks urllib (used internally by
        signalrcore) before the Worker script even runs.  This implementation
        drives the full protocol manually:
          - negotiate  via requests  (respects our custom headers — BIC passes)
          - WebSocket  via websockets (proper Upgrade headers — BIC passes)
        """
        while self._running:
            now = time.time()
            if self._blocked_until > now:
                await asyncio.sleep(min(self._blocked_until - now, 60))
                continue

            try:
                # 1. Negotiate (requests library — gets past Cloudflare BIC)
                neg_headers = {**_BROWSER_HEADERS, "Content-Type": "text/plain;charset=UTF-8"}
                r = requests.post(_NEGOTIATE_URL, timeout=10, headers=neg_headers)
                if r.status_code == 403:
                    self._blocked_until = time.time() + _FORBIDDEN_COOLDOWN_SECONDS
                    print(f"[F1 SignalR] 403 at negotiate (proxy); retrying in {_FORBIDDEN_COOLDOWN_SECONDS}s")
                    continue
                if not r.ok:
                    print(f"[F1 SignalR] negotiate HTTP {r.status_code} (proxy); retrying in 30s")
                    await asyncio.sleep(30)
                    continue

                token  = r.json().get("connectionToken", "")
                cookie = r.cookies.get("AWSALBCORS", "")

                # 2. Connect WebSocket via proxy (websockets library — BIC passes)
                ws_url = f"wss://{_PROXY_HOST}/signalrcore?id={token}"
                ws_hdrs = dict(_BROWSER_HEADERS)
                if cookie:
                    ws_hdrs["Cookie"] = f"AWSALBCORS={cookie}"

                async with _ws_client.connect(
                    ws_url,
                    additional_headers=ws_hdrs,
                    user_agent_header=None,   # suppress websockets' default UA
                ) as ws:
                    print("[F1 SignalR] connected (proxy)")
                    self._connected = True

                    # 3. SignalR Core handshake
                    await ws.send('{"protocol":"json","version":1}' + _SIGNALR_SEP)
                    await asyncio.wait_for(ws.recv(), timeout=10)   # expect {}\x1e

                    # 4. Subscribe to free topics
                    await ws.send(
                        json.dumps({
                            "type":         1,
                            "invocationId": "0",
                            "target":       "Subscribe",
                            "arguments":    [_TOPICS],
                        }) + _SIGNALR_SEP
                    )

                    # 5. Pump incoming messages
                    async for raw in ws:
                        if not self._running:
                            break
                        for frame in str(raw).split(_SIGNALR_SEP):
                            frame = frame.strip()
                            if not frame:
                                continue
                            try:
                                msg = json.loads(frame)
                            except json.JSONDecodeError:
                                continue
                            # type 1 = server push (incremental update)
                            # type 3 = completion of our Subscribe (bulk snapshot)
                            mtype = msg.get("type")
                            if mtype == 1:
                                args = msg.get("arguments", [])
                                if msg.get("target") == "feed" and len(args) >= 2:
                                    self._apply_topic(args[0], args[1])
                            elif mtype == 3:
                                result = msg.get("result", {})
                                if isinstance(result, dict):
                                    for topic, data in result.items():
                                        self._apply_topic(topic, data)
                                    self._connected = True

            except Exception as exc:
                err = str(exc)
                if "403" in err or "Forbidden" in err:
                    self._blocked_until = time.time() + _FORBIDDEN_COOLDOWN_SECONDS
                    print(f"[F1 SignalR] 403 (proxy); retrying in {_FORBIDDEN_COOLDOWN_SECONDS}s")
                else:
                    print(f"[F1 SignalR] proxy connection error: {exc}")
            finally:
                self._connected = False

            if self._running:
                await asyncio.sleep(10)

    @staticmethod
    def _merge_nested(target, source):
        for key, val in source.items():
            if isinstance(val, dict) and isinstance(target.get(key), dict):
                F1LiveTimingClient._merge_nested(target[key], val)
            else:
                target[key] = val


# ── Module-level singleton ────────────────────────────────────────────────────

_client: F1LiveTimingClient | None = None
_client_lock = threading.Lock()


def get_client() -> F1LiveTimingClient | None:
    """Return the running SignalR client, starting it on first call."""
    global _client
    # Need at least one of: signalrcore (direct) or websockets+proxy (proxy mode)
    if not _HAS_SIGNALRCORE and not (_PROXY_HOST and _HAS_WEBSOCKETS):
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = F1LiveTimingClient()
                _client.start()
    return _client
