"""Check live smoke telemetry when a display window receives no stream message."""

from tools.live_ticker_hardware_smoke import _baseline, _post_records


def test_idle_windows_preserve_the_last_known_stream_sequence():
    records = [
        {"kind": "window", "stream": {"last_sequence": 12}},
        {
            "kind": "window", "stream": {"last_sequence": None},
            "finished_at": "2026-10-15T02:00:00+00:00",
            "panel": {"width": 384, "height": 32}, "frames": 333,
        },
    ]
    assert _baseline(records) == (12, 0)
    payload_seen, advanced, sequence, screen = _post_records(
        records, started_at=0, baseline_news=0, baseline_sequence=12,
    )
    assert not payload_seen and not advanced
    assert sequence == 12
    assert screen is not None and screen["frames"] == 333
