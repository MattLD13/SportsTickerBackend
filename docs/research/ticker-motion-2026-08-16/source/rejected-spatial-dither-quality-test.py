"""Check deterministic motion quality at every configured scroll level."""

from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from time import monotonic, sleep

import pytest
from PIL import Image

from ticker_core.app.viewport import CardViewport
from ticker_core.assets import AssetRequest
from ticker_core.bootstrap import create_default_content_catalog
from ticker_core.context import RenderContext
from ticker_core.platform.assets import AssetCoordinator
from ticker_core.rendering import RenderedContent
from ticker_core.runtime import (
    FrameKind,
    RuntimeConfig,
    StripLayout,
    StripSegment,
    TickerRuntime,
)
from ticker_core.protocol import TickerResponse
from ticker_core.runtime import Content


PIXEL_INTERVALS = tuple(
    1.0 / (10.0 + (level - 1) * (30.0 / 9.0))
    for level in range(1, 11)
)


class EdgeCatalog:
    """Render one high-contrast surface with a single measurable edge."""

    def render(self, context, scene):
        del context, scene
        image = Image.new("RGB", (500, 32), (0, 0, 0))
        for y in range(32):
            image.putpixel((200, y), (255, 255, 255))
        return RenderedContent(image)


class SolidCatalog:
    """Render a solid card so the panel edge exposes source padding."""

    def render(self, context, scene):
        del context, scene
        return RenderedContent(Image.new("RGB", (96, 32), (255, 0, 0)))


class PatternCatalog:
    """Render distinct neighboring pixels for exact A/B membership checks."""

    def render(self, context, scene):
        del context, scene
        image = Image.new("RGB", (500, 32))
        pixels = image.load()
        for y in range(32):
            for x in range(500):
                pixels[x, y] = ((x * 37 + y * 11) % 251, (x * 17 + y * 29) % 251, (x * 7 + y * 43) % 251)
        return RenderedContent(image)


def test_runtime_keeps_a_monotonic_30ms_distance_at_all_levels() -> None:
    """Keep logical distance monotonic while preserving one physical cadence."""

    for level, pixel_interval in enumerate(PIXEL_INTERVALS, start=1):
        runtime = TickerRuntime(
            monotonic=lambda: 0.0,
            wall_clock=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
            config=RuntimeConfig(offline_after=10),
        )
        snapshot = runtime.accept_response(_response(pixel_interval))
        runtime.install_strip(snapshot.strip_key, StripLayout(10_000, (StripSegment("game", 10_000),)))
        frames = tuple(runtime.next_frame() for _ in range(8))

        assert all(frame.kind is FrameKind.SCROLL for frame in frames)
        assert tuple(frame.interval for frame in frames) == pytest.approx((0.03,) * len(frames))
        offsets = tuple(frame.scroll_offset for frame in frames)
        assert offsets == pytest.approx(tuple(i * 0.03 / pixel_interval for i in range(8)))
        assert all(right > left for left, right in zip(offsets, offsets[1:]))
        if level == 8:
            assert tuple(right - left for left, right in zip(offsets, offsets[1:])) == pytest.approx((1.0,) * 7)


def test_fractional_motion_reads_the_real_following_panel_column() -> None:
    """Keep the final panel column bright when fractional motion samples ahead."""

    viewport = CardViewport(SolidCatalog())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("solid", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport)
        current = viewport.frame(0.0, scroll_step=0.5)
        following = viewport.frame(1.0, scroll_step=0.5)
        fractional = viewport.frame(0.5, scroll_step=0.5)
        expected = Image.blend(current, following, 0.5)
        assert fractional.getpixel((383, 0)) == expected.getpixel((383, 0))
    finally:
        viewport.close()


