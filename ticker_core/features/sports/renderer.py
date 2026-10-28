"""Render score cards without controller state or network access."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from PIL import Image, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.rendering import ContentScene, FontSet, RenderedContent
from ticker_core.rendering.pixels import draw_hybrid_text, draw_tiny_text, normalize_special_chars

from .pinned import PreparedSportsFullRenderer, hockey_page_count
from .logo_rendering import get_prepared_team_logo
from .stadium_port import PreparedStadiumRenderer

PANEL_H = 32
SPORTS_AD_MIN_WIDTH = 112
SPORTS_AD_MAX_WIDTH = 160


class LogoSource(Protocol):
    """Load a prepared logo without network access."""

    def get(self, url: str | None, size: tuple[int, int]) -> Image.Image | None:
        """Return one prepared RGBA logo."""


def _hex(value: Any, fallback: tuple[int, int, int] = (80, 80, 80)) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            pass
    return fallback


def _dark(color: tuple[int, int, int], factor: float = 0.5) -> tuple[int, int, int]:
    return tuple(int(channel * (1 - factor)) for channel in color)


def _is_sports_ad(game: Mapping[str, Any]) -> bool:
    """Return if one scene owns the campaign-parody renderer."""

    return str(game.get("type") or game.get("kind") or "").strip().lower() == "fan_duel_joke_ad"


def _sports_ad_width(game: Mapping[str, Any]) -> int:
    """Return a compact width for one campaign-parody card."""

    lines = (
        game.get("headline", "FANDUEL"),
        game.get("tagline", ""),
        game.get("detail", "PARODY"),
    )
    largest = max(
        (len(normalize_special_chars(line)) * 5 for line in lines),
        default=0,
    )
    return max(
        SPORTS_AD_MIN_WIDTH,
        min(SPORTS_AD_MAX_WIDTH, 32 + largest + 4),
    )


class SportsRenderer:
    """Render the scoreboard and full sports card families."""

    def __init__(self, fonts: FontSet, logos: LogoSource) -> None:
        self._fonts = fonts
        self._logos = logos
        self._stadium = PreparedStadiumRenderer(logos)
        self._full = PreparedSportsFullRenderer(fonts, logos)
        self._visual_item: Mapping[str, Any] | None = None
        self._visual_item_json: str | None = None
        self._asset_item: Mapping[str, Any] | None = None
        self._asset_revision: int | None = None
        self._pinned_asset_state: tuple[bool, bool] = (False, False)

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render one score card or a 384 pixel full display."""
        if scene.item.get("sports_presentation") == "pinned":
            return RenderedContent(self.render_full(scene.item, page_tick=int(context.now.timestamp()) // 5))
        return RenderedContent(self.render_strip((scene.item,)))


    def render_strip(self, games: Sequence[Mapping[str, Any]], repeat: int = 1) -> Image.Image:
        """Render a gap-separated sequence of normal score cards."""
        cards = [self.render_card(game) for game in games]
        width = sum(card.width for card in cards) * max(1, repeat)
        frame = Image.new("RGB", (max(1, width), PANEL_H), (0, 0, 0))
        x = 0
        for _ in range(max(1, repeat)):
            for card in cards:
                frame.paste(card, (x, 0))
                x += card.width
        return frame

    def render_card(self, game: Mapping[str, Any]) -> Image.Image:
        """Render one 32 pixel stadium score card."""
        if _is_sports_ad(game):
            return self._render_sports_ad(game)
        legacy_image, _ = self._stadium.render(dict(game))
        return legacy_image.convert("RGB")

    def _render_sports_ad(self, game: Mapping[str, Any]) -> Image.Image:
        """Render a compact recreation of a sourced or filler sports campaign card."""

        width = _sports_ad_width(game)
        background = _hex(game.get("background"), (16, 28, 42))
        accent = _hex(game.get("accent"), (24, 210, 110))
        image = Image.new("RGB", (width, PANEL_H), background)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width - 1, PANEL_H - 1), outline=_dark(accent, 0.35))
        draw.rectangle((0, 0, 3, PANEL_H - 1), fill=accent)
        logo_plate = str(game.get("logo_plate") or "").strip()
        if logo_plate:
            draw.rectangle((7, 5, 28, 26), fill=_hex(logo_plate, (255, 255, 255)))
        logo = self._logos.get(str(game.get("logo") or ""), (18, 18))
        if logo is not None:
            image.paste(logo, (9, 7), logo)
        else:
            draw.ellipse((9, 8, 26, 25), outline=accent, width=2)
            draw_hybrid_text(draw, 15, 13, "S", accent)
        draw_hybrid_text(draw, 32, 3, game.get("headline", "FANDUEL"), (255, 255, 255))
        draw_tiny_text(draw, 32, 13, game.get("tagline", "MAKE EVERY MOMENT MORE"), accent)
        draw_tiny_text(draw, 32, 22, game.get("detail", "PARODY"), (150, 170, 185))
        return image

    def render_full(self, game: Mapping[str, Any], *, page_tick: int = 0) -> Image.Image:
        """Render the 384 by 32 sport-specific full display."""
        return self._full.draw_sport_full_bleed(dict(game), page_tick=page_tick).convert("RGB")

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        """Invalidate paged hockey frames at the same cadence as their renderer."""
        pages = 1
        if scene.item.get("sports_presentation") == "pinned" and str(scene.item.get("sport") or "").lower() in {"nhl", "hockey"}:
            pages = hockey_page_count(scene.item.get("situation") or {})
        phase = (int(context.now.timestamp()) // 5) % pages if pages > 1 else None
        if scene.item is not self._visual_item:
            self._visual_item = scene.item
            self._visual_item_json = json.dumps(scene.item, sort_keys=True, default=str, separators=(",", ":"))
        if scene.item.get("sports_presentation") == "pinned":
            if scene.item is not self._asset_item or asset_revision != self._asset_revision:
                self._asset_item = scene.item
                self._asset_revision = asset_revision
                self._pinned_asset_state = (
                    bool(get_prepared_team_logo(
                        self._logos,
                        str(scene.item.get("home_logo") or "") or None,
                        (24, 24),
                        scene.item.get("home_logo_rendering"),
                    )),
                    bool(get_prepared_team_logo(
                        self._logos,
                        str(scene.item.get("away_logo") or "") or None,
                        (24, 24),
                        scene.item.get("away_logo_rendering"),
                    )),
                )
            asset_state: object = self._pinned_asset_state
        else:
            asset_state = asset_revision
        return ("scoreboard", self._visual_item_json, scene.mode, asset_state, phase)
