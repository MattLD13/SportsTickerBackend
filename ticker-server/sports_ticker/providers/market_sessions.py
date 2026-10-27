"""Own regular US equity sessions, holidays, early closes, and final-close refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache


@lru_cache(maxsize=3)
def _calendar(year: int):
    import exchange_calendars
    return exchange_calendars.get_calendar("XNYS", start=f"{year - 1}-01-01", end=f"{year + 1}-12-31")


@dataclass(frozen=True)
class MarketSession:
    open: bool
    closed_session: str | None


def us_equity_session(timestamp: float) -> MarketSession:
    """Use XNYS regular hours and wait one minute before fetching the final close."""
    current = datetime.fromtimestamp(timestamp, timezone.utc)
    calendar = _calendar(current.year)
    session = calendar.date_to_session(current.date().isoformat(), direction="previous")
    opened = calendar.session_open(session).to_pydatetime()
    closed = calendar.session_close(session).to_pydatetime()
    if opened <= current < closed:
        return MarketSession(True, None)
    if current < opened:
        session = calendar.previous_session(session)
        closed = calendar.session_close(session).to_pydatetime()
    if (current - closed).total_seconds() < 60:
        return MarketSession(False, None)
    return MarketSession(False, session.date().isoformat())
