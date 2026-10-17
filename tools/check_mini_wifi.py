"""Test real Mini association recovery after outages longer than the setup timeout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import serial


def check(port: str, output: Path, cycles: int, timeout: float) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + timeout
    incoming = bytearray()
    next_stats = 0.0
    phase = "baseline"
    completed = 0
    lost = False
    data_seen = heartbeat_seen = False
    started_at = 0.0
    results = []
    firmware = None
    with serial.Serial(port, 115200, timeout=0.1, write_timeout=2) as connection, \
         (output / "stats.jsonl").open("w", encoding="utf-8") as stats:
        while time.monotonic() < end:
            now = time.monotonic()
            if now >= next_stats:
                connection.write(b"STATS\n")
                next_stats = now + 1
            incoming.extend(connection.read(min(4096, connection.in_waiting or 1)))
            while b"\n" in incoming:
                raw, _, remaining = incoming.partition(b"\n")
                incoming = bytearray(remaining)
                line = raw.decode("utf-8", errors="replace").strip()
                marker = line.find("MINI_STATS:")
                if marker < 0:
                    continue
                sample = json.loads(line[marker + len("MINI_STATS:"):])
                stats.write(json.dumps(sample) + "\n")
                stats.flush()
                firmware = sample["firmware"]
                display = sample["display"]
                network = display["network"]
                if display["reset_reason"] in (4, 5, 6, 7, 9):
                    raise RuntimeError("Mini restarted after a panic, watchdog, or brownout")
                if "data_age_ms" not in network:
                    raise RuntimeError("Mini firmware lacks Wi-Fi recovery diagnostics")
                fresh = (
                    network["wifi_connected"] and network["http_status"] == 200
                    and network.get("data_age_ms") is not None and network["data_age_ms"] < 30000
                    and not network["wifi_setup_active"] and not network["ble_setup_active"]
                )
                if phase == "baseline" and fresh:
                    connection.write(b"WIFITEST:45000\n")
                    started_at = now
                    lost = False
                    data_seen = heartbeat_seen = False
                    phase = "outage"
                    print(f"Started outage {completed + 1}", flush=True)
                elif phase == "outage":
                    lost |= not network["wifi_connected"]
                    if network["wifi_setup_active"] or network["ble_setup_active"]:
                        raise RuntimeError("A confirmed-network outage entered credential setup")
                    recovered_link = network["wifi_connected"] and not network["wifi_setup_active"] and not network["ble_setup_active"]
                    if lost and recovered_link:
                        data_seen |= network.get("data_age_ms") is not None and network["data_age_ms"] < 30000
                        heartbeat_seen |= network.get("heartbeat_age_ms") is not None and network["heartbeat_age_ms"] < 30000 and network["heartbeat_status"] == 200
                    if lost and recovered_link and data_seen and heartbeat_seen:
                        completed += 1
                        results.append({"cycle": completed, "recovered_seconds": round(now - started_at, 3),
                                        "disconnect_reason": network["last_disconnect_reason"],
                                        "association_attempts": network["association_attempts"]})
                        print(f"Recovered outage {completed}", flush=True)
                        if completed == cycles:
                            result = {"firmware": firmware, "cycles": results, "passed": True}
                            (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                            return result
                        phase = "baseline"
            if len(incoming) > 65536:
                raise RuntimeError("Mini diagnostic line exceeds its input limit")
    raise TimeoutError(f"Mini completed {completed} of {cycles} outage recoveries in phase {phase}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240)
    args = parser.parse_args()
    if args.cycles <= 0 or args.timeout <= 0:
        parser.error("cycles and timeout must be positive")
    print(json.dumps(check(args.port, args.output, args.cycles, args.timeout), indent=2))


if __name__ == "__main__":
    main()
