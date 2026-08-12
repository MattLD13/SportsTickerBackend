"""Define the Pi and backend protocol boundary."""

from .client import (
    CONFIG_ENDPOINT,
    DATA_ENDPOINT,
    TICKER_ENDPOINT_TEMPLATE,
    BackendClient,
    BackendError,
    BackendHttpError,
    BackendPayloadError,
    BackendTransportError,
)
from .model import (
    Alert,
    ContentItem,
    DisplayPayload,
    DeviceState,
    GlobalConfig,
    LocalConfig,
    NewsItem,
    PayloadValidationError,
    TickerResponse,
    canonical_payload_hash,
)
from .mode_translation import translate_server_mode
from .polling import PollBackoff
from .telemetry import TelemetrySnapshot, build_poll_headers

__all__ = [
    "Alert",
    "BackendClient",
    "BackendError",
    "BackendHttpError",
    "BackendPayloadError",
    "BackendTransportError",
    "CONFIG_ENDPOINT",
    "ContentItem",
    "DisplayPayload",
    "DATA_ENDPOINT",
    "DeviceState",
    "GlobalConfig",
    "LocalConfig",
    "NewsItem",
    "PayloadValidationError",
    "PollBackoff",
    "TelemetrySnapshot",
    "TICKER_ENDPOINT_TEMPLATE",
    "TickerResponse",
    "build_poll_headers",
    "canonical_payload_hash",
    "translate_server_mode",
]
