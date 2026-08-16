"""Compose the executable ticker application from environment settings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import monotonic
import os

from ticker_core.app.application import TickerApplication
from ticker_core.app.poller import BackendPoller
from ticker_core.assets import ShortTermContentCache
from ticker_core.bootstrap import create_default_frame_builder
from ticker_core.drivers import MemoryFrameSink, RgbMatrixFrameSink, TkFrameSink
from ticker_core.platform import (
    AssetCoordinator,
    DeviceIdentityStore,
    HealthCollector,
    LocalProvisioningService,
    OtaUpdaterService,
    SubprocessPlatformCommands,
    TickerPiLogger,
    WiFiRecoveryService,
)
from ticker_core.protocol import BackendClient
from ticker_core.rendering import FrameGeometry
from ticker_core.runtime import FramePacer, TickerRuntime


def create_application() -> TickerApplication:
    """Create one fully composed ticker application from environment values."""
    repository = Path(__file__).resolve().parent.parent
    data_directory = Path(os.environ.get("TICKER_DATA_DIR", "~/ticker")).expanduser()
    device_id = load_device_id(data_directory)
    health = HealthCollector(repository)
    logger = TickerPiLogger(data_directory / "logs", system_snapshot=health.snapshot)
    client = BackendClient(
        os.environ.get("TICKER_BACKEND_URL", "https://ticker.mattdicks.org"),
        timeout_seconds=float(os.environ.get("TICKER_BACKEND_TIMEOUT", "5")),
        verify_tls=_enabled("TICKER_VERIFY_TLS", default=True),
    )
    assets = AssetCoordinator(data_directory / "assets")
    frames, viewport = create_default_frame_builder(
        assets,
        card_cpu=_cpu_setting("TICKER_CARD_CPU"),
        geometry=_frame_geometry(),
    )
    runtime = TickerRuntime(monotonic=monotonic, wall_clock=datetime.now)
    commands = SubprocessPlatformCommands()
    wifi_recovery = LocalProvisioningService(
        commands,
        hotspot_starter=lambda details: commands.start_hotspot(
            details.ssid,
            details.password,
            interface=details.interface,
        ),
        state_path=data_directory / "wifi_setup.json",
        portal_cert_path=data_directory / "wifi_setup.crt",
        portal_key_path=data_directory / "wifi_setup.key",
    )
    health.set_wifi_status_provider(wifi_recovery.telemetry)
    device_profile = _device_profile()
    return TickerApplication(
        client=client,
        poller=BackendPoller(client, device_id, telemetry=health.snapshot, profile=device_profile),
        cache=ShortTermContentCache(data_directory / "content" / "last-good.json"),
        assets=assets,
        runtime=runtime,
        viewport=viewport,
        frames=frames,
        pacer=FramePacer(monotonic),
        sink=_create_sink(),
        commands=commands,
        device_id=device_id,
        repository=repository,
        wall_clock=datetime.now,
        update_service=OtaUpdaterService(commands, updater_path=repository / "updater.py"),
        wifi_recovery=wifi_recovery,
        poll_in_process=_enabled("TICKER_POLL_PROCESS"),
        render_cpu=_cpu_setting("TICKER_RENDER_CPU"),
        poll_cpu=_cpu_setting("TICKER_POLL_CPU"),
        logger=logger,
    )


def _device_profile() -> dict[str, object]:
    """Return the explicit Pi hardware profile sent during registration."""

    family = os.environ.get("TICKER_PRODUCT_FAMILY", "normal").strip().lower() or "normal"
    profile: dict[str, object] = {"product_family": family, "hardware": os.environ.get("TICKER_HARDWARE", "pi-zero-2w")}
    if family == "custom":
        profile["display"] = {
            "width": int(os.environ.get("TICKER_DISPLAY_WIDTH", "384")),
            "height": int(os.environ.get("TICKER_DISPLAY_HEIGHT", "32")),
            "panel_count": int(os.environ.get("TICKER_PANEL_COUNT", "6")),
        }
    return profile


def _frame_geometry() -> FrameGeometry:
    """Return the configured logical frame geometry for a Pi deployment."""

    family = os.environ.get("TICKER_PRODUCT_FAMILY", "normal").strip().lower() or "normal"
    configured = os.environ.get("TICKER_DISPLAY_FIT_MODE", "").strip().lower()
    fit_mode = configured or ("crop" if family == "mini" else "letterbox" if family == "custom" else "scale")
    return FrameGeometry(
        width=int(os.environ.get("TICKER_DISPLAY_WIDTH", "384")),
        height=int(os.environ.get("TICKER_DISPLAY_HEIGHT", "32")),
        fit_mode=fit_mode,
    )


def _create_sink():
    """Create the requested hardware, emulator, or memory frame sink."""
    selected = os.environ.get("TICKER_SINK", "hardware").strip().lower()
    if selected in {"memory", "debug"}:
        return MemoryFrameSink()
    if selected in {"emulator", "desktop"}:
        return TkFrameSink(scale=int(os.environ.get("TICKER_EMULATOR_SCALE", "3")))
    if selected in {"hardware", "matrix", "rgbmatrix"}:
        return RgbMatrixFrameSink.create()
    raise ValueError("TICKER_SINK must be hardware, emulator, or memory.")


def _enabled(name: str, *, default: bool = False) -> bool:
    """Read one common true environment value."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes"}


def _cpu_setting(name: str) -> int | None:
    """Read one optional non-negative Linux CPU number."""

    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} cannot be negative.")
    return value


def load_device_id(data_directory: Path, *, windows: bool | None = None) -> str:
    """Load an explicit identifier or select a platform-safe identity store."""
    explicit = os.environ.get("TICKER_DEVICE_ID", "").strip()
    if explicit:
        return explicit
    fallback = data_directory / "ticker_id.txt"
    selected_path = os.environ.get("TICKER_DEVICE_ID_PATH", "").strip()
    if selected_path:
        return DeviceIdentityStore(selected_path, fallback).load()
    is_windows = os.name == "nt" if windows is None else windows
    if is_windows:
        return DeviceIdentityStore(fallback, fallback).load()
    return DeviceIdentityStore.default().load()
