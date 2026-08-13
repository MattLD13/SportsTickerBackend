"""Define the Pi and backend protocol boundary."""

from .client import (
    DATA_ENDPOINT_TEMPLATE,
    HEARTBEAT_ENDPOINT_TEMPLATE,
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
    NewsItem,
    PayloadValidationError,
    TickerSettings,
    TickerResponse,
    canonical_payload_hash,
)
from .polling import PollBackoff
from .telemetry import TelemetrySnapshot

__all__ = [
    "Alert",
    "BackendClient",
    "BackendError",
    "BackendHttpError",
    "BackendPayloadError",
    "BackendTransportError",
    "ContentItem",
    "DisplayPayload",
    "DATA_ENDPOINT_TEMPLATE",
    "DeviceState",
    "HEARTBEAT_ENDPOINT_TEMPLATE",
    "NewsItem",
    "PayloadValidationError",
    "PollBackoff",
    "TelemetrySnapshot",
    "TICKER_ENDPOINT_TEMPLATE",
    "TickerResponse",
    "canonical_payload_hash",
]
