"""Shared messages, records, settings, and templates for every Ticker 3 part."""

PROTOCOL = 1
# The import roots of the Python products in a release folder. Python merges their `ticker` folders.
SOURCE_ROOTS = ("shared", "server", "six")
# The providers that run in worker processes. The core makes the clock result itself.
WORKERS = ("espn", "fotmob", "weather", "golf", "racing", "stock", "flights", "music", "news")


class ContractError(ValueError):
    """Describe a message, record, setting, or template that breaks the contract."""
