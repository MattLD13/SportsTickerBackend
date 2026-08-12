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
from ticker_core.platform import AssetCoordinator, DeviceIdentityStore, HealthCollector, OtaUpdaterService, SubprocessPlatformCommands
from ticker_core.protocol import BackendClient
from ticker_core.runtime import FramePacer, TickerRuntime


def create_application() -> TickerApplication:
    """Create one fully composed ticker application from environment values."""
    repository = Path(__file__).resolve().parent.parent
    data_directory = Path(os.environ.get("TICKER_DATA_DIR", "~/ticker")).expanduser()
    device_id = load_device_id(data_directory)
    health = HealthCollector(repository)
    client = BackendClient(
        os.environ.get("TICKER_BACKEND_URL", "https://ticker.mattdicks.org"),
        timeout_seconds=float(os.environ.get("TICKER_BACKEND_TIMEOUT", "5")),
        verify_tls=_enabled("TICKER_VERIFY_TLS"),
    )
    assets = AssetCoordinator(data_directory / "assets")
    frames, strips = create_default_frame_builder(assets)
    runtime = TickerRuntime(monotonic=monotonic, wall_clock=datetime.now)
    commands = SubprocessPlatformCommands()
    return TickerApplication(
        client=client,
        poller=BackendPoller(client, device_id, telemetry_headers=health.headers),
        cache=ShortTermContentCache(data_directory / "content" / "last-good.json"),
        assets=assets,
        runtime=runtime,
        strips=strips,
        frames=frames,
        pacer=FramePacer(monotonic),
        sink=_create_sink(),
        commands=commands,
        device_id=device_id,
        repository=repository,
        wall_clock=datetime.now,
        update_service=OtaUpdaterService(commands, updater_path=repository / "updater.py"),
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


def _enabled(name: str) -> bool:
    """Read one common true environment value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


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
