"""Own durable update attempts, release quarantine, and fleet cancellation."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from ticker.server.store.models import DeviceMetadata


class UpdateLedger:
    def __init__(self, repository):
        self.repository = repository
        with repository._transaction():
            for statement in (
                "CREATE TABLE IF NOT EXISTS update_releases (family TEXT NOT NULL, version TEXT NOT NULL, quarantined_at REAL, reason TEXT, PRIMARY KEY(family, version))",
                "CREATE TABLE IF NOT EXISTS update_attempts (id TEXT PRIMARY KEY, ticker_id TEXT NOT NULL, family TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)",
                "CREATE TABLE IF NOT EXISTS update_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL, ticker_id TEXT NOT NULL, family TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL, running_version TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(attempt_id, status))",
            ):
                self.db.execute(statement)
            self._migrate_pending()

    @property
    def db(self):
        return self.repository._connection

    def _migrate_pending(self):
        for ticker in self.repository.list_tickers():
            metadata = dict(ticker.device.metadata)
            commands = list(metadata.get("pending_commands", ()))
            legacy_update = metadata.pop("pending_update", None)
            legacy_reboot = metadata.pop("pending_reboot", None)
            if not commands:
                if isinstance(legacy_update, Mapping):
                    commands.append({"id": str(uuid4()), "type": "update", "payload": dict(legacy_update), "created_at": ticker.updated_at, "expires_at": ticker.updated_at + 900})
                if isinstance(legacy_reboot, Mapping):
                    commands.append({"id": legacy_reboot.get("id") or str(uuid4()), "type": "reboot", "payload": {}, "created_at": ticker.updated_at, "expires_at": ticker.updated_at + 900})
            if legacy_update is not None or legacy_reboot is not None:
                metadata["pending_commands"] = commands
                self.repository.update_ticker(ticker.ticker_id, device=DeviceMetadata(last_seen_at=ticker.device.last_seen_at, metadata=metadata))
            for command in commands:
                if not isinstance(command, Mapping) or command.get("type") != "update":
                    continue
                version = str(command.get("payload", {}).get("version", ""))
                if version:
                    self.db.execute(
                        "INSERT OR IGNORE INTO update_attempts VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                        (command["id"], ticker.ticker_id, ticker.profile.product_family, version,
                         float(command.get("created_at", ticker.updated_at)), ticker.updated_at),
                    )

    def quarantined(self, family: str, version: str) -> bool:
        with self.repository._lock:
            row = self.db.execute("SELECT quarantined_at FROM update_releases WHERE family=? AND version=?", (family, version)).fetchone()
            return row is not None and row["quarantined_at"] is not None

    def queue(self, ticker_id: str, version: str, now: float):
        with self.repository._transaction():
            ticker = self.repository.get_ticker(ticker_id)
            if ticker is None:
                raise KeyError(ticker_id)
            family = ticker.profile.product_family
            if self.quarantined(family, version):
                raise ValueError("release is quarantined for this ticker family")
            identifier = str(uuid4())
            command = {"id": identifier, "type": "update", "payload": {"version": version}, "created_at": now, "expires_at": now + 900}
            metadata = dict(ticker.device.metadata)
            previous = [item for item in metadata.get("pending_commands", ()) if isinstance(item, Mapping) and item.get("type") == "update"]
            for item in previous:
                old_version = str(item.get("payload", {}).get("version", ""))
                self.db.execute("UPDATE update_attempts SET status='superseded',updated_at=? WHERE id=?", (now,item["id"]))
                self._event(item["id"], ticker_id, family, old_version, "superseded", "", "", now)
            commands = [dict(item) for item in metadata.get("pending_commands", ()) if isinstance(item, Mapping) and item.get("type") != "update"]
            commands.append(command)
            metadata["pending_commands"] = commands
            self.db.execute("INSERT OR IGNORE INTO update_releases(family, version) VALUES (?, ?)", (family, version))
            self.db.execute("INSERT INTO update_attempts VALUES (?, ?, ?, ?, 'queued', ?, ?)", (identifier, ticker_id, family, version, now, now))
            self._event(identifier, ticker_id, family, version, "queued", "", "", now)
            return self.repository.update_ticker(ticker_id, device=DeviceMetadata(last_seen_at=ticker.device.last_seen_at, metadata=metadata))

    def _event(self, attempt, ticker, family, version, status, running, reason, now):
        self.db.execute("INSERT OR IGNORE INTO update_events(attempt_id,ticker_id,family,version,status,running_version,reason,created_at) VALUES (?,?,?,?,?,?,?,?)", (attempt, ticker, family, version, status, running, reason, now))

    def report(self, ticker_id: str, payload: Mapping, now: float) -> dict:
        identifier = payload.get("id")
        status = payload.get("status")
        version = payload.get("version")
        running = payload.get("running_version")
        reason = payload.get("reason", "")
        if status not in {"started", "installed", "rolled_back", "download_failed"}:
            raise ValueError("invalid update result status")
        if any(not isinstance(value, str) or not value or len(value) > 128 for value in (identifier, version, running)):
            raise ValueError("update result requires id, version, and running_version")
        if reason not in {"", "boot_validation", "boot_reset", "download", "manifest", "render_validation", "service_start"}:
            raise ValueError("invalid update result reason")
        if status == "installed" and running != version:
            raise ValueError("installed version does not match running version")
        if status == "rolled_back" and (running == version or not reason):
            raise ValueError("rollback requires a previous running version and a reason")
        with self.repository._transaction():
            ticker = self.repository.get_ticker(ticker_id)
            attempt = self.db.execute("SELECT * FROM update_attempts WHERE id=? AND ticker_id=? AND version=?", (identifier, ticker_id, version)).fetchone()
            if ticker is None or attempt is None or attempt["family"] != ticker.profile.product_family:
                raise ValueError("update result does not match an assigned attempt")
            previous = self.db.execute("SELECT * FROM update_events WHERE attempt_id=? AND status=?", (identifier, status)).fetchone()
            if previous is not None:
                if previous["running_version"] != running or previous["reason"] != reason:
                    raise ValueError("update result conflicts with the saved result")
                return {"accepted": True, "quarantined": self.quarantined(attempt["family"], version), "cancelled": 0}
            if attempt["status"] in {"installed", "rolled_back", "download_failed"}:
                raise ValueError("update attempt already has a final result")
            family = attempt["family"]
            if status == "started" and self.quarantined(family, version):
                self._event(identifier, ticker_id, family, version, "blocked", running, "release_quarantined", now)
                return {"accepted": True, "quarantined": True, "cancelled": 0}
            self.db.execute("UPDATE update_attempts SET status=?,updated_at=? WHERE id=?", (status, now, identifier))
            self._event(identifier, ticker_id, family, version, status, running, reason, now)
            if status == "rolled_back":
                self.db.execute("INSERT INTO update_releases(family,version,quarantined_at,reason) VALUES (?,?,?,?) ON CONFLICT(family,version) DO UPDATE SET quarantined_at=COALESCE(quarantined_at,excluded.quarantined_at),reason=excluded.reason", (family,version,now,reason))
            cancelled = 0
            for target in self.repository.list_tickers():
                if target.profile.product_family != family:
                    continue
                if status != "rolled_back" and (status not in {"installed", "download_failed"} or target.ticker_id != ticker_id):
                    continue
                metadata = dict(target.device.metadata)
                commands = [dict(item) for item in metadata.get("pending_commands", ()) if isinstance(item, Mapping)]
                removed = [item for item in commands if item.get("type") == "update" and item.get("payload", {}).get("version") == version and (status == "rolled_back" or item.get("id") == identifier)]
                if not removed:
                    continue
                removed_ids = {item["id"] for item in removed}
                metadata["pending_commands"] = [item for item in commands if item.get("id") not in removed_ids]
                self.repository.update_ticker(target.ticker_id, device=DeviceMetadata(last_seen_at=target.device.last_seen_at, metadata=metadata))
                for item in removed:
                    if item["id"] != identifier:
                        self.db.execute("UPDATE update_attempts SET status='cancelled',updated_at=? WHERE id=? AND status NOT IN ('installed','rolled_back')", (now,item["id"]))
                        self._event(item["id"], target.ticker_id, family, version, "cancelled", "", reason, now)
                cancelled += len(removed)
            return {"accepted": True, "quarantined": self.quarantined(family, version), "cancelled": cancelled}

    def history(self, limit: int = 200) -> dict:
        with self.repository._lock:
            return {"releases": [dict(row) for row in self.db.execute("SELECT * FROM update_releases ORDER BY family,version")],
                    "events": [dict(row) for row in self.db.execute("SELECT * FROM update_events ORDER BY event_id DESC LIMIT ?", (min(1000,max(1,limit)),))]}
