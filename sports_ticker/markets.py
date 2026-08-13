"""Define durable stock groups for ticker market content."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketGroup:
    """Name one selectable market group and its ordered symbols."""

    id: str
    label: str
    symbols: tuple[str, ...]
    enabled_by_default: bool = False


MARKET_GROUPS: tuple[MarketGroup, ...] = (
    MarketGroup("stock_tech_ai", "Tech / AI Stocks", ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "AVGO", "ORCL", "CRM", "AMD", "IBM", "INTC", "QCOM", "CSCO", "ADBE", "TXN", "AMAT", "INTU", "NOW", "MU"), True),
    MarketGroup("stock_momentum", "Momentum Stocks", ("COIN", "HOOD", "DKNG", "RBLX", "GME", "AMC", "MARA", "RIOT", "CLSK", "SOFI", "OPEN", "UBER", "DASH", "SHOP", "NET", "SQ", "PYPL", "AFRM", "UPST", "CVNA")),
    MarketGroup("stock_energy", "Energy Stocks", ("XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "KMI", "HAL", "BKR", "HES", "DVN", "OKE", "WMB", "CTRA", "FANG", "TTE", "BP")),
    MarketGroup("stock_finance", "Financial Stocks", ("JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP", "V", "MA", "SCHW", "USB", "PNC", "TFC", "BK", "COF", "SPGI", "MCO", "CB", "PGR")),
    MarketGroup("stock_consumer", "Consumer Stocks", ("WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "CMG", "NKE", "LULU", "KO", "PEP", "PG", "CL", "KMB", "DIS", "NFLX", "CMCSA", "HLT", "MAR")),
)


def selected_market_groups(active: Mapping[str, object]) -> tuple[MarketGroup, ...]:
    """Return enabled market groups from one ticker setting mapping."""

    configured = {str(key).strip().lower(): bool(value) for key, value in active.items()}
    if any(group.id in configured for group in MARKET_GROUPS):
        return tuple(group for group in MARKET_GROUPS if configured.get(group.id, False))
    return tuple(group for group in MARKET_GROUPS if group.enabled_by_default)


__all__ = ["MARKET_GROUPS", "MarketGroup", "selected_market_groups"]
