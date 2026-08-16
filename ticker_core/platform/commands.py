"""Operating-system actions exposed without display runtime policy."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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

    def run_update(self, command: Sequence[str]) -> None:
        """Start the supplied update command."""

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
        spawn: Callable[..., Any] = subprocess.Popen,
        reboot_command: Sequence[str] = ("systemctl", "reboot"),
    ) -> None:
        self._run = run
        self._spawn = spawn
        self._reboot_command = tuple(reboot_command)

    def reboot(self) -> None:
        # Run synchronously so permission or command failures reach the caller
        # instead of leaving the setup screen active with no diagnostic.
        self._run(list(self._reboot_command), check=True)

    def run_update(self, command: Sequence[str]) -> None:
        if not command:
            raise ValueError("Update command must not be empty.")
        self._spawn(list(command))

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
