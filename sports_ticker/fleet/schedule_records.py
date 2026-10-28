"""Store ticker schedule blocks, live-game conditions, and overrides."""

from __future__ import annotations

import json
import sqlite3
import time

from sports_ticker.domain import (
    ScheduleBlock,
    ScheduleCondition,
)

from .json_values import _dump


class ScheduleRecords:
    """Read and write schedule rows for one ticker inside the repository transaction."""

    def create_ticker_schedule_block(self, block: ScheduleBlock) -> ScheduleBlock:
        """Persist one recurring schedule block for one ticker."""

        if not isinstance(block, ScheduleBlock):
            raise TypeError("schedule block must be ScheduleBlock")
        with self._transaction():
            try:
                self._connection.execute(
                    "INSERT INTO ticker_schedule_blocks "
                    "(id, ticker_id, days_of_week_json, start_minute, end_minute, mode, sports_filter, "
                    "enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        block.id,
                        block.ticker_id,
                        _dump(list(block.days_of_week)),
                        block.start_minute,
                        block.end_minute,
                        block.mode,
                        block.sports_filter,
                        int(block.enabled),
                        block.created_at,
                        block.updated_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"schedule block already exists: {block.id}") from error
        return self.get_ticker_schedule_block(block.ticker_id, block.id)  # type: ignore[return-value]

    def get_ticker_schedule_block(self, ticker_id: str, block_id: str) -> ScheduleBlock | None:
        """Return one ticker-owned recurring schedule block."""

        owner = str(ticker_id).strip()
        identifier = str(block_id).strip()
        with self._lock:
            row = self._connection.execute(
                "SELECT id, ticker_id, days_of_week_json, start_minute, end_minute, mode, sports_filter, "
                "enabled, created_at, updated_at FROM ticker_schedule_blocks WHERE id = ? AND ticker_id = ?",
                (identifier, owner),
            ).fetchone()
        return _ticker_schedule_block_from_row(row) if row is not None else None

    def list_ticker_schedule_blocks(self, ticker_id: str) -> tuple[ScheduleBlock, ...]:
        """Return one ticker's recurring blocks in weekly timeline order."""

        owner = str(ticker_id).strip()
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, ticker_id, days_of_week_json, start_minute, end_minute, mode, sports_filter, "
                "enabled, created_at, updated_at FROM ticker_schedule_blocks "
                "WHERE ticker_id = ? ORDER BY start_minute, end_minute, id",
                (owner,),
            ).fetchall()
        return tuple(_ticker_schedule_block_from_row(row) for row in rows)

    def update_ticker_schedule_block(self, block: ScheduleBlock) -> ScheduleBlock:
        """Replace one ticker-owned recurring schedule block."""

        if not isinstance(block, ScheduleBlock):
            raise TypeError("schedule block must be ScheduleBlock")
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE ticker_schedule_blocks SET days_of_week_json = ?, start_minute = ?, end_minute = ?, "
                "mode = ?, sports_filter = ?, enabled = ?, created_at = ?, updated_at = ? "
                "WHERE id = ? AND ticker_id = ?",
                (
                    _dump(list(block.days_of_week)),
                    block.start_minute,
                    block.end_minute,
                    block.mode,
                    block.sports_filter,
                    int(block.enabled),
                    block.created_at,
                    block.updated_at,
                    block.id,
                    block.ticker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(block.id)
        return self.get_ticker_schedule_block(block.ticker_id, block.id)  # type: ignore[return-value]

    def delete_ticker_schedule_block(self, ticker_id: str, block_id: str) -> bool:
        """Delete one ticker-owned recurring schedule block."""

        owner = str(ticker_id).strip()
        identifier = str(block_id).strip()
        with self._transaction():
            cursor = self._connection.execute(
                "DELETE FROM ticker_schedule_blocks WHERE id = ? AND ticker_id = ?",
                (identifier, owner),
            )
            return cursor.rowcount == 1

    def create_ticker_schedule_condition(self, condition: ScheduleCondition) -> ScheduleCondition:
        """Persist one recurring live-game condition for one ticker."""

        if not isinstance(condition, ScheduleCondition):
            raise TypeError("schedule condition must be ScheduleCondition")
        with self._transaction():
            try:
                self._connection.execute(
                    "INSERT INTO ticker_schedule_conditions "
                    "(id, ticker_id, kind, threshold, operator, when_mode, action_sports_filter, "
                    "ignore_pinned, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        condition.id,
                        condition.ticker_id,
                        condition.kind,
                        condition.threshold,
                        condition.operator,
                        condition.when_mode,
                        condition.action_sports_filter,
                        int(condition.ignore_pinned),
                        int(condition.enabled),
                        condition.created_at,
                        condition.updated_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"schedule condition already exists: {condition.id}") from error
        return self.get_ticker_schedule_condition(condition.ticker_id, condition.id)  # type: ignore[return-value]

    def get_ticker_schedule_condition(self, ticker_id: str, condition_id: str) -> ScheduleCondition | None:
        """Return one ticker-owned recurring condition."""

        owner = str(ticker_id).strip()
        identifier = str(condition_id).strip()
        with self._lock:
            row = self._connection.execute(
                "SELECT id, ticker_id, kind, threshold, operator, when_mode, action_sports_filter, "
                "ignore_pinned, enabled, created_at, updated_at FROM ticker_schedule_conditions "
                "WHERE id = ? AND ticker_id = ?",
                (identifier, owner),
            ).fetchone()
        return _ticker_schedule_condition_from_row(row) if row is not None else None

    def list_ticker_schedule_conditions(self, ticker_id: str) -> tuple[ScheduleCondition, ...]:
        """Return one ticker's conditions in priority order."""

        owner = str(ticker_id).strip()
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, ticker_id, kind, threshold, operator, when_mode, action_sports_filter, "
                "ignore_pinned, enabled, created_at, updated_at FROM ticker_schedule_conditions "
                "WHERE ticker_id = ? ORDER BY threshold, updated_at, id",
                (owner,),
            ).fetchall()
        return tuple(_ticker_schedule_condition_from_row(row) for row in rows)

    def update_ticker_schedule_condition(self, condition: ScheduleCondition) -> ScheduleCondition:
        """Replace one ticker-owned recurring condition."""

        if not isinstance(condition, ScheduleCondition):
            raise TypeError("schedule condition must be ScheduleCondition")
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE ticker_schedule_conditions SET kind = ?, threshold = ?, operator = ?, when_mode = ?, "
                "action_sports_filter = ?, ignore_pinned = ?, enabled = ?, created_at = ?, updated_at = ? "
                "WHERE id = ? AND ticker_id = ?",
                (
                    condition.kind,
                    condition.threshold,
                    condition.operator,
                    condition.when_mode,
                    condition.action_sports_filter,
                    int(condition.ignore_pinned),
                    int(condition.enabled),
                    condition.created_at,
                    condition.updated_at,
                    condition.id,
                    condition.ticker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(condition.id)
        return self.get_ticker_schedule_condition(condition.ticker_id, condition.id)  # type: ignore[return-value]

    def delete_ticker_schedule_condition(self, ticker_id: str, condition_id: str) -> bool:
        """Delete one ticker-owned recurring condition."""

        owner = str(ticker_id).strip()
        identifier = str(condition_id).strip()
        with self._transaction():
            cursor = self._connection.execute(
                "DELETE FROM ticker_schedule_conditions WHERE id = ? AND ticker_id = ?",
                (identifier, owner),
            )
            return cursor.rowcount == 1

    def schedule_override_expires_at(self, ticker_id: str, *, now: float) -> float | None:
        """Return one temporary override expiry and clear expired state."""

        identifier = str(ticker_id).strip()
        with self._transaction():
            row = self._connection.execute(
                "SELECT expires_at FROM ticker_schedule_overrides WHERE ticker_id = ? AND enabled = 1",
                (identifier,),
            ).fetchone()
            if row is None:
                return None
            expires_at = float(row["expires_at"])
            if expires_at <= float(now):
                self._connection.execute(
                    "DELETE FROM ticker_schedule_overrides WHERE ticker_id = ?",
                    (identifier,),
                )
                return None
            return expires_at

    def schedule_override_enabled(self, ticker_id: str, *, now: float | None = None) -> bool:
        """Return whether one ticker has a live temporary app override."""

        timestamp = time.time() if now is None else float(now)
        return self.schedule_override_expires_at(ticker_id, now=timestamp) is not None

    def set_schedule_override(
        self,
        ticker_id: str,
        enabled: bool,
        *,
        expires_at: float | None,
        now: float,
    ) -> bool:
        """Set or clear one ticker's temporary app-owned schedule override."""

        identifier = str(ticker_id).strip()
        with self._transaction():
            self._require_ticker_locked(identifier)
            if enabled:
                if expires_at is None or float(expires_at) <= float(now):
                    raise ValueError("schedule override expiry must be in the future")
                self._connection.execute(
                    "INSERT INTO ticker_schedule_overrides (ticker_id, enabled, updated_at, expires_at) "
                    "VALUES (?, 1, ?, ?) ON CONFLICT(ticker_id) DO UPDATE SET enabled = 1, "
                    "updated_at = excluded.updated_at, expires_at = excluded.expires_at",
                    (identifier, float(now), float(expires_at)),
                )
            else:
                self._connection.execute(
                    "DELETE FROM ticker_schedule_overrides WHERE ticker_id = ?",
                    (identifier,),
                )
        return bool(enabled)


def _ticker_schedule_block_from_row(row: sqlite3.Row) -> ScheduleBlock:
    """Build one ticker-owned schedule block from a database row."""

    return ScheduleBlock(
        id=row["id"],
        ticker_id=row["ticker_id"],
        days_of_week=tuple(json.loads(row["days_of_week_json"])),
        start_minute=row["start_minute"],
        end_minute=row["end_minute"],
        mode=row["mode"],
        sports_filter=row["sports_filter"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _ticker_schedule_condition_from_row(row: sqlite3.Row) -> ScheduleCondition:
    """Build one ticker-owned schedule condition from a database row."""

    return ScheduleCondition(
        id=row["id"],
        ticker_id=row["ticker_id"],
        kind=row["kind"],
        threshold=row["threshold"],
        operator=row["operator"],
        when_mode=row["when_mode"],
        action_sports_filter=row["action_sports_filter"],
        ignore_pinned=bool(row["ignore_pinned"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
