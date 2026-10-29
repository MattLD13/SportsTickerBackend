"""Send a short test overlay through the live backend to a real Pi ticker."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

import requests


def _ssh(target: str, identity: Path, command: str) -> str:
    result = subprocess.run(
        [
            "ssh",
            "-i",
            str(identity),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            target,
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.stdout


def _records(text: str) -> list[dict[str, Any]]:
    result = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _baseline(records: list[dict[str, Any]]) -> tuple[int, int]:
    sequence = max(
        (
            int(record.get("stream", {}).get("last_sequence") or 0)
            for record in records
            if record.get("kind") == "window"
        ),
        default=0,
    )
    payloads = [record for record in records if record.get("kind") == "payload"]
    news_count = int(payloads[-1].get("news_count", 0)) if payloads else 0
    return sequence, news_count


def _post_records(
    records: list[dict[str, Any]], *, started_at: float, baseline_news: int, baseline_sequence: int
) -> tuple[bool, bool, int, dict[str, object] | None]:
    payload_seen = any(
        record.get("kind") == "payload"
        and int(record.get("news_count", 0)) > baseline_news
        and _timestamp(record.get("at")) >= started_at
        for record in records
    )
    windows = [
        record
        for record in records
        if record.get("kind") == "window"
        and _timestamp(record.get("finished_at")) >= started_at
    ]
    sequence = max(
        (int(record.get("stream", {}).get("last_sequence") or 0) for record in windows),
        default=0,
    )
    display_window = next(
        (
            record
            for record in sorted(
                windows, key=lambda item: _timestamp(item.get("finished_at")), reverse=True
            )
            if record.get("panel", {}).get("width") == 384
            and record.get("panel", {}).get("height") == 32
            and int(record.get("frames", 0)) > 0
        ),
        None,
    )
    screen = None
    if display_window is not None:
        screen = {
            "finished_at": display_window.get("finished_at"),
            "frames": display_window.get("frames"),
            "fps": display_window.get("fps"),
            "frame_ms_p95": display_window.get("frame_ms", {}).get("p95"),
            "overruns": display_window.get("flags", {}).get("overruns"),
            "panel": display_window.get("panel"),
        }
    return payload_seen, sequence > baseline_sequence, sequence, screen


def _timestamp(value: object) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _active_event(session: requests.Session, url: str, ticker_id: str, event_id: str) -> bool:
    response = session.get(f"{url}/tickers/{ticker_id}/data", timeout=15)
    response.raise_for_status()
    data = response.json()
    return any(
        item.get("event_id") == event_id
        for item in data.get("events", {}).get("news", [])
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    backend_url = args.backend_url.rstrip("/")
    log_path = "/home/mld/ticker/logs/ticker-performance.jsonl"
    service = _ssh(
        args.ssh_target,
        args.ssh_key,
        "systemctl is-active ticker-controller.service && readlink -f /opt/sports-ticker/current",
    ).splitlines()
    if len(service) < 2 or service[0].strip() != "active":
        raise RuntimeError(f"Pi service is not active: {service!r}")
    release = service[1].strip()
    baseline_records = _records(_ssh(args.ssh_target, args.ssh_key, f"tail -n 100 {log_path}"))
    baseline_sequence, baseline_news = _baseline(baseline_records)

    marker = f"CODEX LIVE TEST {uuid4().hex[:10]}"
    session = requests.Session()
    health = session.get(f"{backend_url}/health", timeout=15)
    health.raise_for_status()
    started_at = time.time()
    created = session.post(
        f"{backend_url}/news",
        json={
            "kind": "news",
            "payload": {"text": marker, "sport": "nhl", "category": "TEST"},
            "ticker_ids": [args.ticker_id],
            "ttl_seconds": args.ttl_seconds,
        },
        timeout=15,
    )
    created.raise_for_status()
    event = created.json()
    event_id = str(event["event_id"])
    expires_at = float(event["expires_at"])
    server_seen = False
    device_payload_seen = False
    sequence_seen = False
    last_sequence = baseline_sequence
    screen_window = None
    try:
        deadline = time.monotonic() + args.receive_timeout
        while time.monotonic() < deadline:
            server_seen = _active_event(session, backend_url, args.ticker_id, event_id)
            recent = _records(_ssh(args.ssh_target, args.ssh_key, f"tail -n 100 {log_path}"))
            device_payload_seen, sequence_seen, latest, latest_screen = _post_records(
                recent,
                started_at=float(event.get("created_at", started_at)) - 5.0,
                baseline_news=baseline_news,
                baseline_sequence=baseline_sequence,
            )
            last_sequence = max(last_sequence, latest)
            screen_window = latest_screen or screen_window
            if server_seen and device_payload_seen and sequence_seen and screen_window:
                break
            time.sleep(3)
        if not (server_seen and device_payload_seen and sequence_seen):
            raise RuntimeError(
                "Pi smoke did not pass: "
                f"server_event={server_seen}, payload={device_payload_seen}, "
                f"sequence={sequence_seen}, display_frame={bool(screen_window)}."
            )
    finally:
        # Let the server expire the event so this test leaves no overlay behind.
        time.sleep(max(0.0, expires_at - time.time() + 2.0))

    expiry_deadline = time.monotonic() + 15
    while time.monotonic() < expiry_deadline and _active_event(
        session, backend_url, args.ticker_id, event_id
    ):
        time.sleep(1)
    if _active_event(session, backend_url, args.ticker_id, event_id):
        raise RuntimeError("The test overlay remained active after its TTL.")

    final_records = _records(_ssh(args.ssh_target, args.ssh_key, f"tail -n 100 {log_path}"))
    cleared = any(
        record.get("kind") == "payload"
        and int(record.get("news_count", 0)) <= baseline_news
        and _timestamp(record.get("at")) >= expires_at - 5.0
        for record in final_records
    )
    if not cleared:
        raise RuntimeError("The Pi log has not yet recorded the cleared overlay payload.")
    if screen_window is None:
        raise RuntimeError("The Pi did not report a real 384x32 display frame.")
    display_budget_ok = (
        float(screen_window.get("fps") or 0.0) >= 30.0
        and float(screen_window.get("frame_ms_p95") or float("inf")) <= 30.0
    )
    if not display_budget_ok:
        raise RuntimeError(f"The Pi display missed its 30 FPS frame budget: {screen_window!r}")

    return {
        "hardware": "real Raspberry Pi ticker",
        "service": service[0].strip(),
        "release": release,
        "panel": "384x32",
        "event_id": event_id,
        "marker": marker,
        "server_to_pi_payload": device_payload_seen,
        "websocket_sequence_before": baseline_sequence,
        "websocket_sequence_after": last_sequence,
        "real_screen_telemetry": screen_window,
        "display_budget_ok": display_budget_ok,
        "overlay_expired_on_server": True,
        "overlay_clear_recorded_on_pi": cleared,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="https://ticker.mattdicks.org")
    parser.add_argument("--ticker-id", required=True)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--ssh-key", required=True, type=Path)
    parser.add_argument("--ttl-seconds", type=int, default=60)
    parser.add_argument("--receive-timeout", type=int, default=30)
    args = parser.parse_args()
    if not 30 <= args.ttl_seconds <= 600:
        parser.error("--ttl-seconds must be between 30 and 600")
    if args.receive_timeout < 1:
        parser.error("--receive-timeout must be positive")
    try:
        print(json.dumps(run(args), indent=2))
    except (OSError, requests.RequestException, subprocess.SubprocessError, KeyError, ValueError, RuntimeError) as error:
        print(f"Live ticker hardware smoke failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
