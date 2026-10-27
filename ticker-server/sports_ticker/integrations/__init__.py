"""External account integrations for the rewrite backend."""

from .spotify import (
    SpotifyConfig,
    SpotifyIntegrationError,
    SpotifyIntegrationService,
    SpotifyMusicSource,
)

__all__ = [
    "SpotifyConfig",
    "SpotifyIntegrationError",
    "SpotifyIntegrationService",
    "SpotifyMusicSource",
]
