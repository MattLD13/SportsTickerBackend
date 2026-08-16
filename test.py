"""Run safe hardware, Wi-Fi, and backend diagnostics on a ticker Pi."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import os
import platform
import sys
from threading import Thread
import time
from typing import Callable

from PIL import Image

from ticker_core.composition import load_device_id
from ticker_core.drivers import MemoryFrameSink, RgbMatrixFrameSink
from ticker_core.platform import SubprocessPlatformCommands, WiFiRecoveryService
from ticker_core.platform.wifi import probe_internet
from ticker_core.protocol import BackendClient


COLORS = (
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("white", (255, 255, 255)),
    ("black", (0, 0, 0)),
)


def main() -> int:
    """Run requested diagnostics and return a shell-friendly status code."""
    args = parse_args()
    if args.force_wifi_setup:
        return run_forced_wifi_setup(args)
    failures: list[str] = []
    results: list[dict[str, object]] = []
    print_report_header(args)

    sink = create_sink(args.sink)
    if not run_check("display color cycle", lambda: flash_colors(sink, args.color_seconds), results):
        failures.append("display color cycle")

    if not args.skip_server:
        if not run_check("backend registration and data fetch", check_backend, results):
            failures.append("backend registration and data fetch")

    if not run_check("internet probe", check_internet, results):
        failures.append("internet probe")
    if not args.skip_platform:
        if not run_check("platform command discovery", check_platform_commands, results):
            failures.append("platform command discovery")

    if args.wifi_setup:
        if not run_check("Wi-Fi setup hotspot", lambda: run_wifi_setup(args), results):
            failures.append("Wi-Fi setup hotspot")

    if args.reboot:
        if not run_check("reboot request", lambda: SubprocessPlatformCommands().reboot(), results):
            failures.append("reboot request")

    sink.clear()
    write_report(args, results, failures)
    if failures:
        print(f"\nFAIL ({len(failures)}): " + "; ".join(failures))
        return 1
    print("\nPASS: ticker diagnostics completed")
    return 0


def parse_args() -> argparse.Namespace:
    """Parse diagnostics options while keeping network-changing actions explicit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sink", choices=("auto", "hardware", "memory"), default="auto")
    parser.add_argument("--color-seconds", type=float, default=0.35)
    parser.add_argument("--skip-server", action="store_true")
    parser.add_argument("--skip-platform", action="store_true")
    parser.add_argument("--wifi-setup", action="store_true", help="Start the setup hotspot")
    parser.add_argument(
        "--force-wifi-setup",
        action="store_true",
        help="Ask the running ticker service to enter Wi-Fi setup without changing saved credentials",
    )
    parser.add_argument("--portal", action="store_true", help="Keep the setup portal running")
    parser.add_argument("--portal-port", type=int, default=80)
    parser.add_argument("--reboot", action="store_true", help="Request a reboot after checks")
    parser.add_argument("--report", type=Path, help="Write a JSON manufacturing report to this path")
    return parser.parse_args()


def run_forced_wifi_setup(args: argparse.Namespace) -> int:
    """Request the running ticker service to enter its real Wi-Fi setup mode."""

    data_directory = Path(os.environ.get("TICKER_DATA_DIR", "~/ticker")).expanduser()
    marker = data_directory / "force_wifi_setup.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"expires_at": time.time() + 900.0}, separators=(",", ":")),
        encoding="utf-8",
    )
    print("Forced Wi-Fi setup requested for the running ticker service.")
    print("The ticker will start SportsTicker_Setup on its next Wi-Fi check.")
    print("Press Ctrl+C after completing Wi-Fi setup to remove the test marker.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nWi-Fi setup test stopped.")
        return 0
    finally:
        marker.unlink(missing_ok=True)


def print_report_header(args: argparse.Namespace) -> None:
    """Print enough host context to identify one physical diagnostic run later."""
    print(f"Ticker diagnostics {datetime.now().isoformat(timespec='seconds')}")
    print(f"Host: {platform.platform()} | Python: {sys.version.split()[0]}")
    print(f"Sink: {args.sink} | Backend: {os.environ.get('TICKER_BACKEND_URL', 'https://ticker.mattdicks.org')}")


