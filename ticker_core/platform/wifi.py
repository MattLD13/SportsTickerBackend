"""Wi-Fi recovery and setup portal services."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from collections import deque
import json
import os
import secrets
import socket
import subprocess
import ssl
from threading import Thread
import time
from pathlib import Path
from typing import Any, Protocol

from flask import Flask, render_template_string, request

from ticker_core._enum import StrEnum

from .commands import PlatformCommands, WiFiNetwork


PORTAL_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect your ticker</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #f3f5f7; color: #17212b; }
    main { width: min(100% - 32px, 520px); margin: 0 auto; padding: 28px 0 40px; }
    .card { background: white; border-radius: 18px; box-shadow: 0 8px 30px #17212b18; padding: 24px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    p { color: #52606d; line-height: 1.45; }
    .setup { background: #edf7ff; border: 1px solid #b9def7; border-radius: 12px; padding: 14px; margin: 20px 0; }
    .setup strong, code { color: #075985; font-weight: 700; }
    .setup p { margin: 5px 0 0; font-size: 14px; }
    label { display: block; margin: 18px 0 7px; font-weight: 650; }
    select, input { width: 100%; min-height: 48px; border: 1px solid #c7d0d9; border-radius: 10px; padding: 10px 12px; font-size: 17px; background: white; }
    button { width: 100%; min-height: 50px; margin-top: 24px; border: 0; border-radius: 10px; background: #0969da; color: white; font-size: 17px; font-weight: 700; }
    button:active { background: #0757b5; }
    .help { font-size: 14px; margin-bottom: 0; }
    [hidden] { display: none; }
  </style>
</head>
<body>
  <main>
    <section class="card">
      <h1>Connect your ticker</h1>
      <p>Choose your home Wi-Fi network. The ticker will reboot after it connects.</p>
      <div class="setup">
        <strong>Setup code: {{ setup_code }}</strong>
        <p>Wi-Fi: <code>{{ hotspot.ssid }}</code><br>Password: <code>{{ hotspot.password }}</code><br>Session expires in {{ setup_minutes }} minutes.</p>
      </div>
      <form action="/connect" method="post">
        <label for="ssid_select">Home Wi-Fi network</label>
        <select id="ssid_select" name="ssid_select" onchange="toggleManual()">
          {% for network in networks %}<option value="{{ network }}">{{ network }}</option>{% endfor %}
          <option value="__manual__">Enter network manually</option>
        </select>
        <div id="manual_fields" hidden>
          <label for="ssid_manual">Network name</label>
          <input id="ssid_manual" name="ssid_manual" autocomplete="username">
        </div>
        <label for="password">Home Wi-Fi password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
        <label for="setup_code">Setup code</label>
        <input id="setup_code" name="setup_code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" placeholder="Six digits" required>
        <button type="submit">Connect ticker</button>
      </form>
      <p class="help">Keep this page open while the ticker connects. It will restart automatically.</p>
    </section>
  </main>
  <script>
    function toggleManual() {
      document.getElementById('manual_fields').hidden = document.getElementById('ssid_select').value !== '__manual__';
    }
    toggleManual();
  </script>
</body>
</html>
"""


@dataclass(frozen=True, slots=True)
class HotspotDetails:
    """Describe the hotspot used for Wi-Fi setup."""

    ssid: str
    password: str
    interface: str = "wlan0"


class WiFiAvailability(StrEnum):
    """Name the display-relevant Wi-Fi lifecycle state."""

    ONLINE = "online"
    SETUP_REQUIRED = "setup_required"


@dataclass(frozen=True, slots=True)
class WiFiSetupState:
    """Report the current Wi-Fi recovery state."""

    internet_available: bool
    hotspot_active: bool
    hotspot: HotspotDetails
    setup_url: str = "https://10.42.0.1"
    setup_code: str = "123456"

    @property
    def availability(self) -> WiFiAvailability:
        """Return the typed availability state owned by the platform service."""

        return (
            WiFiAvailability.ONLINE
            if self.internet_available
            else WiFiAvailability.SETUP_REQUIRED
        )


class PortalRunner(Protocol):
    """Run the Flask portal after explicit setup starts."""

    def __call__(self, app: Flask, host: str, port: int) -> None:
        """Run the portal."""


class HotspotStarter(Protocol):
    """Start the Wi-Fi hotspot for setup."""

    def __call__(self, details: HotspotDetails) -> None:
        """Start the hotspot."""


class SetupUnavailableError(RuntimeError):
    """Report an inactive or expired setup session."""


class SetupRateLimitError(RuntimeError):
    """Report too many setup submissions within the configured window."""


def probe_internet() -> bool:
    """Return true when the Pi can reach a public DNS endpoint."""
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=3):
            return True
    except OSError:
        return False


def run_flask_portal(app: Flask, host: str, port: int) -> None:
    """Run the local portal with its generated TLS certificate."""
    app.run(host=host, port=port, ssl_context=app.config.get("TICKER_SSL_CONTEXT"))


