"""Keep tickers, tokens, playlists, and the last manifest of each feature in SQLite.

The store keeps only the SHA-256 of each token. A pairing code works once and expires.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from .hub import App

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, timezone TEXT NOT NULL, device_token TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS app_tokens (token TEXT PRIMARY KEY, ticker_id TEXT NOT NULL REFERENCES tickers(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS pairing (code TEXT PRIMARY KEY, ticker_id TEXT NOT NULL REFERENCES tickers(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS apps (ticker_id TEXT NOT NULL REFERENCES tickers(id) ON DELETE CASCADE, position INTEGER NOT NULL,
    app_id TEXT NOT NULL, feature TEXT NOT NULL, settings TEXT NOT NULL, PRIMARY KEY (ticker_id, position));
CREATE TABLE IF NOT EXISTS manifests (feature TEXT PRIMARY KEY, manifest TEXT NOT NULL, updated_at REAL NOT NULL);
"""


@dataclass(frozen=True)
class Ticker:
    id: str
    name: str
    timezone: str


@dataclass(frozen=True)
class NewTicker:
    ticker: Ticker
    device_token: str
    pairing_code: str


class Store:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time, pairing_seconds: float = 900) -> None:
        self.clock, self.pairing_seconds = clock, pairing_seconds
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        self._lock = Lock()

    def close(self) -> None:
        self._db.close()

    def create_ticker(self, name: str, timezone: str) -> NewTicker:
        ticker = Ticker(secrets.token_hex(6), name, timezone)
        device_token = secrets.token_urlsafe(32)
        with self._lock, self._db:
            self._db.execute("INSERT INTO tickers VALUES (?, ?, ?, ?, ?)", (ticker.id, name, timezone, _hash(device_token), self.clock()))
            code = self._new_code(ticker.id)
        return NewTicker(ticker, device_token, code)

    def pairing_code(self, ticker_id: str) -> str:
        with self._lock, self._db:
            return self._new_code(ticker_id)

    def pair(self, code: str) -> tuple[str, str] | None:
        """Exchange a valid pairing code for an app token. Return the ticker ID and the token."""
        with self._lock, self._db:
            row = self._db.execute("SELECT ticker_id, expires_at FROM pairing WHERE code = ?", (code,)).fetchone()
            if row is None:
                return None
            self._db.execute("DELETE FROM pairing WHERE code = ?", (code,))
            if row[1] < self.clock():
                return None
            token = secrets.token_urlsafe(32)
            self._db.execute("INSERT INTO app_tokens VALUES (?, ?)", (_hash(token), row[0]))
            return row[0], token

    def ticker_for_device(self, token: str) -> Ticker | None:
        return self._ticker("SELECT id, name, timezone FROM tickers WHERE device_token = ?", _hash(token))

    def ticker_for_app(self, token: str, ticker_id: str) -> Ticker | None:
        return self._ticker("SELECT t.id, t.name, t.timezone FROM tickers t JOIN app_tokens a ON a.ticker_id = t.id "
                            "WHERE a.token = ? AND t.id = ?", _hash(token), ticker_id)

    def update_ticker(self, ticker_id: str, *, name: str | None = None, timezone: str | None = None) -> None:
        with self._lock, self._db:
            if name is not None:
                self._db.execute("UPDATE tickers SET name = ? WHERE id = ?", (name, ticker_id))
            if timezone is not None:
                self._db.execute("UPDATE tickers SET timezone = ? WHERE id = ?", (timezone, ticker_id))

    def tickers(self) -> list[Ticker]:
        with self._lock:
            return [Ticker(*row) for row in self._db.execute("SELECT id, name, timezone FROM tickers ORDER BY created_at")]

    def apps(self, ticker_id: str) -> list[App]:
        with self._lock:
            rows = self._db.execute("SELECT app_id, feature, settings FROM apps WHERE ticker_id = ? ORDER BY position", (ticker_id,))
            return [App(app_id, feature, json.loads(settings)) for app_id, feature, settings in rows]

    def set_apps(self, ticker_id: str, apps: list[App]) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM apps WHERE ticker_id = ?", (ticker_id,))
            self._db.executemany("INSERT INTO apps VALUES (?, ?, ?, ?, ?)",
                                 [(ticker_id, position, app.id, app.feature, json.dumps(app.settings)) for position, app in enumerate(apps)])

    def manifests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute("SELECT manifest FROM manifests ORDER BY feature")]

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        stored = {**manifest, "templates": list(manifest["templates"].values())} if isinstance(manifest["templates"], dict) else manifest
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO manifests VALUES (?, ?, ?)", (manifest["feature"], json.dumps(stored), self.clock()))

    def _ticker(self, query: str, *parameters: str) -> Ticker | None:
        with self._lock:
            row = self._db.execute(query, parameters).fetchone()
        return Ticker(*row) if row else None

    def _new_code(self, ticker_id: str) -> str:
        self._db.execute("DELETE FROM pairing WHERE expires_at < ?", (self.clock(),))
        while True:
            code = f"{secrets.randbelow(1_000_000):06d}"
            if self._db.execute("SELECT 1 FROM pairing WHERE code = ?", (code,)).fetchone() is None:
                break
        self._db.execute("INSERT INTO pairing VALUES (?, ?, ?)", (code, ticker_id, self.clock() + self.pairing_seconds))
        return code


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
