"""Check the production Six weather loop with an injected clock."""

from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image, ImageChops, ImageDraw

from ticker_core.context import RenderContext
from ticker_core.features.weather import WeatherRenderer
from ticker_core.features.weather.drawing import ANIMATION_PERIOD, PreparedWeatherRenderer
from ticker_core.ui import ContentScene, load_default_font_set
from tools.rendering.render_frame import render_snapshot


pytestmark = pytest.mark.critical

START = datetime(2026, 8, 24, 12, 0, 10, 800000, tzinfo=timezone.utc)
ICONS = (
    "sun", "clear", "rain", "drizzle", "shower", "snow", "blizzard", "storm",
    "thunder", "lightning", "fog", "mist", "haze", "cloud", "overcast", "moon",
)


@pytest.fixture(scope="module")
def fonts():
    return load_default_font_set()


def weather_item(icon="sun", *, night=False):
    return {
        "id": "weather_main", "family": "weather", "kind": "weather",
        "away_abbr": "BETHLEHEM", "home_abbr": "72", "status": icon.upper(),
        "situation": {
            "icon": icon, "is_day": int(not night), "obs_time": "2026-08-24T12:00",
            "sunrise": "2026-08-24T06:00", "sunset": "2026-08-24T19:45",
            "stats": {"feels": "70", "wind": "12", "humidity": "68", "aqi": "24"},
            "forecast": [
                {"icon": name, "high": 74, "low": 66, "pop": 65, "wind": 12}
                for name in ("sun", "rain", "snow", "storm", "fog")
            ],
        },
    }


def panel(fonts, item, seconds):
    context = RenderContext(START + timedelta(seconds=seconds))
    return WeatherRenderer(fonts).render(context, ContentScene(item, "weather")).image


@pytest.mark.parametrize("icon", ICONS)
@pytest.mark.parametrize("seconds", (0, 0.05, 1.7, 7.25, 23.95))
def test_weather_panel_repeats_with_all_forecast_offsets(fonts, icon, seconds):
    item = weather_item(icon)
    first = panel(fonts, item, seconds)
    later = panel(fonts, item, seconds + ANIMATION_PERIOD)
    assert first.size == (384, 32)
    assert first.tobytes() == later.tobytes()


@pytest.mark.parametrize("icon", ICONS)
def test_small_weather_icons_repeat_at_each_forecast_offset(fonts, icon):
    renderer = PreparedWeatherRenderer(fonts, START)
    for offset in (0, 1.7, 3.4, 5.1, 6.8):
        images = [Image.new("RGB", (32, 32)) for _ in range(2)]
        for image, time in zip(images, (offset, offset + ANIMATION_PERIOD)):
            renderer.draw_weather_pixel_art(ImageDraw.Draw(image), icon, 8, 8, t=time)
        assert images[0].tobytes() == images[1].tobytes()


@pytest.mark.parametrize("icon", ("sun", "rain", "snow", "storm", "fog"))
def test_weather_motion_remains_active(fonts, icon):
    item = weather_item(icon)
    times = (0, 0.3, ANIMATION_PERIOD / 4, ANIMATION_PERIOD / 2, ANIMATION_PERIOD * 3 / 4)
    frames = {panel(fonts, item, seconds).crop((0, 9, 24, 32)).tobytes() for seconds in times}
    assert len(frames) > 1


def test_storm_flash_is_continuous_at_the_loop_boundary(fonts):
    item = weather_item("storm")
    before = panel(fonts, item, ANIMATION_PERIOD - 0.001)
    after = panel(fonts, item, 0.001)
    # A flash must not replace the whole sky when the cycle restarts.
    delta = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    changes = sum(max(pixel) > 2 for pixel in delta.crop((25, 9, 124, 32)).getdata())
    assert changes <= 16


@pytest.mark.parametrize("icon", ("sun", "rain", "snow", "storm", "fog"))
def test_weather_frames_continue_through_the_loop_boundary(fonts, icon):
    item = weather_item(icon)
    before = panel(fonts, item, ANIMATION_PERIOD - 0.001).convert("RGB")
    after = panel(fonts, item, 0.001).convert("RGB")
    delta = ImageChops.difference(before, after)
    # Two milliseconds can move a few pixels. They must not reset the panel.
    assert sum(max(pixel) > 2 for pixel in delta.getdata()) <= 40


def test_clear_night_stars_repeat_without_changing_the_moon(fonts):
    item = weather_item("sun", night=True)
    first = panel(fonts, item, 0.2)
    later = panel(fonts, item, ANIMATION_PERIOD + 0.2)
    assert first.tobytes() == later.tobytes()
    assert (184, 184, 184, 255) in first.crop((0, 5, 24, 32)).getdata()


def test_production_catalog_keeps_the_loop_at_panel_size(tmp_path):
    snapshot = {"mode": "weather", "content": {"items": [weather_item("snow")]}}
    images = [
        render_snapshot(snapshot, "weather", now=START + timedelta(seconds=seconds),
                        prefetch=False, asset_directory=tmp_path)
        for seconds in (0.2, ANIMATION_PERIOD + 0.2)
    ]
    assert images[0].size == (384, 32)
    assert images[0].tobytes() == images[1].tobytes()


@pytest.mark.parametrize("days", [0, 2])
def test_missing_forecast_days_show_no_invented_weather(fonts, days):
    from ticker_core.features.weather.drawing import FORECAST_DAYS, _forecast_column

    item = weather_item()
    item["situation"]["forecast"] = item["situation"]["forecast"][:days]
    frames = [panel(fonts, item, seconds).convert("RGB") for seconds in (0, 0.7, 1.9)]
    for index in range(days, FORECAST_DAYS):
        left, right = _forecast_column(index)
        # The icon band of a missing day has one flat color and does not animate.
        band = (left + 1, 10, right - 1, 24)
        for frame in frames:
            assert len(set(frame.crop(band).getdata())) == 1
        assert frames[0].crop(band).tobytes() == frames[-1].crop(band).tobytes()
