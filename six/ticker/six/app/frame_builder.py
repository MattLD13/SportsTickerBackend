"""Convert runtime decisions into complete panel frames."""

from __future__ import annotations

import json
from typing import Any, Protocol

from PIL import Image

from ticker.six.ui.frame import RenderContext
from ticker.six.ui.news_banner import NewsBanner
from ticker.six.ui.score_alert import ScoreAlert
from ticker.six.ui import CardCatalog, ContentScene
from ticker.six.ui import FrameGeometry
from ticker.six.ui.frame import plain_mapping as _plain_mapping
from ticker.six.ui.screens import Screens, connection_lost, update_overlay
from ticker.six.runtime import Content, FrameDecision, FrameKind


class ViewportSource(Protocol):
    """Provide a frame from the current card surfaces."""

    @property
    def revision(self) -> int:
        """Identify the installed pane pixels."""

    def frame(self, offset: int, width: int = 384, height: int = 32) -> Image.Image:
        """Return one scrolling viewport frame."""


class FrameBuilder:
    """Build one frame from a pure runtime decision."""

    def __init__(
        self,
        catalog: CardCatalog,
        screens: Screens,
        score_alerts: ScoreAlert,
        news_banners: NewsBanner,
        viewport: ViewportSource,
        geometry: FrameGeometry | None = None,
    ) -> None:
        self._catalog = catalog
        self._screens = screens
        self._score_alerts = score_alerts
        self._news_banners = news_banners
        self._viewport = viewport
        self._geometry = geometry or FrameGeometry()
        self._last_base: Image.Image | None = None
        self._cached_content: Content | None = None
        self._cached_content_mapping: dict[str, Any] | None = None

    def visual_key(self, decision: FrameDecision, *, asset_revision: int | None = None) -> tuple[object, ...]:
        """Return the rendering-owned invalidation key for one decision."""
        timestamp = decision.wall_time.timestamp()
        key: list[object] = [decision.kind, decision.mode, decision.payload_key]
        context = RenderContext(decision.wall_time)
        if decision.kind is FrameKind.STATIC and decision.content is not None:
            scene = ContentScene(self._content_data(decision.content), decision.mode, decision.content_elapsed or 0.0)
            key.append(self._catalog.visual_key(context, scene, asset_revision))
        elif decision.kind is FrameKind.SCROLL:
            key.append(decision.scroll_offset)
            key.append(self._viewport.revision)
        elif decision.kind is FrameKind.EMPTY:
            key.append(int(timestamp * self._geometry.width / 60.0))
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
        key.append(_stable_value(decision.update_failure))
        key.append(decision.connection_lost)
        return tuple(key)

    def build(self, decision: FrameDecision) -> Image.Image:
        """Build a complete frame for the configured display geometry."""
        context = RenderContext(decision.wall_time)
        base = True
        if decision.kind in {FrameKind.STOPPED, FrameKind.SLEEP}:
            frame = Image.new("RGB", (self._geometry.width, self._geometry.height), "black")
        elif decision.kind == FrameKind.UPDATE:
            base = False
            frame = update_overlay(
                self._last_base or self._screens.empty(decision.wall_time),
                decision.update_progress or 0.0,
                decision.update_version or "",
            )
        elif decision.kind == FrameKind.PAIRING:
            frame = self._screens.pairing(decision.wall_time, decision.pairing_code)
        elif decision.kind == FrameKind.WIFI_SETUP:
            frame = self._screens.wifi_setup(decision.wifi_state)
        elif decision.kind == FrameKind.OFFLINE:
            frame = self._screens.offline(decision.wall_time, decision.offline_for or 0.0)
        elif decision.kind == FrameKind.SCORE_ALERT:
            base = False
            frame = self._score_alerts.frame(
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
            frame = self._screens.empty(decision.wall_time)
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
            frame = connection_lost(frame)
        if decision.update_failure is not None:
            frame = update_overlay(frame, 0.0, failure_status=decision.update_failure["status"])
        return frame

    def _panel_frame(self, frame: Image.Image) -> Image.Image:
        """Return one RGB frame before an overlay composes over it."""
        image = frame.convert("RGB")
        target = (self._geometry.width, self._geometry.height)
        if image.size == target:
            return image
        if self._geometry.fit_mode == "scale":
            return image.resize(target, Image.Resampling.NEAREST)
        if self._geometry.fit_mode == "crop":
            left = max(0, (image.width - target[0]) // 2)
            top = max(0, (image.height - target[1]) // 2)
            cropped = image.crop((left, top, min(image.width, left + target[0]), min(image.height, top + target[1])))
            frame = Image.new("RGB", target, "black")
            frame.paste(cropped, ((target[0] - cropped.width) // 2, (target[1] - cropped.height) // 2))
            return frame
        frame = Image.new("RGB", target, "black")
        visible = image.crop((0, 0, min(image.width, target[0]), min(image.height, target[1])))
        frame.paste(visible, ((target[0] - visible.width) // 2, (target[1] - visible.height) // 2))
        return frame

    def _render_content(self, context: RenderContext, content: Content, mode: str, elapsed: float) -> Image.Image:
        rendered = self._catalog.render(context, ContentScene(self._content_data(content), mode, elapsed))
        return rendered.image

    def _content_data(self, content: Content) -> dict[str, Any]:
        """Reuse the immutable content projection across animation frames."""
        if self._cached_content is not content:
            self._cached_content = content
            self._cached_content_mapping = _content_mapping(content)
        assert self._cached_content_mapping is not None
        return self._cached_content_mapping

    def _scroll_frame(self, decision: FrameDecision) -> Image.Image:
        offset = max(0, decision.scroll_offset or 0)
        return self._viewport.frame(offset, width=self._geometry.width, height=self._geometry.height)


def _content_mapping(content: Content) -> dict[str, Any]:
    """Expose explicit content identity and family facts to the renderer boundary."""
    data = _plain_mapping(content.data)
    data.setdefault("id", content.id)
    data.setdefault("type", content.type)
    data.setdefault("sport", content.sport)
    return data


def _stable_value(value: object) -> str:
    """Serialize one overlay mapping without comparing frame bytes."""
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)
