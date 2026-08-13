"""Render the established public dashboard from version two data."""

from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import wait
from io import BytesIO
import os
from pathlib import Path
from threading import active_count
from time import monotonic

from flask import abort, current_app, render_template, request, send_file
from PIL import Image, ImageDraw

from . import dashboard_v2


@dashboard_v2.get("/")
@dashboard_v2.get("/dashboard")
def index():
    """Render the original landing page with current V2 fleet facts."""

    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    ticker = tickers[0] if tickers else None
    settings = ticker.display_settings if ticker is not None else None
    mode = "pairing" if ticker is not None and not ticker.pairing.paired else (settings.mode if settings else "sports")
    snapshot = application.get_snapshot(ticker.ticker_id) if ticker is not None else None
    content = snapshot.content if snapshot is not None else ()
    active_sports = settings.active_sports if settings is not None else {}
    fleet = _fleet_rows(tickers)
    visible = _display_content(application, ticker.ticker_id) if ticker is not None else {}
    sports = _league_rows(active_sports, visible)
    utilities = _utility_rows(visible)
    markets = _market_rows(content, visible)
    shown = sum(len(items) for items in visible.values())
    return render_template(
        "dashboard/index.html",
        version_hash=_version_hash(),
        server_version=_version_hash(),
        uptime_str=_uptime(),
        fleet=fleet,
        fleet_online=sum(1 for item in fleet if item["link"] == "online"),
        fleet_dark=sum(1 for item in fleet if item["dark_reason"]),
        server_health=_server_health(),
        global_mode=mode,
        sports_leagues=sports,
        util_leagues=utilities,
        market_leagues=markets,
        panel_cards=shown,
        feed_count=len(sports) + len(utilities) + len(markets),
        display_modes=_display_modes(),
        demo_modes=_demo_modes(),
        panel_w=384,
        panel_h=32,
        scroll_px_s=round(1 / settings.scroll_speed) if settings and settings.scroll_speed else 33,
    )


@dashboard_v2.get("/demo")
def demo():
    """Render the original full-screen panel demo from V2 snapshot data."""

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
    """Render one no-hardware panel preview from current V2 data."""

    mode = str(request.args.get("mode") or "sports").strip().lower()
    if mode not in {item["id"] for item in _demo_modes()}:
        abort(404)
    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    if not tickers:
        abort(404)
    image = _render_preview(_display_content(application, tickers[0].ticker_id, mode=mode), mode)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return send_file(output, mimetype="image/png", max_age=0)


_STARTED_AT = monotonic()


def _version_hash() -> str:
    """Read the deployed source build identifier."""

    configured = str(current_app.config.get("VERSION") or "").strip()
    if configured:
        return configured[:12]
    try:
        return Path(os.environ.get("TICKER_VERSION_FILE", "VERSION")).read_text(encoding="utf-8").strip()[:12] or "unknown"
    except OSError:
        return "unknown"


def _uptime() -> str:
    seconds = int(monotonic() - _STARTED_AT)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m {seconds}s"


def _fleet_rows(tickers) -> list[dict[str, object]]:
    """Project Pi heartbeat metadata into established fleet rows."""

    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for ticker in tickers:
        last_seen = ticker.device.last_seen_at
        age = None if last_seen is None else max(0, int(now - last_seen))
        metadata = ticker.device.metadata
        temperature = metadata.get("temperature_c")
        rows.append({
            "name": ticker.name,
            "id": ticker.ticker_id[:8],
            "link": "online" if age is not None and age < 90 else "off",
            "mode": ("pairing" if not ticker.pairing.paired else ticker.display_settings.mode).replace("_", " "),
            "last_poll": "never" if age is None else f"{age}s ago",
            "uptime": _duration(metadata.get("uptime_seconds")),
            "temp": f"{float(temperature):.0f}C" if isinstance(temperature, (int, float)) else "-",
            "build": str(metadata.get("build") or "-"),
            "dark_reason": "" if age is not None and age < 90 else "No recent heartbeat",
        })
    return rows


def _league_rows(active_sports, visible) -> list[dict[str, str]]:
    """Build every supported league chip from selected ticker content."""

    available = (
        "nfl", "mlb", "nhl", "nba", "ncf_fbs", "ncf_fcs", "march_madness",
        "soccer_epl", "soccer_fa_cup", "soccer_champ", "soccer_champions_league", "soccer_mls",
    )
    records = _visible_sports(visible)
    names = tuple(dict.fromkeys((*available, *(str(value).lower() for value in active_sports), *records)))
    rows = []
    for name in names:
        enabled = bool(active_sports.get(name, True))
        state = "off" if not enabled else "live" if name in records else "on"
        rows.append({"id": name, "label": name.replace("_", " ").upper(), "state": state})
    return rows


