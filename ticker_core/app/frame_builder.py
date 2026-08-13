"""Convert runtime decisions into complete panel frames."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from PIL import Image

from ticker_core.context import RenderContext
from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from ticker_core.features.status import ConnectionLostOverlay
from ticker_core.features.utility import UtilityRenderer
from ticker_core.rendering import ContentRendererCatalog, ContentScene
from ticker_core.runtime import Content, FrameDecision, FrameKind


class StripSource(Protocol):
    """Provide the current seamless strip image."""

    def get(self, payload_key: str | None) -> Image.Image | None:
        """Return the strip for one payload key."""


class FrameBuilder:
    """Build one frame from a pure runtime decision."""

    def __init__(
        self,
        catalog: ContentRendererCatalog,
        utility: UtilityRenderer,
        score_alerts: ScoreAlertRenderer,
        news_banners: NewsBannerRenderer,
        strips: StripSource,
        connection_status: ConnectionLostOverlay | None = None,
    ) -> None:
        self._catalog = catalog
        self._utility = utility
        self._score_alerts = score_alerts
        self._news_banners = news_banners
        self._strips = strips
        self._connection_status = connection_status or ConnectionLostOverlay()
        self._last_base: Image.Image | None = None

    def build(self, decision: FrameDecision) -> Image.Image:
        """Build a complete `384x32` frame."""
        context = RenderContext(decision.wall_time)
        base = True
        if decision.kind in {FrameKind.STOPPED, FrameKind.SLEEP}:
            frame = Image.new("RGB", (384, 32), "black")
        elif decision.kind == FrameKind.UPDATE:
            base = False
            frame = self._utility.update_overlay(
                self._last_base or self._utility.empty(context),
                decision.update_progress or 0.0,
                decision.update_version or "",
            )
        elif decision.kind == FrameKind.PAIRING:
            frame = self._utility.pairing(context, decision.pairing_code)
        elif decision.kind == FrameKind.OFFLINE:
            frame = self._utility.offline(context, decision.offline_for or 0.0)
        elif decision.kind == FrameKind.SCORE_ALERT:
            base = False
            frame = self._score_alerts.render(
                decision.alert or {},
                decision.alert_elapsed or 0.0,
                self._last_base,
            )
        elif decision.kind == FrameKind.STATIC and decision.content is not None:
            frame = self._render_content(context, decision.content, decision.mode)
        elif decision.kind == FrameKind.SCROLL:
            frame = self._scroll_frame(decision)
        else:
            frame = self._utility.empty(context)
        frame = self._panel_frame(frame)
        if base and decision.kind not in {FrameKind.STOPPED, FrameKind.SLEEP}:
            self._last_base = frame.copy()
        if decision.news is not None and decision.kind not in {FrameKind.STOPPED, FrameKind.SLEEP, FrameKind.SCORE_ALERT}:
            frame = self._news_banners.apply(frame, decision.news, decision.news_elapsed or 0.0)
        frame = self._panel_frame(frame)
        if decision.connection_lost and decision.kind not in {FrameKind.STOPPED, FrameKind.SLEEP, FrameKind.OFFLINE}:
            frame = self._connection_status.apply(frame)
        return frame

    @staticmethod
    def _panel_frame(frame: Image.Image) -> Image.Image:
        """Return one RGB panel before an overlay composes over it."""
        image = frame.convert("RGB")
        if image.size == (384, 32):
            return image
        canvas = Image.new("RGB", (384, 32), "black")
        canvas.paste(image.crop((0, 0, 384, 32)), (0, 0))
        return canvas

    def _render_content(self, context: RenderContext, content: Content, mode: str) -> Image.Image:
        rendered = self._catalog.render(context, ContentScene(_plain_mapping(content.data), mode))
        return rendered.image

    def _scroll_frame(self, decision: FrameDecision) -> Image.Image:
        strip = self._strips.get(decision.payload_key)
        if strip is None:
            if self._last_base is not None:
                return self._last_base.copy()
            return self._utility.empty(RenderContext(decision.wall_time))
        offset = max(0, decision.scroll_offset or 0)
        return strip.crop((offset, 0, offset + 384, 32))


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy frozen protocol data into renderer-friendly JSON values."""
    return {str(key): _plain(item) for key, item in value.items()}


def _plain(value: Any) -> Any:
    """Convert immutable protocol containers without changing scalar values."""
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
