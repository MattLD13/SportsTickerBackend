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
    DeviceRegistration,
    REGISTRATION_ENDPOINT,
)
from .model import (
    Alert,
    ContentItem,
    DisplayDelta,
    DisplayItemDelta,
    DisplayPayload,
    DeviceState,
    NewsItem,
    PayloadValidationError,
    TickerSettings,
    TickerResponse,
    apply_display_delta,
    canonical_payload_hash,
    display_delta,
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
    "DeviceRegistration",
    "ContentItem",
    "DisplayDelta",
    "DisplayItemDelta",
    "DisplayPayload",
    "DATA_ENDPOINT_TEMPLATE",
    "DeviceState",
    "HEARTBEAT_ENDPOINT_TEMPLATE",
    "NewsItem",
    "PayloadValidationError",
    "PollBackoff",
    "REGISTRATION_ENDPOINT",
    "TelemetrySnapshot",
    "TICKER_ENDPOINT_TEMPLATE",
    "TickerResponse",
    "apply_display_delta",
    "canonical_payload_hash",
    "display_delta",
]
