"""Render the authenticated version two controller shell."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from io import BytesIO

from flask import abort, current_app, render_template, request, send_file
from PIL import Image, ImageDraw

from sports_ticker.projections import select_display_content

from . import dashboard_v2


@dashboard_v2.get("/dashboard")
def index():
    """Render the controller shell before the browser supplies its token."""

    return render_template("dashboard_v2/index.html")


@dashboard_v2.get("/")
@dashboard_v2.get("/demo")
def demo():
    """Render the public LED panel demonstration from V2 display data."""

    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    settings = tickers[0].display_settings if tickers else None
    return render_template(
        "demo_ticker.html",
        demo_modes=_demo_modes(),
        panel_w=384,
        panel_h=32,
        scroll_px_s=round(1 / settings.scroll_speed) if settings and settings.scroll_speed else 33,
    )


@dashboard_v2.get("/api/preview/strip.png")
def preview_strip():
    """Render one current public panel frame without hardware access."""

    mode = str(request.args.get("mode") or "sports").strip().lower()
    if mode not in {item["id"] for item in _demo_modes()}:
        abort(404)
    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    if not tickers:
        abort(404)
    image = _render_preview(_display_content(application, tickers[0].ticker_id, mode), mode)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return send_file(output, mimetype="image/png", max_age=0)


def _demo_modes() -> list[dict[str, str]]:
    """Return the public demo modes that have a matching V2 renderer."""

    return [
        {"id": "sports", "label": "Sports", "kind": "scroll"},
        {"id": "weather", "label": "Weather", "kind": "static"},
        {"id": "music", "label": "Music", "kind": "static"},
        {"id": "flights", "label": "Flights", "kind": "static"},
        {"id": "airports", "label": "Airports", "kind": "static"},
        {"id": "clock", "label": "Clock", "kind": "canvas"},
    ]


def _display_content(application, ticker_id: str, mode: str) -> dict[str, list[dict[str, object]]]:
    """Project the selected mode through the shared V2 content boundary."""

    data = application.project_data(ticker_id)
    settings = dict(data["settings"])
    settings["mode"] = mode
    settings["pinned_content_id"] = ""
    return select_display_content(data["content"], settings)


class _PreviewAssets:
    """Disable asset reads while the public preview creates a frame."""

    def image(self, url: str, processor: str, size: tuple[int, int]):
        del url, processor, size
        return None


@lru_cache(maxsize=1)
def _preview_catalog():
    """Create one memory-only catalog for public preview frames."""

    from ticker_core.bootstrap import create_default_content_catalog

    return create_default_content_catalog(_PreviewAssets())


def _render_preview(content: dict[str, list[dict[str, object]]], mode: str) -> Image.Image:
    """Render the V2 content selection into one 384 by 32 frame."""

    from ticker_core.context import RenderContext
    from ticker_core.rendering import ContentScene

    items = [item for records in content.values() for item in records]
    if not items:
        image = Image.new("RGB", (384, 32), "black")
        ImageDraw.Draw(image).text((8, 10), f"NO {mode.upper()} DATA", fill="white")
        return image
    catalog = _preview_catalog()
    context = RenderContext(datetime.now())
    cards = [
        catalog.render(context, ContentScene(dict(item.get("data") or {}), mode)).image.convert("RGBA")
        for item in items
    ]
    if mode != "sports":
        return cards[0].convert("RGB")
    width = sum(card.width + 1 for card in cards)
    strip = Image.new("RGBA", (max(384, width), 32), "black")
    x = 0
    draw = ImageDraw.Draw(strip)
    for card in cards:
        draw.line((x, 0, x, 31), fill=(45, 45, 45, 255))
        x += 1
        strip.alpha_composite(card, (x, 0))
        x += card.width
    return strip.convert("RGB")
