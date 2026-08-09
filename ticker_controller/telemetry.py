"""Health facts a controller reports about itself.

A Pi behind a panel is headless and often out of reach, so its own state has to
travel with traffic it already sends. These values ride as headers on the /data
poll, which costs no extra request and no extra thread.

Read them back with GET /api/health, or on the dashboard.
"""

import os
import subprocess
import sys
import time

# Wall-clock start, not monotonic: the number is reported to a server that
# wants "how long has this board been up", not an interval measurement.
_STARTED = time.time()

# The Pi exposes its SoC temperature here, in millidegrees Celsius. The panels
# themselves carry no sensor, so this is the controller's temperature and it is
# reported under that name.
_TEMP_PATH = '/sys/class/thermal/thermal_zone0/temp'

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_build_id = None


def uptime_seconds() -> int:
    """Seconds since this controller process started."""
    return int(max(0, time.time() - _STARTED))


def soc_temp_c():
    """Controller temperature in Celsius, or None where the sensor is absent."""
    try:
        with open(_TEMP_PATH) as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None


def build_id() -> str:
    """The checkout this controller is running, as "r<count>+<sha>".

    Read from git once and kept, because it cannot change while the process
    lives: updater.py restarts the service after it pulls. The format matches
    the server's own version string, so the dashboard can compare them.
    """
    global _build_id
    if _build_id is not None:
        return _build_id
    kwargs = dict(cwd=_REPO_ROOT, stderr=subprocess.DEVNULL, encoding='utf-8', timeout=5)
    try:
        count = subprocess.check_output(['git', 'rev-list', '--count', 'HEAD'], **kwargs).strip()
        sha = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], **kwargs).strip()
        _build_id = f"r{count}+{sha}"
    except Exception:
        _build_id = 'unknown'
    return _build_id


def poll_headers() -> dict:
    """Telemetry headers to attach to a /data poll.

    A value the board cannot read is left out rather than sent as a placeholder,
    so the dashboard can tell "no sensor" apart from "sensor reads zero".
    """
    headers = {
        'X-Ticker-Uptime': str(uptime_seconds()),
        'X-Ticker-Build': build_id(),
        'X-Ticker-Python': sys.version.split()[0],
    }
    temp = soc_temp_c()
    if temp is not None:
        headers['X-Ticker-Temp'] = str(temp)
    return headers
