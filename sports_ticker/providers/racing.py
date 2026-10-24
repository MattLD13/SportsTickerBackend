"""Adapt each racing series through its own source and stale-data scope."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sports_ticker.domain import DisplaySettings

from .contracts import ProviderHealth, ProviderResult
from .features import RacingSource, _FeatureProvider, _content_payload


class RacingProvider(_FeatureProvider):
    """Adapt one injected racing source into distinct racing kinds."""

    family = "racing"
    provider_name = "racing"

    def __init__(self, source: RacingSource) -> None:
        super().__init__(source)

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        """Fetch and normalize each enabled racing series."""

        if not isinstance(settings, DisplaySettings):
            raise TypeError("settings must be DisplaySettings")
        series = ("f1", "indycar", "nascar", "wec", "imsa")
        results = []
        failures = []
        health = {}
        for name in series:
            if not settings.active_sports.get(name, True):
                continue
            active = {**settings.active_sports, **dict.fromkeys(series, False), name: True}
            result = self._fetch_normalized(
                replace(settings, active_sports=active),
                lambda payload: _content_payload(payload, self.family, _racing_kind),
                cache_scope=name,
            )
            results.append(result)
            health[name] = {"healthy": result.health.healthy, "error": result.health.error}
            if not result.health.healthy:
                failures.append(f"{name}: {result.health.error}")
        return ProviderResult(
            content=tuple(item for result in results for item in result.content),
            observed_at=max((result.observed_at for result in results), default=None),
            health=ProviderHealth(
                healthy=not results or any(result.health.healthy for result in results),
                provider="racing", error="; ".join(failures) or None, diagnostic={"series": health},
            ),
        )


def _racing_kind(record: dict[str, Any], group: str | None) -> str:
    candidates = (
        group,
        record.get("kind"),
        record.get("type"),
        record.get("sport"),
        record.get("league"),
        record.get("series"),
    )
    for raw in candidates:
        value = str(raw or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")
        if value in {"f1", "formula1"} or "f1" in record:
            return "f1"
        if value in {"indycar", "indy"} or "indycar" in record:
            return "indycar"
        if value in {"nascar"} or "nascar" in record:
            return "nascar"
        for series in ("wec", "imsa"):
            if value == series or series in record:
                return series
    raise ValueError("racing record must identify a supported series")


__all__ = ["RacingProvider", "RacingSource"]
