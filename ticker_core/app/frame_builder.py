"""Convert runtime decisions into complete panel frames."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Protocol

from PIL import Image

from ticker_core.context import RenderContext
from ticker_core.features.alerts import NewsBannerRenderer, ScoreAlertRenderer
from ticker_core.features.status import ConnectionLostOverlay
from ticker_core.features.utility import UtilityRenderer
from ticker_core.rendering import ContentRendererCatalog, ContentScene
from ticker_core.runtime import Content, FrameDecision, FrameKind


class ViewportSource(Protocol):
    """Provide a frame from the current card surfaces."""

    def frame(self, offset: int, width: int = 384, height: int = 32) -> Image.Image:
        """Return one scrolling viewport frame."""


class FrameBuilder:
    """Build one frame from a pure runtime decision."""

    def __init__(
        self,
        catalog: ContentRendererCatalog,
        utility: UtilityRenderer,
        score_alerts: ScoreAlertRenderer,
        news_banners: NewsBannerRenderer,
        viewport: ViewportSource,
        connection_status: ConnectionLostOverlay | None = None,
    ) -> None:
        self._catalog = catalog
        self._utility = utility
        self._score_alerts = score_alerts
        self._news_banners = news_banners
        self._viewport = viewport
        self._connection_status = connection_status or ConnectionLostOverlay()
        self._last_base: Image.Image | None = None

    def visual_key(self, decision: FrameDecision, *, asset_revision: int | None = None) -> tuple[object, ...]:
        """Return the rendering-owned invalidation key for one decision."""
        timestamp = decision.wall_time.timestamp()
        key: list[object] = [decision.kind, decision.mode, decision.payload_key]
        context = RenderContext(decision.wall_time)
        if decision.kind is FrameKind.STATIC and decision.content is not None:
            scene = ContentScene(_content_mapping(decision.content), decision.mode, decision.content_elapsed or 0.0)
            key.append(self._catalog.visual_key(context, scene, asset_revision))
        elif decision.kind is FrameKind.SCROLL:
            key.append(decision.scroll_offset)
        elif decision.kind is FrameKind.EMPTY:
            key.append(int(timestamp * 384 / 60.0))
        elif decision.kind is FrameKind.PAIRING:
            key.append(decision.pairing_code)
            key.append(int(timestamp * 2))
        elif decision.kind is FrameKind.OFFLINE:
            key.append(int(decision.offline_for or 0.0))
            key.append(int(timestamp * 2))
        elif decision.kind is FrameKind.SCORE_ALERT:
            key.append(_stable_value(decision.alert))
            key.append(int(max(0.0, decision.alert_elapsed or 0.0) * 30))
        elif decision.kind is FrameKind.UPDATE:
            key.append(decision.update_version)
            key.append(round(decision.update_progress or 0.0, 3))
            key.append(int(timestamp * 30))
        elif decision.kind is FrameKind.WIFI_SETUP:
            key.append(repr(decision.wifi_state))
        if decision.news is not None:
            key.append(_stable_value(decision.news))
            key.append(int(max(0.0, decision.news_elapsed or 0.0) * 30))
        key.append(decision.connection_lost)
        return tuple(key)

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
        elif decision.kind == FrameKind.WIFI_SETUP:
            frame = self._utility.wifi_setup(context, decision.wifi_state)
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
            frame = self._render_content(
                context,
                decision.content,
                decision.mode,
                decision.content_elapsed or 0.0,
            )
        elif decision.kind == FrameKind.SCROLL:
            frame = self._scroll_frame(decision)
        else:
            frame = self._utility.empty(context)
        frame = self._panel_frame(frame)
        if base and decision.kind not in {FrameKind.STOPPED, FrameKind.SLEEP}:
            self._last_base = frame.copy()
        if decision.news is not None and decision.kind not in {
            FrameKind.STOPPED,
            FrameKind.SLEEP,
            FrameKind.SCORE_ALERT,
            FrameKind.WIFI_SETUP,
        }:
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

    def _render_content(self, context: RenderContext, content: Content, mode: str, elapsed: float) -> Image.Image:
        rendered = self._catalog.render(context, ContentScene(_content_mapping(content), mode, elapsed))
        return rendered.image

    def _scroll_frame(self, decision: FrameDecision) -> Image.Image:
        offset = max(0, decision.scroll_offset or 0)
        return self._viewport.frame(offset)


def _plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy frozen protocol data into renderer-friendly JSON values."""
    return {str(key): _plain(item) for key, item in value.items()}


def _content_mapping(content: Content) -> dict[str, Any]:
    """Expose explicit content identity and family facts to the renderer boundary."""
    data = _plain_mapping(content.data)
    data.setdefault("id", content.id)
    data.setdefault("type", content.type)
    data.setdefault("sport", content.sport)
    return data


def _plain(value: Any) -> Any:
    """Convert immutable protocol containers without changing scalar values."""
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _stable_value(value: object) -> str:
    """Serialize one overlay mapping without comparing frame bytes."""
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)
