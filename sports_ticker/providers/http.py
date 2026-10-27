"""Bounded HTTP connection pools for provider JSON and text reads."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
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


class _PooledHttpClient:
    """Reuse verified connections across concurrent provider reads without automatic request retries."""

    def __init__(self, *, user_agent: str = "SportsTickerBackend/8") -> None:
        self._user_agent = str(user_agent).strip() or "SportsTickerBackend/8"
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

    def _get_text(self, url: str, *, timeout: float, accept: str) -> str:
        target = str(url).strip()
        if not target:
            raise ValueError("url must not be empty")
        request_timeout = float(timeout)
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        try:
            response = self._pool.request(
                "GET", target,
                headers={"Accept": accept, "User-Agent": self._user_agent},
                timeout=Timeout(connect=request_timeout, read=request_timeout),
                preload_content=True,
            )
        except (HTTPError, OSError) as error:
            raise JsonHttpError(f"request failed for {target}: {error}") from error
        if not 200 <= response.status < 300:
            raise JsonHttpError(f"HTTP {response.status} for {target}: {response.reason}")
        try:
            return response.data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise JsonHttpError(f"response was not UTF-8 for {target}") from error


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
