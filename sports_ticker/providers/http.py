"""Small injected JSON HTTP ports for native providers."""

from __future__ import annotations

import json
import math
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class JsonHttpError(RuntimeError):
    """Describe an HTTP, decoding, or JSON response failure."""


@runtime_checkable
class JsonHttpClient(Protocol):
    """Fetch one URL and decode its response as JSON."""

    def get_json(self, url: str, *, timeout: float) -> Any:
        """Return the decoded JSON response for ``url``."""


class UrllibJsonHttpClient:
    """Implement the JSON HTTP port with Python's standard library."""

    def __init__(self, *, user_agent: str = "SportsTickerBackend/8") -> None:
        self._user_agent = str(user_agent).strip() or "SportsTickerBackend/8"

    def get_json(self, url: str, *, timeout: float) -> Any:
        """Fetch and decode JSON with a required finite positive timeout."""

        target = str(url).strip()
        if not target:
            raise ValueError("url must not be empty")
        request_timeout = float(timeout)
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("timeout must be a finite positive number")

        request = Request(
            target,
            headers={"Accept": "application/json", "User-Agent": self._user_agent},
        )
        try:
            with urlopen(request, timeout=request_timeout) as response:
                body = response.read()
                status = getattr(response, "status", None)
                if status is not None and not 200 <= int(status) < 300:
                    raise JsonHttpError(f"HTTP {status} for {target}")
        except HTTPError as exc:
            raise JsonHttpError(
                f"HTTP {exc.code} for {target}: {exc.reason}"
            ) from exc
        except URLError as exc:
            raise JsonHttpError(f"request failed for {target}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise JsonHttpError(f"request timed out for {target}") from exc
        except OSError as exc:
            raise JsonHttpError(f"request failed for {target}: {exc}") from exc

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JsonHttpError(f"response was not UTF-8 for {target}") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise JsonHttpError(
                f"invalid JSON for {target} at line {exc.lineno}, column {exc.colno}"
            ) from exc


__all__ = ["JsonHttpClient", "JsonHttpError", "UrllibJsonHttpClient"]
