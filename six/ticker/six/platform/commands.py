"""Operating-system actions exposed without display runtime policy."""

from __future__ import annotations

import subprocess
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class WiFiNetwork:
    """A visible wireless network."""

    ssid: str


@runtime_checkable
class PlatformCommands(Protocol):
    """System actions requested by controller policy."""

    def reboot(self) -> None:
        """Request a host reboot."""

    def run_update(self, command: Sequence[str], *, working_directory: Path) -> None:
        """Start the supplied update command in `working_directory`."""

    def list_wifi_networks(self) -> list[WiFiNetwork]:
        """Return visible Wi-Fi networks."""

    def connect_wifi(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        """Connect an interface to Wi-Fi."""

    def start_hotspot(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        """Start the setup hotspot on one wireless interface."""

    def stop_hotspot(self, *, interface: str = "wlan0") -> None:
        """Disconnect one wireless interface from its setup hotspot."""


class SubprocessPlatformCommands:
    """Use system commands for Pi platform actions."""

    def __init__(
        self,
        *,
        run: Callable[..., Any] = subprocess.run,
        reboot_command: Sequence[str] = ("systemctl", "--no-block", "reboot"),
    ) -> None:
        self._run = run
        self._reboot_command = tuple(reboot_command)

    def reboot(self) -> None:
        # Run synchronously so permission or command failures reach the caller
        # instead of leaving the setup screen active with no diagnostic.
        self._run(list(self._reboot_command), check=True)

    def run_update(self, command: Sequence[str], *, working_directory: Path) -> None:
        if not command:
            raise ValueError("Update command must not be empty.")
        environment = ["--setenv=" + key + "=" + value for key, value in os.environ.items()
                       if key in {"TICKER_DATA_DIR", "TICKER_BACKEND_URL", "TICKER_DEVICE_TOKEN_FILE",
                                  "TICKER_RELEASE_ROOT", "TICKER_RELEASE_LINK", "TICKER_FRAME_HEALTH_PATH", "PYTHONPATH"}]
        self._run(["systemd-run", "--collect", "--unit=sports-ticker-updater", f"--working-directory={working_directory}",
                   *environment, *command], check=True)

    def list_wifi_networks(self) -> list[WiFiNetwork]:
        result = self._run(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
        names = {name.strip() for name in result.stdout.splitlines() if name.strip()}
        return [WiFiNetwork(ssid=name) for name in sorted(names)]

    def connect_wifi(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        if not ssid:
            raise ValueError("Wi-Fi SSID must not be empty.")
        self._run(
            ["nmcli", "dev", "wifi", "connect", ssid, "password", password, "ifname", interface],
            check=True,
            timeout=30,
        )

    def start_hotspot(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        """Start a NetworkManager hotspot for local recovery."""

        if not ssid or not password:
            raise ValueError("Wi-Fi hotspot credentials must not be empty.")
        self._run(
            [
                "nmcli",
                "device",
                "wifi",
                "hotspot",
                "ifname",
                interface,
                "ssid",
                ssid,
                "password",
                password,
            ],
            check=True,
        )

    def stop_hotspot(self, *, interface: str = "wlan0") -> None:
        """Disconnect the hotspot before NetworkManager joins home Wi-Fi."""

        self._run(["nmcli", "device", "disconnect", interface], check=False)
