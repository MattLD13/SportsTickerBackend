from datetime import datetime, timedelta, timezone

from PIL import Image

from ticker_core.app.frame_builder import FrameBuilder
from ticker_core.rendering import RenderedContent
from ticker_core.rendering import ContentRendererCatalog
from ticker_core.runtime import Content, FrameDecision, FrameKind


class Catalog:
    def __init__(self):
        self.elapsed = []

    def render(self, context, scene):
        del context
        self.elapsed.append(scene.elapsed)
        return RenderedContent(Image.new("RGB", (384, 32), (1, 2, 3)))


class Utility:
    def empty(self, context):
        del context
        return Image.new("RGB", (384, 32))


class Alerts:
    def __init__(self):
        self.under = None

    def render(self, alert, elapsed, under):
        del alert, elapsed
        self.under = under
        return Image.new("RGB", (384, 32), (4, 5, 6))


class News:
    def __init__(self):
        self.calls = 0

    def apply(self, frame, news, elapsed):
        del news, elapsed
        self.calls += 1
        return Image.new("RGB", frame.size, (7, 8, 9))


class Viewport:
    def frame(self, offset):
        del offset
        return Image.new("RGB", (384, 32))


def keyed_catalog() -> ContentRendererCatalog:
    catalog = ContentRendererCatalog()
    renderer = Catalog()
    for family in ("scoreboard", "music", "weather", "racing", "golf", "clock", "empty"):
        catalog.register(family, renderer)
    return catalog


def decision(kind, **values):
    return FrameDecision(kind, 0.03, 100, False, datetime(2026, 8, 12, tzinfo=timezone.utc), "sports", **values)


def test_score_alert_uses_clean_base_and_outranks_news() -> None:
    alerts = Alerts()
    news = News()
    builder = FrameBuilder(Catalog(), Utility(), alerts, news, Viewport())
    content = Content("game", "game", "nba", {})

    builder.build(decision(FrameKind.STATIC, content=content, news={"id": "news"}))
    builder.build(decision(FrameKind.SCORE_ALERT, alert={"id": "score"}, news={"id": "news"}))

    assert alerts.under.getpixel((0, 0)) == (1, 2, 3)
    assert news.calls == 1


def test_static_content_receives_elapsed_animation_time() -> None:
    catalog = Catalog()
    builder = FrameBuilder(catalog, Utility(), Alerts(), News(), Viewport())
    content = Content("race", "racing", "indycar", {})

    builder.build(decision(FrameKind.STATIC, content=content, content_elapsed=2.5))

    assert catalog.elapsed == [2.5]


def test_visual_key_owns_update_animation_without_crashing() -> None:
    builder = FrameBuilder(Catalog(), Utility(), Alerts(), News(), Viewport())
    first = decision(FrameKind.UPDATE, update_version="2026.08", update_progress=0.2)
    second = decision(FrameKind.UPDATE, update_version="2026.08", update_progress=0.2)
    assert builder.visual_key(first) == builder.visual_key(second)


