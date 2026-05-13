"""Configuration constants for the Sports Ticker backend.

The first package refactor keeps implementation in ``runtime`` and exposes
stable module-level import targets for follow-up extraction work.
"""

from .core import (
    API_TIMEOUT,
    BLANK_LOGO_SENTINEL,
    BLANK_LOGO_URL,
    CACHE_TTL,
    DEFAULT_TICKER_SETTINGS,
    FOTMOB_LEAGUE_MAP,
    GAME_CACHE_FILE,
    GLOBAL_CONFIG_FILE,
    HEADERS,
    LEAGUE_OPTIONS,
    MODE_MIGRATIONS,
    SERVER_VERSION,
    SPORTS_UPDATE_INTERVAL,
    STOCKS_UPDATE_INTERVAL,
    TICKER_DATA_DIR,
    TIMEOUTS,
    VALID_MODES,
    WORKER_THREAD_COUNT,
)
