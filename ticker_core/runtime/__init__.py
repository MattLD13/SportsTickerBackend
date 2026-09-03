"""State and timing services for the rewritten Pi controller."""

from .model import (
    Content,
    ContentClassification,
    DEFAULT_SCORE_ALERT_DURATION,
    FrameDecision,
    FrameKind,
    ModeRequest,
    PayloadSnapshot,
    RuntimeConfig,
    StripLayout,
    StripSegment,
    UpdateRequest,
)
from .pacing import FramePacer
from .state import CANONICAL_MODES, TickerRuntime, classify_content, remap_strip_offset

__all__ = [
    "Content",
    "CANONICAL_MODES",
    "ContentClassification",
    "DEFAULT_SCORE_ALERT_DURATION",
    "FrameDecision",
    "FrameKind",
    "FramePacer",
    "ModeRequest",
    "PayloadSnapshot",
    "RuntimeConfig",
    "StripLayout",
    "StripSegment",
    "TickerRuntime",
    "UpdateRequest",
    "classify_content",
    "remap_strip_offset",
]
