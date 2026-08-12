from ticker_core.protocol import PollBackoff, TelemetrySnapshot, build_poll_headers


def test_backoff_is_deterministic_and_resets_after_contact() -> None:
    backoff = PollBackoff(initial_seconds=1, maximum_seconds=5, multiplier=2)

    assert backoff.delay_seconds == 0
    assert backoff.after_failure().delay_seconds == 1
    assert backoff.after_failure().after_failure().delay_seconds == 2
    assert backoff.after_failure().after_failure().after_failure().delay_seconds == 4
    assert backoff.after_failure().after_failure().after_failure().after_failure().delay_seconds == 5
    assert backoff.after_failure().after_success().failures == 0


def test_telemetry_headers_keep_the_deployed_names() -> None:
    headers = build_poll_headers(TelemetrySnapshot(42, "r1+abc", "3.13.0", 51.2))

    assert headers == {
        "X-Ticker-Uptime": "42",
        "X-Ticker-Build": "r1+abc",
        "X-Ticker-Python": "3.13.0",
        "X-Ticker-Temp": "51.2",
    }
