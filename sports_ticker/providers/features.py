"""Shared ports and composition for non-scoreboard feature providers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

from sports_ticker.domain import DisplaySettings

from .contracts import Provider, ProviderHealth, ProviderResult
from .normalization import normalize_provider_result
from .stale_cache import SettingsResultCache


FeaturePayload: TypeAlias = Mapping[str, Any] | list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]


class FeatureSource(Protocol):
    """Port for one injected source of feature records."""

    def fetch(self, settings: DisplaySettings) -> FeaturePayload:
        """Return source mappings for the supplied display settings."""


class GolfSource(FeatureSource, Protocol):
    """Port for golf source data."""


class RacingSource(FeatureSource, Protocol):
    """Port for F1, IndyCar, and NASCAR source data."""


class StockSource(FeatureSource, Protocol):
    """Port for stock source data."""


class FlightsSource(FeatureSource, Protocol):
    """Port for visitor-flight and airport-HUD source data."""


class MusicSource(FeatureSource, Protocol):
    """Port for music source data."""


class NewsSource(FeatureSource, Protocol):
    """Port for news source data."""


class _FeatureProvider:
    """Provide stale-result handling for one injected feature source."""

    family = ""
    provider_name = "feature"

    def __init__(self, source: FeatureSource) -> None:
        if not callable(getattr(source, "fetch", None)):
            raise TypeError("source must provide fetch(settings)")
        self._source = source
        self._stale_cache = SettingsResultCache()

    def _fetch_normalized(
        self,
        settings: DisplaySettings,
        prepare: Callable[[FeaturePayload], Mapping[str, Any]],
        fetch: Callable[[], FeaturePayload] | None = None,
    ) -> ProviderResult:
        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")
        try:
            payload = self._source.fetch(settings) if fetch is None else fetch()
            normalized = prepare(payload)
            result = normalize_provider_result(
                normalized,
                settings,
                provider=self.provider_name,
            )
            if result.health.healthy:
                self._stale_cache.set(settings, result)
                return result
            return self._stale_result(settings, result.health.error or "source unhealthy")
        except Exception as error:
            return self._stale_result(settings, str(error) or type(error).__name__)

    def _stale_result(self, settings: DisplaySettings, error: str) -> ProviderResult:
        result = self._stale_cache.get(settings)
        if result is None:
            return ProviderResult(
                health=ProviderHealth(
                    healthy=False,
                    provider=self.provider_name,
                    error=f"stale: {error}",
                )
            )
        return ProviderResult(
            content=result.content,
            alerts=result.alerts,
            news=result.news,
            observed_at=result.observed_at,
            health=ProviderHealth(
                healthy=False,
                provider=self.provider_name,
                error=f"stale: {error}",
            ),
        )


def _content_payload(
    payload: FeaturePayload,
    family: str,
    kind_for: Callable[[dict[str, Any], str | None], str],
    family_for: Callable[[dict[str, Any], str | None], str] | None = None,
) -> Mapping[str, Any]:
    """Prepare source records while assigning canonical content families."""

    metadata, raw_content = _extract_content(payload)
    records = []
    for record, group in _records(raw_content):
        if not isinstance(record, Mapping):
            raise TypeError("feature records must be mappings")
        item = dict(record)
        item["family"] = family if family_for is None else family_for(item, group)
        item["kind"] = kind_for(item, group)
        records.append(item)
    metadata["content"] = records
    return metadata


def _news_payload(payload: FeaturePayload) -> Mapping[str, Any]:
    """Prepare source records in the result news channel, never content."""

    if not isinstance(payload, Mapping):
        raw_news = payload
        metadata: dict[str, Any] = {}
    elif "news" in payload:
        raw_news = payload["news"]
        metadata = _metadata(payload)
    elif _is_record_mapping(payload):
        raw_news = payload
        metadata = {}
    else:
        raw_news = _first(payload, "items", "content", "data")
        metadata = _metadata(payload)
        if raw_news is None:
            raw_news = () if metadata else payload

    records = []
    for record, _group in _records(raw_news):
        if not isinstance(record, Mapping):
            raise TypeError("news records must be mappings")
        records.append(dict(record))
    metadata.pop("content", None)
    metadata["news"] = records
    return metadata


def _extract_content(payload: FeaturePayload) -> tuple[dict[str, Any], Any]:
    if not isinstance(payload, Mapping):
        return {}, payload
    if _is_record_mapping(payload):
        return {}, payload
    raw_content = _first(payload, "content", "items", "games", "data")
    if raw_content is None:
        metadata = _metadata(payload)
        if metadata:
            return metadata, ()
        return {}, payload
    return _metadata(payload), raw_content


def _metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in (
            "alerts",
            "health",
            "healthy",
            "observed_at",
            "observation_time",
        )
        if key in payload
    }


def _records(value: Any, group: str | None = None) -> tuple[tuple[Any, str | None], ...]:
    if isinstance(value, Mapping):
        if _is_record_mapping(value):
            return ((value, group),)
        flattened: list[tuple[Any, str | None]] = []
        for key, item in value.items():
            if key in {"health", "healthy", "observed_at", "observation_time"}:
                continue
            if isinstance(item, (Mapping, list, tuple)):
                flattened.extend(_records(item, str(key)))
        if flattened:
            return tuple(flattened)
        if all(
            str(key).strip().lower()
            in {"health", "healthy", "observed_at", "observation_time"}
            for key in value
        ):
            return ()
        return ((value, group),)
    if isinstance(value, (list, tuple)):
        flattened = []
        for item in value:
            flattened.extend(_records(item, group))
        return tuple(flattened)
    raise TypeError("feature payload must be a mapping or list")


def _is_record_mapping(value: Mapping[str, Any]) -> bool:
    record_keys = {
        "id",
        "identifier",
        "uid",
        "key",
        "family",
        "kind",
        "type",
        "sport",
        "league",
        "series",
        "symbol",
        "headline",
        "title",
        "text",
        "name",
        "price",
        "status",
        "state",
        "is_shown",
        "visible",
        "home_abbr",
        "away_abbr",
        "home_team",
        "away_team",
        "guest_name",
    }
    return any(str(key).strip().lower() in record_keys for key in value)


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


@dataclass(frozen=True, slots=True)
class FeatureProviders:
    """Compose explicitly supplied providers for all feature families."""

    golf: Provider
    racing: Provider
    stock: Provider
    flights: Provider
    music: Provider
    news: Provider

    def __post_init__(self) -> None:
        for provider in self.as_tuple():
            if not callable(getattr(provider, "fetch", None)):
                raise TypeError("feature providers must implement fetch(settings)")

    @property
    def stocks(self) -> Provider:
        """Return the stock provider under its source-oriented plural name."""

        return self.stock

    def as_tuple(self) -> tuple[Provider, ...]:
        """Return providers in stable refresh order."""

        return (self.golf, self.racing, self.stock, self.flights, self.music, self.news)

    @property
    def providers(self) -> tuple[Provider, ...]:
        """Return the composite as an iterable provider collection."""

        return self.as_tuple()

    def __iter__(self) -> Iterable[Provider]:
        return iter(self.as_tuple())


__all__ = [
    "FeaturePayload",
    "FeatureProviders",
    "FeatureSource",
    "FlightsSource",
    "GolfSource",
    "MusicSource",
    "NewsSource",
    "RacingSource",
    "StockSource",
    "_FeatureProvider",
    "_content_payload",
    "_news_payload",
]
