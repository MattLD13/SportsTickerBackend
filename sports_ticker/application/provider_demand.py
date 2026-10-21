"""Decide specialty-provider demand from fleet presence and schedule ownership."""

from __future__ import annotations

from datetime import datetime

from sports_ticker.domain import DisplaySettings
from sports_ticker.fleet import TickerRepository
from .schedule import ScheduleService


class ProviderDemand:
    """Prefetch scheduled specialty modes for devices seen within ninety seconds."""

    def __init__(self, repository: TickerRepository, schedules: ScheduleService, *, horizon_seconds: float = 600) -> None:
        self.repository = repository
        self.schedules = schedules
        self.horizon_seconds = horizon_seconds

    def __call__(self, provider: str, ticker_id: str, settings: DisplaySettings, now: datetime) -> bool:
        if provider not in {"golf", "stock", "flights"}:
            return True
        ticker = self.repository.get_ticker(ticker_id)
        if ticker is None:
            return False
        app_override = self.schedules.schedule_override(ticker_id)
        if not app_override and (
            ticker.device.last_seen_at is None
            or now.timestamp() - ticker.device.last_seen_at > 90
        ):
            return False
        modes = self.schedules.modes_within(ticker_id, ticker.display_settings, now=now,
                                          horizon_seconds=self.horizon_seconds,
                                          allowed_modes=ticker.profile.capabilities.modes)
        if provider == "golf":
            return "sports" in modes and settings.active_sports.get("golf", True)
        if provider == "flights":
            return bool(modes & {"flights", "airports"})
        return "stock" in modes
