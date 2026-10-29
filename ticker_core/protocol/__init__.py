"""Define the Pi and backend protocol boundary."""

from .client import (
    BackendClient,
    BackendError,
    BackendHttpError,
    BackendPayloadError,
    BackendTransportError,
    DeviceRegistration,
    REGISTRATION_ENDPOINT,
)
from .stream import DeviceStreamState, StreamMessage
from .model import (
    Alert,
    ContentItem,
    DisplayDelta,
    DisplayItemDelta,
    DisplayPayload,
    DeviceState,
    NewsItem,
    PayloadValidationError,
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
    "DeviceStreamState",
    "ContentItem",
    "DisplayDelta",
    "DisplayItemDelta",
    "DisplayPayload",
    "DeviceState",
    "NewsItem",
    "PayloadValidationError",
    "PollBackoff",
    "REGISTRATION_ENDPOINT",
    "StreamMessage",
    "TelemetrySnapshot",
    "TickerResponse",
    "apply_display_delta",
    "canonical_payload_hash",
    "display_delta",
]
