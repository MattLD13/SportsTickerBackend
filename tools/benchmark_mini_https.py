"""Compare fresh and reused HTTPS connections with one fixed authenticated response."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics
import time
import serial


def benchmark(port: str, pairs: int, timeout: float) -> dict:
    results = []
    incoming = bytearray()
    deadline = time.monotonic() + timeout
    sent = False
    next_command = 0.0
    with serial.Serial(port, 115200, timeout=0.1, write_timeout=2) as connection:
        while time.monotonic() < deadline and len(results) < pairs * 2:
            now = time.monotonic()
            if not sent and now >= next_command:
                cold = len(results) % 2 == 0
                connection.write(b"CHECKAUTH:COLD\n" if cold else b"CHECKAUTH\n")
                sent = True
            incoming.extend(connection.read(min(4096, connection.in_waiting or 1)))
            while b"\n" in incoming:
                raw, _, incoming = incoming.partition(b"\n")
                line = raw.decode(errors="replace")
                marker = line.find("MINI_AUTH_CHECK:")
                if marker < 0:
                    continue
                body = line[marker + len("MINI_AUTH_CHECK:"):].strip()
                sent = False
                next_command = now + 0.2
                if body == "BUSY":
                    continue
                value = json.loads(body)
                if value["status"] != 200:
                    raise RuntimeError(f"Device authentication check failed: {value['status']}")
                if value["cold"] != (len(results) % 2 == 0):
                    raise RuntimeError("Unexpected benchmark response order")
                results.append(value)
                print(f"Completed connection sample {len(results)}/{pairs * 2}", flush=True)
    if len(results) != pairs * 2:
        raise TimeoutError("HTTPS benchmark did not complete")
    if len({item["bytes"] for item in results}) != 1:
        raise RuntimeError("The benchmark response size changed")
    cold = [item["request_ms"] for item in results if item["cold"]]
    warm = [item["request_ms"] for item in results if not item["cold"] and item["reused"]]
    if len(warm) != pairs:
        raise RuntimeError("The network did not preserve every measured warm connection")
    return {"pairs": pairs, "response_bytes": results[0]["bytes"], "cold_p50_ms": statistics.median(cold),
            "warm_p50_ms": statistics.median(warm), "samples": results,
            "reduction_percent": round((1 - statistics.median(warm) / statistics.median(cold)) * 100, 2)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--pairs", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.pairs < 1 or args.timeout <= 0:
        parser.error("pairs and timeout must be positive")
    result = benchmark(args.port, args.pairs, args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))


if __name__ == "__main__":
    main()