def _market_rows(content, visible) -> list[dict[str, str]]:
    """Show individual configured market symbols instead of one stock label."""

    configured = ["SPY", "QQQ", "DIA", "IWM"]
    for item in content:
        if getattr(item, "family", "") != "stock":
            continue
        data = getattr(item, "data", {})
        symbol = str(data.get("symbol") or data.get("home_abbr") or "").upper()
        if symbol and symbol not in configured:
            configured.append(symbol)
    shown = {
        str((item.get("data") or {}).get("symbol") or (item.get("data") or {}).get("home_abbr") or "").upper()
        for item in visible.get("stock", ())
        if isinstance(item, dict)
    }
    return [{"id": symbol.lower(), "label": symbol, "state": "live" if symbol in shown else "on"} for symbol in configured]


def _utility_rows(visible) -> list[dict[str, str]]:
    """Show a utility as live only when the selected mode can render it."""

    families = ("weather", "music", "flights", "airports", "golf", "racing", "clock")
    shown = set(visible)
    return [{"id": name, "label": name.replace("_", " ").upper(), "state": "live" if name in shown else "on"} for name in families]


def _display_modes() -> list[dict[str, str]]:
    return [
        {"id": "sports", "name": "Sports", "desc": "Scores, golf, and racing", "group": "Sports"},
        {"id": "weather", "name": "Weather", "desc": "Current local conditions", "group": "Data"},
        {"id": "music", "name": "Music", "desc": "Connected Spotify playback", "group": "Data"},
        {"id": "flights", "name": "Flights", "desc": "Tracked visitor flight", "group": "Flight"},
        {"id": "airports", "name": "Airports", "desc": "Arrivals and departures", "group": "Flight"},
        {"id": "stock", "name": "Stocks", "desc": "Live market index quotes", "group": "Data"},
        {"id": "clock", "name": "Clock", "desc": "Full panel time and date", "group": "Data"},
    ]


def _demo_modes() -> list[dict[str, str]]:
    return [
        {"id": "sports", "label": "Sports", "kind": "scroll"},
        {"id": "weather", "label": "Weather", "kind": "static"},
        {"id": "music", "label": "Music", "kind": "static"},
        {"id": "flights", "label": "Flights", "kind": "static"},
        {"id": "airports", "label": "Airports", "kind": "static"},
        {"id": "stock", "label": "Stocks", "kind": "scroll"},
        {"id": "clock", "label": "Clock", "kind": "canvas"},
    ]


def _display_content(application, ticker_id: str, *, mode: str | None = None) -> dict[str, list[dict[str, object]]]:
    data = application.project_data(ticker_id, mode=mode)
    return data["content"]


def _preview_assets():
    """Return the long-term server cache used by the public panel renderer."""

    assets = current_app.extensions.get("sports_ticker.dashboard_assets")
    if assets is not None:
        return assets
    from ticker_core.platform.assets import AssetCoordinator

    directory = Path(current_app.config.get("DASHBOARD_ASSET_CACHE", "ticker_data/dashboard-assets"))
    assets = AssetCoordinator(directory)
    assets.start()
    current_app.extensions["sports_ticker.dashboard_assets"] = assets
    return assets


def _preview_catalog(assets):
    """Build the content catalog once around the shared image cache."""

    catalog = current_app.extensions.get("sports_ticker.dashboard_preview_catalog")
    if catalog is not None:
        return catalog
    from ticker_core.bootstrap import create_default_content_catalog

    catalog = create_default_content_catalog(assets)
    current_app.extensions["sports_ticker.dashboard_preview_catalog"] = catalog
    return catalog


def _render_preview(content: dict[str, list[dict[str, object]]], mode: str) -> Image.Image:
    from ticker_core.context import RenderContext
    from ticker_core.rendering import ContentScene

    items = [item for records in content.values() for item in records if isinstance(item, dict)]
    if not items:
        image = Image.new("RGB", (384, 32), "black")
        ImageDraw.Draw(image).text((8, 10), f"NO {mode.upper()} DATA", fill="white")
        return image
    assets = _preview_assets()
    source_items = [dict(item.get("data") or {}) for item in items]
    futures = assets.prefetch_payload({"content": {"sports": source_items}})
    wait(futures, timeout=5)
    catalog = _preview_catalog(assets)
    context = RenderContext(datetime.now())
    cards = [catalog.render(context, ContentScene(dict(item.get("data") or {}), mode)).image.convert("RGBA") for item in items]
    if mode not in {"sports", "stock"}:
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


def _duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    hours, remainder = divmod(max(0, int(value)), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _server_health() -> dict[str, object]:
    try:
        import resource
        rss_mb: float | str = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except ImportError:
        rss_mb = "-"
    try:
        fds: int | str = len(os.listdir("/proc/self/fd"))
    except OSError:
        fds = "-"
    return {"rss_mb": rss_mb, "threads": active_count(), "fds": fds}


def _visible_sports(visible) -> set[str]:
    """Read selected league names without confusing fetched and rendered data."""

    names = set()
    for item in visible.get("sports", ()):
        if not isinstance(item, dict):
            continue
        data = item.get("data") or {}
        if isinstance(data, dict):
            name = str(data.get("sport") or data.get("league") or "").lower()
            if name:
                names.add(name)
    return names
