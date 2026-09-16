"""Apply the shared weekly schedule to ticker display settings."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timezone
import time
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import (
    DISPLAY_MODES,
    SCHEDULE_DAY_GROUPS,
    ContentItem,
    DisplaySettings,
    ScheduleBlock,
    ScheduleCondition,
)
from sports_ticker.fleet import TickerRepository

from .state_store import SnapshotStore


_LIVE_STATES = frozenset(("in", "half", "crit"))
_LIVE_GAME_FRESHNESS_SECONDS = 120.0
class ScheduleService:
    """Own shared schedule rules and effective mode selection."""

    def __init__(
        self,
        repository: TickerRepository,
        snapshots: SnapshotStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Capture durable rules, live snapshots, and one wall clock."""

        self._repository = repository
        self._snapshots = snapshots
        self._clock = clock

    def document(self) -> dict[str, object]:
        """Return the complete shared schedule document."""

        blocks = self._repository.list_schedule_blocks()
        grouped = {
            group: [block_to_mapping(block) for block in blocks if block.day_group == group]
            for group in SCHEDULE_DAY_GROUPS
        }
        return {
            "api_version": "v2",
            "timezone_policy": "ticker",
            "day_groups": list(SCHEDULE_DAY_GROUPS),
            "tickers": [
                {
                    "id": ticker.ticker_id,
                    "name": ticker.name,
                }
                for ticker in self._repository.list_tickers()
            ],
            "blocks": grouped,
            "conditions": [
                condition_to_mapping(condition)
                for condition in self._repository.list_schedule_conditions()
            ],
            "live_games": self.live_game_count(),
        }

    def create_block(
        self,
        *,
        day_group: str,
        start_minute: int,
        end_minute: int,
        mode: str,
        enabled: bool = True,
        block_id: str | None = None,
    ) -> ScheduleBlock:
        """Create one non-overlapping recurring time block."""

        now = self._clock()
        block = ScheduleBlock(
            id=block_id or f"schedule_{uuid4().hex}",
            day_group=day_group,
            start_minute=start_minute,
            end_minute=end_minute,
            mode=mode,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        self._validate_block_overlap(block)
        return self._repository.create_schedule_block(block)

    def update_block(self, block_id: str, **changes: object) -> ScheduleBlock:
        """Update one recurring time block after validating its new interval."""

        current = self._repository.get_schedule_block(block_id)
        if current is None:
            raise KeyError(str(block_id).strip())
        block = ScheduleBlock(
            id=current.id,
            day_group=changes.get("day_group", current.day_group),
            start_minute=changes.get("start_minute", current.start_minute),
            end_minute=changes.get("end_minute", current.end_minute),
            mode=changes.get("mode", current.mode),
            enabled=changes.get("enabled", current.enabled),
            created_at=current.created_at,
            updated_at=self._clock(),
        )
        self._validate_block_overlap(block)
        return self._repository.update_schedule_block(block)

    def delete_block(self, block_id: str) -> bool:
        """Delete one recurring time block."""

        return self._repository.delete_schedule_block(block_id)

    def create_condition(
        self,
        *,
        kind: str,
        threshold: int,
        mode: str,
        enabled: bool = True,
        condition_id: str | None = None,
    ) -> ScheduleCondition:
        """Create one recurring live-data condition."""

        now = self._clock()
        condition = ScheduleCondition(
            id=condition_id or f"condition_{uuid4().hex}",
            kind=kind,
            threshold=threshold,
            mode=mode,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        return self._repository.create_schedule_condition(condition)

    def update_condition(self, condition_id: str, **changes: object) -> ScheduleCondition:
        """Update one recurring live-data condition."""

        current = self._repository.get_schedule_condition(condition_id)
        if current is None:
            raise KeyError(str(condition_id).strip())
        condition = ScheduleCondition(
            id=current.id,
            kind=changes.get("kind", current.kind),
            threshold=changes.get("threshold", current.threshold),
            mode=changes.get("mode", current.mode),
            enabled=changes.get("enabled", current.enabled),
            created_at=current.created_at,
            updated_at=self._clock(),
        )
        return self._repository.update_schedule_condition(condition)

    def delete_condition(self, condition_id: str) -> bool:
        """Delete one recurring live-data condition."""

        return self._repository.delete_schedule_condition(condition_id)

    def schedule_override(self, ticker_id: str) -> bool:
        """Return whether the app owns the ticker mode over the schedule."""

        return self._repository.schedule_override_enabled(ticker_id)

    def set_schedule_override(self, ticker_id: str, enabled: bool) -> bool:
        """Set or clear one ticker's app-owned schedule override."""

        return self._repository.set_schedule_override(ticker_id, enabled, now=self._clock())

    def resolve(
        self,
        ticker_id: str,
        settings: DisplaySettings,
        *,
        allowed_modes: Iterable[str] = (),
        now: datetime | None = None,
    ) -> tuple[DisplaySettings, dict[str, object]]:
        """Return one ticker's effective settings and schedule status."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("schedule settings must be DisplaySettings")
        current = _utc_datetime(self._clock()) if now is None else _utc_datetime(now)
        local = _local_datetime(current, settings.timezone)
        live_games = self.live_game_count()
        condition = self._active_condition(live_games)
        block = self._active_block(local)
        override = self.schedule_override(ticker_id)
        supported = {
            str(mode).strip().lower()
            for mode in allowed_modes
            if str(mode).strip()
        }

        selected = condition or block
        selected_mode = None if selected is None else selected.mode
        supported_rule = selected_mode is not None and (
            not supported or selected_mode in supported
        )
        if override:
            effective = settings
            source = "app_override"
        elif supported_rule and selected_mode is not None:
            effective = _with_mode(settings, selected_mode)
            source = "condition" if condition is not None else "time"
        else:
            effective = settings
            source = "base"

        status: dict[str, object] = {
            "active": bool(supported_rule and selected is not None),
            "override": override,
            "source": source,
            "mode": effective.mode,
            "live_games": live_games,
            "timezone": settings.timezone or str(local.tzinfo),
            "local_day": local.strftime("%A").lower(),
            "day_group": _day_group(local),
            "local_time": local.strftime("%H:%M"),
            "rule_id": None if selected is None else selected.id,
            "scheduled_mode": selected_mode if supported_rule else None,
        }
        return effective, status

    def effective_settings(
        self,
        ticker_id: str,
        settings: DisplaySettings,
        *,
        allowed_modes: Iterable[str] = (),
        now: datetime | None = None,
    ) -> DisplaySettings:
        """Return one ticker's effective settings without its status payload."""

        effective, _ = self.resolve(
            ticker_id,
            settings,
            allowed_modes=allowed_modes,
            now=now,
        )
        return effective

    def status(
        self,
        ticker_id: str,
        settings: DisplaySettings,
        *,
        allowed_modes: Iterable[str] = (),
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Return one ticker's current schedule status."""

        _, status = self.resolve(
            ticker_id,
            settings,
            allowed_modes=allowed_modes,
            now=now,
        )
        return status

    def live_game_count(self) -> int:
        """Count fresh live games once across every ticker snapshot."""

        now = _utc_datetime(self._clock())
        identifiers: set[str] = set()
        for snapshot in self._snapshots.list_snapshots():
            observed_at = _utc_datetime(snapshot.observed_at)
            age = (now - observed_at).total_seconds()
            if age > _LIVE_GAME_FRESHNESS_SECONDS:
                continue
            for item in snapshot.content:
                if _is_live_game(item):
                    identifiers.add(item.id)
        return len(identifiers)

    def _active_block(self, local: datetime) -> ScheduleBlock | None:
        group = _day_group(local)
        minute = local.hour * 60 + local.minute
        candidates = [
            block
            for block in self._repository.list_schedule_blocks()
            if block.enabled
            and block.day_group == group
            and block.start_minute <= minute < block.end_minute
        ]
        return max(candidates, key=lambda block: (block.updated_at, block.id), default=None)

    def _active_condition(self, live_games: int) -> ScheduleCondition | None:
        candidates = [
            condition
            for condition in self._repository.list_schedule_conditions()
            if condition.enabled and condition.kind == "live_games" and live_games >= condition.threshold
        ]
        return max(
            candidates,
            key=lambda condition: (condition.threshold, condition.updated_at, condition.id),
            default=None,
        )

    def _validate_block_overlap(self, block: ScheduleBlock) -> None:
        """Reject conflicting enabled blocks in one recurring day group."""

        for existing in self._repository.list_schedule_blocks():
            if existing.id == block.id or not existing.enabled or not block.enabled:
                continue
            if existing.day_group != block.day_group:
                continue
            if max(existing.start_minute, block.start_minute) < min(existing.end_minute, block.end_minute):
                raise ValueError("enabled schedule blocks cannot overlap")


def block_to_mapping(block: ScheduleBlock) -> dict[str, object]:
    """Project one schedule block for the JSON API."""

    return {
        "id": block.id,
        "day_group": block.day_group,
        "start_minute": block.start_minute,
        "end_minute": block.end_minute,
        "mode": block.mode,
        "enabled": block.enabled,
        "created_at": block.created_at,
        "updated_at": block.updated_at,
    }


def condition_to_mapping(condition: ScheduleCondition) -> dict[str, object]:
    """Project one schedule condition for the JSON API."""

    return {
        "id": condition.id,
        "kind": condition.kind,
        "threshold": condition.threshold,
        "mode": condition.mode,
        "enabled": condition.enabled,
        "created_at": condition.created_at,
        "updated_at": condition.updated_at,
    }


def _with_mode(settings: DisplaySettings, mode: str) -> DisplaySettings:
    """Change only the mode while clearing incompatible sports pin state."""

    if mode == settings.mode:
        return settings
    if mode == "sports":
        return replace(settings, mode=mode)
    return replace(settings, mode=mode, sports_presentation="rotation", pinned_content_id="")


def _is_live_game(item: ContentItem) -> bool:
    """Return whether one canonical item represents a live game."""

    return item.family == "sports" and str(item.data.get("state") or "").strip().lower() in _LIVE_STATES


def _day_group(local: datetime) -> str:
    """Return the recurring schedule lane for one local datetime."""

    return "weekdays" if local.weekday() < 5 else "weekends"


def _utc_datetime(value: float | datetime) -> datetime:
    """Normalize one clock value into an aware UTC datetime."""

    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_datetime(now: datetime, timezone_name: str) -> datetime:
    """Convert UTC time into the ticker's configured timezone."""

    name = str(timezone_name).strip()
    if name:
        try:
            return now.astimezone(ZoneInfo(name))
        except ZoneInfoNotFoundError:
            pass
    return now.astimezone()


__all__ = [
    "ScheduleService",
    "block_to_mapping",
    "condition_to_mapping",
]
