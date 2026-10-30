"""Check that background shutdown does not close an active client."""

from threading import Event, Thread

from ticker.server.providers.background import BackgroundTask
from ticker.server.providers.factory import create_provider


def test_background_cleanup_waits_until_the_active_request_finishes():
    started, release, cleaned = Event(), Event(), Event()
    worker = BackgroundTask(cleaned.set, wait_seconds=0.01)

    def request():
        started.set()
        assert release.wait(2)
        assert not cleaned.is_set()

    assert worker.start(request, name="test-request")
    assert started.wait(2)
    worker.close()
    worker.close()
    assert not cleaned.is_set()
    assert not worker.start(request, name="late-request")
    release.set()
    assert cleaned.wait(2)


def test_close_during_thread_start_prevents_the_request():
    entering_start, allow_start, cleaned, requested = Event(), Event(), Event(), Event()

    class DelayedStart(Thread):
        def start(self):
            entering_start.set()
            assert allow_start.wait(2)
            super().start()

    worker = BackgroundTask(cleaned.set, wait_seconds=0.01, thread_factory=DelayedStart)
    starter = Thread(target=lambda: worker.start(requested.set, name="delayed"))
    starter.start()
    assert entering_start.wait(2)
    worker.close()
    assert not cleaned.is_set()
    allow_start.set()
    starter.join(2)
    assert not starter.is_alive()
    assert cleaned.wait(2)
    assert not requested.is_set()


def test_cleanup_failure_is_not_repeated():
    calls = []

    def cleanup():
        calls.append(1)
        raise RuntimeError("close failed")

    worker = BackgroundTask(cleanup)
    import pytest
    with pytest.raises(RuntimeError, match="close failed"):
        worker.close()
    worker.close()
    assert calls == [1]


def test_factory_owned_news_dependencies_preserve_injected_catalog():
    class Catalog:
        closed = 0
        def team_colors(self, league): return {}
        def team_name_map(self, league): return {}
        def close(self): self.closed += 1

    catalog = Catalog()
    provider = create_provider("news", catalog=catalog)
    provider.close()
    provider.close()
    assert catalog.closed == 0


def test_shared_catalog_waits_for_news_lease(monkeypatch):
    from ticker.server.providers.catalog import EspnTeamCatalog

    class Client:
        closed = 0
        def close(self): self.closed += 1

    monkeypatch.setattr("ticker.server.providers.catalog.PooledJsonHttpClient", Client)
    catalog = EspnTeamCatalog({})
    provider = create_provider("news", catalog=catalog)
    client = catalog._client
    catalog.close()
    assert client.closed == 0
    provider.close()
    assert client.closed == 1
    catalog.close()
    assert client.closed == 1
