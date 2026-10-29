"""Verify provider clients close only when their owner created them."""

import pytest

from sports_ticker.providers.catalog import EspnTeamCatalog
from sports_ticker.providers.fotmob import FotMobSoccerProvider
from sports_ticker.providers.weather import HybridWeatherProvider, OpenMeteoWeatherProvider
from sports_ticker.providers.weather_location import WeatherLocationResolver
from sports_ticker.providers.stock_catalog import StockSymbolCatalog
from sports_ticker.providers.golf_source import EspnGolfSource


class Client:
    def __init__(self, **kwargs):
        self.closed = 0

    def close(self):
        self.closed += 1

    def get_json(self, url, *, timeout):
        raise RuntimeError("source unavailable")


@pytest.mark.parametrize("factory,module", [
    (lambda client=None: EspnTeamCatalog({}, client), "catalog"),
    (lambda client=None: FotMobSoccerProvider({}, client), "fotmob"),
    (lambda client=None: OpenMeteoWeatherProvider(client), "weather"),
    (lambda client=None: HybridWeatherProvider(client), "weather"),
    (lambda client=None: WeatherLocationResolver(client), "weather_location"),
    (lambda client=None: StockSymbolCatalog(client), "stock_catalog"),
    (lambda client=None: EspnGolfSource(client), "golf_source"),
])
def test_default_client_closes_once_and_injected_client_remains_open(monkeypatch, factory, module):
    monkeypatch.setattr(f"sports_ticker.providers.{module}.PooledJsonHttpClient", Client)
    provider = factory()
    client = provider.client if module in {"weather", "weather_location"} else provider._client
    provider.close()
    provider.close()
    assert client.closed == 1

    injected = Client()
    provider = factory(injected)
    provider.close()
    assert injected.closed == 0


def test_hybrid_weather_shares_one_owned_client_with_fallback(monkeypatch):
    monkeypatch.setattr("sports_ticker.providers.weather.PooledJsonHttpClient", Client)
    provider = HybridWeatherProvider()
    assert provider.client is provider._open_meteo.client
    provider._open_meteo.close()
    assert provider.client.closed == 0
    provider.close()
    assert provider.client.closed == 1


def test_application_closes_owned_resources_once_but_not_injected_catalog(tmp_path):
    from sports_ticker.application import BackendApplication
    from sports_ticker.application.state_store import SnapshotStore
    from sports_ticker.fleet import TickerRepository

    owned = Client()
    injected_catalog = Client()
    application = BackendApplication(
        TickerRepository(tmp_path / "fleet.db"), SnapshotStore(),
        catalog=injected_catalog, owned_resources=(owned,),
    )
    application.own_resource(owned)
    application.close()
    application.close()
    assert owned.closed == 1
    assert injected_catalog.closed == 0


def test_factory_owns_golf_source_but_injected_source_stays_open(monkeypatch):
    from sports_ticker.providers.factory import create_provider
    from sports_ticker.providers.golf import GolfProvider

    monkeypatch.setattr("sports_ticker.providers.golf_source.PooledJsonHttpClient", Client)
    provider = create_provider("golf")
    client = provider._source._client
    provider.close()
    provider.close()
    assert client.closed == 1

    source = EspnGolfSource()
    GolfProvider(source).close()
    assert source._client.closed == 0
    source.close()


def test_bootstrap_closes_route_catalog_and_resolver(tmp_path, monkeypatch):
    from ticker3.offline import create_offline_application

    monkeypatch.setattr("sports_ticker.providers.weather_location.PooledJsonHttpClient", Client)
    monkeypatch.setattr("sports_ticker.providers.stock_catalog.PooledJsonHttpClient", Client)
    app = create_offline_application(tmp_path / "fleet.db", [])
    application = app.extensions["ticker.application"]
    stock_client = app.extensions["ticker.stock_catalog"]._client
    weather_client = application.weather_location_resolver.__self__.client
    application.close()
    application.close()
    assert stock_client.closed == 1
    assert weather_client.closed == 1
