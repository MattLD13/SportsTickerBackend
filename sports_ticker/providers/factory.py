"""Construct exactly one provider without starting unrelated sources."""
from urllib.parse import urlencode


def create_provider(name, *, spotify=None, catalog=None, database_path=None):
    from sports_ticker.leagues import ESPN_SCOREBOARD_PATHS, FOTMOB_LEAGUES, TEAM_CATALOG_PATHS, league_for
    if name == "espn":
        from .espn import EspnScoreboardProvider
        from .espn_fastcast import EspnFastcastSource, fastcast_topic
        from .nhl_live import NhlLiveSituationSource
        urls = {}
        for league, path in ESPN_SCOREBOARD_PATHS.items():
            query = urlencode(dict(league_for(league).scoreboard_query))
            urls[league] = f"https://site.web.api.espn.com/apis/site/v2/sports/{path}/scoreboard" + ("?" + query if query else "")
        provider = EspnScoreboardProvider(urls, fastcast=EspnFastcastSource({key: fastcast_topic(url) for key, url in urls.items()}),
                                         nhl_situation_source=NhlLiveSituationSource())
        provider.own_nhl_situation_source()
        return provider
    if name == "fotmob":
        from .fotmob import FotMobSoccerProvider
        return FotMobSoccerProvider(FOTMOB_LEAGUES)
    if name == "news":
        from .catalog import EspnTeamCatalog
        from .news_source import EspnNewsSource
        from .news import NewsProvider
        from .news_transactions import NhlTradeTrackerSource
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
        from sports_ticker.integrations import SpotifyConfig, SpotifyIntegrationService, SpotifyMusicSource
        from sports_ticker.fleet import TickerRepository
        from .music import MusicProvider
        if spotify is None:
            spotify = SpotifyIntegrationService(TickerRepository(database_path), SpotifyConfig.from_environment())
        return MusicProvider(SpotifyMusicSource(spotify))
    if name == "weather":
        from .weather import HybridWeatherProvider
        return HybridWeatherProvider()
    if name == "racing":
        from .racing import RacingProvider
        from .racing_live import LiveRacingSource
        provider = RacingProvider(LiveRacingSource())
        provider.own_source()
        return provider
    if name == "golf":
        from .golf import GolfProvider
        from .golf_source import EspnGolfSource
        provider = GolfProvider(EspnGolfSource())
        provider.own_source()
        return provider
    if name == "stock":
        from .stocks import StockProvider
        from .stock_source import FinnhubStockSource
        provider = StockProvider(FinnhubStockSource())
        provider.own_source()
        return provider
    if name == "flights":
        from .flights import FlightsProvider
        from .flight_source import FlightRadarSource
        return FlightsProvider(FlightRadarSource())
    if name == "clock":
        from .clock import ClockProvider
        return ClockProvider()
    raise ValueError("unknown provider component")
