from __future__ import annotations

from datetime import datetime, timezone
import time
import json

from ticker_core.context import RenderContext
from ticker_core.features.utility import UtilityRenderer
from ticker_core.platform import HotspotDetails, WiFiNetwork, WiFiRecoveryService, WiFiSetupState
from ticker_core.rendering import load_default_font_set




class Commands:
    def __init__(self) -> None:
        self.connected: list[tuple[str, str, str]] = []
        self.stopped: list[str] = []
        self.reboots = 0

    def list_wifi_networks(self) -> list[WiFiNetwork]:
        return [WiFiNetwork("Home")]

    def connect_wifi(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        self.connected.append((ssid, password, interface))

    def stop_hotspot(self, *, interface: str = "wlan0") -> None:
        self.stopped.append(interface)

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
        setup_failure_threshold=3,
    )

    service.start_setup()
    service.start_setup()
    state = service.start_setup()
    response = service.portal_app().test_client().post(
        "/connect",
        data={"ssid_select": "Home", "password": "secret", "setup_code": state.setup_code},
    )

    assert state.hotspot_active is True
    assert state.setup_url == "https://10.42.0.1"
    assert len(state.setup_code) == 6
    assert hotspots[0].password == f"T{state.setup_code}!"
    assert hotspots == [HotspotDetails("SportsTicker_Setup", f"T{state.setup_code}!")]
    assert response.status_code == 200
    assert len(background) == 1
    background[0]()
    assert commands.stopped == ["wlan0"]
    assert commands.connected == [("Home", "secret", "wlan0")]
    assert commands.reboots == 1


def test_wifi_setup_renderer_returns_the_real_panel_size() -> None:
    """Render one setup state without network work in the renderer."""

    state = WiFiSetupState(
        internet_available=False,
        hotspot_active=True,
        hotspot=HotspotDetails("SportsTicker_Setup", "setup1234"),
        setup_code="123456",
    )
    frame = UtilityRenderer(load_default_font_set()).wifi_setup(
        RenderContext(datetime(2026, 8, 15, tzinfo=timezone.utc)),
        state,
    )
    assert frame.size == (384, 32)


def test_wifi_setup_page_is_mobile_friendly_and_rejects_wrong_code() -> None:
    """Show setup credentials and require the local six-digit code."""

    commands = Commands()
    background: list[object] = []
    service = WiFiRecoveryService(
        commands,
        internet_probe=lambda: False,
        hotspot_starter=lambda details: None,
        background=lambda action: background.append(action),
        setup_failure_threshold=3,
    )
    service.start_setup()
    service.start_setup()
    state = service.start_setup()
    client = service.portal_app().test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert b"name=\"viewport\"" in page.data
    assert state.setup_code.encode() in page.data
    assert state.hotspot.password.encode() in page.data

    response = client.post(
        "/connect",
        data={"ssid_select": "Home", "password": "secret", "setup_code": "000000"},
    )
    assert response.status_code == 403
    assert background == []


def test_wifi_setup_expires_and_limits_code_attempts() -> None:
    """Expire one setup session and stop repeated guesses before they reach Wi-Fi commands."""

    service = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: False,
        hotspot_starter=lambda details: None,
        setup_ttl_seconds=0.001,
        max_setup_attempts=1,
        setup_failure_threshold=3,
    )
    service.start_setup()
    service.start_setup()
    state = service.start_setup()
    client = service.portal_app().test_client()
    time.sleep(0.01)
    expired = client.post(
        "/connect",
        data={"ssid_select": "Home", "password": "secret", "setup_code": state.setup_code},
    )
    assert expired.status_code == 410

    service = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: False,
        hotspot_starter=lambda details: None,
        max_setup_attempts=1,
        setup_failure_threshold=3,
    )
    service.start_setup()
    service.start_setup()
    state = service.start_setup()
    client = service.portal_app().test_client()
    invalid = {"ssid_select": "Home", "password": "secret", "setup_code": "000000"}
    assert client.post("/connect", data=invalid).status_code == 403
    assert client.post("/connect", data=invalid).status_code == 429


def test_local_setup_pin_persists_without_storing_wifi_password(tmp_path) -> None:
    """Keep one local setup PIN across service construction without persisting credentials."""

    state_path = tmp_path / "wifi_setup.json"
    first = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: False,
        hotspot_starter=lambda details: None,
        setup_failure_threshold=1,
        state_path=state_path,
    )
    first.start_setup()
    second = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: False,
        hotspot_starter=lambda details: None,
        setup_failure_threshold=1,
        state_path=state_path,
    )
    assert second.start_setup().setup_code == first.start_setup().setup_code
    assert "password" not in state_path.read_text(encoding="utf-8").lower()


