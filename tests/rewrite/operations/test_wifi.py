from __future__ import annotations

from datetime import datetime, timezone

from ticker_core.context import RenderContext
from ticker_core.features.utility import UtilityRenderer
from ticker_core.platform import HotspotDetails, WiFiNetwork, WiFiRecoveryService, WiFiSetupState
from ticker_core.rendering import load_default_font_set


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


def test_wifi_setup_renderer_returns_the_real_panel_size() -> None:
    """Render one setup state without network work in the renderer."""

    state = WiFiSetupState(
        internet_available=False,
        hotspot_active=True,
        hotspot=HotspotDetails("SportsTicker_Setup", "setup1234"),
    )
    frame = UtilityRenderer(load_default_font_set()).wifi_setup(
        RenderContext(datetime(2026, 8, 15, tzinfo=timezone.utc)),
        state,
    )
    assert frame.size == (384, 32)
