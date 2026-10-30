"""Replay identical captured traffic through the application on a physical Pi matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import sys
import tempfile
import time


class CapturedConnection:
    """Supply paced messages to the production stream decoder."""

    def __init__(self, messages: list[dict], interval: float) -> None:
        self._messages = messages
        self._interval = interval
        self._index = 0
        self._deadline = time.monotonic()

    def recv(self) -> str:
        cycle, index = divmod(self._index, len(self._messages))
        time.sleep(max(0.0, self._deadline - time.monotonic()))
        message = {**self._messages[index], "stream_id": f"captured-{cycle}"}
        self._index += 1
        self._deadline += self._interval
        return json.dumps(message, separators=(",", ":"))

    def close(self) -> None:
        pass


class ReplayTransportClient:
    """Replace network I/O while retaining the production poller and protocol."""

    def __init__(self, messages: list[dict], interval: float) -> None:
        self._messages = messages
        self._interval = interval
        self.last_response_bytes = 0

    def register_device(self, *args, **kwargs):
        return None

    def fetch_data(self, device_id):
        from ticker.six.protocol import TickerResponse

        payload = self._messages[0]["payload"]
        self.last_response_bytes = len(json.dumps(payload).encode())
        return TickerResponse.from_payload(payload)

    def open_device_stream(self, *args, **kwargs):
        return CapturedConnection(self._messages, self._interval)

    def remember_stream_response(self, *args):
        pass

    def close(self):
        pass


class DisabledCommands:
    """Reject platform actions during the temporary hardware replay."""

    def __getattr__(self, name):
        raise RuntimeError(f"Platform action is disabled during replay: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--messages", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=float, default=20)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    if args.warmup < 0 or args.seconds < 20 or args.interval <= 0:
        parser.error("Use nonnegative warmup, at least 20 measurement seconds, and a positive message interval.")
    sys.path[:0] = [os.path.join(str(args.repository.resolve()), name) for name in ("shared", "server", "six", "")]
    sys.dont_write_bytecode = True

    from ticker.six.app.application import TickerApplication
    from ticker.six.app.poller import BackendPoller
    from ticker.six.assets import ShortTermContentCache
    from ticker.six.bootstrap import create_default_frame_builder
    from ticker.six.drivers import RgbMatrixFrameSink
    from ticker.six.platform import AssetCoordinator, TickerPiLogger
    from ticker.six.runtime import FramePacer, TickerRuntime

    messages = json.loads(args.messages.read_text(encoding="utf-8-sig"))
    if not messages or messages[0].get("type") != "snapshot":
        parser.error("The capture must start with a full snapshot.")
    for message in messages:
        for root in (message.get("payload", {}), message.get("changes", {})):
            for command in ("update", "reboot"):
                root.get("meta", {}).pop(command, None)
    source_digest = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()

    with tempfile.TemporaryDirectory(prefix="pi-stream-replay-") as temporary:
        scratch = Path(temporary)
        assets = AssetCoordinator("/home/mld/ticker/assets")
        frames, viewport = create_default_frame_builder(assets)
        client = ReplayTransportClient(messages, args.interval)
        runtime = TickerRuntime(monotonic=time.monotonic, wall_clock=datetime.now)
        logger = TickerPiLogger(scratch / "logs")
        application = TickerApplication(
            client=client, poller=BackendPoller(client, "replay-ticker", telemetry=lambda: None),
            cache=ShortTermContentCache(scratch / "content.json"), assets=assets,
            runtime=runtime, viewport=viewport, frames=frames,
            pacer=FramePacer(time.monotonic), sink=RgbMatrixFrameSink.create(),
            commands=DisabledCommands(), device_id="replay-ticker",
            repository=args.repository, wall_clock=datetime.now,
            poll_in_process=True, render_cpu=1, poll_cpu=2, logger=logger,
        )
        measured_at = None
        try:
            application.start()
            warmup_end = time.monotonic() + args.warmup
            while time.monotonic() < warmup_end + args.seconds:
                if measured_at is None and time.monotonic() >= warmup_end:
                    logger._flush_window(force=True)
                    measured_at = datetime.now(timezone.utc).timestamp()
                application.step()
                application._stop.wait(application._pacer.next_delay(application._last_decision.interval))
            if application._last_frame is not None:
                application._last_frame.save(args.output.with_suffix(".png"))
        finally:
            application.close()
        records = [json.loads(line) for line in (scratch / "logs/ticker-performance.jsonl").read_text().splitlines()]
        windows = [
            record for record in records if record.get("kind") == "window"
            and datetime.fromisoformat(record["started_at"]).timestamp() >= measured_at
        ]
        total_frames = sum(window["frames"] for window in windows)
        total_seconds = sum(window["duration_s"] for window in windows)
        overruns = sum(window["flags"]["overruns"] for window in windows)
        report = {
            "hardware": "real Pi and 384x32 matrix", "source_sha256": source_digest,
            "repository": str(args.repository), "frame_count": total_frames,
            "duration_seconds": round(total_seconds, 3), "fps": round(total_frames / total_seconds, 3),
            "overruns": overruns, "overrun_percent": round(100 * overruns / total_frames, 3),
            "frame_ms_max": max(window["frame_ms"]["max"] for window in windows),
            "window_p95_ms_max": max(window["frame_ms"]["p95"] for window in windows),
            "stream_messages": sum(sum(window["stream"]["messages"].values()) for window in windows),
            "windows": windows,
        }
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "windows"}, indent=2))


if __name__ == "__main__":
    main()
