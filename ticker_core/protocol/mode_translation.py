"""Translate retired server modes at the protocol boundary."""

from __future__ import annotations


_LEGACY_MODE_ALIASES = {
    "all": "sports",
    "live": "sports",
    "my_teams": "sports",
    "stocks": "sports",
    "golf": "sports",
    "masters": "sports",
    "indycar": "sports",
    "f1": "sports",
    "nascar": "sports",
    "soccer_full": "sports_full",
    "indycar_full": "sports_full",
    "f1_full": "sports_full",
    "nascar_full": "sports_full",
    "flight_tracker": "flights",
    "flight2": "flights",
    "poop_fetcher": "sports",
}


def translate_server_mode(value: str) -> str:
    """Map a deployed server mode into a canonical ticker mode."""

    mode = value.strip().lower()
    return _LEGACY_MODE_ALIASES.get(mode, mode)
