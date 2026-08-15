"""Collect low-overhead Pi performance history."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
try:
    import resource
except ImportError:  # pragma: no cover - Windows does not provide resource.
    resource = None  # type: ignore[assignment]
from threading import Event, Thread
import time
from typing import Any, TypeAlias


_QueuedRecord: TypeAlias = dict[str, Any] | tuple["_Window", int] | None


class TickerPiLogger:
    """Aggregate ticker health in memory and write bounded JSONL history off-loop."""

    def __init__(
        self,
        directory: Path | str,
        *,
        window_seconds: float = 10.0,
        max_file_bytes: int = 10 * 1024 * 1024,
        max_files: int = 5,
        system_snapshot: Callable[[], object] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("The performance window must be positive.")
        if max_file_bytes <= 0:
            raise ValueError("The performance log size must be positive.")
        if max_files <= 0:
            raise ValueError("The performance log count must be positive.")
        self._directory = Path(directory)
        self._window_seconds = window_seconds
        self._max_file_bytes = max_file_bytes
        self._max_files = max_files
        self._system_snapshot = system_snapshot
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._records: queue.Queue[_QueuedRecord] = queue.Queue(maxsize=32)
        self._stop = Event()
        self._worker: Thread | None = None
        self._started = False
        self._window: _Window | None = None
        self._previous_frame_started: float | None = None
        self._dropped_records = 0
        self._previous_process_time = time.process_time()
        self._previous_system_time = time.monotonic()

    def start(self) -> None:
        """Start the background writer after the ticker owns the logger."""
        if self._started:
            return
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        self._stop.clear()
        self._started = True
        self._worker = Thread(target=self._write_loop, name="ticker-performance-log", daemon=True)
        self._worker.start()

    def close(self) -> None:
        """Flush the active window and stop the background writer."""
        if not self._started:
            return
        self._flush_window(force=True)
        self._stop.set()
        self._enqueue(None)
        if self._worker is not None:
            self._worker.join(timeout=3.0)
        self._worker = None
        self._started = False

    def record_frame(
        self,
        *,
        started_at: float,
        present_started_at: float,
        finished_at: float,
        interval: float,
        kind: object,
        mode: str,
        brightness: int,
        inverted: bool,
        stale: bool,
        connection_lost: bool,
        wall_time: datetime,
        width: int,
        height: int,
    ) -> None:
        """Record one frame without performing disk, JSON, or system work."""
        if not self._started:
            return
        if self._window is None:
            self._window = _Window(self._monotonic(), wall_time)
        total_ms = max(0.0, (finished_at - started_at) * 1000.0)
        work_ms = max(0.0, (present_started_at - started_at) * 1000.0)
        present_ms = max(0.0, (finished_at - present_started_at) * 1000.0)
        interval_ms = None
        if self._previous_frame_started is not None:
            interval_ms = max(0.0, (started_at - self._previous_frame_started) * 1000.0)
        self._previous_frame_started = started_at
        self._window.add_frame(
            total_ms=total_ms,
            work_ms=work_ms,
            present_ms=present_ms,
            interval_ms=interval_ms,
            scheduled_ms=max(0.0, interval * 1000.0),
            kind=str(kind),
            mode=mode,
            brightness=brightness,
            inverted=inverted,
            stale=stale,
            connection_lost=connection_lost,
            width=width,
            height=height,
            finished_at=finished_at,
            wall_time=wall_time,
        )
        if finished_at - self._window.started_at >= self._window_seconds:
            self._flush_window()

    def record_poll(
        self,
        *,
        success: bool,
        elapsed_ms: float,
        response_bytes: int | None = None,
        error: BaseException | None = None,
        retry_in: float | None = None,
    ) -> None:
        """Record one backend poll as an asynchronous event."""
        if not self._started:
            return
        record: dict[str, Any] = {
            "schema": 1,
            "kind": "poll",
            "at": self._timestamp(),
            "success": success,
            "elapsed_ms": round(max(0.0, elapsed_ms), 3),
        }
        if response_bytes is not None:
            record["response_bytes"] = max(0, int(response_bytes))
        if retry_in is not None:
            record["retry_in_s"] = round(max(0.0, retry_in), 3)
        if error is not None:
            record["error_type"] = type(error).__name__
            record["error"] = _error_text(error)
        self._enqueue(record)

    def record_payload(self, response: object) -> None:
        """Record bounded facts from one accepted backend payload."""
        if not self._started:
            return
        settings = getattr(response, "settings", None)
        content = getattr(response, "content", ())
        alerts = getattr(response, "alerts", ())
        news = getattr(response, "news", ())
        record = {
            "schema": 1,
            "kind": "payload",
            "at": self._timestamp(),
            "payload_key": str(getattr(response, "payload_key", ""))[:16],
            "mode": str(getattr(settings, "mode", "")),
            "brightness": _number(getattr(settings, "brightness", None)),
            "content_count": _length(content),
            "alert_count": _length(alerts),
            "news_count": _length(news),
        }
        self._enqueue(record)

    def record_issue(self, source: str, error: BaseException | str, **details: Any) -> None:
        """Record one actionable issue without blocking the ticker loop."""
        if not self._started:
            return
        record: dict[str, Any] = {
            "schema": 1,
            "kind": "issue",
            "at": self._timestamp(),
            "source": source,
        }
        if isinstance(error, BaseException):
            record["error_type"] = type(error).__name__
            record["error"] = _error_text(error)
        else:
            record["error"] = str(error)[:500]
        for key, value in details.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[key] = value
        self._enqueue(record)

    def _flush_window(self, *, force: bool = False) -> None:
        window = self._window
        if window is None or not window.frames:
            return
        if not force and self._monotonic() - window.started_at < self._window_seconds:
            return
        self._window = None
        queued = (window, self._dropped_records)
        self._dropped_records = 0
        self._enqueue(queued)

    def _enqueue(self, record: _QueuedRecord) -> None:
        try:
            self._records.put_nowait(record)
        except queue.Full:
            if record is not None:
                self._dropped_records += 1

    def _timestamp(self) -> str:
        return self._wall_clock().astimezone(timezone.utc).isoformat()

    def _write_loop(self) -> None:
        while not self._stop.is_set() or not self._records.empty():
            try:
                record = self._records.get(timeout=0.25)
            except queue.Empty:
                continue
            if record is None:
                continue
            if isinstance(record, tuple):
                window, dropped_records = record
                finished_at = time.monotonic()
                process_time = time.process_time()
                cpu_percent = round(
                    max(0.0, process_time - self._previous_process_time)
                    / max(0.001, finished_at - self._previous_system_time)
                    * 100.0,
                    3,
                )
                self._previous_process_time = process_time
                self._previous_system_time = finished_at
                record = window.finish(
                    self._system_snapshot,
                    dropped_records,
                    cpu_percent,
                )
            try:
                self._write_record(record)
            except (OSError, TypeError, ValueError):
                continue

    def _write_record(self, record: Mapping[str, Any]) -> None:
        path = self._directory / "ticker-performance.jsonl"
        encoded = (json.dumps(record, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        if path.exists() and path.stat().st_size + len(encoded) > self._max_file_bytes:
            self._rotate(path)
        with path.open("ab") as stream:
            stream.write(encoded)

    def _rotate(self, path: Path) -> None:
        if self._max_files == 1:
            path.unlink(missing_ok=True)
            return
        oldest = self._directory / f"{path.name}.{self._max_files - 1}"
        if oldest.exists():
            oldest.unlink()
        for index in range(self._max_files - 2, 0, -1):
            source = self._directory / f"{path.name}.{index}"
            target = self._directory / f"{path.name}.{index + 1}"
            if source.exists():
                source.replace(target)
        if path.exists():
            path.replace(self._directory / f"{path.name}.1")


class _Window:
    """Hold fixed-size aggregate state for one history window."""

    __slots__ = (
        "started_at", "wall_started", "frames", "total_ms", "work_ms", "present_ms",
        "interval_ms", "scheduled_ms", "brightness_total", "brightness_min", "brightness_max",
        "kinds", "modes", "inverted", "stale", "connection_lost", "overruns", "samples",
        "width", "height", "ended_at", "wall_ended",
    )

    def __init__(self, started_at: float, wall_started: datetime) -> None:
        self.started_at = started_at
        self.wall_started = wall_started
        self.frames = 0
        self.total_ms = _Metric()
        self.work_ms = _Metric()
        self.present_ms = _Metric()
        self.interval_ms = _Metric()
        self.scheduled_ms = _Metric()
        self.brightness_total = 0
        self.brightness_min = 101
        self.brightness_max = -1
        self.kinds: Counter[str] = Counter()
        self.modes: Counter[str] = Counter()
        self.inverted = 0
        self.stale = 0
        self.connection_lost = 0
        self.overruns = 0
        self.samples: list[float] = []
        self.width = 0
        self.height = 0
        self.ended_at = started_at
        self.wall_ended = wall_started

    def add_frame(
        self,
        *,
        total_ms: float,
        work_ms: float,
        present_ms: float,
        interval_ms: float | None,
        scheduled_ms: float,
        kind: str,
        mode: str,
        brightness: int,
        inverted: bool,
        stale: bool,
        connection_lost: bool,
        width: int,
        height: int,
        finished_at: float,
        wall_time: datetime,
    ) -> None:
        self.frames += 1
        self.total_ms.add(total_ms)
        self.work_ms.add(work_ms)
        self.present_ms.add(present_ms)
        self.scheduled_ms.add(scheduled_ms)
        if interval_ms is not None:
            self.interval_ms.add(interval_ms)
        if len(self.samples) < 512:
            self.samples.append(total_ms)
        self.brightness_total += brightness
        self.brightness_min = min(self.brightness_min, brightness)
        self.brightness_max = max(self.brightness_max, brightness)
        self.kinds[kind] += 1
        self.modes[mode] += 1
        self.inverted += int(inverted)
        self.stale += int(stale)
        self.connection_lost += int(connection_lost)
        self.overruns += int(total_ms > scheduled_ms > 0)
        self.width = width
        self.height = height
        self.ended_at = finished_at
        self.wall_ended = wall_time

    def finish(
        self,
        system_snapshot: Callable[[], object] | None,
        dropped_records: int,
        cpu_percent: float,
    ) -> dict[str, Any]:
        duration_s = max(0.001, self.ended_at - self.started_at)
        record: dict[str, Any] = {
            "schema": 1,
            "kind": "window",
            "started_at": self.wall_started.astimezone(timezone.utc).isoformat(),
            "finished_at": self.wall_ended.astimezone(timezone.utc).isoformat(),
            "duration_s": round(duration_s, 3),
            "panel": {"width": self.width, "height": self.height},
            "frames": self.frames,
            "fps": round(self.frames / duration_s, 3),
            "frame_ms": self.total_ms.summary(self.samples),
            "work_ms": self.work_ms.summary(),
            "present_ms": self.present_ms.summary(),
            "interval_ms": self.interval_ms.summary(),
            "scheduled_ms": self.scheduled_ms.summary(),
            "brightness": {
                "min": self.brightness_min if self.frames else None,
                "max": self.brightness_max if self.frames else None,
                "avg": round(self.brightness_total / self.frames, 3) if self.frames else None,
            },
            "kinds": dict(self.kinds),
            "modes": dict(self.modes),
            "flags": {
                "inverted_frames": self.inverted,
                "stale_frames": self.stale,
                "connection_lost_frames": self.connection_lost,
                "overruns": self.overruns,
                "dropped_records": dropped_records,
            },
        }
        if system_snapshot is not None:
            try:
                record["system"] = _system_record(system_snapshot(), cpu_percent)
            except Exception as error:
                record["system_error"] = type(error).__name__
        else:
            record["system"] = _system_record(None, cpu_percent)
        return record


class _Metric:
    __slots__ = ("count", "total", "minimum", "maximum")

    def __init__(self) -> None:
        self.count = 0
        self.total = 0.0
        self.minimum = math.inf
        self.maximum = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    def summary(self, samples: list[float] | None = None) -> dict[str, Any]:
        if not self.count:
            return {"count": 0}
        result: dict[str, Any] = {
            "count": self.count,
            "min": round(self.minimum, 3),
            "avg": round(self.total / self.count, 3),
            "max": round(self.maximum, 3),
        }
        if samples:
            ordered = sorted(samples)
            result["p50"] = round(_percentile(ordered, 0.50), 3)
            result["p95"] = round(_percentile(ordered, 0.95), 3)
            result["p99"] = round(_percentile(ordered, 0.99), 3)
        return result


def _percentile(values: list[float], fraction: float) -> float:
    index = min(len(values) - 1, max(0, math.ceil(fraction * len(values)) - 1))
    return values[index]


def _system_record(snapshot: object, cpu_percent: float) -> dict[str, Any]:
    record: dict[str, Any] = {
        "cpu_percent": cpu_percent,
        "rss_mb": _rss_mb(),
        "load_1m": _load_1m(),
    }
    temperature = getattr(snapshot, "temperature_c", None)
    if temperature is not None:
        record["temperature_c"] = temperature
    return record


def _rss_mb() -> float | None:
    if resource is None:
        return None
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024.0, 3)
    except (OSError, ValueError, IndexError):
        pass
    try:
        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return round(value / (1024.0 if os.name != "darwin" else 1024.0 * 1024.0), 3)
    except (AttributeError, OSError, ValueError):
        return None


def _load_1m() -> float | None:
    try:
        return round(os.getloadavg()[0], 3)
    except (AttributeError, OSError):
        return None


def _error_text(error: BaseException) -> str:
    text = str(error).strip()
    return text[:500] if text else type(error).__name__


def _length(value: object) -> int:
    try:
        return len(value)  # type: ignore[arg-type]
    except TypeError:
        return 0


def _number(value: object) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
