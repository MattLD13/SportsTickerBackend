"""Background SignalR Core client for F1 Live Timing (livetiming.formula1.com).

Uses the /signalrcore endpoint (ASP.NET Core SignalR), matching the approach
of the FastF1 library. A cookie-based negotiate handshake obtains the
AWSALBCORS token needed for the WebSocket upgrade. TimingData, DriverList,
LapCount, TrackStatus, ExtrapolatedClock, and SessionInfo are all free and
require no F1TV subscription.
"""

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

_NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate"
_WS_URL        = "wss://livetiming.formula1.com/signalrcore"
_FORBIDDEN_COOLDOWN_SECONDS = int(os.getenv("F1_SIGNALR_403_COOLDOWN_SECONDS", "21600"))

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

        while self._running:
            now = time.time()
            if self._blocked_until > now:
                time.sleep(min(self._blocked_until - now, 60))
                continue

            open_event  = threading.Event()
            close_event = threading.Event()

            try:
                # 1. Pre-negotiate to obtain the AWSALBCORS load-balancer cookie
                r = requests.options(_NEGOTIATE_URL, timeout=10)
                if r.status_code == 403:
                    self._blocked_until = time.time() + _FORBIDDEN_COOLDOWN_SECONDS
                    print(f"[F1 SignalR] 403 at negotiate; disabled for {_FORBIDDEN_COOLDOWN_SECONDS}s")
                    continue
                r.raise_for_status()

                cookie_val = r.cookies.get("AWSALBCORS", "")
                headers    = {"Cookie": f"AWSALBCORS={cookie_val}"} if cookie_val else {}

                # 2. Build SignalR Core connection (no F1TV auth — free topics only)
                conn = (
                    HubConnectionBuilder()
                    .with_url(_WS_URL, options={
                        "verify_ssl":           True,
                        "access_token_factory": None,
                        "headers":              headers,
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
                    print(f"[F1 SignalR] 403 Forbidden; disabled for {_FORBIDDEN_COOLDOWN_SECONDS}s")
                else:
                    print(f"[F1 SignalR] connection error: {exc}")
            finally:
                self._connected = False

            if self._running:
                time.sleep(10)

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
    if not _HAS_SIGNALRCORE:
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = F1LiveTimingClient()
                _client.start()
    return _client
