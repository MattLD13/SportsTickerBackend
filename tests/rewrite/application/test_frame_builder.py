from datetime import datetime, timezone

from PIL import Image

from ticker_core.app.frame_builder import FrameBuilder
from ticker_core.rendering import RenderedContent
from ticker_core.runtime import Content, FrameDecision, FrameKind


class Catalog:
    def render(self, context, scene):
        del context, scene
        return RenderedContent(Image.new("RGB", (384, 32), (1, 2, 3)), static=True)


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