class WiFiRecoveryService:
    """Detect internet loss and run explicit Wi-Fi recovery."""

    def __init__(
        self,
        commands: PlatformCommands,
        *,
        internet_probe: Callable[[], bool] = probe_internet,
        hotspot_starter: HotspotStarter,
        portal_runner: PortalRunner = run_flask_portal,
        background: Callable[[Callable[[], None]], Any] | None = None,
        hotspot: HotspotDetails | None = None,
        setup_code: str | None = None,
        portal_host: str = "0.0.0.0",
        portal_port: int = 443,
        portal_address: str = "10.42.0.1",
        portal_cert_path: Path | str | None = None,
        portal_key_path: Path | str | None = None,
        setup_failure_threshold: int = 3,
        setup_ttl_seconds: float = 900.0,
        max_setup_attempts: int = 5,
        setup_attempt_window_seconds: float = 60.0,
        state_path: Path | str | None = None,
        force_setup_path: Path | str | None = None,
    ) -> None:
        self._commands = commands
        self._internet_probe = internet_probe
        self._hotspot_starter = hotspot_starter
        self._portal_runner = portal_runner
        self._background = background or _start_background
        self._state_path = Path(state_path) if state_path is not None else None
        self._force_setup_path = Path(force_setup_path) if force_setup_path is not None else None
        self._portal_host = portal_host
        self._portal_port = portal_port
        self._portal_address = portal_address
        self._portal_cert_path = Path(portal_cert_path) if portal_cert_path is not None else None
        self._portal_key_path = Path(portal_key_path) if portal_key_path is not None else None
        self._setup_url = _portal_url(portal_address, portal_port, secure=True)
        if setup_failure_threshold <= 0:
            raise ValueError("setup_failure_threshold must be positive")
        if setup_ttl_seconds <= 0:
            raise ValueError("setup_ttl_seconds must be positive")
        if max_setup_attempts <= 0:
            raise ValueError("max_setup_attempts must be positive")
        if setup_attempt_window_seconds <= 0:
            raise ValueError("setup_attempt_window_seconds must be positive")
        self._setup_failure_threshold = setup_failure_threshold
        self._setup_ttl_seconds = setup_ttl_seconds
        self._max_setup_attempts = max_setup_attempts
        self._setup_attempt_window_seconds = setup_attempt_window_seconds
        self._setup_code = setup_code or self._load_setup_code() or _new_setup_code()
        self._hotspot = hotspot or HotspotDetails(
            "SportsTicker_Setup",
            _hotspot_password(self._setup_code),
        )
        self._consecutive_failures = 0
        self._setup_started_at: float | None = None
        self._setup_attempts: deque[float] = deque()
        self._last_internet_available: bool | None = None
        self._hotspot_active = False
        self._portal: Flask | None = None

    def is_internet_available(self) -> bool:
        """Return the current public internet status."""
        return self._internet_probe()

    def telemetry(self) -> dict[str, object]:
        """Return bounded Wi-Fi facts for heartbeat telemetry without probing the network."""
        return {
            "wifi_available": self._last_internet_available,
            "wifi_setup_active": self._hotspot_active,
        }

    def setup_state(self) -> WiFiSetupState:
        """Return current setup data without starting recovery."""
        return WiFiSetupState(
            internet_available=self.is_internet_available(),
            hotspot_active=self._hotspot_active,
            hotspot=self._hotspot,
            setup_url=self._setup_url,
            setup_code=self._setup_code,
        )

    def scan_networks(self) -> list[WiFiNetwork]:
        """Return visible SSIDs for the setup page."""
        return self._commands.list_wifi_networks()

    def start_setup(self) -> WiFiSetupState:
        """Start the setup hotspot when the internet is unavailable."""
        forced = self._force_setup_requested()
        internet_available = self.is_internet_available() and not forced
        self._last_internet_available = internet_available
        if internet_available:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
        if not internet_available and not self._hotspot_active and (
            forced or self._consecutive_failures >= self._setup_failure_threshold
        ):
            self._hotspot_starter(self._hotspot)
            self._hotspot_active = True
            self._setup_started_at = time.monotonic()
            self._persist_setup_state()
        return WiFiSetupState(
            internet_available,
            self._hotspot_active,
            self._hotspot,
            self._setup_url,
            self._setup_code,
        )

    def _force_setup_requested(self) -> bool:
        """Return true while a short-lived test marker requests Wi-Fi setup."""

        if self._force_setup_path is None:
            return False
        try:
            value = json.loads(self._force_setup_path.read_text(encoding="utf-8"))
            return time.time() < float(value.get("expires_at") or 0.0)
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def portal_app(self) -> Flask:
        """Return the setup portal without running a server."""
        if self._portal is None:
            self._portal = self._build_portal()
        return self._portal

    def start_portal(self) -> bool:
        """Run the setup portal after setup starts explicitly."""
        state = self.start_setup()
        if state.internet_available or not state.hotspot_active:
            return False
        app = self.portal_app()
        app.config["TICKER_SSL_CONTEXT"] = self._portal_tls_context()
        self._portal_runner(app, self._portal_host, self._portal_port)
        return True

    def _portal_tls_context(self) -> tuple[str, str]:
        """Return a short-lived self-signed certificate for the isolated setup hotspot."""

        if self._portal_cert_path is None or self._portal_key_path is None:
            raise RuntimeError("secure Wi-Fi setup needs portal certificate and key paths")
        certificate = self._portal_cert_path
        key = self._portal_key_path
        certificate.parent.mkdir(parents=True, exist_ok=True)
        key.parent.mkdir(parents=True, exist_ok=True)
        if not certificate.exists() or not key.exists():
            command = [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-subj",
                f"/CN={self._portal_address}",
                "-addext",
                f"subjectAltName=IP:{self._portal_address}",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
            except (OSError, subprocess.CalledProcessError) as error:
                raise RuntimeError("openssl is required for secure Wi-Fi setup") from error
        try:
            os.chmod(key, 0o600)
        except OSError:
            pass
        return str(certificate), str(key)

    def connect_and_reboot(self, ssid: str, password: str, setup_code: str) -> None:
        """Connect to Wi-Fi and request a reboot."""
        self._ensure_setup_available()
        if not secrets.compare_digest(setup_code.strip(), self._setup_code):
            raise ValueError("The setup code is invalid.")
        if not ssid.strip():
            raise ValueError("Wi-Fi SSID must not be empty.")
        self._commands.connect_wifi(ssid, password, interface=self._hotspot.interface)
        self._clear_setup_state()
        self._commands.reboot()

    def _load_setup_code(self) -> str | None:
        """Load one unexpired local setup PIN from the Pi data directory."""

        if self._state_path is None:
            return None
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
            code = str(value.get("setup_code") or "")
            created = float(value.get("created_at") or 0.0)
            if code.isdigit() and len(code) == 6 and time.time() - created <= self._setup_ttl_seconds:
                return code
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        return None

    def _persist_setup_state(self) -> None:
        """Persist the local setup PIN without storing the home Wi-Fi password."""

        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps({"setup_code": self._setup_code, "created_at": time.time()}, separators=(",", ":")),
                encoding="utf-8",
            )
        except OSError:
            return

    def _clear_setup_state(self) -> None:
        """Remove setup state and any temporary force marker after Wi-Fi succeeds."""

        for path in (self._state_path, self._force_setup_path):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue

    def _build_portal(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def home() -> str:
            networks = [network.ssid for network in self.scan_networks()]
            return render_template_string(
                PORTAL_TEMPLATE,
                networks=networks,
                hotspot=self._hotspot,
                setup_code=self._setup_code,
                setup_minutes=max(1, round(self._setup_ttl_seconds / 60)),
            )

        @app.post("/connect")
        def connect() -> tuple[str, int] | str:
            selected = request.form.get("ssid_select", "")
            ssid = request.form.get("ssid_manual", "") if selected == "__manual__" else selected
            password = request.form.get("password", "")
            setup_code = request.form.get("setup_code", "")
            if not ssid.strip() or not password or not setup_code.strip():
                return "Network name, password, and setup code are required.", 400
            try:
                self._ensure_setup_available()
                self._check_setup_attempt()
            except SetupUnavailableError as error:
                return str(error), 410
            except SetupRateLimitError as error:
                return str(error), 429
            if not secrets.compare_digest(setup_code.strip(), self._setup_code):
                return "The setup code is invalid.", 403
            self._background(lambda: self.connect_and_reboot(ssid, password, setup_code))
            return "<main><h1>Settings saved</h1><p>The ticker is connecting and will reboot shortly.</p></main>"

        return app

    def _ensure_setup_available(self) -> None:
        if not self._hotspot_active or self._setup_started_at is None:
            raise SetupUnavailableError("The Wi-Fi setup session is not active.")
        if time.monotonic() - self._setup_started_at > self._setup_ttl_seconds:
            raise SetupUnavailableError("The Wi-Fi setup session expired. Restart the ticker to try again.")

    def _check_setup_attempt(self) -> None:
        now = time.monotonic()
        while self._setup_attempts and now - self._setup_attempts[0] > self._setup_attempt_window_seconds:
            self._setup_attempts.popleft()
        if len(self._setup_attempts) >= self._max_setup_attempts:
            raise SetupRateLimitError("Too many setup attempts. Wait one minute and try again.")
        self._setup_attempts.append(now)


class LocalProvisioningService(WiFiRecoveryService):
    """Own the local first-boot setup boundary before backend connectivity exists."""


def _start_background(action: Callable[[], None]) -> None:
    Thread(target=action, daemon=True).start()


def _new_setup_code() -> str:
    """Return one cryptographically random six-digit setup code for this setup session, preserving leading zeroes in every generated value."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hotspot_password(setup_code: str) -> str:
    """Adapt the six-digit code to NetworkManager's eight-character WPA minimum while keeping the visible code easy to recognize during setup."""
    return f"T{setup_code}!"


def _portal_url(address: str, port: int, *, secure: bool = True) -> str:
    """Build the user-facing setup URL for the hotspot gateway."""
    suffix = "" if port == 80 else f":{port}"
    if secure and port == 443:
        suffix = ""
    return f"{'https' if secure else 'http'}://{address}{suffix}"
