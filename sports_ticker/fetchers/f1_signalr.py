"""Background SignalR client for F1 Live Timing (livetiming.formula1.com).

Connects to the official F1 timing WebSocket feed and keeps an in-memory
snapshot of live driver positions, gaps, and session status.
"""

import json
import threading
import time
import urllib.parse

import requests

try:
    import websocket
    _HAS_WEBSOCKET = True
except ImportError:
    _HAS_WEBSOCKET = False

_SIGNALR_HOST = "livetiming.formula1.com"
_NEGOTIATE_URL = f"https://{_SIGNALR_HOST}/signalr/negotiate"
_WS_BASE       = f"wss://{_SIGNALR_HOST}/signalr/connect"

_TOPICS = [
    "DriverList",
    "TimingData",
    "TrackStatus",
    "SessionStatus",
    "RaceControlMessages",
]

_HEADERS = {
    "User-Agent":      "Mozilla/5.0",
    "Accept":          "application/json",
    "Accept-Language": "en",
}


class F1LiveTimingClient:
    """
    Persistent SignalR WebSocket client for F1 live timing.

    Start once at import time via module-level singleton.
    Call get_live_data() from any thread to read the latest snapshot.
    """

    def __init__(self):
        self._lock     = threading.Lock()
        self._ws       = None
        self._running  = False
        self._invoke_id = 0
        self._connected = False

        # Live data store — updated in place as messages arrive
        self._driver_list   = {}   # keyed by racing number string
        self._timing_lines  = {}   # keyed by racing number string
        self._track_status  = {}
        self._session_status = ''

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if self._running or not _HAS_WEBSOCKET:
            return
        self._running = True
        t = threading.Thread(target=self._run_loop, name='f1_signalr', daemon=True)
        t.start()

    def stop(self):
        self._running = False
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    @property
    def is_connected(self):
        return self._connected

    def get_live_data(self):
        """Return a snapshot of the latest timing data (thread-safe)."""
        with self._lock:
            return {
                'driver_list':    dict(self._driver_list),
                'timing_lines':   dict(self._timing_lines),
                'track_status':   dict(self._track_status),
                'session_status': self._session_status,
            }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _negotiate(self):
        params = {
            'clientProtocol': '1.5',
            'connectionData': '[{"name":"streaming"}]',
        }
        r = requests.get(_NEGOTIATE_URL, params=params, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()['ConnectionToken']

    def _ws_url(self, token):
        qs = urllib.parse.urlencode({
            'clientProtocol': '1.5',
            'transport':      'webSockets',
            'connectionToken': token,
            'connectionData': '[{"name":"streaming"}]',
        })
        return f"{_WS_BASE}?{qs}"

    def _on_open(self, ws):
        self._invoke_id += 1
        msg = json.dumps({
            'H': 'streaming',
            'M': 'Subscribe',
            'A': [_TOPICS],
            'I': self._invoke_id,
        })
        ws.send(msg)

    def _on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        # Response to our Subscribe call — contains the full initial state
        result = msg.get('R')
        if isinstance(result, dict):
            self._apply_initial_state(result)
            self._connected = True

        # Incremental push messages from the server
        for item in msg.get('M', []):
            if str(item.get('H', '')).lower() == 'streaming' and item.get('M') == 'feed':
                args = item.get('A', [])
                if len(args) >= 2:
                    self._apply_feed(args[0], args[1])

    def _on_error(self, ws, error):
        print(f"[F1 SignalR] error: {error}")

    def _on_close(self, ws, code, msg):
        self._connected = False

    def _apply_initial_state(self, state):
        with self._lock:
            dl = state.get('DriverList', {})
            if isinstance(dl, dict):
                self._driver_list.update(dl)

            td = state.get('TimingData', {})
            if isinstance(td, dict):
                lines = td.get('Lines', {})
                if isinstance(lines, dict):
                    self._timing_lines.update(lines)

            ts = state.get('TrackStatus', {})
            if isinstance(ts, dict):
                self._track_status.update(ts)

            ss = state.get('SessionStatus', {})
            if isinstance(ss, dict):
                self._session_status = str(ss.get('Status', self._session_status))

    def _apply_feed(self, topic, data):
        if not isinstance(data, dict):
            return
        with self._lock:
            if topic == 'DriverList':
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

    @staticmethod
    def _merge_nested(target, source):
        """Recursively merge source into target (dict of dicts)."""
        for key, val in source.items():
            if isinstance(val, dict) and isinstance(target.get(key), dict):
                F1LiveTimingClient._merge_nested(target[key], val)
            else:
                target[key] = val

    def _run_loop(self):
        while self._running:
            try:
                token = self._negotiate()
                url   = self._ws_url(token)
                self._ws = websocket.WebSocketApp(
                    url,
                    header=[f"{k}: {v}" for k, v in _HEADERS.items()],
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                print(f"[F1 SignalR] connection loop error: {exc}")
            finally:
                self._connected = False
            if self._running:
                time.sleep(5)


# ── Module-level singleton ────────────────────────────────────────────────────

_client: F1LiveTimingClient | None = None
_client_lock = threading.Lock()


def get_client() -> F1LiveTimingClient | None:
    """Return the running SignalR client, starting it on first call."""
    global _client
    if not _HAS_WEBSOCKET:
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = F1LiveTimingClient()
                _client.start()
    return _client
