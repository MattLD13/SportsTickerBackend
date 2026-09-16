"""Apply one ticker's recurring weekly schedule to its display settings."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import time as time_module
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sports_ticker.domain import (
    ContentItem,
    DisplaySettings,
    ScheduleBlock,
    ScheduleCondition,
    SCHEDULE_DAY_NAMES,
)
from sports_ticker.fleet import TickerRepository

from .state_store import SnapshotStore


_LIVE_STATES = frozenset(("in", "half", "crit"))
_LIVE_GAME_FRESHNESS_SECONDS = 120.0


class ScheduleService:
    """Own ticker schedules, temporary overrides, condition precedence, and effective settings."""

    def __init__(
        self,
        repository: TickerRepository,
        snapshots: SnapshotStore,
        *,
        clock: Callable[[], float] = time_module.time,
    ) -> None:
        """Capture durable rules, live snapshots, and one wall clock for deterministic evaluation."""

        self._repository = repository
        self._snapshots = snapshots
        self._clock = clock

    def document(
        self,
        ticker_id: str,
        settings: DisplaySettings,
        *,
        allowed_modes: Iterable[str] = (),
    ) -> dict[str, object]:
        """Return one ticker's recurring rules, calendar lanes, conditions, and effective state."""

        identifier = str(ticker_id).strip()
        blocks = self._repository.list_ticker_schedule_blocks(identifier)
        conditions = self._repository.list_ticker_schedule_conditions(identifier)
        block_values = [block_to_mapping(block) for block in blocks]
        return {
            "api_version": "v2",
            "ticker_id": identifier,
            "timezone": settings.timezone,
            "days": [
                {
                    "day_of_week": day,
                    "name": SCHEDULE_DAY_NAMES[day],
                    "blocks": [
                        value for value in block_values if day in value["days_of_week"]
                    ],
                }
                for day in range(7)
            ],
            "blocks": block_values,
            "conditions": [condition_to_mapping(condition) for condition in conditions],
            "live_games": self.live_game_count(),
            "effective": self.status(
                identifier,
                settings,
                allowed_modes=allowed_modes,
            ),
        }

    def create_block(
        self,
        ticker_id: str,
        *,
        days_of_week: Iterable[object],
        start_minute: int,
        end_minute: int,
        mode: str,
        sports_filter: str | None = None,
        enabled: bool = True,
        block_id: str | None = None,
    ) -> ScheduleBlock:
        """Create one enabled weekly block after rejecting overlapping intervals for shared days."""

        identifier = self._require_ticker(ticker_id)
        now = self._clock()
        block = ScheduleBlock(
            id=block_id or f"schedule_{uuid4().hex}",
            ticker_id=identifier,
            days_of_week=tuple(days_of_week),
            start_minute=start_minute,
            end_minute=end_minute,
            mode=mode,
            sports_filter=sports_filter,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        self._validate_block_overlap(block)
        return self._repository.create_ticker_schedule_block(block)

    def update_block(self, ticker_id: str, block_id: str, **changes: object) -> ScheduleBlock:
        """Update one ticker-owned weekly block while preserving immutable ownership and creation time."""

        identifier = self._require_ticker(ticker_id)
        current = self._repository.get_ticker_schedule_block(identifier, block_id)
        if current is None:
            raise KeyError(str(block_id).strip())
        next_mode = changes.get("mode", current.mode)
        next_filter = changes.get("sports_filter", current.sports_filter)
        if str(next_mode).strip().lower() != "sports":
            next_filter = None
        block = ScheduleBlock(
            id=current.id,
            ticker_id=identifier,
            days_of_week=changes.get("days_of_week", current.days_of_week),
            start_minute=changes.get("start_minute", current.start_minute),
            end_minute=changes.get("end_minute", current.end_minute),
            mode=next_mode,
            sports_filter=next_filter,
            enabled=changes.get("enabled", current.enabled),
            created_at=current.created_at,
            updated_at=self._clock(),
        )
        self._validate_block_overlap(block)
        return self._repository.update_ticker_schedule_block(block)

    def delete_block(self, ticker_id: str, block_id: str) -> bool:
        """Delete one ticker-owned weekly block."""

        identifier = self._require_ticker(ticker_id)
        return self._repository.delete_ticker_schedule_block(identifier, block_id)

    def create_condition(
        self,
        ticker_id: str,
        *,
        kind: str,
        threshold: int,
        operator: str = "gt",
        when_mode: str = "sports",
        action_sports_filter: str = "live",
        ignore_pinned: bool = True,
        enabled: bool = True,
        condition_id: str | None = None,
    ) -> ScheduleCondition:
        """Create one ticker-owned live-game condition for scheduled sports mode."""

        identifier = self._require_ticker(ticker_id)
        now = self._clock()
        condition = ScheduleCondition(
            id=condition_id or f"condition_{uuid4().hex}",
            ticker_id=identifier,
            kind=kind,
            threshold=threshold,
            operator=operator,
            when_mode=when_mode,
            action_sports_filter=action_sports_filter,
            ignore_pinned=ignore_pinned,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        return self._repository.create_ticker_schedule_condition(condition)

    def update_condition(
        self,
        ticker_id: str,
        condition_id: str,
        **changes: object,
    ) -> ScheduleCondition:
        """Update one ticker-owned live-game condition with validated domain values."""

        identifier = self._require_ticker(ticker_id)
        current = self._repository.get_ticker_schedule_condition(identifier, condition_id)
        if current is None:
            raise KeyError(str(condition_id).strip())
        condition = ScheduleCondition(
            id=current.id,
            ticker_id=identifier,
            kind=changes.get("kind", current.kind),
            threshold=changes.get("threshold", current.threshold),
            operator=changes.get("operator", current.operator),
            when_mode=changes.get("when_mode", current.when_mode),
            action_sports_filter=changes.get(
                "action_sports_filter",
                current.action_sports_filter,
            ),
            ignore_pinned=changes.get("ignore_pinned", current.ignore_pinned),
            enabled=changes.get("enabled", current.enabled),
            created_at=current.created_at,
            updated_at=self._clock(),
        )
        return self._repository.update_ticker_schedule_condition(condition)

    def delete_condition(self, ticker_id: str, condition_id: str) -> bool:
        """Delete one ticker-owned live-game condition."""

        identifier = self._require_ticker(ticker_id)
        return self._repository.delete_ticker_schedule_condition(identifier, condition_id)

    def schedule_override(self, ticker_id: str) -> bool:
        """Return whether one ticker has an unexpired app-owned schedule override."""

        return self._repository.schedule_override_enabled(
            ticker_id,
            now=float(self._clock()),
        )

    def schedule_override_expires_at(self, ticker_id: str) -> float | None:
        """Return one ticker's unexpired app override deadline."""

        return self._repository.schedule_override_expires_at(
            ticker_id,
            now=float(self._clock()),
        )

    def set_schedule_override(
        self,
        ticker_id: str,
        enabled: bool,
        *,
        settings: DisplaySettings,
    ) -> bool:
        """Set an override until the current schedule transition or clear it immediately."""

        identifier = self._require_ticker(ticker_id)
        now = float(self._clock())
        if not enabled:
            return self._repository.set_schedule_override(
                identifier,
                False,
                expires_at=None,
                now=now,
            )
        expiry = self._next_schedule_transition(identifier, settings, now)
        return self._repository.set_schedule_override(
            identifier,
            True,
            expires_at=expiry,
            now=now,
        )

    def resolve(
        self,
        ticker_id: str,
        settings: DisplaySettings,
        *,
        allowed_modes: Iterable[str] = (),
        now: datetime | None = None,
    ) -> tuple[DisplaySettings, dict[str, object]]:
        """Resolve one ticker's settings using override, time block, condition, and base precedence."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("schedule settings must be DisplaySettings")
        identifier = str(ticker_id).strip()
        current = _utc_datetime(self._clock()) if now is None else _utc_datetime(now)
        current_timestamp = current.timestamp()
        local = _local_datetime(current, settings.timezone)
        supported = {
            str(mode).strip().lower()
            for mode in allowed_modes
            if str(mode).strip()
        }
        block = self._active_block(identifier, local)
        block_supported = block is not None and (
            not supported or block.mode in supported
        )
        scheduled = _with_block(settings, block) if block_supported and block else settings
        live_games = self.live_game_count()
        condition = self._active_condition(identifier, live_games, scheduled)
        override_expires_at = self._repository.schedule_override_expires_at(
            identifier,
            now=current_timestamp,
        )
        override = override_expires_at is not None
        if override:
            effective = settings
            source = "app_override"
        elif condition is not None:
            effective = replace(scheduled, sports_filter=condition.action_sports_filter)
            source = "condition"
        elif block_supported and block is not None:
            effective = scheduled
            source = "time"
        else:
            effective = settings
            source = "base"

        status: dict[str, object] = {
            "active": source in {"time", "condition"},
            "override": override,
            "override_expires_at": override_expires_at,
            "source": source,
            "mode": effective.mode,
            "sports_filter": effective.sports_filter,
            "sports_presentation": effective.sports_presentation,
            "live_games": live_games,
            "timezone": settings.timezone or str(local.tzinfo),
            "local_day": SCHEDULE_DAY_NAMES[local.weekday()],
            "day_of_week": local.weekday(),
            "local_time": local.strftime("%H:%M"),
            "rule_id": None if block is None or not block_supported else block.id,
            "condition_id": None if condition is None else condition.id,
            "scheduled_mode": scheduled.mode if block_supported and block is not None else None,
            "scheduled_sports_filter": (
                scheduled.sports_filter if block_supported and block is not None else None
            ),
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
        """Return one ticker's effective display settings without status metadata."""

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
        """Return one ticker's effective schedule metadata without duplicating evaluation rules."""

        _, status = self.resolve(
            ticker_id,
            settings,
            allowed_modes=allowed_modes,
            now=now,
        )
        return status

    def live_game_count(self) -> int:
        """Count fresh live games once across all provider snapshots."""

        now = _utc_datetime(self._clock())
        identifiers: set[str] = set()
        for snapshot in self._snapshots.list_snapshots():
            observed_at = _utc_datetime(snapshot.observed_at)
            if (now - observed_at).total_seconds() > _LIVE_GAME_FRESHNESS_SECONDS:
                continue
            for item in snapshot.content:
                if _is_live_game(item):
                    identifiers.add(item.id)
        return len(identifiers)

    def _require_ticker(self, ticker_id: str) -> str:
        """Require one existing ticker and return its normalized identifier."""

        identifier = str(ticker_id).strip()
        if not identifier or self._repository.get_ticker(identifier) is None:
            raise KeyError(identifier)
        return identifier

    def _active_block(self, ticker_id: str, local: datetime) -> ScheduleBlock | None:
        """Select the latest updated enabled block that contains the local weekly minute."""

        minute = local.hour * 60 + local.minute
        candidates = [
            block
            for block in self._repository.list_ticker_schedule_blocks(ticker_id)
            if block.enabled
            and local.weekday() in block.days_of_week
            and block.start_minute <= minute < block.end_minute
        ]
        return max(candidates, key=lambda block: (block.updated_at, block.id), default=None)

    def _active_condition(
        self,
        ticker_id: str,
        live_games: int,
        settings: DisplaySettings,
    ) -> ScheduleCondition | None:
        """Select a live-game condition only while scheduled sports mode can switch to live sports."""

        if settings.mode != "sports" or settings.sports_filter == "live":
            return None
        candidates = [
            condition
            for condition in self._repository.list_ticker_schedule_conditions(ticker_id)
            if condition.enabled
            and condition.when_mode == "sports"
            and (not condition.ignore_pinned or settings.sports_presentation != "pinned")
            and _condition_matches(condition, live_games)
        ]
        return max(
            candidates,
            key=lambda condition: (condition.threshold, condition.updated_at, condition.id),
            default=None,
        )

    def _validate_block_overlap(self, block: ScheduleBlock) -> None:
        """Reject enabled intervals that overlap on at least one recurring weekday."""

        for existing in self._repository.list_ticker_schedule_blocks(block.ticker_id):
            if existing.id == block.id or not existing.enabled or not block.enabled:
                continue
            if not set(existing.days_of_week).intersection(block.days_of_week):
                continue
            if max(existing.start_minute, block.start_minute) < min(
                existing.end_minute,
                block.end_minute,
            ):
                raise ValueError("enabled schedule blocks cannot overlap")

    def _next_schedule_transition(
        self,
        ticker_id: str,
        settings: DisplaySettings,
        now: float,
    ) -> float:
        """Find the next active block end or future block start in the ticker's local timezone."""

        current = _utc_datetime(now)
        local = _local_datetime(current, settings.timezone)
        blocks = tuple(
            block
            for block in self._repository.list_ticker_schedule_blocks(ticker_id)
            if block.enabled
        )
        active = self._active_block(ticker_id, local)
        if active is not None:
            end_date = local.date()
            if active.end_minute == 1440:
                end_date += timedelta(days=1)
                end_minute = 0
            else:
                end_minute = active.end_minute
            return _local_timestamp(end_date, end_minute, local.tzinfo)
        candidates: list[float] = []
        for offset in range(8):
            candidate_date = local.date() + timedelta(days=offset)
            weekday = candidate_date.weekday()
            for block in blocks:
                if weekday not in block.days_of_week:
                    continue
                timestamp = _local_timestamp(candidate_date, block.start_minute, local.tzinfo)
                if timestamp > now:
                    candidates.append(timestamp)
        if candidates:
            return min(candidates)
        return now + 7 * 24 * 60 * 60


def block_to_mapping(block: ScheduleBlock) -> dict[str, object]:
    """Project one ticker-owned weekly block into the stable API contract."""

    return {
        "id": block.id,
        "ticker_id": block.ticker_id,
        "days_of_week": list(block.days_of_week),
        "day_names": [SCHEDULE_DAY_NAMES[day] for day in block.days_of_week],
        "start_minute": block.start_minute,
        "end_minute": block.end_minute,
        "mode": block.mode,
        "sports_filter": block.sports_filter,
        "enabled": block.enabled,
        "created_at": block.created_at,
        "updated_at": block.updated_at,
    }


def condition_to_mapping(condition: ScheduleCondition) -> dict[str, object]:
    """Project one ticker-owned live-game condition into the stable API contract."""

    return {
        "id": condition.id,
        "ticker_id": condition.ticker_id,
        "kind": condition.kind,
        "threshold": condition.threshold,
        "operator": condition.operator,
        "when_mode": condition.when_mode,
        "action_sports_filter": condition.action_sports_filter,
        "ignore_pinned": condition.ignore_pinned,
        "enabled": condition.enabled,
        "created_at": condition.created_at,
        "updated_at": condition.updated_at,
    }


def _with_block(settings: DisplaySettings, block: ScheduleBlock) -> DisplaySettings:
    """Apply a block's mode and optional sports filter while preserving unrelated settings."""

    effective = _with_mode(settings, block.mode)
    if block.mode == "sports" and block.sports_filter is not None:
        effective = replace(effective, sports_filter=block.sports_filter)
    return effective


def _with_mode(settings: DisplaySettings, mode: str) -> DisplaySettings:
    """Change top-level mode and clear incompatible sports pin state."""

    if mode == settings.mode:
        return settings
    if mode == "sports":
        return replace(settings, mode=mode)
    return replace(settings, mode=mode, sports_presentation="rotation", pinned_content_id="")


def _condition_matches(condition: ScheduleCondition, live_games: int) -> bool:
    """Evaluate one supported live-game comparison."""

    if condition.operator == "gte":
        return live_games >= condition.threshold
    return live_games > condition.threshold


def _is_live_game(item: ContentItem) -> bool:
    """Return whether one canonical item represents a live game."""

    return item.family == "sports" and str(item.data.get("state") or "").strip().lower() in _LIVE_STATES


def _utc_datetime(value: float | datetime) -> datetime:
    """Normalize one clock value into an aware UTC datetime."""

    parsed = value if isinstance(value, datetime) else datetime.fromtimestamp(float(value), tz=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_datetime(now: datetime, timezone_name: str) -> datetime:
    """Convert UTC time into one ticker's configured timezone with a local fallback."""

    name = str(timezone_name).strip()
    if name:
        try:
            return now.astimezone(ZoneInfo(name))
        except ZoneInfoNotFoundError:
            pass
    return now.astimezone()


def _local_timestamp(day: date, minute: int, timezone_info: object) -> float:
    """Convert one local calendar minute into an absolute timestamp."""

    zone = timezone_info if hasattr(timezone_info, "utcoffset") else timezone.utc
    local = datetime.combine(day, time.min, tzinfo=zone) + timedelta(minutes=minute)
    return local.timestamp()


__all__ = ["ScheduleService", "block_to_mapping", "condition_to_mapping"]
