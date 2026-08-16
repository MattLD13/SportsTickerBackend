import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ticker_core.platform import TickerPiLogger


def test_pi_logger_writes_frame_history_and_events_off_loop(tmp_path) -> None:
    logger = TickerPiLogger(
        tmp_path,
        window_seconds=60,
        system_snapshot=lambda: SimpleNamespace(temperature_c=43.2),
    )
    wall = datetime(2026, 8, 15, tzinfo=timezone.utc)
    logger.start()
    logger.record_frame(
        started_at=1.0,
        present_started_at=1.002,
        finished_at=1.006,
        interval=1 / 30,
        kind="scroll",
        mode="sports",
        brightness=75,
        inverted=True,
        stale=True,
        connection_lost=True,
        wall_time=wall,
        width=384,
        height=32,
    )
    logger.record_frame(
        started_at=1.03,
        present_started_at=1.032,
        finished_at=1.038,
        interval=1 / 30,
        kind="static",
        mode="sports",
        brightness=85,
        inverted=False,
        stale=False,
        connection_lost=False,
        wall_time=wall + timedelta(seconds=1),
        width=384,
        height=32,
    )
    logger.record_poll(success=False, elapsed_ms=502.5, error=TimeoutError("backend timeout"), retry_in=1.0)
    logger.record_issue("frame", RuntimeError("render failed"), mode="sports")
    logger.close()

    path = tmp_path / "ticker-performance.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    window = next(record for record in records if record["kind"] == "window")
    poll = next(record for record in records if record["kind"] == "poll")
    issue = next(record for record in records if record["kind"] == "issue")

    assert window["panel"] == {"height": 32, "width": 384}
    assert window["frames"] == 2
    assert window["frame_ms"]["p95"] == 8.0
    assert window["brightness"] == {"avg": 80.0, "max": 85, "min": 75}
    assert window["flags"]["inverted_frames"] == 1
    assert window["flags"]["stale_frames"] == 1
    assert window["flags"]["connection_lost_frames"] == 1
    assert window["system"]["temperature_c"] == 43.2
    assert poll["success"] is False
    assert poll["error_type"] == "TimeoutError"
    assert issue["source"] == "frame"


def test_pi_logger_rotates_bounded_files(tmp_path) -> None:
    logger = TickerPiLogger(tmp_path, window_seconds=60, max_file_bytes=100, max_files=3)
    logger.start()
    for index in range(4):
        logger.record_issue("test", "x" * 100, index=index)
    logger.close()

    files = list(tmp_path.glob("ticker-performance.jsonl*"))
    assert len(files) <= 3


def test_pi_logger_records_idle_ticks_and_viewport_age(tmp_path) -> None:
    clock = [10.0]
    logger = TickerPiLogger(tmp_path, window_seconds=60, monotonic=lambda: clock[0])
    wall = datetime(2026, 8, 15, tzinfo=timezone.utc)
    logger.start()
    logger.record_tick(
        interval=1 / 30,
        kind="static",
        mode="sports",
        wall_time=wall,
        presented=False,
        last_present_age=4.25,
        viewport={"desired": 2, "pending": 0, "ready": 2, "committed_generation": 3},
    )
    logger.close()

    path = tmp_path / "ticker-performance.jsonl"
    window = next(record for record in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()) if record["kind"] == "window")
    assert window["frames"] == 0
    assert window["loop_ticks"] == 1
    assert window["skipped_ticks"] == 1
    assert window["fps"] == 0.0
    assert window["last_present_age_s"] == 4.25
    assert window["viewport"]["committed_generation"] == 3
