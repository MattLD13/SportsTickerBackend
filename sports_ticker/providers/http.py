"""Bounded HTTP connection pools for provider JSON and text reads."""

from __future__ import annotations

import json
import math
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any, Protocol, runtime_checkable

from urllib3 import PoolManager
from urllib3.exceptions import HTTPError
from urllib3.util import Retry, Timeout

from sports_ticker.tls import verified_https_context


class JsonHttpError(RuntimeError):
    """Describe an HTTP, decoding, or JSON response failure."""


class OwnedClient:
    """Close a constructed client once and leave an injected client alone."""

    def __init__(self, client: Any, create: Callable[[], Any]) -> None:
        self.client = create() if client is None else client
        self._owned = client is None
        self._lock = Lock()

    def close(self) -> None:
        with self._lock:
            if not self._owned:
                return
            self._owned = False
        self.client.close()


@runtime_checkable
class JsonHttpClient(Protocol):
    """Fetch one URL and decode its response as JSON."""

    def get_json(self, url: str, *, timeout: float) -> Any:
        """Return the decoded JSON response for ``url``."""


@runtime_checkable
class TextHttpClient(Protocol):
    """Fetch one URL and return its decoded text response."""

    def get_text(self, url: str, *, timeout: float) -> str:
        """Return the response body for ``url``."""


@dataclass(frozen=True, slots=True)
class _StoredBody:
    validators: dict[str, str]
    text: str


class _PooledHttpClient:
    """Reuse verified connections across concurrent provider reads without automatic request retries.

    Each request asks for a gzip body. When a response carries an ETag or a
    Last-Modified date, the client keeps the body and sends those validators on
    the next read of the same URL. A 304 answer then returns the kept body, so an
    unchanged source costs headers only. Each read still reaches the source.
    """

    def __init__(self, *, user_agent: str = "SportsTickerBackend/8", stored_characters: int = 16 * 1024 * 1024) -> None:
        self._user_agent = str(user_agent).strip() or "SportsTickerBackend/8"
        self._stored: OrderedDict[tuple[str, str], _StoredBody] = OrderedDict()
        self._stored_size = 0
        self._stored_limit = int(stored_characters)
        self._stored_lock = Lock()
        self._pool = PoolManager(
            num_pools=16, maxsize=8,
            ssl_context=verified_https_context(),
            retries=Retry(
                total=None, connect=0, read=0, status=0, other=0, redirect=5,
                respect_retry_after_header=False,
            ),
        )

    def close(self) -> None:
        """Close retained idle connections when the owner stops this client."""
        self._pool.clear()
        with self._stored_lock:
            self._stored.clear()
            self._stored_size = 0

    def _get_text(self, url: str, *, timeout: float, accept: str) -> str:
        target = str(url).strip()
        if not target:
            raise ValueError("url must not be empty")
        request_timeout = float(timeout)
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        key = (target, accept)
        with self._stored_lock:
            stored = self._stored.get(key)
        headers = {"Accept": accept, "Accept-Encoding": "gzip, deflate", "User-Agent": self._user_agent}
        if stored is not None:
            headers.update(stored.validators)
        try:
            response = self._pool.request(
                "GET", target,
                headers=headers,
                timeout=Timeout(connect=request_timeout, read=request_timeout),
                preload_content=True,
            )
        except (HTTPError, OSError) as error:
            raise JsonHttpError(f"request failed for {target}: {error}") from error
        if response.status == 304 and stored is not None:
            with self._stored_lock:
                if key in self._stored:
                    self._stored.move_to_end(key)
            return stored.text
        if not 200 <= response.status < 300:
            raise JsonHttpError(f"HTTP {response.status} for {target}: {response.reason}")
        try:
            text = response.data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise JsonHttpError(f"response was not UTF-8 for {target}") from error
        self._store(key, response.headers, text)
        return text

    def _store(self, key: tuple[str, str], headers: Any, text: str) -> None:
        validators = {}
        if etag := headers.get("ETag"):
            validators["If-None-Match"] = etag
        if modified := headers.get("Last-Modified"):
            validators["If-Modified-Since"] = modified
        keep = bool(validators) and "no-store" not in headers.get("Cache-Control", "").lower() and len(text) <= self._stored_limit
        with self._stored_lock:
            previous = self._stored.pop(key, None)
            if previous is not None:
                self._stored_size -= len(previous.text)
            if not keep:
                return
            self._stored[key] = _StoredBody(validators, text)
            self._stored_size += len(text)
            while self._stored_size > self._stored_limit:
                _, evicted = self._stored.popitem(last=False)
                self._stored_size -= len(evicted.text)


class PooledJsonHttpClient(_PooledHttpClient):
    """Read JSON through a shared pool owned by this provider client."""

    def get_json(self, url: str, *, timeout: float) -> Any:
        """Fetch and decode JSON with a required finite positive timeout."""
        text = self._get_text(url, timeout=timeout, accept="application/json")
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise JsonHttpError(f"invalid JSON for {str(url).strip()} at line {error.lineno}, column {error.colno}") from error


class PooledTextHttpClient(_PooledHttpClient):
    """Read text through a shared pool owned by this provider client."""

    def get_text(self, url: str, *, timeout: float) -> str:
        """Fetch text with a required finite positive timeout."""
        return self._get_text(url, timeout=timeout, accept="text/html")


__all__ = [
    "JsonHttpClient", "JsonHttpError", "TextHttpClient",
    "PooledJsonHttpClient", "PooledTextHttpClient",
]
