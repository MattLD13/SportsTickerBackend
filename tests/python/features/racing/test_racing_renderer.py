"""Exercise the native racing renderer without a legacy controller oracle."""

from datetime import datetime, timezone

import pytest
from PIL import Image

from ticker_core.context import RenderContext
from ticker_core.features.racing import MemoryRacingAssets, RacingRenderer
from ticker_core.rendering import ContentScene, load_default_font_set
from ticker_core.rendering.catalog import content_family
from sports_ticker.projections.racing_display import racing_cards


def _item(series: str) -> dict:
    item = {
        "sport": series,
        "state": "in",
        series: {
            "short_name": "Test Grand Prix",
            "session_type": "Race",
            "flag": "GREEN",
            "drivers": [{"pos": "1", "abbr": "AAA", "name": "Driver AAA", "car": "1", "gap": ""}],
        },
    }
    item["racing_display"] = {"cards": racing_cards(item)}
    return item


def test_each_racing_series_renders_a_panel_frame() -> None:
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    context = RenderContext(datetime(2026, 8, 11, tzinfo=timezone.utc))

    for series in ("indycar", "f1", "nascar", "wec", "imsa"):
        assert content_family({"sport": series, "type": series}, "sports") == "racing"
        scroll = renderer.render(context, ContentScene(_item(series), "sports")).image
        full = renderer.render(
            context,
            ContentScene({**_item(series), "sports_presentation": "pinned"}, "sports"),
        ).image

        assert scroll.height == full.height == 32
        assert scroll.width >= 128
        assert full.size == (384, 32)