@pytest.mark.parametrize("phase", tuple(index / 64 for index in range(65)))
def test_fractional_motion_uses_exact_q_over_64_a_or_b_coverage(phase: float) -> None:
    """Select exact q/64 source pixels without creating intermediate RGB values."""

    viewport = CardViewport(PatternCatalog())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("pattern", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport)
        current = viewport.frame(0.0, scroll_step=0.3)
        following = viewport.frame(1.0, scroll_step=0.3)
        output = viewport.frame(phase, scroll_step=0.3)
        current_pixels = tuple(current.getdata())
        following_pixels = tuple(following.getdata())
        output_pixels = tuple(output.getdata())
        differing = [(a, b, value) for a, b, value in zip(current_pixels, following_pixels, output_pixels) if a != b]
        assert differing
        assert all(value == a or value == b for a, b, value in differing)
        selected = sum(value == b for a, b, value in differing)
        assert abs(selected / len(differing) - round(phase * 64) / 64) < 1 / 128
        expected = round(phase * 64) / 64
        for tile_y in range(0, 32, 32):
            for tile_x in range(0, 384, 32):
                tile = []
                for y in range(tile_y, tile_y + 32):
                    for x in range(tile_x, tile_x + 32):
                        index = y * 384 + x
                        if current_pixels[index] != following_pixels[index]:
                            tile.append((current_pixels[index], following_pixels[index], output_pixels[index]))
                assert tile
                assert abs(sum(value == b for a, b, value in tile) / len(tile) - expected) < 1 / 128
    finally:
        viewport.close()


@pytest.mark.parametrize("level", range(1, 8))
def test_slow_levels_progress_without_intermediate_rgb(level: int) -> None:
    """Move every slow level each frame while selecting only adjacent source pixels."""

    step = 0.3 + (level - 1) * 0.1
    viewport = CardViewport(PatternCatalog())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("pattern", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport)
        frames = []
        for index in range(8):
            offset = index * step
            current = viewport.frame(int(offset), scroll_step=1.0)
            following = viewport.frame(int(offset) + 1, scroll_step=1.0)
            output = viewport.frame(offset, scroll_step=step)
            assert all(value == a or value == b for a, b, value in zip(current.getdata(), following.getdata(), output.getdata()))
            frames.append(output.tobytes())
        assert all(left != right for left, right in zip(frames, frames[1:]))
    finally:
        viewport.close()


@pytest.mark.parametrize("step", (1.0, 1.1, 1.2))
def test_fast_levels_are_exact_crisp_integer_columns(step: float) -> None:
    """Keep level eight and faster levels free from fractional blending."""

    viewport = CardViewport(PatternCatalog())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("pattern", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport)
        for index in range(8):
            offset = index * step
            assert viewport.frame(offset, scroll_step=step).tobytes() == viewport.frame(int(offset), scroll_step=1.0).tobytes()
    finally:
        viewport.close()


def test_dither_has_no_eight_pixel_periodic_texture() -> None:
    """Reject a repeated 8x8 mask that creates a visible panel texture."""

    viewport = CardViewport(PatternCatalog())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("pattern", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport)
        current = viewport.frame(0.0, scroll_step=0.3)
        following = viewport.frame(1.0, scroll_step=0.3)
        output = viewport.frame(0.5, scroll_step=0.3)
        masks = []
        for a, b, value in zip(current.getdata(), following.getdata(), output.getdata()):
            masks.append(value == b if a != b else False)
        matches = []
        for y in range(32):
            for x in range(384 - 8):
                matches.append(masks[y * 384 + x] == masks[y * 384 + x + 8])
        assert sum(matches) / len(matches) < 0.9
    finally:
        viewport.close()


