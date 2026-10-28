"""Store encrypted Spotify connections and OAuth attempts."""

from __future__ import annotations

import json
import hmac
import sqlite3
import time
from .json_values import _dump
from .models import (
    SpotifyConnection,
    SpotifyOAuthAttempt,
)


class SpotifyRecords:
    """Persist controller-group Spotify connections and single-use OAuth attempts."""

    def save_group_spotify_connection(self, group_id: str, connection: SpotifyConnection) -> SpotifyConnection:
        """Create or update one encrypted Spotify connection shared by a controller group."""

        identifier = str(group_id).strip()
        if not identifier:
            raise ValueError("controller group ID must not be empty")
        if not isinstance(connection, SpotifyConnection):
            raise TypeError("connection must be SpotifyConnection")
        with self._transaction():
            self._connection.execute(
                "INSERT INTO spotify_group_connections "
                "(controller_group_id, spotify_account_id, display_name, scopes_json, "
                "refresh_token_ciphertext, status, priority, connected_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(controller_group_id, spotify_account_id) DO UPDATE SET "
                "display_name = excluded.display_name, scopes_json = excluded.scopes_json, "
                "refresh_token_ciphertext = excluded.refresh_token_ciphertext, "
                "status = excluded.status, priority = excluded.priority, updated_at = excluded.updated_at",
                (
                    identifier,
                    connection.spotify_account_id,
                    connection.display_name,
                    _dump(connection.scopes),
                    connection.refresh_token_ciphertext,
                    connection.status,
                    int(connection.priority),
                    connection.connected_at,
                    connection.updated_at,
                ),
            )
        return self.get_group_spotify_connection(identifier, connection.spotify_account_id)  # type: ignore[return-value]

    def get_group_spotify_connection(
        self, group_id: str, spotify_account_id: str | None = None
    ) -> SpotifyConnection | None:
        """Read one shared encrypted Spotify connection."""

        values: list[str] = [str(group_id).strip()]
        clause = "WHERE controller_group_id = ?"
        if spotify_account_id:
            clause += " AND spotify_account_id = ?"
            values.append(str(spotify_account_id).strip())
        with self._lock:
            row = self._connection.execute(
                "SELECT controller_group_id AS ticker_id, spotify_account_id, display_name, scopes_json, "
                "refresh_token_ciphertext, status, priority, connected_at, updated_at "
                f"FROM spotify_group_connections {clause} "
                "ORDER BY priority DESC, connected_at ASC LIMIT 1",
                tuple(values),
            ).fetchone()
        return None if row is None else self._spotify_connection_from_row(row)

    def list_group_spotify_connections(
        self, group_id: str, *, fallback_ticker_id: str | None = None
    ) -> tuple[SpotifyConnection, ...]:
        """Read shared connections and support legacy ticker-owned records during migration."""

        identifier = str(group_id).strip()
        with self._lock:
            rows = self._connection.execute(
                "SELECT controller_group_id AS ticker_id, spotify_account_id, display_name, scopes_json, "
                "refresh_token_ciphertext, status, priority, connected_at, updated_at "
                "FROM spotify_group_connections WHERE controller_group_id = ? "
                "ORDER BY priority DESC, connected_at ASC",
                (identifier,),
            ).fetchall()
            if not rows and fallback_ticker_id:
                rows = self._connection.execute(
                    "SELECT ticker_id, spotify_account_id, display_name, scopes_json, "
                    "refresh_token_ciphertext, status, priority, connected_at, updated_at "
                    "FROM spotify_connections WHERE ticker_id = ? "
                    "ORDER BY priority DESC, connected_at ASC",
                    (str(fallback_ticker_id).strip(),),
                ).fetchall()
        return tuple(self._spotify_connection_from_row(row) for row in rows)

    def delete_group_spotify_connection(self, group_id: str, spotify_account_id: str | None = None) -> bool:
        """Remove one shared Spotify account or every account in a controller group."""

        identifier = str(group_id).strip()
        with self._transaction():
            if spotify_account_id:
                cursor = self._connection.execute(
                    "DELETE FROM spotify_group_connections WHERE controller_group_id = ? AND spotify_account_id = ?",
                    (identifier, str(spotify_account_id).strip()),
                )
            else:
                cursor = self._connection.execute(
                    "DELETE FROM spotify_group_connections WHERE controller_group_id = ?",
                    (identifier,),
                )
            return cursor.rowcount > 0

    def set_group_spotify_priority(
        self, group_id: str, spotify_account_id: str | None
    ) -> tuple[SpotifyConnection, ...]:
        """Set one preferred shared Spotify account for a controller group."""

        identifier = str(group_id).strip()
        account_id = str(spotify_account_id or "").strip()
        with self._transaction():
            self._connection.execute(
                "UPDATE spotify_group_connections SET priority = 0 WHERE controller_group_id = ?",
                (identifier,),
            )
            if account_id:
                self._connection.execute(
                    "UPDATE spotify_group_connections SET priority = 1 "
                    "WHERE controller_group_id = ? AND spotify_account_id = ?",
                    (identifier, account_id),
                )
        return self.list_group_spotify_connections(identifier)

    @staticmethod
    def _spotify_connection_from_row(row: sqlite3.Row) -> SpotifyConnection:
        """Build one Spotify connection from a database row."""

        return SpotifyConnection(
            ticker_id=row["ticker_id"],
            spotify_account_id=row["spotify_account_id"],
            display_name=row["display_name"],
            scopes=tuple(json.loads(row["scopes_json"])),
            refresh_token_ciphertext=row["refresh_token_ciphertext"],
            status=row["status"],
            priority=bool(row["priority"]),
            connected_at=row["connected_at"],
            updated_at=row["updated_at"],
        )

    def create_spotify_oauth_attempt(self, attempt: SpotifyOAuthAttempt) -> None:
        """Persist one authorization attempt before opening Spotify."""

        if not isinstance(attempt, SpotifyOAuthAttempt):
            raise TypeError("attempt must be SpotifyOAuthAttempt")
        with self._transaction():
            self._require_ticker_locked(attempt.ticker_id)
            self._connection.execute(
                "DELETE FROM spotify_oauth_attempts WHERE expires_at <= ? OR used_at IS NOT NULL",
                (attempt.created_at,),
            )
            self._connection.execute(
                "INSERT INTO spotify_oauth_attempts "
                "(attempt_id, ticker_id, state_hash, verifier_ciphertext, expires_at, used_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id,
                    attempt.ticker_id,
                    attempt.state_hash,
                    attempt.verifier_ciphertext,
                    attempt.expires_at,
                    attempt.used_at,
                    attempt.created_at,
                ),
            )

    def consume_spotify_oauth_attempt(
        self,
        attempt_id: str,
        state_hash: str,
        *,
        now: float | None = None,
    ) -> SpotifyOAuthAttempt:
        """Atomically consume a matching unexpired OAuth attempt."""

        identifier = str(attempt_id).strip()
        digest = str(state_hash).strip()
        current_time = time.time() if now is None else float(now)
        with self._transaction():
            row = self._connection.execute(
                "SELECT attempt_id, ticker_id, state_hash, verifier_ciphertext, expires_at, used_at, created_at "
                "FROM spotify_oauth_attempts WHERE attempt_id = ?",
                (identifier,),
            ).fetchone()
            if row is None or row["used_at"] is not None or row["expires_at"] <= current_time:
                raise ValueError("Spotify authorization attempt is invalid or expired")
            if not hmac.compare_digest(str(row["state_hash"]), digest):
                raise ValueError("Spotify authorization state is invalid")
            self._connection.execute(
                "UPDATE spotify_oauth_attempts SET used_at = ? WHERE attempt_id = ? AND used_at IS NULL",
                (current_time, identifier),
            )
            return SpotifyOAuthAttempt(
                attempt_id=row["attempt_id"],
                ticker_id=row["ticker_id"],
                state_hash=row["state_hash"],
                verifier_ciphertext=row["verifier_ciphertext"],
                expires_at=row["expires_at"],
                created_at=row["created_at"],
                used_at=current_time,
            )