def test_force_setup_marker_starts_wifi_mode_without_network_change(tmp_path) -> None:
    """Force setup mode from a short-lived marker while internet remains available."""

    marker = tmp_path / "force_wifi_setup.json"
    marker.write_text(json.dumps({"expires_at": time.time() + 60}), encoding="utf-8")
    hotspots: list[HotspotDetails] = []
    service = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: True,
        hotspot_starter=hotspots.append,
        force_setup_path=marker,
    )

    state = service.start_setup()

    assert state.internet_available is False
    assert state.hotspot_active is True
    assert len(hotspots) == 1
    assert not marker.exists()
    service.connect_and_reboot("Home", "secret", state.setup_code)
    assert not marker.exists()

    rebooted = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: True,
        hotspot_starter=lambda details: None,
        force_setup_path=marker,
    )
    assert rebooted.start_setup().internet_available is True


def test_ble_setup_owns_credentials_without_starting_hotspot() -> None:
    commands = Commands()
    captured: list[tuple[str, object]] = []
    service = WiFiRecoveryService(
        commands,
        internet_probe=lambda: False,
        hotspot_starter=lambda details: captured.append(("hotspot", details)),
        setup_failure_threshold=1,
        ble_starter=lambda code, callback: captured.append((code, callback)),
        ble_stopper=lambda: captured.append(("stop", None)),
    )

    state = service.start_setup()

    assert state.hotspot_active is False
    assert state.ble_active is True
    assert captured[0][0] == state.setup_code
    callback = captured[0][1]
    assert callable(callback)
    callback("Home", "secret")
    assert commands.connected == [("Home", "secret", "wlan0")]
    assert commands.stopped == []
    assert commands.reboots == 1


def test_local_setup_portal_requires_tls_context(tmp_path) -> None:
    """Pass the generated certificate pair to the portal runner."""

    captured: list[tuple[object, str, int]] = []
    certificate = tmp_path / "portal.crt"
    key = tmp_path / "portal.key"
    certificate.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    service = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: False,
        hotspot_starter=lambda details: None,
        setup_failure_threshold=1,
        portal_runner=lambda app, host, port: captured.append((app, host, port)),
        portal_cert_path=certificate,
        portal_key_path=key,
    )

    service.start_portal()

    app, host, port = captured[0]
    assert host == "0.0.0.0"
    assert port == 443
    assert app.config["TICKER_SSL_CONTEXT"] == (str(certificate), str(key))


def test_wifi_setup_default_threshold_is_twelve() -> None:
    """Trigger setup only after 12 consecutive failed probes by default."""

    hotspots: list[HotspotDetails] = []
    service = WiFiRecoveryService(
        Commands(),
        internet_probe=lambda: False,
        hotspot_starter=hotspots.append,
    )

    for _ in range(11):
        state = service.start_setup()
        assert state.hotspot_active is False
        assert state.internet_available is False

    state = service.start_setup()
    assert state.hotspot_active is True
    assert len(hotspots) == 1


def test_wifi_setup_auto_recovers_when_internet_returns() -> None:
    """Tear down hotspot or BLE setup when internet connectivity returns."""

    commands = Commands()
    hotspots: list[HotspotDetails] = []
    internet_status = [False]
    captured_stops: list[str] = []
    service = WiFiRecoveryService(
        commands,
        internet_probe=lambda: internet_status[0],
        hotspot_starter=hotspots.append,
        setup_failure_threshold=1,
        ble_starter=lambda code, cb: None,
        ble_stopper=lambda: captured_stops.append("ble_stopped"),
    )

    state = service.start_setup()
    assert state.ble_active is True
    assert state.internet_available is False

    internet_status[0] = True
    recovered = service.start_setup()

    assert recovered.ble_active is False
    assert recovered.internet_available is True
    assert captured_stops == ["ble_stopped"]

    hotspot_service = WiFiRecoveryService(
        commands,
        internet_probe=lambda: internet_status[0],
        hotspot_starter=hotspots.append,
        setup_failure_threshold=1,
    )
    internet_status[0] = False
    active = hotspot_service.start_setup()
    assert active.hotspot_active is True

    internet_status[0] = True
    recovered_hotspot = hotspot_service.start_setup()
    assert recovered_hotspot.hotspot_active is False
    assert recovered_hotspot.internet_available is True
    assert commands.stopped == ["wlan0"]


def test_probe_internet_checks_targets() -> None:
    """Return true when a target connection succeeds and false when all fail."""
    from ticker_core.platform.wifi import probe_internet

    assert probe_internet(targets=(("127.0.0.1", 1),), timeout=0.01) is False
