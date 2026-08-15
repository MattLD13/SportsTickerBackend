"""Provider ports and canonical payload normalization."""

from .contracts import Provider, ProviderHealth, ProviderPort, ProviderResult
from .catalog import EspnTeamCatalog
from .espn import EspnScoreboardProvider
from .fotmob import FotMobSoccerProvider
from .features import (
    FeaturePayload,
    FeatureProviders,
    FeatureSource,
    FlightsSource,
    GolfSource,
    MusicSource,
    NewsSource,
    RacingSource,
    StockSource,
)
from .flights import FlightsProvider
from .golf import GolfProvider
from .http import (
    JsonHttpClient,
    JsonHttpError,
    TextHttpClient,
    UrllibJsonHttpClient,
    UrllibTextHttpClient,
)
from .music import MusicProvider
from .normalization import normalize_content, normalize_provider_result, normalize_settings
from .news import NewsProvider
from .racing import RacingProvider
from .racing_live import LiveRacingSource
from .score_alerts import ScoreAlertTracker
from .stocks import StockProvider
from .weather import OpenMeteoWeatherProvider

__all__ = [
    "Provider",
    "ProviderHealth",
    "ProviderPort",
    "ProviderResult",
    "EspnScoreboardProvider",
    "FotMobSoccerProvider",
    "EspnTeamCatalog",
    "FeaturePayload",
    "FeatureProviders",
    "FeatureSource",
    "FlightsProvider",
    "FlightsSource",
    "GolfProvider",
    "GolfSource",
    "JsonHttpClient",
    "JsonHttpError",
    "LiveRacingSource",
    "MusicProvider",
    "MusicSource",
    "NewsProvider",
    "NewsSource",
    "OpenMeteoWeatherProvider",
    "RacingProvider",
    "RacingSource",
    "ScoreAlertTracker",
    "StockProvider",
    "StockSource",
    "TextHttpClient",
    "UrllibJsonHttpClient",
    "UrllibTextHttpClient",
    "normalize_content",
    "normalize_provider_result",
    "normalize_settings",
]
