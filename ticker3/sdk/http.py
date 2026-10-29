"""Read upstream JSON once for every subscription that needs it.

The client asks for gzip, keeps bodies that carry an ETag or a Last-Modified
date, and revalidates them. Reads of one URL that start while a read is open
share that read. A caller can accept a body that is at most `reuse` seconds old.
A host can have a minimum spacing between requests, for sources with a rate rule.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from urllib3 import PoolManager
from urllib3.exceptions import HTTPError
from urllib3.util import Retry, Timeout

USER_AGENT = "Ticker3/1"


class UpstreamError(RuntimeError):
    """Describe a failed upstream read."""


@dataclass
class _Body:
    text: str
    validators: dict[str, str]
    read_at: float


class HttpClient:
    def __init__(self, *, ssl_context=None, spacing: dict[str, float] | None = None, clock: Callable[[], float] = time.monotonic,
                 kept_characters: int = 16 * 1024 * 1024) -> None:
        if ssl_context is None:
            import ssl

            import certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())
        self._pool = PoolManager(num_pools=32, maxsize=8, ssl_context=ssl_context,
                                 retries=Retry(total=None, connect=0, read=0, status=0, other=0, redirect=5))
        self._spacing = dict(spacing or {})
        self._clock = clock
        self._kept: OrderedDict[str, _Body] = OrderedDict()
        self._kept_size = 0
        self._kept_limit = kept_characters
        self._open: dict[str, asyncio.Future[str]] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_next: dict[str, float] = {}
        self.requests = 0
        self.not_modified = 0

    def close(self) -> None:
        self._pool.clear()

    async def get_json(self, url: str, *, reuse: float = 0.0, timeout: float = 10.0, accept: str = "application/json") -> Any:
        text = await self.get_text(url, reuse=reuse, timeout=timeout, accept=accept)
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise UpstreamError(f"invalid JSON from {_host(url)}: {error}") from error

    async def get_text(self, url: str, *, reuse: float = 0.0, timeout: float = 10.0, accept: str = "text/html") -> str:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        kept = self._kept.get(url)
        if kept is not None and reuse > 0 and self._clock() - kept.read_at <= reuse:
            return kept.text
        pending = self._open.get(url)
        if pending is not None:
            return await asyncio.shield(pending)
        future = asyncio.get_running_loop().create_future()
        self._open[url] = future
        try:
            text = await self._read(url, timeout, accept)
            future.set_result(text)
            return text
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as error:
            future.set_exception(error)
            # Mark the error as read. A waiter can be absent.
            future.exception()
            raise
        finally:
            del self._open[url]

    async def _read(self, url: str, timeout: float, accept: str) -> str:
        host = _host(url)
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._host_next.get(host, 0.0) - self._clock()
            if wait > 0:
                await asyncio.sleep(wait)
            kept = self._kept.get(url)
            headers = {"Accept": accept, "Accept-Encoding": "gzip, deflate", "User-Agent": USER_AGENT,
                       **(kept.validators if kept else {})}
            try:
                response = await asyncio.to_thread(self._pool.request, "GET", url, headers=headers,
                                                   timeout=Timeout(connect=timeout, read=timeout), preload_content=True)
            except (HTTPError, OSError) as error:
                raise UpstreamError(f"request to {host} failed: {error}") from error
            finally:
                self.requests += 1
                if host in self._spacing:
                    self._host_next[host] = self._clock() + self._spacing[host]
        if response.status == 304 and kept is not None:
            self.not_modified += 1
            kept.read_at = self._clock()
            self._kept.move_to_end(url)
            return kept.text
        if not 200 <= response.status < 300:
            raise UpstreamError(f"HTTP {response.status} from {host}")
        try:
            text = response.data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise UpstreamError(f"response from {host} is not UTF-8") from error
        self._keep(url, response.headers, text)
        return text

    def _keep(self, url: str, headers: Any, text: str) -> None:
        validators = {}
        if etag := headers.get("ETag"):
            validators["If-None-Match"] = etag
        if modified := headers.get("Last-Modified"):
            validators["If-Modified-Since"] = modified
        previous = self._kept.pop(url, None)
        if previous is not None:
            self._kept_size -= len(previous.text)
        if "no-store" in headers.get("Cache-Control", "").lower() or len(text) > self._kept_limit:
            return
        self._kept[url] = _Body(text, validators, self._clock())
        self._kept_size += len(text)
        while self._kept_size > self._kept_limit:
            _, evicted = self._kept.popitem(last=False)
            self._kept_size -= len(evicted.text)


def _host(url: str) -> str:
    return urlsplit(url).hostname or "unknown"
