"""Check TLS teardown against the physical Mini and its mounted file system."""

from __future__ import annotations

import argparse
import json
import time

import serial


def check(port: str, iterations: int, timeout: float) -> dict:
    started = time.monotonic()
    deadline = started + timeout
    completed = 0
    pending = False
    pending_until = 0.0
    response_timeouts = 0
    next_request = 0.0
    firmware = None
    incoming = bytearray()
    with serial.Serial(port, 115200, timeout=0.1, write_timeout=2) as connection:
        connection.write(b"STATS\n")
        while completed < iterations and time.monotonic() < deadline:
            now = time.monotonic()
            if pending and now >= pending_until:
                pending = False
                response_timeouts += 1
            if not pending and now >= next_request:
                connection.write(b"CHECKTLS\n")
                pending = True
                pending_until = now + 3
            incoming.extend(connection.read(min(4096, connection.in_waiting or 1)))
            while b"\n" in incoming:
                raw, _, remaining = incoming.partition(b"\n")
                incoming = bytearray(remaining)
                line = raw.decode("utf-8", errors="replace").strip()
                marker = line.find("MINI_")
                if marker >= 0:
                    line = line[marker:]
                if line.startswith("MINI_STATS:"):
                    firmware = json.loads(line[len("MINI_STATS:"):])["firmware"]
                if not line.startswith("MINI_TLS_CHECK:"):
                    continue
                pending = False
                result = line[len("MINI_TLS_CHECK:"):]
                if result == "PASS":
                    completed += 1
                    next_request = now + 0.1
                elif result == "BUSY":
                    next_request = now + 0.25
                else:
                    raise RuntimeError(f"Mini TLS teardown failed: {result}")
            if len(incoming) > 65536:
                raise RuntimeError("Mini diagnostic input exceeds the line limit")
    if completed != iterations:
        raise TimeoutError(f"Mini {firmware} completed {completed} of {iterations} TLS teardown checks")
    return {
        "firmware": firmware,
        "checks": completed,
        "closed_clients": completed * 16,
        "file_round_trips": completed,
        "response_timeouts": response_timeouts,
        "elapsed_s": round(time.monotonic() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if args.iterations <= 0 or args.timeout <= 0:
        parser.error("iterations and timeout must be positive")
    print(json.dumps(check(args.port, args.iterations, args.timeout), indent=2))


if __name__ == "__main__":
    main()
