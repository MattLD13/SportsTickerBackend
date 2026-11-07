"""Verify cross-provider scoreboard ordering."""

from datetime import datetime, timezone
import pytest

from sports_ticker.application.refresh import RefreshService
from sports_ticker.application.state_store import SnapshotStore
from sports_ticker.domain import ContentItem, DisplaySettings
from sports_ticker.providers.contracts import ProviderHealth, ProviderResult

pytestmark = pytest.mark.critical


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


def test_racing_and_games_share_order_on_both_ticker_contracts() -> None:
    from sports_ticker.projections.data_api import project_data_v2
    from sports_ticker.projections.device_data import project_device_data
    from ticker_core.protocol import TickerResponse
    from tools.mini.racing_vectors import game

    race = game("imsa")
    race.update(startTimeUTC="2026-08-16T00:00:00Z", state="pre")
    final = _game("final", "2026-08-15T20:00:00Z")
    final = ContentItem(id=final.id, family=final.family, kind=final.kind,
                        data={**final.data, "state": "post", "status": "FINAL"})
    store = SnapshotStore()
    service = RefreshService((Source(_game("late", "2026-08-16T01:00:00Z"), final),
                              Source(ContentItem(id="race", family="racing", kind="imsa", data=race)),
                              Source(_game("early", "2026-08-15T23:30:00Z"))), store)
    assert service.refresh("ticker-1", DisplaySettings()).success
    snapshot = store.get("ticker-1")
    assert [item.id for item in snapshot.content] == ["early", "race", "late", "final"]
    payload = project_data_v2(snapshot, ProviderHealth(provider="test"), {})
    six = TickerResponse.from_payload(payload)
    assert [item.id for item in six.content if item.family in {"sports", "racing"}] == ["early", "race", "late", "final"]
    mini = project_device_data(payload, mini=True)
    assert [item["rotation_order"] for item in mini["content"]["sports"]] == [0, 2, 3]
    assert [item["rotation_order"] for item in mini["content"]["racing"]] == [1, 1, 1, 1]


def test_snapshot_store_notifies_stream_listeners_after_replacement() -> None:
    store = SnapshotStore()
    changes = []
    listener = changes.append
    store.add_change_listener(listener)
    service = RefreshService((Source(_game("game-1", "2026-08-15T23:30:00Z")),), store)

    service.refresh("ticker-1", DisplaySettings())

    assert changes == ["ticker-1"]
    store.remove_change_listener(listener)
    service.refresh("ticker-1", DisplaySettings())
    assert changes == ["ticker-1"]
