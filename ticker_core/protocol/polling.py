"""Provide deterministic retry timing for backend polls."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PollBackoff:
    """Track polling failures without owning a thread or a clock."""

    failures: int = 0
    initial_seconds: float = 1.0
    maximum_seconds: float = 30.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.failures < 0:
            raise ValueError("failures must not be negative")
        if self.initial_seconds <= 0 or self.maximum_seconds <= 0:
            raise ValueError("backoff durations must be positive")
        if self.maximum_seconds < self.initial_seconds:
            raise ValueError("maximum_seconds must cover initial_seconds")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least one")

    @property
    def delay_seconds(self) -> float:
        """Return the delay for the recorded failure count."""

        if self.failures == 0:
            return 0.0
        return min(self.maximum_seconds, self.initial_seconds * self.multiplier ** (self.failures - 1))

    def after_failure(self) -> "PollBackoff":
        """Return the state after one failed poll."""

        return PollBackoff(self.failures + 1, self.initial_seconds, self.maximum_seconds, self.multiplier)

    def after_success(self) -> "PollBackoff":
        """Return the reset state after one successful poll."""

        return PollBackoff(0, self.initial_seconds, self.maximum_seconds, self.multiplier)
