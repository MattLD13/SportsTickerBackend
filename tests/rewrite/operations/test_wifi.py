from __future__ import annotations

from ticker_core.platform import HotspotDetails, WiFiNetwork, WiFiRecoveryService


class Commands:
    def __init__(self) -> None:
        self.connected: list[tuple[str, str, str]] = []
        self.reboots = 0

    def list_wifi_networks(self) -> list[WiFiNetwork]:
        return [WiFiNetwork("Home")]

    def connect_wifi(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        self.connected.append((ssid, password, interface))

    def reboot(self) -> None:
        self.reboots += 1

    def run_update(self, command: object) -> None:
        raise AssertionError("Wi-Fi setup does not update.")


def test_wifi_setup_starts_hotspot_and_connects_from_portal() -> None:
    commands = Commands()
    hotspots: list[HotspotDetails] = []
    background: list[object] = []
    service = WiFiRecoveryService(
        commands,
        internet_probe=lambda: False,
        hotspot_starter=hotspots.append,
        background=lambda action: background.append(action),
    )

    state = service.start_setup()
    response = service.portal_app().test_client().post(
        "/connect", data={"ssid_select": "Home", "password": "secret"}
    )

    assert state.hotspot_active is True
    assert hotspots == [HotspotDetails("SportsTicker_Setup", "setup1234")]
    assert response.status_code == 200
    assert len(background) == 1
    background[0]()
    assert commands.connected == [("Home", "secret", "wlan0")]
    assert commands.reboots == 1
