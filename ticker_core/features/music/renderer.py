"""Render music playback without mutable controller globals."""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, replace
from typing import Any

from PIL import Image, ImageDraw, ImageOps, ImageStat

from ticker_core.context import RenderContext
from ticker_core.features.utility.primitives import PANEL_H, PANEL_W, normal_text
from ticker_core.features.utility.renderer import EmptyLogoSource, LogoSource
from ticker_core.rendering import ContentScene, FontSet, RenderedContent


@dataclass(frozen=True, slots=True)
class MusicAnimationState:
    """Hold explicit animation values between music frames."""

    cover_url: str = ""
    rotation: float = 0.0
    scroll: float = 0.0
    previous_time: float | None = None
    dominant: tuple[int, int, int] = (29, 185, 84)
    spindle: str = "black"
    visualizer: tuple[float, ...] = (2.0,) * 16
    artwork: Image.Image | None = None
    previous_artwork: Image.Image | None = None
    previous_dominant: tuple[int, int, int] = (29, 185, 84)
    fade_alpha: float = 1.0


class MusicRenderer:
    """Render music cards from supplied artwork and animation state."""

    _vinyl_size = 51
    _cover_size = 42
    _phase = (0.0,) * 16

    def __init__(self, fonts: FontSet, logos: LogoSource | None = None) -> None:
        self._fonts = fonts
        self._logos = logos or EmptyLogoSource()
        self._mask = Image.new("L", (self._cover_size, self._cover_size), 0)
        ImageDraw.Draw(self._mask).ellipse((0, 0, self._cover_size, self._cover_size), fill=255)
        self._scratch = Image.new("RGBA", (self._vinyl_size, self._vinyl_size), (0, 0, 0, 0))
        ImageDraw.Draw(self._scratch).ellipse((0, 0, self._vinyl_size - 1, self._vinyl_size - 1), fill=(20, 20, 20), outline=(50, 50, 50))
        self._state = MusicAnimationState()

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        """Render one music item while retaining its animation state."""
        image, self._state = self.render_with_state(context, scene.item, self._state)
        return RenderedContent(image, static=True)

    def render_with_state(self, context: RenderContext, item: object, state: MusicAnimationState) -> tuple[Image.Image, MusicAnimationState]:
        """Render one frame and return the next explicit state."""
        game = item if isinstance(item, dict) else {}
        now = context.now.timestamp()
        elapsed = 0.0 if state.previous_time is None else max(0.0, now - state.previous_time)
        situation = game.get("situation", {})
        situation = situation if isinstance(situation, dict) else {}
        playing = bool(game.get("is_playing", situation.get("is_playing", False)))
        progress = self._number(game.get("progress", situation.get("progress")))
        fetch_time = self._number(game.get("fetch_ts", situation.get("fetch_ts")), now)
        duration = max(1.0, self._number(game.get("duration", situation.get("duration")), 1.0))
        local_progress = min(duration, progress + (now - fetch_time) if playing else progress)
        cover_url = str(game.get("cover") or game.get("home_logo") or "")
        title = str(game.get("name") or game.get("away_abbr") or "Unknown")
        artist = str(game.get("artist") or game.get("home_abbr") or "Unknown")
        loaded_artwork = self._logos.get(cover_url, (self._cover_size, self._cover_size)) if cover_url else None
        artwork = state.artwork if state.cover_url == cover_url and state.artwork is not None else loaded_artwork
        previous_artwork = state.previous_artwork
        previous_dominant = state.previous_dominant
        fade_alpha = state.fade_alpha
        dominant, spindle = self._colors(artwork, state.dominant, state.spindle)
        if cover_url != state.cover_url or (artwork is not None and state.artwork is None):
            previous_artwork = state.artwork
            if previous_artwork is None:
                last_cover = str(game.get("last_cover") or "")
                previous_artwork = self._logos.get(last_cover, (self._cover_size, self._cover_size)) if last_cover else None
            previous_dominant = state.dominant
            fade_alpha = 0.5 if previous_artwork is not None and artwork is not None else 1.0
        fade_alpha = min(1.0, fade_alpha + 0.1 * elapsed)
        smooth_alpha = fade_alpha * fade_alpha * (3.0 - 2.0 * fade_alpha)
        ui_color = tuple(
            int(previous_dominant[index] + (dominant[index] - previous_dominant[index]) * smooth_alpha)
            for index in range(3)
        )
        next_state = replace(
            state,
            cover_url=cover_url,
            rotation=(state.rotation - 100.0 * elapsed) % 360 if playing else state.rotation,
            scroll=state.scroll + 15.0 * elapsed if playing else state.scroll,
            previous_time=now,
            dominant=dominant,
            spindle=spindle,
            artwork=artwork,
            previous_artwork=previous_artwork,
            previous_dominant=previous_dominant,
            fade_alpha=fade_alpha,
        )
        image = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        composite = self._scratch.copy()
        current_cover = self._cover_artwork(artwork)
        prior_cover = self._cover_artwork(previous_artwork)
        if current_cover is not None:
            if prior_cover is not None and smooth_alpha < 1.0:
                current_cover = Image.blend(prior_cover, current_cover, smooth_alpha)
            composite.paste(current_cover, ((self._vinyl_size - self._cover_size) // 2,) * 2, current_cover)
        inner = ImageDraw.Draw(composite)
        inner.ellipse((22, 22, 28, 28), fill="#222")
        inner.ellipse((23, 23, 27, 27), fill=spindle)
        rotated = composite.rotate(next_state.rotation, resample=Image.Resampling.BICUBIC)
        image.paste(rotated, (4, -9), rotated)
        text_x = 60
        self._scroll_text(image, title, self._fonts.medium, text_x, 0, 188, next_state.scroll, "white")
        self._scroll_text(image, artist, self._fonts.tiny, text_x + 16, 17, 172, next_state.scroll, (180, 180, 180))
        draw.ellipse((text_x, 15, text_x + 12, 27), fill=ui_color)
        for y0, y1, x0, x1 in ((18, 24, 63, 69), (20, 26, 63, 69), (22, 27, 64, 68)):
            draw.arc((x0, y0, x1, y1), 190, 350, fill="black", width=1)
        heights = self._visualizer(draw, 248, 6, 80, 20, playing, now, ui_color, state.visualizer)
        next_state = replace(next_state, visualizer=heights)
        draw.rectangle((0, 31, int(PANEL_W * max(0.0, min(1.0, local_progress / duration))), 31), fill=ui_color)
        remaining = f"-{self._time_text(duration - local_progress)}"
        draw.text((PANEL_W - draw.textlength(remaining, font=self._fonts.tiny) - 5, 10), remaining, font=self._fonts.tiny, fill="white")
        return image, next_state

    def _cover_artwork(self, artwork: Image.Image | None) -> Image.Image | None:
        """Fit one prepared cover into the centered vinyl label."""
        if artwork is None:
            return None
        cover = ImageOps.fit(artwork.convert("RGBA"), (self._cover_size, self._cover_size), centering=(0.5, 0.5))
        cover.putalpha(self._mask)
        return cover

    def _visualizer(self, draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, playing: bool, now: float, color: tuple[int, int, int], old: tuple[float, ...]) -> tuple[float, ...]:
        del width
        heights: list[float] = []
        for index in range(16):
            base = math.sin(now * 4 + self._phase[index])
            noise = math.sin(now * 12 + index * 0.5) * (0.5 + (index % 5) * 0.175)
            if index < 5:
                amplitude = 8.0 + math.sin(now * 2) * 2
            elif index < 11:
                amplitude = 6.0
            else:
                amplitude = 4.0 + noise * 2
            target = max(2.0, min(float(height), abs(base + noise) * amplitude)) if playing else 2.0
            value = old[index] + (target - old[index]) * 0.25
            heights.append(value)
            factor = index / 15 * 0.6
            shade = tuple(int(channel + (255 - channel) * factor) for channel in color)
            h = int(value)
            start = y + height // 2 - h // 2
            bx = x + index * 5
            draw.rectangle((bx, start, bx + 1, start + h), fill=shade)
        return tuple(heights)

    def _scroll_text(self, canvas: Image.Image, value: object, font: object, x: int, y: int, max_width: int, scroll: float, color: object) -> None:
        text = normal_text(value)
        draw = ImageDraw.Draw(canvas)
        text_width = draw.textlength(text, font=font)
        if text_width <= max_width - 2:
            draw.text((x, y), text, font=font, fill=color)
            return
        loop = text_width + 40
        offset = scroll % loop
        strip = Image.new("RGBA", (max_width, PANEL_H), (0, 0, 0, 0))
        strip_draw = ImageDraw.Draw(strip)
        strip_draw.text((-offset, 0), text, font=font, fill=color)
        if -offset + text_width < max_width:
            strip_draw.text((-offset + loop, 0), text, font=font, fill=color)
        canvas.paste(strip, (x, y), strip)

    @staticmethod
    def _number(value: object, fallback: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _time_text(seconds: float) -> str:
        minutes, remaining = divmod(int(max(0.0, seconds)), 60)
        return f"{minutes}:{remaining:02d}"

    @staticmethod
    def _colors(image: Image.Image | None, dominant: tuple[int, int, int], spindle: str) -> tuple[tuple[int, int, int], str]:
        if image is None:
            return dominant, spindle
        red, green, blue = ImageStat.Stat(image.convert("RGB")).mean[:3]
        brightness = 0.299 * red + 0.587 * green + 0.114 * blue
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        saturation = 0.0 if saturation < 0.2 else min(1.0, saturation * 1.5) if saturation < 0.5 else saturation
        value = 0.5 if value < 0.3 else min(1.0, value * 1.3) if value < 0.8 else value
        result = colorsys.hsv_to_rgb(hue, saturation, value)
        return tuple(int(channel * 255) for channel in result), "white" if brightness < 140 else "black"
