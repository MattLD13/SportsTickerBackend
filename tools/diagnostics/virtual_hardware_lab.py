"""Run the real Pi controller against deterministic virtual backend hardware."""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests
import websocket
from hypercorn.asyncio import serve
from hypercorn.config import Config

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from ticker.six.app.application import TickerApplication
from ticker.six.app.poller import BackendPoller
from ticker.six.assets import MemoryAssetView, ShortTermContentCache
from ticker.six.bootstrap import create_default_frame_builder
from ticker.six.drivers import MemoryFrameSink
from ticker.six.protocol import BackendClient
from ticker.six.ui import FrameGeometry
from ticker.six.runtime import FramePacer, RuntimeConfig, TickerRuntime
from ticker.shared.domain import ContentItem, DisplaySettings, TickerSnapshot
from ticker.server.store import PairingState
from ticker.server.api.asgi import TickerASGI
from ticker.server.offline import create_offline_application


DEVICE_ID = "virtual-ticker-01"
DEVICE_TOKEN = sha256(b"isolated-virtual-ticker-credential").hexdigest()
SNAPSHOT = REPOSITORY / "tests" / "fixtures" / "display" / "render_snapshot.json"


class LoopbackHttpSession:
    """Send requests to the local API."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._session = requests.Session()
        self._lock = threading.Lock()
        self.requests_seen: list[dict[str, object]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Call the real local API and record its response status."""
        started = time.monotonic()
        path = urlsplit(url).path
        with self._lock:
            request_record: dict[str, object] = {"method": method, "path": path}
            self.requests_seen.append(request_record)
        response = self._session.request(
            method,
            f"{self._base_url}{path}",
            **kwargs,
        )
        request_record["status"] = response.status_code
        request_record["json_payload_bytes"] = len(response.content)
        request_record["elapsed_ms"] = (time.monotonic() - started) * 1000.0
        return response

    def close(self) -> None:
        """Close the local HTTP session."""
        self._session.close()
        self.closed = True


class RestPollProbe:
    """Measure the former HTTP snapshot polling path against the same API."""

    def __init__(self, base_url: str, *, interval: float = 0.5) -> None:
        self.url = f"{base_url}/data"
        self.interval = interval
        self.ready = threading.Event()
        self.changed = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.target_score: str | None = None
        self.changed_at: float | None = None
        self.records: list[dict[str, object]] = []
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, name="virtual-rest-poll-probe", daemon=True)
        self._session = requests.Session()
        self._session.headers["X-Device-Token"] = DEVICE_TOKEN

    def start(self) -> None:
        self._thread.start()

    def set_target(self, score: str) -> None:
        with self._lock:
            self.target_score = score
            self.changed_at = None
            self.changed.clear()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        self._session.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                response = self._session.get(self.url, timeout=2)
                response.raise_for_status()
                payload = response.json()
                score = str(payload["content"]["sports"][0]["data"]["away_score"])
                record: dict[str, object] = {
                    "json_payload_bytes": len(response.content),
                    "elapsed_ms": (time.monotonic() - started) * 1000.0,
                    "observed_at": time.monotonic(),
                    "score": score,
                }
                with self._lock:
                    self.records.append(record)
                    if self.target_score is not None and score == self.target_score and self.changed_at is None:
                        self.changed_at = float(record["observed_at"])
                        self.changed.set()
                self.ready.set()
            except Exception as error:
                self.error = str(error)
                self.ready.set()
            remaining = max(0.0, self.interval - (time.monotonic() - started))
            if self._stop.wait(remaining):
                return