def test_real_sports_luminance_and_temporal_error_stay_bounded() -> None:
    """Keep real text and prepared logos close to continuous luminance without temporal ripple."""

    urls = (
        "https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/nym.png",
        "https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/bos.png",
    )
    assets = AssetCoordinator(Path("ticker_data/rewrite_assets"))
    try:
        futures = assets.prefetch(tuple(AssetRequest(url, "logo", (22, 22)) for url in urls))
        assert all(future.result() is not None for future in futures)
        catalog = create_default_content_catalog(assets)
        item = Content(
            "mlb-real",
            "scoreboard",
            "mlb",
            {
                "sport": "mlb",
                "state": "in",
                "status": "TOP 7TH",
                "away_abbr": "NYM",
                "home_abbr": "BOS",
                "away_score": "3",
                "home_score": "2",
                "away_logo": urls[0],
                "home_logo": urls[1],
                "situation": {"activeTeam": "NYM", "onFirst": True, "onSecond": True, "balls": 3, "strikes": 2, "outs": 2},
            },
        )
        viewport = CardViewport(catalog)
        try:
            viewport.update((item,), RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc)), "sports")
            _drain(viewport)

            def luminance(image: Image.Image) -> float:
                return sum(channel * weight for pixel in image.getdata() for channel, weight in zip(pixel, (0.2126, 0.7152, 0.0722)))

            continuous = []
            dithered = []
            for index in range(24):
                offset = index * 0.3
                current = viewport.frame(int(offset), scroll_step=1.0)
                following = viewport.frame(int(offset) + 1, scroll_step=1.0)
                continuous.append(Image.blend(current, following, offset - int(offset)))
                dithered.append(viewport.frame(offset, scroll_step=0.3))
            for expected, actual in zip(continuous, dithered):
                assert abs(luminance(actual) - luminance(expected)) / max(luminance(expected), 1.0) < 0.02

            def second_rms(images: list[Image.Image]) -> float:
                rows = [[luminance(image.crop((x, y, x + 8, y + 8))) for image in images] for y in range(0, 32, 8) for x in range(0, 384, 8)]
                values = [second for row in rows for second in (row[index + 2] - 2 * row[index + 1] + row[index] for index in range(len(row) - 2))]
                return sqrt(sum(value * value for value in values) / max(1, len(values)))

            assert second_rms(dithered) <= second_rms(continuous) * 1.10
        finally:
            viewport.close()
    finally:
        assets.close()


@pytest.mark.parametrize("level", (9, 10))
def test_high_speed_edges_never_blend_neighboring_columns(level: int) -> None:
    """Keep high-speed edge pixels in the source palette without neighboring-image ghosts."""

    viewport = CardViewport(EdgeCatalog())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("edge", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport)
        interval = PIXEL_INTERVALS[level - 1]
        step = 0.03 / interval
        palette = {(0, 0, 0), (45, 45, 45), (255, 255, 255)}
        for index in range(12):
            image = viewport.frame(index * 0.03 / interval, scroll_step=step)
            assert {pixel for pixel in image.getdata()} <= palette
    finally:
        viewport.close()


@pytest.mark.parametrize("level", range(1, 8))
def test_low_speed_edge_energy_has_no_brightness_modulation(level: int) -> None:
    """Keep one moving edge smooth without a visible brightness ripple."""

    viewport = CardViewport(EdgeCatalog())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))
    try:
        viewport.update((Content("edge", "scoreboard", "nfl", {}),), context, "sports")
        _drain(viewport)
        frames = []
        energies = []
        for index in range(12):
            image = viewport.frame(index * 0.03 / PIXEL_INTERVALS[level - 1])
            frames.append(image)
            energies.append(sum(image.getpixel((x, 0))[0] for x in range(150, 250)))
        assert all(left.tobytes() != right.tobytes() for left, right in zip(frames, frames[1:]))
        assert max(energies) - min(energies) <= 1
    finally:
        viewport.close()


def _response(scroll_interval: float) -> TickerResponse:
    return TickerResponse.from_payload(
        {
            "api_version": "v2",
            "snapshot": {"ticker_id": "ticker-1", "revision": 1, "observed_at": "2026-08-11T00:00:00+00:00", "stale": False},
            "settings": {"mode": "sports", "sports_presentation": "rotation", "pinned_content_id": "", "brightness": 100, "scroll_speed": scroll_interval, "inverted": False},
            "content": {"sports": [{"id": "game", "family": "sports", "kind": "scoreboard", "is_shown": True, "data": {"sport": "nfl", "state": "in"}}]},
            "events": {"alerts": [], "news": []},
            "health": {"provider": "refresh", "healthy": True, "error": None},
            "meta": {"pairing": {"paired": True, "code": None}},
        }
    )


def _drain(viewport: CardViewport) -> None:
    deadline = monotonic() + 1.0
    while viewport.layout is None and monotonic() < deadline:
        viewport.install_completed()
        sleep(0.005)
    viewport.install_completed()
    assert viewport.layout is not None
