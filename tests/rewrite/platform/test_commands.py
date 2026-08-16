from __future__ import annotations

from types import SimpleNamespace

import pytest

from ticker_core.platform import SubprocessPlatformCommands, WiFiNetwork


def test_platform_commands_delegate_to_injected_subprocesses() -> None:
    runs: list[tuple[list[str], dict]] = []
    spawned: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        runs.append((command, kwargs))
        return SimpleNamespace(stdout="Zulu\nAlpha\nZulu\n")

    commands = SubprocessPlatformCommands(run=run, spawn=lambda command: spawned.append(command))

    assert commands.list_wifi_networks() == [WiFiNetwork("Alpha"), WiFiNetwork("Zulu")]
    commands.connect_wifi("Ticker", "secret")
    commands.start_hotspot("Setup", "setup1234", interface="wlan1")
    commands.run_update(["python", "updater.py"])
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
    assert spawned == [["python", "updater.py"], ["reboot"]]


def test_update_command_requires_an_executable() -> None:
    commands = SubprocessPlatformCommands(spawn=lambda command: None)

    with pytest.raises(ValueError, match="Update command"):
        commands.run_update([])
