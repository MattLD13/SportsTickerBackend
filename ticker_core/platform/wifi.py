"""Wi-Fi recovery and setup portal services."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import socket
from threading import Thread
from typing import Any, Protocol

from flask import Flask, render_template_string, request

from .commands import PlatformCommands, WiFiNetwork


PORTAL_TEMPLATE = """
<!doctype html>
<title>Setup Wi-Fi</title>
<h2>Setup Wi-Fi</h2>
<form action="/connect" method="post">
  <label>Network <select name="ssid_select">
    {% for network in networks %}<option value="{{ network }}">{{ network }}</option>{% endfor %}
    <option value="__manual__">Enter manually</option>
  </select></label>
  <label>Network name <input name="ssid_manual"></label>
  <label>Password <input name="password" type="password" required></label>
  <button type="submit">Connect</button>
</form>
"""


@dataclass(frozen=True, slots=True)
class HotspotDetails:
    """Describe the hotspot used for Wi-Fi setup."""

    ssid: str
    password: str
    interface: str = "wlan0"


@dataclass(frozen=True, slots=True)
class WiFiSetupState:
    """Report the current Wi-Fi recovery state."""

    internet_available: bool
    hotspot_active: bool
    hotspot: HotspotDetails


class PortalRunner(Protocol):
    """Run the Flask portal after explicit setup starts."""

    def __call__(self, app: Flask, host: str, port: int) -> None:
        """Run the portal."""


class HotspotStarter(Protocol):
    """Start the Wi-Fi hotspot for setup."""

    def __call__(self, details: HotspotDetails) -> None:
        """Start the hotspot."""


def probe_internet() -> bool:
    """Return true when the Pi can reach a public DNS endpoint."""
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=3):
            return True
    except OSError:
        return False


def run_flask_portal(app: Flask, host: str, port: int) -> None:
    """Run the portal with Flask's local server."""
    app.run(host=host, port=port)


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
        hotspot: HotspotDetails = HotspotDetails("SportsTicker_Setup", "setup1234"),
        portal_host: str = "0.0.0.0",
        portal_port: int = 80,
    ) -> None:
        self._commands = commands
        self._internet_probe = internet_probe
        self._hotspot_starter = hotspot_starter
        self._portal_runner = portal_runner
        self._background = background or _start_background
        self._hotspot = hotspot
        self._portal_host = portal_host
        self._portal_port = portal_port
        self._hotspot_active = False
        self._portal: Flask | None = None

    def is_internet_available(self) -> bool:
        """Return the current public internet status."""
        return self._internet_probe()

    def setup_state(self) -> WiFiSetupState:
        """Return current setup data without starting recovery."""
        return WiFiSetupState(
            internet_available=self.is_internet_available(),
            hotspot_active=self._hotspot_active,
            hotspot=self._hotspot,
        )

    def scan_networks(self) -> list[WiFiNetwork]:
        """Return visible SSIDs for the setup page."""
        return self._commands.list_wifi_networks()

    def start_setup(self) -> WiFiSetupState:
        """Start the setup hotspot when the internet is unavailable."""
        internet_available = self.is_internet_available()
        if not internet_available and not self._hotspot_active:
            self._hotspot_starter(self._hotspot)
            self._hotspot_active = True
        return WiFiSetupState(internet_available, self._hotspot_active, self._hotspot)

    def portal_app(self) -> Flask:
        """Return the setup portal without running a server."""
        if self._portal is None:
            self._portal = self._build_portal()
        return self._portal

    def start_portal(self) -> bool:
        """Run the setup portal after setup starts explicitly."""
        state = self.start_setup()
        if state.internet_available:
            return False
        self._portal_runner(self.portal_app(), self._portal_host, self._portal_port)
        return True

    def connect_and_reboot(self, ssid: str, password: str) -> None:
        """Connect to Wi-Fi and request a reboot."""
        if not ssid.strip():
            raise ValueError("Wi-Fi SSID must not be empty.")
        self._commands.connect_wifi(ssid, password, interface=self._hotspot.interface)
        self._commands.reboot()

    def _build_portal(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def home() -> str:
            networks = [network.ssid for network in self.scan_networks()]
            return render_template_string(PORTAL_TEMPLATE, networks=networks)

        @app.post("/connect")
        def connect() -> tuple[str, int] | str:
            selected = request.form.get("ssid_select", "")
            ssid = request.form.get("ssid_manual", "") if selected == "__manual__" else selected
            password = request.form.get("password", "")
            if not ssid.strip() or not password:
                return "Network name and password are required.", 400
            self._background(lambda: self.connect_and_reboot(ssid, password))
            return "<h2>Settings saved. Rebooting...</h2>"

        return app


def _start_background(action: Callable[[], None]) -> None:
    Thread(target=action, daemon=True).start()
