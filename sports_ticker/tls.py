"""Build the public HTTPS trust context from the maintained Certifi bundle."""

from __future__ import annotations

from functools import lru_cache
import ssl

import certifi


@lru_cache(maxsize=1)
def verified_https_context() -> ssl.SSLContext:
    """Return a cached TLS context using Certifi's maintained root bundle."""

    return ssl.create_default_context(cafile=certifi.where())


__all__ = ["verified_https_context"]
