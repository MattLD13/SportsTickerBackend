"""Dependency-injected refresh service for complete ticker snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sports_ticker.domain import DisplaySettings, TickerSnapshot
from sports_ticker.providers import (
    Provider,
    ProviderHealth,
    normalize_provider_result,
    normalize_settings,
)
from sports_ticker.providers.sports_display import sports_content_sort_key

from .state_store import SnapshotStore


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """Report refresh success, staleness, provider health, and error text."""

    success: bool
    stale: bool
    health: ProviderHealth
    error: str | None = None

    @property
    def error_text(self) -> str | None:
        """Return the refresh error text for callers using an explicit name."""

        return self.error


class RefreshService:
    """Build and atomically publish complete snapshots from injected providers."""

    def __init__(self, providers: Iterable[Provider], store: SnapshotStore) -> None:
        """Capture provider ports and the snapshot store through dependency injection."""

        self._providers = tuple(providers)
        self._store = store

    def refresh(
        self,
        ticker_id: str,
        settings: DisplaySettings | Mapping[str, object] | None = None,
        provider_data: Mapping[str, object] | None = None,
    ) -> RefreshOutcome:
        """Publish one ticker snapshot from fetched data or direct provider ports."""

        effective_settings = normalize_settings(settings)
        normalized = []
        failures: list[str] = []
        if provider_data is None:
            source_results = (
                (
                    type(provider).__name__,
                    _fetch_provider(provider, str(ticker_id), effective_settings),
                )
                for provider in self._providers
            )
        else:
            source_results = provider_data.items()

        try:
            for provider_name, result in source_results:
                try:
                    normalized.append(
                        normalize_provider_result(
                            result,
                            effective_settings,
                            provider=str(provider_name),
                        )
                    )
                except Exception as error:
                    failures.append(f"{provider_name}: {error}")
        except Exception as error:
            failures.append(f"provider fetch: {error}")

        unhealthy = [result.health for result in normalized if not result.health.healthy]
        if failures or unhealthy or not normalized:
            errors = failures + [
                f"{health.provider}: {health.error or 'provider unhealthy'}"
                for health in unhealthy
            ]
            error = "; ".join(errors) if errors else "no providers configured"
            return RefreshOutcome(
                success=False,
                stale=True,
                health=ProviderHealth(
                    healthy=False,
                    provider="refresh",
                    error=error,
                ),
                error=error,
            )

        observed_at = max(
            (result.observed_at for result in normalized if result.observed_at is not None),
            default=datetime.now(timezone.utc),
        )
        content = tuple(item for result in normalized for item in result.content)
        scoreboard = iter(
            sorted(
                (item for item in content if item.family == "sports"),
                key=sports_content_sort_key,
            )
        )
        ordered_content = tuple(
            next(scoreboard) if item.family == "sports" else item for item in content
        )
        snapshot = TickerSnapshot(
            ticker_id=str(ticker_id),
            revision=0,
            observed_at=observed_at,
            content=ordered_content,
            alerts=tuple(item for result in normalized for item in result.alerts),
            news=tuple(item for result in normalized for item in result.news),
            effective_settings=effective_settings,
        )
        self._store.replace(snapshot)
        return RefreshOutcome(
            success=True,
            stale=False,
            health=ProviderHealth(healthy=True, provider="refresh"),
        )


def refresh_ticker(
    ticker_id: str,
    providers: Iterable[Provider],
    settings: DisplaySettings | Mapping[str, object] | None,
    store: SnapshotStore,
) -> RefreshOutcome:
    """Refresh one ticker using explicit provider, settings, and store dependencies."""

    return RefreshService(providers, store).refresh(ticker_id, settings)


def _fetch_provider(
    provider: Provider,
    ticker_id: str,
    settings: DisplaySettings,
) -> object:
    """Use a scoped provider method when data belongs to one ticker."""

    scoped_fetch = getattr(provider, "fetch_for_ticker", None)
    if callable(scoped_fetch):
        return scoped_fetch(ticker_id, settings)
    return provider.fetch(settings)


__all__ = ["RefreshOutcome", "RefreshService", "refresh_ticker"]