class LoopbackStreamConnector:
    """Open real local WebSockets and inject a controlled stream interruption."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.offline = False
        self.connections = 0
        self.disconnects = 0
        self.subprotocols: list[str | None] = []
        self.messages: list[dict[str, object]] = []

    def __call__(self, url: str, **kwargs: Any):
        with self._lock:
            if self.offline:
                raise websocket.WebSocketException("virtual stream link is disconnected")
        connection = websocket.create_connection(url, **kwargs)
        with self._lock:
            self.connections += 1
            self.subprotocols.append(connection.getsubprotocol())
        return _LoopbackStreamConnection(self, connection)

    def set_offline(self, value: bool) -> None:
        with self._lock:
            self.offline = value


class _LoopbackStreamConnection:
    def __init__(self, owner: LoopbackStreamConnector, connection) -> None:
        self._owner = owner
        self._connection = connection

    def recv(self):
        with self._owner._lock:
            offline = self._owner.offline
        if offline:
            self._connection.close()
            with self._owner._lock:
                self._owner.disconnects += 1
            raise websocket.WebSocketConnectionClosedException("virtual stream link is disconnected")
        raw = self._connection.recv()
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            message = {}
        if isinstance(message, dict):
            with self._owner._lock:
                self._owner.messages.append({
                    "type": message.get("type"),
                    "seq": message.get("seq"),
                    "json_payload_bytes": len(raw.encode("utf-8")),
                    "received_at": time.monotonic(),
                })
        return raw

    def close(self) -> None:
        self._connection.close()

class VirtualAssets(MemoryAssetView):
    """Keep all asset reads in memory and prevent external image requests."""

    def prefetch_payload(self, payload: object) -> tuple[object, ...]:
        del payload
        return ()

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass


class VirtualPlatformCommands:
    """Reject system actions so a virtual run cannot reboot or reconfigure a host."""

    def reboot(self) -> None:
        raise RuntimeError("reboot is disabled in the virtual hardware lab")

    def run_update(self, command, *, working_directory) -> None:
        del command, working_directory
        raise RuntimeError("updates are disabled in the virtual hardware lab")

    def list_wifi_networks(self):
        return []

    def connect_wifi(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        del ssid, password, interface
        raise RuntimeError("Wi-Fi changes are disabled in the virtual hardware lab")

    def start_hotspot(self, ssid: str, password: str, *, interface: str = "wlan0") -> None:
        del ssid, password, interface
        raise RuntimeError("hotspot changes are disabled in the virtual hardware lab")

    def stop_hotspot(self, *, interface: str = "wlan0") -> None:
        del interface
        raise RuntimeError("Wi-Fi changes are disabled in the virtual hardware lab")


class VirtualRunLogger:
    """Record controller poll errors for actionable bench failures."""

    def __init__(self, viewport_generation) -> None:
        self.polls: list[dict[str, object]] = []
        self.issues: list[dict[str, object]] = []
        self.frames: list[dict[str, object]] = []
        self.stream_events: list[dict[str, object]] = []
        self.latency: list[dict[str, object]] = []
        self._viewport_generation = viewport_generation

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def record_poll(self, **values) -> None:
        self.polls.append(values)

    def record_stream(self, event, **values) -> None:
        self.stream_events.append({"event": event, **values})

    def record_latency(self, value) -> None:
        self.latency.append(dict(value))

    def record_issue(self, source, error, **details) -> None:
        self.issues.append({"source": source, "error": str(error), **details})

    def record_frame(self, **values) -> None:
        self.frames.append({
            "finished_at": values.get("finished_at"),
            "viewport_generation": self._viewport_generation(),
        })

    def record_tick(self, **values) -> None:
        pass

    def record_payload(self, response) -> None:
        del response


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload


class HypercornThread:
    """Run one local Hypercorn server with ASGI lifespan management."""

    def __init__(self, application: TickerASGI) -> None:
        self.application = application
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="virtual-hypercorn", daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.error is not None:
                raise RuntimeError("Hypercorn failed to start") from self.error
            try:
                response = requests.get(f"{self.base_url}/health", timeout=0.2)
                if response.status_code == 200:
                    return
            except requests.RequestException:
                pass
            self._ready.wait(0.02)
        raise RuntimeError("Timed out waiting for the local Hypercorn API.")

    def close(self) -> None:
        if self._loop is not None and self._shutdown is not None:
            self._loop.call_soon_threadsafe(self._shutdown.set)
        self._thread.join(timeout=8)
        if self._thread.is_alive():
            raise RuntimeError("Hypercorn did not stop within eight seconds.")
        if self.error is not None:
            raise RuntimeError("Hypercorn stopped with an error") from self.error

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as error:
            self.error = error
            self._ready.set()

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._shutdown = asyncio.Event()
        self._ready.set()
        config = Config()
        config.bind = [self.base_url.removeprefix("http://")]
        config.workers = 1
        config.websocket_ping_interval = 20.0
        config.accesslog = None
        config.errorlog = None
        await serve(
            self.application,
            config,
            shutdown_trigger=self._shutdown.wait,
            mode="asgi",
        )


def _expire_events(flask_app):
    """Remove expired overlays every 0.1 seconds, as the engine does each pass. Return the stop function."""
    events = flask_app.extensions["ticker.application"].event_service
    stop = threading.Event()

    def run() -> None:
        while not stop.wait(0.1):
            events.remove_expired()

    thread = threading.Thread(target=run, name="virtual-event-expiry", daemon=True)
    thread.start()

    def close() -> None:
        stop.set()
        thread.join(timeout=2)

    return close


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _snapshot(payload: dict[str, Any], *, revision: int) -> TickerSnapshot:
    records = payload.get("content", {}).get("sports", [])
    content = tuple(
        ContentItem(
            id=str(item["id"]),
            family=str(item["family"]),
            kind=str(item["kind"]),
            is_shown=bool(item.get("is_shown", True)),
            data=item.get("data", {}),
        )
        for item in records
    )
    return TickerSnapshot(
        ticker_id=DEVICE_ID,
        revision=revision,
        observed_at=datetime.now(timezone.utc),
        content=content,
        alerts=(),
        news=(),
        effective_settings=DisplaySettings(mode="sports"),
    )


def _wait_for(app: TickerApplication, predicate, timeout: float, label: str, logger=None, session=None):
    deadline = time.monotonic() + timeout
    last_decision = None
    while time.monotonic() < deadline:
        decision = app.step()
        last_decision = decision
        if predicate(decision):
            return decision
        time.sleep(0.01)
    snapshot = app.runtime.snapshot
    raise RuntimeError(
        f"Timed out waiting for {label}. Last frame={getattr(last_decision, 'kind', None)}. "
        f"Snapshot={'none' if snapshot is None else snapshot.key}. "
        f"Viewport={getattr(app._viewport, 'status', None)}. "
        f"Polls={getattr(logger, 'polls', None)}. "
        f"Issues={getattr(logger, 'issues', None)}. "
        f"HTTP={getattr(session, 'requests_seen', None)}."
    )


def _save_frame(app: TickerApplication, output: Path, name: str) -> dict[str, object]:
    image = getattr(app.sink, "last_image", None)
    if image is None:
        raise RuntimeError(f"No matrix frame was presented for {name}.")
    if image.size != (384, 32):
        raise RuntimeError(f"Expected a 384x32 frame, received {image.width}x{image.height}.")
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{name}.png"
    image.save(path)
    return {
        "name": name,
        "file": path.name,
        "width": image.width,
        "height": image.height,
        "sha256_rgb": sha256(image.tobytes()).hexdigest(),
        "non_black_pixels": sum(pixel != (0, 0, 0) for pixel in image.getdata()),
    }


def run(output: Path, snapshot: Path = SNAPSHOT) -> dict[str, object]:
    """Exercise registration, rendering, outage overlay, and data recovery."""
    output.mkdir(parents=True, exist_ok=True)
    payload = _load_payload(snapshot)
    captures: list[dict[str, object]] = []
    requests_seen: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="ticker-virtual-backend-") as temporary:
        flask_app = create_offline_application(Path(temporary) / "ticker.sqlite3")
        backend_app = flask_app.extensions["ticker.application"]
        backend_app.repository.create_ticker(
            DEVICE_ID,
            display_settings=DisplaySettings(mode="sports"),
            name="Virtual Sports Ticker",
            credential_hash=sha256(DEVICE_TOKEN.encode()).hexdigest(),
            pairing=PairingState(paired=True),
        )
        snapshot_store = backend_app.snapshot_store
        snapshot_store.replace(_snapshot(payload, revision=1))
        backend = TickerASGI(flask_app, start=_expire_events, http_threads=4)
        server = HypercornThread(backend)
        stream_transport = LoopbackStreamConnector()
        ticker = None
        session = None
        server_started = False
        try:
            server.start()
            server_started = True
            session = LoopbackHttpSession(server.base_url)
            client = BackendClient(
                server.base_url,
                session=session,
                stream_connector=stream_transport,
                device_token=DEVICE_TOKEN,
            )  # type: ignore[arg-type]
            assets = VirtualAssets()
            frames, viewport = create_default_frame_builder(assets, geometry=FrameGeometry(384, 32, "scale"))
            sink = MemoryFrameSink(384, 32)
            run_logger = VirtualRunLogger(lambda: viewport.status["committed_generation"])
            runtime = TickerRuntime(monotonic=time.monotonic, wall_clock=datetime.now, config=RuntimeConfig(offline_after=0.25))
            ticker = TickerApplication(
                client=client,
                poller=BackendPoller(client, DEVICE_ID, telemetry=lambda: {}, heartbeat_interval=3600),
                cache=ShortTermContentCache(output / "virtual-content-cache.json"),
                assets=assets,  # type: ignore[arg-type]
                runtime=runtime,
                viewport=viewport,
                frames=frames,
                pacer=FramePacer(time.monotonic),
                sink=sink,
                commands=VirtualPlatformCommands(),
                device_id=DEVICE_ID,
                repository=REPOSITORY,
                wall_clock=datetime.now,
                logger=run_logger,
            )
            _wait_for(
                ticker,
                lambda decision: runtime.snapshot is not None
                and decision.kind.value in {"scroll", "static"}
                and sink.last_image is not None,
                8,
                "rendered sports content frame from the API",
                run_logger,
                session,
            )
            initial_key = runtime.snapshot.key if runtime.snapshot is not None else ""
            captures.append(_save_frame(ticker, output, "01-online"))

            stream_transport.set_offline(True)
            _wait_for(
                ticker,
                lambda decision: decision.connection_lost,
                5,
                "connection-loss overlay",
            )
            captures.append(_save_frame(ticker, output, "02-disconnected"))

            stream_transport.set_offline(False)
            updated_payload = deepcopy(payload)
            updated_payload["content"]["sports"][0]["data"]["away_score"] = "24"
            snapshot_store.replace(_snapshot(updated_payload, revision=2))
            _wait_for(
                ticker,
                lambda _: runtime.snapshot is not None and runtime.snapshot.key != initial_key,
                5,
                "updated payload after reconnection",
            )
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                ticker.step()
                time.sleep(0.01)
            captures.append(_save_frame(ticker, output, "03-recovered"))

            rest_probe = RestPollProbe(server.base_url, interval=0.5)
            rest_probe.start()
            if not rest_probe.ready.wait(5) or rest_probe.error is not None:
                raise RuntimeError(f"REST efficiency probe failed: {rest_probe.error}")
            stream_hub = backend.hub
            projection_start = stream_hub.metrics
            message_start = len(stream_transport.messages)
            probe_record_start = len(rest_probe.records)
            measurement_started = time.monotonic()
            warm_until = measurement_started + 0.75
            while time.monotonic() < warm_until:
                ticker.step()
                time.sleep(0.01)

            frame_record_start = len(run_logger.frames)
            viewport_generation_before = viewport.status["committed_generation"]
            rest_probe.set_target("25")
            benchmark_payload = deepcopy(updated_payload)
            benchmark_payload["content"]["sports"][0]["data"]["away_score"] = "25"
            change_started = time.monotonic()
            snapshot_store.replace(_snapshot(benchmark_payload, revision=3))
            device_delta = None
            rest_changed_at = None
            pi_applied_at = None
            frame_present_at = None
            benchmark_deadline = change_started + 5
            while time.monotonic() < benchmark_deadline:
                ticker.step()
                messages = stream_transport.messages[message_start:]
                if device_delta is None:
                    device_delta = next((
                        item for item in messages
                        if item.get("type") == "delta" and item.get("seq", 0) > 2
                    ), None)
                if rest_changed_at is None:
                    rest_changed_at = rest_probe.changed_at
                current_snapshot = runtime.snapshot
                if pi_applied_at is None and current_snapshot is not None:
                    current_item = next((item for item in current_snapshot.content if item.id == "nfl-live"), None)
                    if current_item is not None and str(current_item.data.get("away_score")) == "25":
                        pi_applied_at = time.monotonic()
                viewport_generation = viewport.status["committed_generation"]
                if viewport_generation > viewport_generation_before and frame_present_at is None:
                    frame_present_at = next((
                        float(item["finished_at"])
                        for item in run_logger.frames[frame_record_start:]
                        if item["finished_at"] is not None
                        and float(item["finished_at"]) >= change_started
                        and int(item["viewport_generation"]) >= viewport_generation
                    ), None)
                if device_delta is not None and rest_changed_at is not None and pi_applied_at is not None and frame_present_at is not None:
                    break
                time.sleep(0.01)
            measurement_finished = time.monotonic()
            rest_probe.close()
            projection_finish = stream_hub.metrics
            if device_delta is None or rest_changed_at is None or pi_applied_at is None:
                raise RuntimeError(
                    "Efficiency comparison missed an update. "
                    f"WebSocket={device_delta}, REST={rest_changed_at}, Pi={pi_applied_at}."
                )
            for _ in range(25):
                ticker.step()
                time.sleep(0.01)
            captures.append(_save_frame(ticker, output, "04-benchmark-update"))
            measurement_seconds = measurement_finished - measurement_started
            measured_http = [
                record for record in rest_probe.records[probe_record_start:]
                if measurement_started <= float(record["observed_at"]) <= measurement_finished
            ]
            measured_ws = [
                record for record in stream_transport.messages[message_start:]
                if change_started <= float(record["received_at"]) <= measurement_finished
            ]
            mean_http_bytes = (
                sum(int(record["json_payload_bytes"]) for record in measured_http) / len(measured_http)
                if measured_http else 0.0
            )
            mean_http_latency = (
                sum(float(record["elapsed_ms"]) for record in measured_http) / len(measured_http)
                if measured_http else 0.0
            )
            projector_reads = int(projection_finish["projection_reads"]) - int(projection_start["projection_reads"])
            projector_seconds = float(projection_finish["projection_seconds"]) - float(projection_start["projection_seconds"])
            delta_message = next(
                item for item in measured_ws
                if item.get("type") == "delta" and item.get("seq") == device_delta.get("seq")
            )
            efficiency = {
                "measurement_seconds": round(measurement_seconds, 3),
                "rest_baseline": {
                    "poll_interval_seconds": 0.5,
                    "requests": len(measured_http),
                    "requests_per_second": round(len(measured_http) / measurement_seconds, 2),
                    "mean_json_payload_bytes": round(mean_http_bytes),
                    "mean_request_latency_ms": round(mean_http_latency, 2),
                    "update_detection_ms": round((rest_changed_at - change_started) * 1000, 2),
                },
                "websocket": {
                    "frames_during_window": len(measured_ws),
                    "delta_json_payload_bytes": int(delta_message["json_payload_bytes"]),
                    "update_delivery_ms": round((float(device_delta["received_at"]) - change_started) * 1000, 2),
                    "pi_state_apply_ms": round((pi_applied_at - change_started) * 1000, 2),
                    "frame_present_ms": round((frame_present_at - change_started) * 1000, 2),
                },
                "stream_projector": {
                    "idle_check_interval_seconds": 1.0,
                    "projection_reads": projector_reads,
                    "projection_reads_per_second": round(projector_reads / measurement_seconds, 2),
                    "projection_wall_ms": round(projector_seconds * 1000, 2),
                    "mean_projection_ms": round(projector_seconds * 1000 / projector_reads, 3) if projector_reads else 0,
                },
                "daily_estimate_per_active_ticker": {
                    "rest_display_gets_at_500ms": round(86400 / 0.5),
                    "websocket_steady_state_display_gets": 0,
                    "websocket_idle_projection_checks_at_1s": round(86400 / 1.0),
                    "rest_projection_reads_at_500ms": round(86400 / 0.5),
                    "websocket_projection_reads_at_measured_rate": round(projector_reads / measurement_seconds * 86400),
                    "rest_projection_reads_at_measured_rate": round(len(measured_http) / measurement_seconds * 86400),
                    "measured_projection_read_ratio_websocket_to_rest": round(
                        (projector_reads / len(measured_http)) if measured_http else 0,
                        2,
                    ),
                    "rest_json_payload_mib_at_measured_mean": round(mean_http_bytes * (86400 / 0.5) / (1024 * 1024), 2),
                },
            }
            requests_seen = session.requests_seen
        finally:
            if "rest_probe" in locals():
                rest_probe.close()
            if ticker is not None:
                ticker.close()
            if session is not None:
                session.close()
            if server_started:
                server.close()
            backend_app.close()
    checks = {
        "registration_route": any(item["path"] == "/register" for item in requests_seen),
        "data_route_served_by_local_api": any(
            item["path"] == "/data" and item.get("status") == 200
            for item in requests_seen
        ),
        "disconnect_injected_at_client_transport": any(
            item.get("result") == "simulated_transport_loss" for item in requests_seen
        ) or stream_transport.disconnects > 0,
        "websocket_subprotocol_accepted": "ticker" in stream_transport.subprotocols,
        "delta_reached_device": any(item.get("type") == "delta" for item in stream_transport.messages),
        "reconnect_replayed_after_cursor": (
            len(stream_transport.messages) >= 2
            and stream_transport.messages[0].get("type") == "snapshot"
            and stream_transport.messages[1].get("type") == "delta"
            and stream_transport.messages[1].get("seq") == stream_transport.messages[0].get("seq", 0) + 1
        ),
        "disconnect_overlay_changed_frame": captures[0]["sha256_rgb"] != captures[1]["sha256_rgb"],
        "score_update_changed_frame": captures[0]["sha256_rgb"] != captures[2]["sha256_rgb"],
        "all_frames_are_384x32": all(item["width"] == 384 and item["height"] == 32 for item in captures),
        "http_session_closed": bool(session and session.closed),
        "efficiency_probe_measured_both_transports": bool(efficiency["rest_baseline"]["requests"] and efficiency["websocket"]["delta_json_payload_bytes"]),
        "device_stream_metrics_recorded": any(item.get("event") == "message" and item.get("sequence") for item in run_logger.stream_events),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Virtual hardware checks failed: {checks}")
    return {
        "hardware_model": "Pi controller + 384x32 RGB matrix memory sink",
        "backend_model": "real Flask API over Hypercorn ASGI with temporary SQLite",
        "checks": checks,
        "frames": captures,
        "requests": requests_seen,
        "websocket_connections": stream_transport.connections,
        "websocket_disconnects": stream_transport.disconnects,
        "websocket_subprotocols": stream_transport.subprotocols,
        "websocket_messages": stream_transport.messages,
        "device_stream_metrics": run_logger.stream_events,
        "efficiency_comparison": efficiency,
        "network_calls": "loopback only",
        "platform_commands": "disabled",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--output-dir", type=Path, default=Path("previews/virtual-hardware"))
    args = parser.parse_args()
    report = run(args.output_dir.resolve(), args.snapshot.resolve())
    report_path = args.output_dir.resolve() / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Report saved to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
