from ticker_core.protocol import PollBackoff


def test_backoff_is_deterministic_and_resets_after_contact() -> None:
    backoff = PollBackoff(initial_seconds=1, maximum_seconds=5, multiplier=2)

    assert backoff.delay_seconds == 0
    assert backoff.after_failure().delay_seconds == 1
    assert backoff.after_failure().after_failure().delay_seconds == 2
    assert backoff.after_failure().after_failure().after_failure().delay_seconds == 4
    assert backoff.after_failure().after_failure().after_failure().after_failure().delay_seconds == 5
    assert backoff.after_failure().after_success().failures == 0
