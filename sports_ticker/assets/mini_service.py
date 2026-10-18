"""Prepare public Mini sprites in one bounded background asset service."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
from threading import RLock
import time
from typing import Callable
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import requests

from .mini_sprite import SpritePolicy, WIRE_BYTES, encode_sprite, validate_sprite


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_HOSTS = frozenset({
    "i.scdn.co",
    "a.espncdn.com", "raw.githubusercontent.com", "images.fotmob.com",
    "assets.nhle.com", "upload.wikimedia.org", "cdn.nba.com",
})
SOURCE_LIMIT = 256 * 1024


@dataclass(frozen=True, slots=True)
class SourceReply:
    """Carry one bounded source response and its conditional request validators."""

    body: bytes | None
    etag: str = ""
    modified: str = ""


def fetch_source(url: str, etag: str, modified: str) -> SourceReply:
    """Fetch approved public image hosts with bounded redirects and image bytes."""
    headers = {"User-Agent": "SportsTickerMiniSprites/1", "Accept": "image/png,image/jpeg"}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    for _ in range(4):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _HOSTS or parsed.username or parsed.port not in {None, 443}:
            raise ValueError("unsupported public logo source")
        with requests.get(url, headers=headers, stream=True, timeout=(3, 6), allow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code == 304:
                return SourceReply(None, response.headers.get("ETag", etag), response.headers.get("Last-Modified", modified))
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(8192):
                body.extend(chunk)
                if len(body) > SOURCE_LIMIT:
                    raise ValueError("logo source exceeds the download limit")
            if not body:
                raise ValueError("logo source is empty")
            return SourceReply(bytes(body), response.headers.get("ETag", ""), response.headers.get("Last-Modified", ""))
    raise ValueError("logo source exceeds the redirect limit")


class MiniSpriteService:
    """Own source refresh, sprite identity, validated storage, and background preparation."""

    def __init__(
        self, directory: str | Path, *, policy: SpritePolicy = SpritePolicy(),
        fetcher: Callable[[str, str, str], SourceReply] = fetch_source,
        clock: Callable[[], float] = time.time, refresh_seconds: float = 900,
        max_entries: int = 256, max_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if refresh_seconds <= 0 or max_entries < 1 or max_bytes < SOURCE_LIMIT + WIRE_BYTES:
            raise ValueError("invalid Mini asset cache limits")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.policy, self._fetch, self._clock = policy, fetcher, clock
        self._refresh = refresh_seconds
        self._max_entries, self._max_bytes = max_entries, max_bytes
        self._lock = RLock()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mini-sprites")
        self._pending: dict[str, Future] = {}
        self._entries: dict[str, dict] = {}
        self._checksums: dict[str, str] = {}
        self._retry: dict[str, float] = {}
        self._closed = False
        try:
            index = json.loads((self.directory / "index.json").read_text())
            for identity, checksum in index["checksums"].items():
                try:
                    if (_DIGEST.fullmatch(identity) and _DIGEST.fullmatch(checksum)
                            and validate_sprite((self.directory / f"{identity}.mts").read_bytes(), checksum)):
                        self._checksums[identity] = checksum
                except (OSError, TypeError):
                    continue
            for url, entry in index["entries"].items():
                if self._valid_entry(entry):
                    self._entries[url] = entry
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            pass

    def _valid_entry(self, entry: dict) -> bool:
        try:
            return (
                isinstance(entry["checked_at"], (int, float)) and math.isfinite(entry["checked_at"])
                and isinstance(entry.get("etag", ""), str) and isinstance(entry.get("modified", ""), str)
                and bool(_DIGEST.fullmatch(entry["asset_id"]))
                and bool(_DIGEST.fullmatch(entry["source_sha256"]))
                and self._checksums.get(entry["asset_id"]) == entry["sha256"]
                and validate_sprite((self.directory / f'{entry["asset_id"]}.mts').read_bytes(), entry["sha256"])
                and self.policy.identity((self.directory / f'{entry["source_sha256"]}.src').read_bytes()) == entry["asset_id"]
            )
        except (OSError, KeyError, TypeError):
            return False

    def reference(self, *source_urls: str) -> dict:
        """Return ready metadata or queue preparation without waiting for network work."""
        source_urls = tuple(dict.fromkeys(url for url in source_urls if url))
        if not source_urls:
            return {"state": "unavailable"}
        source_url = hashlib.sha256(json.dumps(source_urls).encode()).hexdigest()
        with self._lock:
            entry = self._entries.get(source_url)
            now = self._clock()
            fresh = entry is not None and now - entry["checked_at"] < self._refresh
            if not fresh and now >= self._retry.get(source_url, 0) and source_url not in self._pending and not self._closed:
                if len(self._pending) < 64:
                    self._pending[source_url] = self._worker.submit(self._prepare, source_url, source_urls)
            if entry is None:
                return {"state": "pending" if source_url in self._pending else "unavailable"}
            return {
                "state": "ready", "asset_id": entry["asset_id"], "sha256": entry["sha256"],
                "url": f'/api/v2/assets/mini-sports/{entry["asset_id"]}.mts',
                "length": WIRE_BYTES, "width": 18, "height": 18,
                "format": "rgb565-le-mask-lsb", "pipeline_version": self.policy.pipeline_version,
                "refreshing": not fresh,
            }

    def _prepare(self, url: str, source_urls: tuple[str, ...]) -> None:
        try:
            with self._lock:
                previous = dict(self._entries.get(url, {}))
            for candidate in source_urls:
                try:
                    with self._lock:
                        shared = next((dict(entry) for entry in self._entries.values() if entry.get("chosen_source") == candidate and self._clock() - entry["checked_at"] < self._refresh), None)
                    if shared is not None:
                        source = (self.directory / f'{shared["source_sha256"]}.src').read_bytes()
                        reply = SourceReply(source, shared.get("etag", ""), shared.get("modified", ""))
                        checked_at = shared["checked_at"]
                    else:
                        same_source = previous.get("chosen_source") == candidate
                        reply = self._fetch(candidate, previous.get("etag", "") if same_source else "", previous.get("modified", "") if same_source else "")
                        source = reply.body if reply.body is not None else (self.directory / f'{previous["source_sha256"]}.src').read_bytes()
                        checked_at = self._clock()
                    if not 0 < len(source) <= SOURCE_LIMIT:
                        raise ValueError("invalid Mini logo source size")
                    asset_id, body = encode_sprite(source, self.policy)
                    break
                except (OSError, ValueError, KeyError, requests.RequestException):
                    if candidate == source_urls[-1]:
                        raise
            checksum = hashlib.sha256(body).hexdigest()
            if not validate_sprite(body, checksum):
                raise ValueError("invalid prepared Mini sprite")
            source_hash = hashlib.sha256(source).hexdigest()
            self._atomic_file(self.directory / f"{source_hash}.src", source)
            self._atomic_file(self.directory / f"{asset_id}.mts", body)
            with self._lock:
                self._checksums[asset_id] = checksum
                self._entries[url] = {
                    "asset_id": asset_id, "sha256": checksum, "source_sha256": source_hash,
                    "etag": reply.etag, "modified": reply.modified, "checked_at": checked_at, "chosen_source": candidate,
                }
                self._retry.pop(url, None)
                self._prune(asset_id, source_hash)
                self._atomic_file(self.directory / "index.json", json.dumps({
                    "entries": self._entries, "checksums": self._checksums,
                }, sort_keys=True).encode())
        except (OSError, ValueError, KeyError, requests.RequestException):
            with self._lock:
                self._retry[url] = self._clock() + 60
                if len(self._retry) > self._max_entries:
                    self._retry.pop(next(iter(self._retry)))
        finally:
            with self._lock:
                self._pending.pop(url, None)

    @staticmethod
    def _atomic_file(path: Path, body: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _prune(self, asset_id: str, source_hash: str) -> None:
        if len(self._entries) > self._max_entries:
            self._entries = dict(sorted(self._entries.items(), key=lambda item: item[1]["checked_at"], reverse=True)[:self._max_entries])
        protected = {f"{asset_id}.mts", f"{source_hash}.src"}
        files = sorted(
            (path for path in self.directory.iterdir() if path.suffix in {".mts", ".src"}),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        total = sum(path.stat().st_size for path in files)
        count = sum(path.suffix == ".mts" for path in files)
        for path in files:
            if total <= self._max_bytes and count <= self._max_entries:
                break
            if path.name in protected:
                continue
            total -= path.stat().st_size
            count -= int(path.suffix == ".mts")
            path.unlink()
        self._entries = {
            url: entry for url, entry in self._entries.items()
            if (self.directory / f'{entry["asset_id"]}.mts').exists()
            and (self.directory / f'{entry["source_sha256"]}.src').exists()
        }
        self._checksums = {
            identity: checksum for identity, checksum in self._checksums.items()
            if (self.directory / f"{identity}.mts").exists()
        }

    def read(self, asset_id: str) -> tuple[bytes, str] | None:
        """Serve only validated, already prepared public image content."""
        if not _DIGEST.fullmatch(asset_id):
            return None
        with self._lock:
            try:
                body = (self.directory / f"{asset_id}.mts").read_bytes()
            except OSError:
                self._entries = {url: entry for url, entry in self._entries.items() if entry["asset_id"] != asset_id}
                return None
            checksum = self._checksums.get(asset_id, "")
            if validate_sprite(body, checksum):
                return body, checksum
            self._checksums.pop(asset_id, None)
            self._entries = {url: entry for url, entry in self._entries.items() if entry["asset_id"] != asset_id}
            return None

    def wait(self) -> None:
        """Wait for queued jobs during an offline validation or controlled shutdown."""
        with self._lock:
            pending = tuple(self._pending.values())
        for job in pending:
            job.result()

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._worker.shutdown(wait=True, cancel_futures=True)
