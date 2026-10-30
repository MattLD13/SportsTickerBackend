from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ticker.six.platform import SubprocessPlatformCommands, WiFiNetwork


def test_platform_commands_delegate_to_injected_subprocesses() -> None:
    runs: list[tuple[list[str], dict]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        runs.append((command, kwargs))
        return SimpleNamespace(stdout="Zulu\nAlpha\nZulu\n")

    commands = SubprocessPlatformCommands(run=run)

    assert commands.list_wifi_networks() == [WiFiNetwork("Alpha"), WiFiNetwork("Zulu")]
    commands.connect_wifi("Ticker", "secret")
    commands.start_hotspot("Setup", "setup1234", interface="wlan1")
    commands.stop_hotspot(interface="wlan1")
    commands.run_update(["python", "-m", "ticker.six.updater"], working_directory=Path("/opt/release"))
    commands.reboot()

    assert runs[1][0] == ["nmcli", "dev", "wifi", "connect", "Ticker", "password", "secret", "ifname", "wlan0"]
    assert runs[2][0] == [
        "nmcli",
        "device",
        "wifi",
        "hotspot",
        "ifname",
        "wlan1",
        "ssid",
        "Setup",
        "password",
        "setup1234",
    ]
    assert runs[-2][0][:3] == ["systemd-run", "--collect", "--unit=sports-ticker-updater"]
    assert "--working-directory=/opt/release" in runs[-2][0]
    assert runs[-2][0][-3:] == ["python", "-m", "ticker.six.updater"]
    assert runs[-1][0] == ["systemctl", "--no-block", "reboot"]


def test_update_command_requires_an_executable() -> None:
    commands = SubprocessPlatformCommands()

    with pytest.raises(ValueError, match="Update command"):
        commands.run_update([], working_directory=Path("/opt/release"))
