"""Shared messages, records, settings, and templates for every Ticker 3 part."""

PROTOCOL = 1
# The providers that run in worker processes. The core makes the clock result itself.
WORKERS = ("espn", "fotmob", "weather", "golf", "racing", "stock", "flights", "music", "news")


class ContractError(ValueError):
    """Describe a message, record, setting, or template that breaks the contract."""
