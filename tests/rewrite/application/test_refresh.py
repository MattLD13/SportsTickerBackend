"""Verify cross-provider scoreboard ordering."""

from datetime import datetime, timezone

from sports_ticker.application.refresh import RefreshService
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.domain import ContentItem, DisplaySettings
from sports_ticker.providers.contracts import ProviderHealth, ProviderResult


class Source:
    def __init__(self, *items: ContentItem) -> None:
        self.items = items

    def fetch(self, settings: DisplaySettings) -> ProviderResult:
        del settings
        return ProviderResult(
            content=self.items,
            observed_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            health=ProviderHealth(provider="test"),
        )


def _game(identifier: str, start: str) -> ContentItem:
    return ContentItem(
        id=identifier,
        family="sports",
        kind="scoreboard",
        data={"sport": "soccer_mls", "state": "pre", "startTimeUTC": start},
    )


def test_refresh_interleaves_espn_and_fotmob_scoreboards_by_start_time() -> None:
    store = SnapshotStore()
    service = RefreshService(
        (
            Source(_game("nfl-later", "2026-08-16T01:00:00Z")),
            Source(_game("mls-earlier", "2026-08-15T23:30:00Z")),
        ),
        store,
    )

    outcome = service.refresh("ticker-1", DisplaySettings())

    assert outcome.success
    snapshot = store.get("ticker-1")
    assert snapshot is not None
    assert [item.id for item in snapshot.content] == ["mls-earlier", "nfl-later"]
