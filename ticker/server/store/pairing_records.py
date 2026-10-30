"""Store pairing codes, controller groups, and controller credentials."""

from __future__ import annotations

import time
from ticker.server.store.json_values import _dump
from ticker.server.store.models import (
    TickerRecord,
)


class PairingRecords:
    """Issue and exchange pairing codes and authorize controller tokens."""

    def list_tickers_for_controller(self, token_hash: str) -> tuple[TickerRecord, ...]:
        """Return only tickers owned by one hashed controller token."""

        digest = str(token_hash).strip()
        if not digest:
            return ()
        with self._lock:
            rows = self._connection.execute(
                "SELECT DISTINCT t.ticker_id, t.name, t.created_at, t.updated_at "
                "FROM tickers AS t "
                "INNER JOIN controller_sessions AS s ON s.ticker_id = t.ticker_id "
                "WHERE s.token_hash = ? OR EXISTS ("
                "SELECT 1 FROM controller_sessions AS anchor "
                "WHERE anchor.token_hash = ? AND anchor.controller_group_id IS NOT NULL "
                "AND anchor.controller_group_id = s.controller_group_id) "
                "ORDER BY t.ticker_id",
                (digest, digest),
            ).fetchall()
            return tuple(self._read_record(row) for row in rows)

    def controller_group_id_for_ticker(self, ticker_id: str) -> str | None:
        """Return the shared controller group assigned to one ticker."""

        identifier = str(ticker_id).strip()
        with self._lock:
            row = self._connection.execute(
                "SELECT controller_group_id FROM ticker_pairing WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            value = None if row is None else row["controller_group_id"]
            return str(value).strip() if value else None

    def controller_group_id_for_pairing_code(self, pairing_code: str) -> str | None:
        """Return the current group owner for one unexpired pairing code."""

        with self._lock:
            row = self._connection.execute(
                "SELECT controller_group_id FROM ticker_pairing WHERE pairing_code = ?",
                (str(pairing_code).strip(),),
            ).fetchone()
            value = None if row is None else row["controller_group_id"]
            return str(value).strip() if value else None

    def exchange_pairing_code(
        self,
        pairing_code: str,
        token_hash: str,
        *,
        now: float | None = None,
        controller_group_id: str | None = None,
        controller_group_secret_hash: str | None = None,
    ) -> TickerRecord:
        """Consume one pairing code and create one controller token record."""

        code = str(pairing_code).strip()
        digest = str(token_hash).strip()
        if not code or not digest:
            raise ValueError("pairing code and controller token are required")
        current_time = time.time() if now is None else float(now)
        group_id = str(controller_group_id or "").strip() or None
        secret_hash = str(controller_group_secret_hash or "").strip() or None
        if (group_id is None) != (secret_hash is None):
            raise ValueError("controller group credentials must be provided together")
        with self._transaction():
            row = self._connection.execute(
                "SELECT ticker_id, pairing_code_expires_at, controller_group_id FROM ticker_pairing WHERE pairing_code = ?",
                (code,),
            ).fetchone()
            if row is None:
                raise ValueError("pairing code is invalid or already used")
            expires_at = row["pairing_code_expires_at"]
            if expires_at is not None and current_time > float(expires_at):
                raise ValueError("pairing code has expired")
            ticker_id = str(row["ticker_id"])
            stored_group_id = str(row["controller_group_id"] or "").strip() or None
            if stored_group_id is not None and group_id is not None and stored_group_id != group_id:
                raise ValueError("pairing code belongs to another controller group")
            session_group_id = group_id
            if group_id is not None:
                group_row = self._connection.execute(
                    "SELECT group_id FROM controller_groups WHERE group_id = ? AND secret_hash = ?",
                    (group_id, secret_hash),
                ).fetchone()
                if group_row is None:
                    if stored_group_id is not None:
                        raise ValueError("controller group credentials are invalid")
                    self._connection.execute(
                        "INSERT INTO controller_groups (group_id, secret_hash, created_at) VALUES (?, ?, ?)",
                        (group_id, secret_hash, current_time),
                    )
                    session_group_id = group_id
            self._connection.execute(
                "INSERT INTO controller_sessions (token_hash, ticker_id, controller_group_id, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (digest, ticker_id, session_group_id, current_time, current_time),
            )
            self._connection.execute(
                "UPDATE ticker_pairing SET paired = 1, pairing_code = NULL, pairing_code_expires_at = NULL, controller_group_id = ? WHERE ticker_id = ?",
                (stored_group_id or group_id, ticker_id),
            )
            ticker_row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (ticker_id,),
            ).fetchone()
            if ticker_row is None:
                raise KeyError(ticker_id)
            return self._read_record(ticker_row)

    def issue_pairing_code(
        self,
        ticker_id: str,
        pairing_code: str,
        *,
        expires_at: float | None = None,
    ) -> TickerRecord:
        """Issue one unused controller pairing code for an existing ticker."""

        identifier = str(ticker_id).strip()
        code = str(pairing_code).strip()
        if not identifier or not code:
            raise ValueError("ticker ID and pairing code are required")
        with self._transaction():
            self._require_ticker_locked(identifier)
            existing = self._connection.execute(
                "SELECT ticker_id FROM ticker_pairing WHERE pairing_code = ?",
                (code,),
            ).fetchone()
            if existing is not None and str(existing["ticker_id"]) != identifier:
                raise ValueError("pairing code is already in use")
            pairing_row = self._connection.execute(
                "SELECT paired FROM ticker_pairing WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if pairing_row is None:
                self._connection.execute(
                    "INSERT INTO ticker_pairing "
                    "(ticker_id, pairing_code, pairing_code_expires_at, paired, client_ids_json) VALUES (?, ?, ?, ?, ?)",
                    (identifier, code, expires_at, 0, _dump(())),
                )
            else:
                self._connection.execute(
                    "UPDATE ticker_pairing SET pairing_code = ?, pairing_code_expires_at = ? WHERE ticker_id = ?",
                    (code, expires_at, identifier),
                )
            ticker_row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if ticker_row is None:
                raise KeyError(identifier)
            return self._read_record(ticker_row)

    def unpair_ticker(
        self,
        ticker_id: str,
        pairing_code: str,
        *,
        expires_at: float | None = None,
    ) -> TickerRecord:
        """Revoke one controller and reset the ticker to pairing mode."""

        identifier = str(ticker_id).strip()
        code = str(pairing_code).strip()
        if not identifier or not code:
            raise ValueError("ticker ID and pairing code are required")
        with self._transaction():
            self._require_ticker_locked(identifier)
            existing = self._connection.execute(
                "SELECT ticker_id FROM ticker_pairing WHERE pairing_code = ?",
                (code,),
            ).fetchone()
            if existing is not None and str(existing["ticker_id"]) != identifier:
                raise ValueError("pairing code is already in use")
            self._connection.execute(
                "DELETE FROM controller_sessions WHERE ticker_id = ?", (identifier,)
            )
            self._connection.execute(
                "DELETE FROM spotify_oauth_attempts WHERE ticker_id = ?", (identifier,)
            )
            self._connection.execute(
                "DELETE FROM spotify_connections WHERE ticker_id = ?", (identifier,)
            )
            self._connection.execute(
                "INSERT INTO ticker_pairing "
                "(ticker_id, pairing_code, pairing_code_expires_at, controller_group_id, paired, client_ids_json) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker_id) DO UPDATE SET pairing_code = excluded.pairing_code, "
                "pairing_code_expires_at = excluded.pairing_code_expires_at, "
                "controller_group_id = excluded.controller_group_id, "
                "paired = excluded.paired, client_ids_json = excluded.client_ids_json",
                (identifier, code, expires_at, None, 0, _dump(())),
            )
            self._connection.execute(
                "UPDATE tickers SET updated_at = ? WHERE ticker_id = ?",
                (time.time(), identifier),
            )
            row = self._connection.execute(
                "SELECT ticker_id, name, created_at, updated_at FROM tickers WHERE ticker_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise KeyError(identifier)
            return self._read_record(row)

    def authorize_controller(
        self,
        ticker_id: str,
        token_hash: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Validate one opaque controller token for its bound ticker."""

        identifier = str(ticker_id).strip()
        digest = str(token_hash).strip()
        if not identifier or not digest:
            return False
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            cursor = self._connection.execute(
                "UPDATE controller_sessions SET last_used_at = ? "
                "WHERE token_hash = ? AND (ticker_id = ? OR (controller_group_id IS NOT NULL AND EXISTS ("
                "SELECT 1 FROM ticker_pairing WHERE ticker_id = ? AND controller_group_id = controller_sessions.controller_group_id)))",
                (current_time, digest, identifier, identifier),
            )
            return cursor.rowcount == 1