def test_completed_f1_cards_show_leader_time_and_following_gaps(monkeypatch) -> None:
    import ticker_core.features.racing.renderer as rendering

    drawn = []
    original = rendering.draw_tiny_text

    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)

    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    item = _item("f1")
    item.update(state="post", sports_presentation="pinned")
    item["f1"].update(session_type="Practice 1", drivers=[
        {"pos": 1, "abbr": "LEC", "name": "Charles Leclerc", "gap": "1:36.052", "best_time": "1:36.052"},
        {"pos": 2, "abbr": "VER", "name": "Max Verstappen", "gap": "+0.084", "best_time": "1:36.136"},
    ])
    item["racing_display"] = {"cards": racing_cards(item)}
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    renderer.render(RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert "1:36.052" in drawn
    assert "+0.084" in drawn
    assert "1:36.136" not in drawn


@pytest.mark.parametrize("series,count", [("f1", 22), ("indycar", 27), ("nascar", 37), ("wec", 35), ("imsa", 54)])
def test_pinned_carousel_builds_the_entire_field(series, count):
    item = _item(series)
    item["sports_presentation"] = "pinned"
    item[series]["drivers"] = [
        {"pos": n, "car": str(n), "name": f"Car {n}", "gap": f"+{n}.123"}
        for n in range(1, count + 1)
    ]
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    result = renderer.render(RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    cards, strip, width = next(iter(renderer._strip_cache.values()))
    assert len(cards) == count
    assert width == sum(card.width + 6 for card in cards)
    assert strip.width > width
    assert result.image.size == (384, 32)


def test_pinned_racing_visual_key_ignores_unrelated_asset_revisions() -> None:
    assets = MemoryRacingAssets()
    renderer = RacingRenderer(load_default_font_set(), assets)
    item = _item("f1")
    item["sports_presentation"] = "pinned"
    car_url = "https://assets.example/f1-car.png"
    item["f1"]["drivers"][0]["car_illustration"] = car_url
    scene = ContentScene(item, "sports")
    context = RenderContext(datetime(2026, 10, 25, tzinfo=timezone.utc))

    original = renderer.visual_key(context, scene, assets.revision)
    assets.put_image("https://assets.example/unrelated.png", "logo", (18, 18), Image.new("RGBA", (18, 18)))
    unrelated_asset = renderer.visual_key(context, scene, assets.revision)
    assert unrelated_asset == original

    assets.put_image(car_url, "car", (130, 20), Image.new("RGBA", (130, 20)))
    active_car_ready = renderer.visual_key(context, scene, assets.revision)
    assert active_car_ready != unrelated_asset


def test_pinned_carousel_reuses_unchanged_driver_cards(monkeypatch) -> None:
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    context = RenderContext(datetime(2026, 10, 25, tzinfo=timezone.utc))
    item = _item("f1")
    item["sports_presentation"] = "pinned"
    item["f1"]["drivers"] = [
        {"pos": 1, "abbr": "AAA", "name": "Driver AAA", "car": "1", "gap": "+0.1"},
        {"pos": 2, "abbr": "BBB", "name": "Driver BBB", "car": "2", "gap": "+0.2"},
    ]
    calls = []
    original = RacingRenderer._driver_card_base

    def count_card(self, driver, f1):
        calls.append(str(driver.get("abbr")))
        return original(self, driver, f1)

    monkeypatch.setattr(RacingRenderer, "_driver_card_base", count_card)
    first = renderer.render(context, ContentScene(item, "sports")).image
    updated = {**item, "f1": {**item["f1"], "drivers": [
        item["f1"]["drivers"][0], {**item["f1"]["drivers"][1], "gap": "+0.3"},
    ]}}
    second = renderer.render(context, ContentScene(updated, "sports")).image

    assert calls == ["AAA", "BBB"]
    assert first.tobytes() != second.tobytes()


def test_indycar_race_uses_speed_instead_of_gap(monkeypatch):
    import ticker_core.features.racing.renderer as rendering

    drawn = []
    original = rendering.draw_tiny_text

    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)

    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    item = _item("indycar")
    item["sports_presentation"] = "pinned"
    item["indycar"]["drivers"] = [{"pos": 2, "car": "2", "name": "Driver", "gap": "+1.234", "speed": "220.123"}]
    item["racing_display"] = {"cards": racing_cards(item)}
    RacingRenderer(load_default_font_set(), MemoryRacingAssets()).render(
        RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert "+1.234" not in drawn
    assert "220.123 MPH" in drawn


def test_scroll_has_separate_class_cards_in_class_order():
    from tools.mini.racing_vectors import game
    item = game("imsa")
    item["racing_display"] = {"cards": racing_cards(item)}
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    result = renderer.render(RenderContext(datetime(2026, 10, 24, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert result.image.height == 32
    assert result.image.width < 128 * 4
    assert [card["class_label"] for card in item["racing_display"]["cards"]] == ["GTP", "LMP2", "GTD PRO", "GTD"]


def test_flag_labels_stay_out_of_scroll_header_and_remain_in_pinned_view(monkeypatch):
    import ticker_core.features.racing.renderer as rendering
    from tools.mini.racing_vectors import game
    drawn = []
    original = rendering.draw_tiny_text

    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)

    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    for code in ("SAFETY CAR", "VSC", "FCY", "UNKNOWN"):
        item = game("f1", code)
        item["racing_display"] = {"cards": racing_cards(item)}
        renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
        label = item["racing_display"]["cards"][0]["signals"][0]["label"]
        for pinned in (False, True):
            drawn.clear()
            if pinned:
                item["sports_presentation"] = "pinned"
            renderer.render(RenderContext(datetime(2026, 10, 24, tzinfo=timezone.utc)), ContentScene(item, "sports"))
            assert any(label in text for text in drawn) == pinned
            assert all("None" not in text for text in drawn)


def test_multiclass_scroll_uses_class_colors_and_one_flag(monkeypatch):
    import ticker_core.features.racing.renderer as rendering
    from tools.mini.racing_vectors import game
    item = game("wec")
    item["racing_display"] = {"cards": racing_cards(item)}
    item["racing_display"]["cards"][0]["class_color"] = "#e21e19"
    item["racing_display"]["cards"][1]["class_color"] = "#0b9314"
    drawn, flags = [], []
    original_text, original_flag = rendering.draw_tiny_text, rendering._draw_mini_flag
    def record(draw, x, y, text, color):
        drawn.append((text, color))
        return original_text(draw, x, y, text, color)
    def flag(draw, x, y, signal):
        flags.append(x)
        return original_flag(draw, x, y, signal)
    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    monkeypatch.setattr(rendering, "_draw_mini_flag", flag)
    renderer = RacingRenderer(load_default_font_set(), MemoryRacingAssets())
    image = renderer.render(RenderContext(datetime(2026, 10, 24, tzinfo=timezone.utc)), ContentScene(item, "sports")).image
    assert image.width < 262 and image.height == 32
    assert ("HY", (226, 30, 25)) in drawn
    assert ("LMGT3", (11, 147, 20)) in drawn
    assert flags == [image.width - 12]


def test_pinned_race_does_not_substitute_interval_for_missing_gap(monkeypatch):
    import ticker_core.features.racing.renderer as rendering
    drawn = []
    original = rendering.draw_tiny_text
    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)
    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    item = _item("f1")
    item["sports_presentation"] = "pinned"
    item["f1"]["drivers"] = [{"pos": 2, "car": "1", "name": "Driver", "interval": "+0.723"}]
    item["racing_display"] = {"cards": racing_cards(item)}
    RacingRenderer(load_default_font_set(), MemoryRacingAssets()).render(
        RenderContext(datetime(2026, 10, 23, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert "+0.723" not in drawn


@pytest.mark.parametrize("sport", ["f1", "indycar", "nascar", "wec", "imsa"])
def test_scroll_header_includes_lap_count_for_live_races(sport, monkeypatch):
    import ticker_core.features.racing.renderer as rendering
    from tools.mini.racing_vectors import game
    drawn = []
    original = rendering.draw_tiny_text
    def record(draw, x, y, text, color):
        drawn.append(str(text))
        return original(draw, x, y, text, color)
    monkeypatch.setattr(rendering, "draw_tiny_text", record)
    item = game(sport)
    item["racing_display"] = {"cards": racing_cards(item)}
    RacingRenderer(load_default_font_set(), MemoryRacingAssets()).render(
        RenderContext(datetime(2026, 10, 24, tzinfo=timezone.utc)), ContentScene(item, "sports"))
    assert any("65/200" in text for text in drawn)
