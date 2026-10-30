"""Construct exactly one provider without starting unrelated sources."""
from urllib.parse import urlencode


def create_provider(name, *, spotify=None, catalog=None, database_path=None):
    from ticker.shared.leagues import ESPN_SCOREBOARD_PATHS, FOTMOB_LEAGUES, TEAM_CATALOG_PATHS, league_for
    if name == "espn":
        from ticker.server.providers.espn import EspnScoreboardProvider
        from ticker.server.providers.espn_fastcast import EspnFastcastSource, fastcast_topic
        from ticker.server.providers.nhl_live import NhlLiveSituationSource
        urls = {}
        for league, path in ESPN_SCOREBOARD_PATHS.items():
            query = urlencode(dict(league_for(league).scoreboard_query))
            urls[league] = f"https://site.web.api.espn.com/apis/site/v2/sports/{path}/scoreboard" + ("?" + query if query else "")
        provider = EspnScoreboardProvider(urls, fastcast=EspnFastcastSource({key: fastcast_topic(url) for key, url in urls.items()}),
                                         nhl_situation_source=NhlLiveSituationSource())
        provider.own_nhl_situation_source()
        return provider
    if name == "fotmob":
        from ticker.server.providers.fotmob import FotMobSoccerProvider
        return FotMobSoccerProvider(FOTMOB_LEAGUES)
    if name == "news":
        from ticker.server.providers.catalog import EspnTeamCatalog
        from ticker.server.providers.news_source import EspnNewsSource
        from ticker.server.providers.news import NewsProvider
        from ticker.server.providers.news_transactions import NhlTradeTrackerSource
        owns_catalog = catalog is None
        catalog = catalog if catalog is not None else EspnTeamCatalog(TEAM_CATALOG_PATHS)
        transactions = NhlTradeTrackerSource(catalog.team_name_map)
        source = EspnNewsSource({key: f"https://site.web.api.espn.com/apis/site/v2/sports/{path}/news" for key, path in TEAM_CATALOG_PATHS.items()},
                                team_color_lookup=catalog.team_colors, transaction_confirmation_source=transactions)
        source.own_dependency(transactions)
        if isinstance(catalog, EspnTeamCatalog):
            source.own_dependency(catalog.lease())
        if owns_catalog:
            source.own_dependency(catalog)
        provider = NewsProvider(source)
        provider.own_source()
        return provider
    if name == "music":
        from ticker.server.spotify import SpotifyConfig, SpotifyIntegrationService, SpotifyMusicSource
        from ticker.server.store import TickerRepository
        from ticker.server.providers.music import MusicProvider
        if spotify is None:
            spotify = SpotifyIntegrationService(TickerRepository(database_path), SpotifyConfig.from_environment())
        return MusicProvider(SpotifyMusicSource(spotify))
    if name == "weather":
        from ticker.server.providers.weather import HybridWeatherProvider
        return HybridWeatherProvider()
    if name == "racing":
        from ticker.server.providers.racing import RacingProvider
        from ticker.server.providers.racing_live import LiveRacingSource
        provider = RacingProvider(LiveRacingSource())
        provider.own_source()
        return provider
    if name == "golf":
        from ticker.server.providers.golf import GolfProvider
        from ticker.server.providers.golf_source import EspnGolfSource
        provider = GolfProvider(EspnGolfSource())
        provider.own_source()
        return provider
    if name == "stock":
        from ticker.server.providers.stocks import StockProvider
        from ticker.server.providers.stock_source import FinnhubStockSource
        provider = StockProvider(FinnhubStockSource())
        provider.own_source()
        return provider
    if name == "flights":
        from ticker.server.providers.flights import FlightsProvider
        from ticker.server.providers.flight_source import FlightRadarSource
        return FlightsProvider(FlightRadarSource())
    raise ValueError("unknown provider component")