def create_sink(selection: str):
    """Create the requested display sink and fail with a useful hardware message."""
    if selection == "memory" or (selection == "auto" and os.name == "nt"):
        return MemoryFrameSink()
    try:
        return RgbMatrixFrameSink.create()
    except Exception as error:
        if selection == "auto":
            print(f"WARN: hardware display unavailable ({error}), using memory sink")
            return MemoryFrameSink()
        raise


def flash_colors(sink, seconds: float) -> None:
    """Flash red, green, blue, white, and black across the complete 384x32 display."""
    if seconds <= 0:
        raise ValueError("--color-seconds must be positive")
    for name, color in COLORS:
        print(f"  color: {name}")
        sink.present(Image.new("RGB", (sink.width, sink.height), color))
        time.sleep(seconds)


def check_backend() -> None:
    """Register this device and fetch one validated V2 payload from the configured backend."""
    data_directory = Path(os.environ.get("TICKER_DATA_DIR", "~/ticker")).expanduser()
    device_id = load_device_id(data_directory)
    client = BackendClient(
        os.environ.get("TICKER_BACKEND_URL", "https://ticker.mattdicks.org"),
        timeout_seconds=float(os.environ.get("TICKER_BACKEND_TIMEOUT", "5")),
        verify_tls=os.environ.get("TICKER_VERIFY_TLS", "true").lower() not in {"0", "false", "no"},
    )
    try:
        registration = client.register_device(device_id, name="Ticker diagnostics")
        response = client.fetch_data(device_id)
        print(f"  backend: ticker={registration.ticker_id} paired={registration.paired} mode={response.settings.mode}")
    finally:
        client.close()


def check_internet() -> None:
    """Check the same public reachability probe used by Wi-Fi recovery."""
    if not probe_internet():
        raise RuntimeError("the public internet probe failed")
    print("  internet: reachable")


def check_platform_commands() -> None:
    """Confirm NetworkManager can answer a read-only wireless scan."""
    networks = SubprocessPlatformCommands().list_wifi_networks()
    print(f"  Wi-Fi networks visible: {len(networks)}")


def run_wifi_setup(args: argparse.Namespace) -> None:
    """Start the real setup hotspot, validate its portal, and optionally keep it serving."""
    commands = SubprocessPlatformCommands()
    service = WiFiRecoveryService(
        commands,
        internet_probe=lambda: False,
        hotspot_starter=lambda details: commands.start_hotspot(
            details.ssid,
            details.password,
            interface=details.interface,
        ),
        setup_failure_threshold=1,
        portal_port=args.portal_port,
    )
    state = service.start_setup()
    print(f"  hotspot: {state.hotspot.ssid} password={state.hotspot.password}")
    print(f"  portal: {state.setup_url} code={state.setup_code}")
    page = service.portal_app().test_client().get("/")
    if page.status_code != 200:
        raise RuntimeError(f"setup portal returned HTTP {page.status_code}")
    if not args.portal:
        return
    portal_thread = Thread(target=service.start_portal, name="ticker-diagnostic-portal", daemon=True)
    portal_thread.start()
    print("  portal running. Press Ctrl+C after completing setup.")
    try:
        while portal_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("  portal stopped by operator")


def run_check(name: str, action: Callable[[], None], results: list[dict[str, object]]) -> bool:
    """Run one diagnostic action and record failures without hiding later checks."""
    started = time.monotonic()
    try:
        action()
        results.append({"name": name, "status": "pass", "duration_seconds": round(time.monotonic() - started, 3)})
        print(f"PASS {name}")
        return True
    except Exception as error:
        results.append({"name": name, "status": "fail", "duration_seconds": round(time.monotonic() - started, 3), "error": str(error)})
        print(f"FAIL {name}: {error}")
        return False


def write_report(args: argparse.Namespace, results: list[dict[str, object]], failures: list[str]) -> None:
    """Write one bounded manufacturing record when the operator requests a report path."""
    if args.report is None:
        return
    data_directory = Path(os.environ.get("TICKER_DATA_DIR", "~/ticker")).expanduser()
    report = {
        "observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "device_id": load_device_id(data_directory),
        "host": platform.platform(),
        "python": sys.version.split()[0],
        "backend_url": os.environ.get("TICKER_BACKEND_URL", "https://ticker.mattdicks.org"),
        "status": "fail" if failures else "pass",
        "checks": results,
    }
    args.report.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.report.expanduser().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {args.report.expanduser()}")


if __name__ == "__main__":
    raise SystemExit(main())
