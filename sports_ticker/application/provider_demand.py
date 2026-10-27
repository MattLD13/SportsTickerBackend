"""Decide specialty-provider demand from each ticker's effective schedule."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import TickerRepository
from .schedule import ScheduleService


class ProviderDemand:
    """Prefetch scheduled specialty modes for every configured ticker."""

    def __init__(self, repository: TickerRepository, schedules: ScheduleService, *, horizon_seconds: float = 600) -> None:
        self.repository = repository
        self.schedules = schedules
        self.horizon_seconds = horizon_seconds

    def __call__(
        self,
        providers: tuple[str, ...],
        settings_by_ticker: Mapping[str, DisplaySettings],
        now: datetime,
    ) -> dict[str, frozenset[str]]:
        """Resolve each ticker's horizon once for one complete scheduler pass."""
        specialty = {"golf", "stock", "flights"}.intersection(providers)
        active = {
            name: set() if name in specialty else set(settings_by_ticker)
            for name in providers
        }
        if specialty:
            for ticker_id, settings in settings_by_ticker.items():
                ticker = self.repository.get_ticker(ticker_id)
                if ticker is None:
                    continue
                modes = self.schedules.modes_within(
                    ticker_id, ticker.display_settings, now=now,
                    horizon_seconds=self.horizon_seconds,
                    allowed_modes=ticker.profile.capabilities.modes,
                )
                if "golf" in specialty and "sports" in modes and settings.active_sports.get("golf", True):
                    active["golf"].add(ticker_id)
                if "flights" in specialty and modes & {"flights", "airports"}:
                    active["flights"].add(ticker_id)
                if "stock" in specialty and "stock" in modes:
                    active["stock"].add(ticker_id)
        return {name: frozenset(tickers) for name, tickers in active.items()}
