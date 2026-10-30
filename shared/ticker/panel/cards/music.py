"""Draw the playing track: a spinning record with the cover art, scrolling text, a visualizer, and progress."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from PIL import Image, ImageDraw, ImageOps

from ticker.shared.music_palette import artwork_colors

from ticker.panel.frame import ContentScene, ItemKey, Logos, NoLogos, RenderContext, RenderedContent
from ticker.panel.text import FontSet, clean_text

WIDTH, HEIGHT = 384, 32
RECORD, COVER = 51, 42
GREEN = (29, 185, 84)
BARS, BAR_X, BAR_Y, BAR_HEIGHT = 16, 248, 6, 20


@dataclass(frozen=True, slots=True)
class MusicState:
    """The animation values that carry from one music frame to the next."""

    cover_url: str = ""
    rotation: float = 0.0
    scroll: float = 0.0
    previous_time: float | None = None
    dominant: tuple[int, int, int] = GREEN
    spindle: str = "black"
    visualizer: tuple[float, ...] = (2.0,) * BARS
    artwork: Image.Image | None = None
    previous_artwork: Image.Image | None = None
    previous_dominant: tuple[int, int, int] = GREEN
    fade_alpha: float = 1.0


class MusicCard:
    def __init__(self, fonts: FontSet, logos: Logos | None = None) -> None:
        self._key = ItemKey("music")
        self._fonts = fonts
        self._logos = logos or NoLogos()
        self._mask = Image.new("L", (COVER, COVER), 0)
        ImageDraw.Draw(self._mask).ellipse((0, 0, COVER, COVER), fill=255)
        self._record = Image.new("RGBA", (RECORD, RECORD), (0, 0, 0, 0))
        ImageDraw.Draw(self._record).ellipse((0, 0, RECORD - 1, RECORD - 1), fill=(20, 20, 20), outline=(50, 50, 50))
        self._state = MusicState()

    def visual_key(self, context: RenderContext, scene: ContentScene, asset_revision: int | None = None) -> object:
        # The equalizer and the progress move at 30 frames each second.
        return self._key(scene, asset_revision, int(context.now.timestamp() * 30))

    def render(self, context: RenderContext, scene: ContentScene) -> RenderedContent:
        image, self._state = self.frame(context.now, scene.item, self._state)
        return RenderedContent(image)

    def frame(self, at: datetime, item: object, state: MusicState) -> tuple[Image.Image, MusicState]:
        """Draw one frame and return the state for the next frame."""
        track = item if isinstance(item, dict) else {}
        now = at.timestamp()
        elapsed = 0.0 if state.previous_time is None else max(0.0, now - state.previous_time)
        situation = track.get("situation", {})
        situation = situation if isinstance(situation, dict) else {}
        playing = bool(track.get("is_playing", situation.get("is_playing", False)))
        progress = _number(track.get("progress", situation.get("progress")))
        fetched = _number(track.get("fetch_ts", situation.get("fetch_ts")), now)
        duration = max(1.0, _number(track.get("duration", situation.get("duration")), 1.0))
        position = min(duration, progress + (now - fetched) if playing else progress)
        cover_url = str(track.get("cover") or track.get("home_logo") or "")
        loaded = self._logos.get(cover_url, (COVER, COVER)) if cover_url else None
        artwork = state.artwork if state.cover_url == cover_url and state.artwork is not None else loaded
        dominant, spindle = artwork_colors(artwork, state.dominant, state.spindle)
        previous_artwork, previous_dominant, fade = state.previous_artwork, state.previous_dominant, state.fade_alpha
        if cover_url != state.cover_url or (artwork is not None and state.artwork is None):
            # A new cover fades in over the last cover.
            previous_artwork = state.artwork if state.artwork is not None else self._last_cover(track)
            previous_dominant = (artwork_colors(previous_artwork, state.dominant, state.spindle)[0]
                                 if previous_artwork is not None else state.dominant)
            fade = 0.5 if previous_artwork is not None and artwork is not None else 1.0
        fade = min(1.0, fade + 0.1 * elapsed)
        blend = fade * fade * (3.0 - 2.0 * fade)
        accent = tuple(int(previous_dominant[index] + (dominant[index] - previous_dominant[index]) * blend) for index in range(3))
        state = replace(state, cover_url=cover_url,
                        rotation=(state.rotation - 100.0 * elapsed) % 360 if playing else state.rotation,
                        scroll=state.scroll + 15.0 * elapsed if playing else state.scroll,
                        previous_time=now, dominant=dominant, spindle=spindle, artwork=artwork,
                        previous_artwork=previous_artwork, previous_dominant=previous_dominant, fade_alpha=fade)
        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)
        record = self._spun_record(artwork, previous_artwork, blend, spindle, state.rotation)
        image.paste(record, (4, -9), record)
        title = str(track.get("name") or track.get("away_abbr") or "Unknown")
        artist = str(track.get("artist") or track.get("home_abbr") or "Unknown")
        _scroll_text(image, title, self._fonts.medium, 60, 0, 188, state.scroll, "white")
        _scroll_text(image, artist, self._fonts.tiny, 76, 17, 172, state.scroll, (180, 180, 180))
        # The artist icon: a filled circle with three dark arcs, like a speaker.
        draw.ellipse((60, 15, 72, 27), fill=accent)
        for y0, y1, x0, x1 in ((18, 24, 63, 69), (20, 26, 63, 69), (22, 27, 64, 68)):
            draw.arc((x0, y0, x1, y1), 190, 350, fill="black", width=1)
        state = replace(state, visualizer=_visualizer(draw, playing, now, accent, state.visualizer))
        draw.rectangle((0, 31, int(WIDTH * max(0.0, min(1.0, position / duration))), 31), fill=accent)
        remaining = f"-{_clock(duration - position)}"
        draw.text((WIDTH - draw.textlength(remaining, font=self._fonts.tiny) - 5, 10), remaining, font=self._fonts.tiny, fill="white")
        return image, state

    def _last_cover(self, track: dict) -> Image.Image | None:
        last_song = track.get("last_song") if isinstance(track.get("last_song"), dict) else {}
        url = str(track.get("last_cover") or track.get("last_logo") or last_song.get("cover") or "")
        return self._logos.get(url, (COVER, COVER)) if url else None

    def _spun_record(self, artwork, previous, blend: float, spindle: str, rotation: float) -> Image.Image:
        record = self._record.copy()
        cover, prior = self._label(artwork), self._label(previous)
        if cover is not None:
            if prior is not None and blend < 1.0:
                cover = Image.blend(prior, cover, blend)
            record.paste(cover, ((RECORD - COVER) // 2,) * 2, cover)
        draw = ImageDraw.Draw(record)
        draw.ellipse((22, 22, 28, 28), fill="#222")
        draw.ellipse((23, 23, 27, 27), fill=spindle)
        return record.rotate(rotation, resample=Image.Resampling.BICUBIC)

    def _label(self, artwork: Image.Image | None) -> Image.Image | None:
        """Fit the cover into the round record label."""
        if artwork is None:
            return None
        cover = ImageOps.fit(artwork.convert("RGBA"), (COVER, COVER), centering=(0.5, 0.5))
        cover.putalpha(self._mask)
        return cover


def _visualizer(draw: ImageDraw.ImageDraw, playing: bool, now: float, color, old: tuple[float, ...]) -> tuple[float, ...]:
    """Draw 16 bars that ease toward wave heights, and return the new heights."""
    heights = []
    for index in range(BARS):
        base = math.sin(now * 4 + 0.0)
        noise = math.sin(now * 12 + index * 0.5) * (0.5 + (index % 5) * 0.175)
        amplitude = 8.0 + math.sin(now * 2) * 2 if index < 5 else 6.0 if index < 11 else 4.0 + noise * 2
        target = max(2.0, min(float(BAR_HEIGHT), abs(base + noise) * amplitude)) if playing else 2.0
        value = old[index] + (target - old[index]) * 0.25
        heights.append(value)
        tint = index / 15 * 0.6
        shade = tuple(int(channel + (255 - channel) * tint) for channel in color)
        height = int(value)
        top = BAR_Y + BAR_HEIGHT // 2 - height // 2
        x = BAR_X + index * 5
        draw.rectangle((x, top, x + 1, top + height), fill=shade)
    return tuple(heights)


def _scroll_text(canvas: Image.Image, value: object, font, x: int, y: int, width: int, scroll: float, color) -> None:
    """Draw text that fits, or a loop of the text that scrolls with `scroll`."""
    text = clean_text(value)
    draw = ImageDraw.Draw(canvas)
    length = draw.textlength(text, font=font)
    if length <= width - 2:
        draw.text((x, y), text, font=font, fill=color)
        return
    loop = length + 40
    offset = scroll % loop
    strip = Image.new("RGBA", (width, HEIGHT), (0, 0, 0, 0))
    strip_draw = ImageDraw.Draw(strip)
    strip_draw.text((-offset, 0), text, font=font, fill=color)
    if -offset + length < width:
        strip_draw.text((-offset + loop, 0), text, font=font, fill=color)
    canvas.paste(strip, (x, y), strip)


def _number(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clock(seconds: float) -> str:
    minutes, remaining = divmod(int(max(0.0, seconds)), 60)
    return f"{minutes}:{remaining:02d}"
