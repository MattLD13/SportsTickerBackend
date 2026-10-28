"""Create and migrate the fleet SQLite schema."""

from __future__ import annotations



class SchemaMigrations:
    """Create tables and apply in-place migrations on the owned connection."""

    def _create_schema(self) -> None:
        with self._transaction():
            schema = (
                """
                CREATE TABLE IF NOT EXISTS tickers (
                    ticker_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """,
                """

                CREATE TABLE IF NOT EXISTS ticker_display_settings (
                    ticker_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """

                CREATE TABLE IF NOT EXISTS ticker_pairing (
                    ticker_id TEXT PRIMARY KEY,
                    pairing_code TEXT,
                    pairing_code_expires_at REAL,
                    controller_group_id TEXT,
                    paired INTEGER NOT NULL,
                    client_ids_json TEXT NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """

                CREATE TABLE IF NOT EXISTS ticker_devices (
                    ticker_id TEXT PRIMARY KEY,
                    last_seen_at REAL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS device_credentials (
                    ticker_id TEXT PRIMARY KEY REFERENCES tickers(ticker_id) ON DELETE CASCADE,
                    token_sha256 TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS overlay_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL CHECK (event_type IN ('alerts', 'news')),
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    target_ticker_ids_json TEXT,
                    delivery_state TEXT NOT NULL CHECK (
                        delivery_state IN ('pending', 'acknowledged', 'expired')
                    )
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS overlay_event_deliveries (
                    event_id TEXT NOT NULL,
                    ticker_id TEXT NOT NULL,
                    delivery_state TEXT NOT NULL CHECK (
                        delivery_state IN ('acknowledged', 'expired')
                    ),
                    acknowledged_at REAL,
                    PRIMARY KEY (event_id, ticker_id),
                    FOREIGN KEY (event_id) REFERENCES overlay_events(event_id) ON DELETE CASCADE,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS spotify_connections (
                    ticker_id TEXT NOT NULL,
                    spotify_account_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    refresh_token_ciphertext TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('connected', 'reauthorization_required')),
                    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority IN (0, 1)),
                    connected_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (ticker_id, spotify_account_id),
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS controller_groups (
                    group_id TEXT PRIMARY KEY,
                    secret_hash TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS spotify_group_connections (
                    controller_group_id TEXT NOT NULL,
                    spotify_account_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    refresh_token_ciphertext TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('connected', 'reauthorization_required')),
                    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority IN (0, 1)),
                    connected_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (controller_group_id, spotify_account_id)
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS spotify_oauth_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    ticker_id TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    verifier_ciphertext TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    used_at REAL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS controller_sessions (
                    token_hash TEXT PRIMARY KEY,
                    ticker_id TEXT NOT NULL,
                    controller_group_id TEXT,
                    created_at REAL NOT NULL,
                    last_used_at REAL NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS schedule_blocks (
                    id TEXT PRIMARY KEY,
                    day_group TEXT NOT NULL CHECK (day_group IN ('weekdays', 'weekends')),
                    start_minute INTEGER NOT NULL,
                    end_minute INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS schedule_conditions (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('live_games')),
                    threshold INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS ticker_schedule_blocks (
                    id TEXT PRIMARY KEY,
                    ticker_id TEXT NOT NULL,
                    days_of_week_json TEXT NOT NULL,
                    start_minute INTEGER NOT NULL,
                    end_minute INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    sports_filter TEXT,
                    enabled INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS ticker_schedule_conditions (
                    id TEXT PRIMARY KEY,
                    ticker_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('live_games')),
                    threshold INTEGER NOT NULL,
                    operator TEXT NOT NULL CHECK (operator IN ('gt', 'gte')),
                    when_mode TEXT NOT NULL,
                    action_sports_filter TEXT NOT NULL,
                    ignore_pinned INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS ticker_schedule_overrides (
                    ticker_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE
                );
                """,
                """
                CREATE INDEX IF NOT EXISTS controller_sessions_ticker_id
                ON controller_sessions(ticker_id);
                """,
            )
            for statement in schema:
                self._connection.execute(statement)
            self._migrate_pairing_expiry_locked()
            self._migrate_controller_group_locked()
            self._migrate_controller_session_group_locked()
            self._migrate_spotify_connections_locked()
            self._migrate_schedule_override_expiry_locked()
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS ticker_schedule_blocks_ticker_day "
                "ON ticker_schedule_blocks(ticker_id, start_minute, end_minute)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS ticker_schedule_conditions_ticker "
                "ON ticker_schedule_conditions(ticker_id, threshold)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS controller_sessions_group_id "
                "ON controller_sessions(controller_group_id)"
            )
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS spotify_connections_one_priority "
                "ON spotify_connections(ticker_id) WHERE priority = 1"
            )
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS spotify_group_connections_one_priority "
                "ON spotify_group_connections(controller_group_id) WHERE priority = 1"
            )

    def _migrate_spotify_connections_locked(self) -> None:
        """Replace the former one-account table while preserving its account."""

        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(spotify_connections)")
        }
        if "priority" in columns:
            return
        self._connection.execute(
            "CREATE TABLE spotify_connections_next ("
            "ticker_id TEXT NOT NULL, spotify_account_id TEXT NOT NULL, "
            "display_name TEXT NOT NULL, scopes_json TEXT NOT NULL, "
            "refresh_token_ciphertext TEXT NOT NULL, "
            "status TEXT NOT NULL CHECK (status IN ('connected', 'reauthorization_required')), "
            "priority INTEGER NOT NULL DEFAULT 0 CHECK (priority IN (0, 1)), "
            "connected_at REAL NOT NULL, updated_at REAL NOT NULL, "
            "PRIMARY KEY (ticker_id, spotify_account_id), "
            "FOREIGN KEY (ticker_id) REFERENCES tickers(ticker_id) ON DELETE CASCADE)"
        )
        self._connection.execute(
            "INSERT INTO spotify_connections_next "
            "(ticker_id, spotify_account_id, display_name, scopes_json, "
            "refresh_token_ciphertext, status, priority, connected_at, updated_at) "
            "SELECT ticker_id, spotify_account_id, display_name, scopes_json, "
            "refresh_token_ciphertext, status, 0, connected_at, updated_at "
            "FROM spotify_connections"
        )
        self._connection.execute("DROP TABLE spotify_connections")
        self._connection.execute("ALTER TABLE spotify_connections_next RENAME TO spotify_connections")

    def _migrate_schedule_override_expiry_locked(self) -> None:
        """Add the expiry timestamp used by temporary app schedule overrides."""

        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(ticker_schedule_overrides)")
        }
        if "expires_at" not in columns:
            self._connection.execute(
                "ALTER TABLE ticker_schedule_overrides ADD COLUMN expires_at REAL NOT NULL DEFAULT 0"
            )

    def _migrate_pairing_expiry_locked(self) -> None:
        """Add durable pairing expiry to databases created before the field existed."""

        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(ticker_pairing)")
        }
        if "pairing_code_expires_at" not in columns:
            self._connection.execute(
                "ALTER TABLE ticker_pairing ADD COLUMN pairing_code_expires_at REAL"
            )

    def _migrate_controller_group_locked(self) -> None:
        """Add the controller group owner used by shared app integrations."""

        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(ticker_pairing)")
        }
        if "controller_group_id" not in columns:
            self._connection.execute(
                "ALTER TABLE ticker_pairing ADD COLUMN controller_group_id TEXT"
            )

    def _migrate_controller_session_group_locked(self) -> None:
        """Add nullable group ownership to existing controller sessions."""

        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(controller_sessions)")
        }
        if "controller_group_id" not in columns:
            self._connection.execute(
                "ALTER TABLE controller_sessions ADD COLUMN controller_group_id TEXT"
            )
