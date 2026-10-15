"""Capture live Mini pane timing and complete displayed pixel matrices over USB."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import time

from PIL import Image, ImageDraw
import serial
from serial.tools import list_ports


def checksum(pixels: bytes) -> int:
    result = 2166136261
    for value in pixels:
        result = ((result ^ value) * 16777619) & 0xFFFFFFFF
    return result


@dataclass
class CapturedFrame:
    metadata: dict
    pixels: bytes


class FrameReceiver:
    def __init__(self) -> None:
        self.metadata: dict | None = None
        self.pixels = bytearray(6144)
        self.offsets: set[int] = set()

    def accept(self, line: str) -> CapturedFrame | None:
        if line.startswith("MINI_FRAME_BEGIN:"):
            metadata = json.loads(line.partition(":")[2])
            if (metadata.get("v"), metadata.get("width"), metadata.get("height"),
                metadata.get("format"), metadata.get("bytes")) != (1, 64, 32, "rgb888", 6144):
                raise ValueError("unsupported Mini frame contract")
            self.metadata = metadata
            self.offsets.clear()
        elif line.startswith("MINI_PIX:"):
            _, identifier, offset, encoded = line.split(":")
            position = int(offset, 16)
            data = bytes.fromhex(encoded)
            if self.metadata is None or int(identifier, 16) != self.metadata["id"]:
                raise ValueError("pixel packet has no matching frame")
            if position % 16 or not 0 <= position <= 6144 - 16 or len(data) != 16 or position in self.offsets:
                raise ValueError("invalid or duplicate pixel packet")
            self.pixels[position:position + 16] = data
            self.offsets.add(position)
        elif line.startswith("MINI_FRAME_END:"):
            _, identifier, digest = line.split(":")
            if self.metadata is None or int(identifier, 16) != self.metadata["id"] or len(self.offsets) != 384:
                raise ValueError("incomplete Mini frame")
            actual = checksum(self.pixels)
            if actual != int(digest, 16) or actual != self.metadata["fnv1a32"]:
                raise ValueError("Mini frame checksum mismatch")
            result = CapturedFrame(self.metadata, bytes(self.pixels))
            self.metadata = None
            return result
        return None


def save_frame(frame: CapturedFrame, output: Path, number: int) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"frame_{number:04d}"
    image = Image.frombytes("RGB", (64, 32), frame.pixels)
    image.save(path.with_suffix(".png"))
    image.resize((512, 256), Image.Resampling.NEAREST).save(path.with_name(path.name + "_8x.png"))
    matrix = [[frame.pixels[(y * 64 + x) * 3:(y * 64 + x + 1) * 3].hex() for x in range(64)] for y in range(32)]
    path.with_suffix(".matrix.txt").write_text("\n".join(" ".join(row) for row in matrix) + "\n", encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps({**frame.metadata, "matrix": matrix}, indent=2), encoding="utf-8")
    return path.with_suffix(".png")


def save_gallery(paths: list[Path], output: Path) -> None:
    if not paths:
        return
    paths = paths[-12:]
    columns = min(3, len(paths))
    gallery = Image.new("RGB", (columns * 400, ((len(paths) + columns - 1) // columns) * 220), "#151515")
    draw = ImageDraw.Draw(gallery)
    for index, path in enumerate(paths):
        x, y = (index % columns) * 400, (index // columns) * 220
        metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        pane = metadata["pane"]
        draw.text((x + 8, y + 4), f'{pane["kind"]} / {pane["item_id"]} / page {pane["index"] + 1}', fill="white")
        with Image.open(path) as image:
            gallery.paste(image.resize((384, 192), Image.Resampling.NEAREST), (x + 8, y + 23))
    gallery.save(output / "gallery.png")


def collect(port: str, duration: float, output: Path, stats_every: float, capture_every: float) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    receiver = FrameReceiver()
    visits: dict[tuple[int, int], dict] = {}
    frames: list[Path] = []
    samples: list[dict] = []
    errors: list[str] = []
    boot = 0
    sample_starts: dict[int, int] = {}
    last_uptime = 0
    pending_until = 0.0
    next_stats = next_capture = 0.0
    incoming = bytearray()
    for attempt in range(50):
        try:
            connection = serial.Serial(port, 115200, timeout=0.1, write_timeout=2)
            break
        except serial.SerialException:
            if attempt == 49:
                raise
            time.sleep(0.2)
    started = time.monotonic()
    with connection, \
         (output / "stats.jsonl").open("w", encoding="utf-8") as stats_file, \
         (output / "serial.log").open("w", encoding="utf-8") as serial_file:
        while time.monotonic() - started < duration:
            now = time.monotonic()
            if now >= next_stats:
                connection.write(b"STATS\n")
                next_stats = now + stats_every
            if now >= next_capture and now >= pending_until:
                connection.write(b"CAPTURE\n")
                next_capture = now + capture_every
                pending_until = now + 31
            incoming.extend(connection.read(min(4096, connection.in_waiting or 1)))
            while b"\n" in incoming:
                raw, _, remaining = incoming.partition(b"\n")
                incoming = bytearray(remaining)
                line = raw.decode("utf-8", errors="replace").strip()
                marker = line.find("MINI_")
                if marker >= 0:
                    line = line[marker:]
                if "PIN:" not in line and "token" not in line.lower() and "password" not in line.lower():
                    serial_file.write(line + "\n")
                try:
                    if line.startswith("MINI_STATS:"):
                        record = json.loads(line.partition(":")[2])
                        stats_file.write(json.dumps(record) + "\n")
                        display = record["display"]
                        if display["uptime_us"] < last_uptime:
                            boot += 1
                        last_uptime = display["uptime_us"]
                        first_sample_us = sample_starts.setdefault(boot, last_uptime)
                        samples.append(record)
                        for visit in display["visits"]:
                            if visit["ended_us"] >= first_sample_us:
                                visits[(boot, visit["visit"])] = {"boot": boot, **visit}
                    elif line.startswith(("MINI_FRAME_", "MINI_PIX:")):
                        frame = receiver.accept(line)
                        if frame is not None:
                            frames.append(save_frame(frame, output / "frames", len(frames) + 1))
                            pending_until = 0
                    elif line.startswith("MINI_ERROR:"):
                        errors.append(line)
                        pending_until = 0
                except (ValueError, KeyError) as error:
                    errors.append(str(error))
                    receiver = FrameReceiver()
                    pending_until = 0
            if len(incoming) > 65536:
                raise ValueError("serial line exceeds the diagnostic input limit")
    timed = [visit["shown_us"] / 1000 for visit in visits.values() if visit["target_ms"] > 0]
    with (output / "visits.csv").open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["boot", "visit", "kind", "item_id", "index", "count", "target_ms", "shown_ms", "difference_ms"])
        writer.writeheader()
        for visit in visits.values():
            row = {key: visit[key] for key in writer.fieldnames if key in visit}
            row["shown_ms"] = visit["shown_us"] / 1000
            row["difference_ms"] = row["shown_ms"] - visit["target_ms"] if visit["target_ms"] else ""
            writer.writerow(row)
    summary = {"duration_s": time.monotonic() - started, "frames": len(frames), "stats_samples": len(samples),
               "completed_visits": len(visits), "timed_visits": len(timed), "errors": errors,
               "dwell_min_ms": min(timed) if timed else None, "dwell_mean_ms": statistics.mean(timed) if timed else None,
               "dwell_max_ms": max(timed) if timed else None, "last_stats": samples[-1] if samples else None}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    save_gallery(frames, output)
    if not frames or not samples:
        raise RuntimeError("Mini returned no complete frames or timing samples")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--stats-every", type=float, default=2)
    parser.add_argument("--capture-every", type=float, default=3)
    parser.add_argument("--output", type=Path, default=Path("previews/mini-diagnostics"))
    args = parser.parse_args()
    if min(args.duration, args.stats_every, args.capture_every) <= 0:
        parser.error("duration and sample intervals must be positive")
    port = args.port or next((port.device for port in list_ports.comports() if (port.vid, port.pid) == (0x239A, 0x8125)), None)
    if port is None:
        parser.error("Mini USB runtime port is unavailable")
    summary = collect(port, args.duration, args.output, args.stats_every, args.capture_every)
    print(json.dumps({key: value for key, value in summary.items() if key != "last_stats"}, indent=2))


if __name__ == "__main__":
    main()