def test_visual_key_preserves_rendering_cadence_classes() -> None:
    builder = FrameBuilder(keyed_catalog(), Utility(), Alerts(), News(), Viewport())
    base = datetime(2026, 8, 12, tzinfo=timezone.utc)

    def at(kind, **values):
        return FrameDecision(kind, 0.03, 100, False, base, "sports", **values)

    music = Content("music", "music", "music", {"type": "music", "sport": "music"})
    golf = Content("golf", "golf", "golf", {"type": "golf", "sport": "golf", "sports_presentation": "pinned"})
    weather = Content("weather", "weather", "weather", {"type": "weather", "sport": "weather"})
    racing = Content("race", "racing", "f1", {"type": "racing", "sport": "f1"})
    clock = Content("clock", "clock", "clock", {"type": "clock", "sport": "clock"})

    assert builder.visual_key(at(FrameKind.STATIC, content=music, content_elapsed=0.0)) != builder.visual_key(
        FrameDecision(FrameKind.STATIC, 0.03, 100, False, base + timedelta(seconds=0.04), "sports", content=music),
    )
    assert builder.visual_key(at(FrameKind.STATIC, content=weather)) != builder.visual_key(
        FrameDecision(FrameKind.STATIC, 0.03, 100, False, base + timedelta(seconds=0.04), "sports", content=weather),
    )
    assert builder.visual_key(at(FrameKind.STATIC, content=racing)) != builder.visual_key(
        FrameDecision(FrameKind.STATIC, 0.03, 100, False, base + timedelta(seconds=0.04), "sports", content=racing),
    )
    assert builder.visual_key(at(FrameKind.STATIC, content=golf, content_elapsed=0.0)) == builder.visual_key(
        FrameDecision(FrameKind.STATIC, 0.03, 100, False, base + timedelta(seconds=3.9), "sports", content=golf, content_elapsed=3.9),
    )
    assert builder.visual_key(at(FrameKind.STATIC, content=golf, content_elapsed=0.0)) != builder.visual_key(
        FrameDecision(FrameKind.STATIC, 0.03, 100, False, base + timedelta(seconds=4.1), "sports", content=golf, content_elapsed=4.1),
    )
    assert builder.visual_key(at(FrameKind.STATIC, content=clock)) == builder.visual_key(
        FrameDecision(FrameKind.STATIC, 0.03, 100, False, base + timedelta(seconds=0.9), "sports", content=clock),
    )
    assert builder.visual_key(at(FrameKind.STATIC, content=clock)) != builder.visual_key(
        FrameDecision(FrameKind.STATIC, 0.03, 100, False, base + timedelta(seconds=1.1), "sports", content=clock),
    )


def test_visual_key_invalidates_empty_scroll_overlays_output_and_assets() -> None:
    builder = FrameBuilder(keyed_catalog(), Utility(), Alerts(), News(), Viewport())
    base = datetime(2026, 8, 12, tzinfo=timezone.utc)
    empty = decision(FrameKind.EMPTY)
    assert builder.visual_key(empty) != builder.visual_key(
        FrameDecision(FrameKind.EMPTY, 0.03, 100, False, base + timedelta(seconds=0.2), "sports"),
    )
    scroll = decision(FrameKind.SCROLL, scroll_offset=1)
    assert builder.visual_key(scroll) != builder.visual_key(
        decision(FrameKind.SCROLL, scroll_offset=2),
    )
    pairing = decision(FrameKind.PAIRING, pairing_code="123456")
    assert builder.visual_key(pairing) != builder.visual_key(
        FrameDecision(FrameKind.PAIRING, 0.03, 100, False, base + timedelta(seconds=0.5), "sports", pairing_code="123456"),
    )
    offline = decision(FrameKind.OFFLINE, offline_for=2.0)
    assert builder.visual_key(offline) != builder.visual_key(
        FrameDecision(FrameKind.OFFLINE, 0.03, 100, False, base + timedelta(seconds=0.5), "sports", offline_for=2.0),
    )
    static = decision(FrameKind.STATIC, content=Content("game", "scoreboard", "nfl", {"type": "scoreboard", "sport": "nfl"}))
    assert builder.visual_key(static, asset_revision=1) != builder.visual_key(static, asset_revision=2)


def test_static_no_games_content_advances_the_minute_progress_bar() -> None:
    builder = FrameBuilder(keyed_catalog(), Utility(), Alerts(), News(), Viewport())
    base = datetime(2026, 8, 12, tzinfo=timezone.utc)
    content = Content("no-games", "empty", "sports", {"no_games": True})
    first = FrameDecision(FrameKind.STATIC, 0.03, 100, False, base, "sports", content=content)
    second = FrameDecision(
        FrameKind.STATIC,
        0.03,
        100,
        False,
        base + timedelta(seconds=0.2),
        "sports",
        content=content,
    )

    assert builder.visual_key(first) != builder.visual_key(second)
