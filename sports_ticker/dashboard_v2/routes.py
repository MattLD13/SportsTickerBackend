"""Render the established public dashboard from version two data."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path
from time import monotonic

from flask import abort, current_app, render_template, request, send_file
from PIL import Image, ImageDraw

from sports_ticker.projections import select_display_content

from . import dashboard_v2


@dashboard_v2.get("/")
def public_index():
    """Render the original landing page with current V2 fleet facts."""

    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    ticker = tickers[0] if tickers else None
    settings = ticker.display_settings if ticker is not None else None
    mode = "pairing" if ticker is not None and not ticker.pairing.paired else (settings.mode if settings else "sports")
    snapshot = application.get_snapshot(ticker.ticker_id) if ticker is not None else None
    content = snapshot.content if snapshot is not None else ()
    active_sports = settings.active_sports if settings is not None else {}
    sports = _league_rows(active_sports, content, "sports")
    utilities = _utility_rows(content)
    markets = _league_rows(active_sports, content, "stock")
    fleet = _fleet_rows(tickers)
    visible = _display_content(application, ticker.ticker_id) if ticker is not None else {}
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
        live_count=shown,
        active_count=shown,
        league_count=len(sports) + len(utilities) + len(markets),
        display_modes=_display_modes(),
        demo_modes=_demo_modes(),
        panel_w=384,
        panel_h=32,
        scroll_px_s=round(1 / settings.scroll_speed) if settings and settings.scroll_speed else 33,
    )


@dashboard_v2.get("/dashboard")
def index():
    """Render the controller shell before the browser supplies its token."""

    return render_template("dashboard_v2/index.html")


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
    """Render one stable public panel preview without ticker state."""

    mode = str(request.args.get("mode") or "sports").strip().lower()
    if mode not in {item["id"] for item in _demo_modes()}:
        abort(404)
    content = _live_sports_content() if mode == "sports" else {}
    image = _render_preview(content or _demo_content(mode), mode)
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


def _league_rows(active_sports, content, family: str) -> list[dict[str, str]]:
    """Build complete original coverage chips from V2 configuration."""

    records = {str(item.data.get("sport", item.family)).lower() for item in content if item.family == family}
    available = (
        "nfl", "mlb", "nhl", "nba", "ncf_fbs", "ncf_fcs", "march_madness",
        "soccer_epl", "soccer_fa_cup", "soccer_champ", "soccer_champions_league", "soccer_mls",
    ) if family == "sports" else ("stock",) if family == "stock" else ()
    names = tuple(dict.fromkeys((*available, *(str(value).lower() for value in active_sports), *records)))
    return [
        {"id": name, "label": name.replace("_", " ").upper(), "state": "live" if name in records else "on"}
        for name in names if active_sports.get(name, True)
    ]


def _utility_rows(content) -> list[dict[str, str]]:
    families = ("weather", "music", "flights", "airports", "golf", "racing", "clock")
    shown = {item.family for item in content}
    return [{"id": name, "label": name.replace("_", " ").upper(), "state": "live" if name in shown else "on"} for name in families]


def _display_modes() -> list[dict[str, str]]:
    return [
        {"id": "sports", "name": "Sports", "desc": "Scores, golf, and racing", "group": "Sports"},
        {"id": "weather", "name": "Weather", "desc": "Current local conditions", "group": "Data"},
        {"id": "music", "name": "Music", "desc": "Connected Spotify playback", "group": "Data"},
        {"id": "flights", "name": "Flights", "desc": "Tracked visitor flight", "group": "Flight"},
        {"id": "airports", "name": "Airports", "desc": "Arrivals and departures", "group": "Flight"},
        {"id": "clock", "name": "Clock", "desc": "Full panel time and date", "group": "Data"},
    ]


def _demo_modes() -> list[dict[str, str]]:
    return [
        {"id": "sports", "label": "Sports", "kind": "scroll"},
        {"id": "weather", "label": "Weather", "kind": "static"},
        {"id": "music", "label": "Music", "kind": "canvas"},
        {"id": "flights", "label": "Flights", "kind": "static"},
        {"id": "airports", "label": "Airports", "kind": "static"},
        {"id": "clock", "label": "Clock", "kind": "canvas"},
    ]


def _live_sports_content() -> dict[str, list[dict[str, object]]]:
    """Return the first current sports projection that contains display items."""

    application = current_app.extensions["sports_ticker.backend_application"]
    for ticker in application.list_tickers():
        content = _display_content(application, ticker.ticker_id, mode="sports")
        if content:
            _preview_assets().prefetch(content)
            return content
    return {}


def _demo_content(mode: str) -> dict[str, list[dict[str, object]]]:
    """Return fixed public samples for every data-driven demo mode."""

    samples = {
        "sports": {
            "sports": [{
                "data": {
                    "type": "scoreboard",
                    "sport": "nhl",
                    "away_abbr": "NYR",
                    "away_score": 3,
                    "away_color": "#0038a8",
                    "away_logo": "demo:nyr",
                    "home_abbr": "NJD",
                    "home_score": 2,
                    "home_color": "#ce1126",
                    "home_logo": "demo:njd",
                    "state": "in",
                    "status": "3RD 12:41",
                    "situation": {"possession": "NYR"},
                },
            }],
        },
        "weather": {
            "weather": [{
                "data": {
                    "type": "weather",
                    "sport": "weather",
                    "home_abbr": "76",
                    "away_abbr": "NEW YORK CITY",
                    "status": "PARTLY CLOUDY",
                    "situation": {
                        "icon": "partly_cloudy",
                        "is_day": 1,
                        "cloud_cover": 42,
                        "stats": {"aqi": "38", "uv": "6", "feels": "77", "wind": "9", "humidity": "58"},
                        "forecast": [
                            {"day": "TODAY", "icon": "partly_cloudy", "high": 79, "low": 66},
                            {"day": "TUE", "icon": "sun", "high": 82, "low": 68},
                            {"day": "WED", "icon": "rain", "high": 75, "low": 65, "pop": 65, "wind": 12},
                            {"day": "THU", "icon": "cloud", "high": 77, "low": 64},
                            {"day": "FRI", "icon": "sun", "high": 81, "low": 67},
                        ],
                    },
                },
            }],
        },
        "flights": {
            "flights": [{
                "data": {
                    "type": "flight_visitor",
                    "sport": "flight",
                    "id": "flight_blank",
                    "guest_name": "NO FLIGHT SELECTED",
                    "route": "TRACKER > SETUP",
                    "origin_city": "TRACKER",
                    "dest_city": "SETUP",
                    "alt": 0,
                    "dist": 0,
                    "eta_str": "--",
                    "speed": 0,
                    "progress": 0,
                    "status": "ADD FLIGHT",
                    "is_delayed": False,
                    "is_live": False,
                },
            }],
        },
        "airports": {
            "airports": [{
                "data": {
                    "type": "flight_airport_hud",
                    "sport": "airport",
                    "weather": {"iata": "EWR", "city": "NEWARK", "away_abbr": "76F", "status": "PARTLY CLOUDY"},
                    "arrivals": [
                        {"flight_number": "UA 188", "airport_code": "LAX", "airport_city": "LOS ANGELES"},
                        {"flight_number": "DL 402", "airport_code": "ATL", "airport_city": "ATLANTA"},
                    ],
                    "departures": [
                        {"flight_number": "UA 205", "airport_code": "SFO", "airport_city": "SAN FRANCISCO"},
                        {"flight_number": "B6 117", "airport_code": "MCO", "airport_city": "ORLANDO"},
                    ],
                },
            }],
        },
    }
    return samples.get(mode, {})


def _display_content(application, ticker_id: str, *, mode: str | None = None) -> dict[str, list[dict[str, object]]]:
    data = application.project_data(ticker_id)
    settings = dict(data["settings"])
    if mode is not None:
        settings["mode"] = mode
        settings["pinned_content_id"] = ""
    return select_display_content(data["content"], settings)


class _PreviewAssets:
    """Read prepared team marks after a route-level prefetch completes."""

    def __init__(self, directory: Path) -> None:
        from ticker_core.platform.assets import AssetCoordinator

        self._coordinator = AssetCoordinator(directory)

    def image(self, url: str, processor: str, size: tuple[int, int]):
        if url.startswith("demo:"):
            return _demo_logo(url, size)
        return self._coordinator.image(url, processor, size)

    def prefetch(self, content: dict[str, list[dict[str, object]]]) -> None:
        """Prepare current sports logos before the renderer reads them."""

        from ticker_core.assets import AssetRequest

        requests = []
        for items in content.values():
            for item in items:
                data = item.get("data") if isinstance(item, dict) else None
                if not isinstance(data, dict):
                    continue
                for field in ("home_logo", "away_logo"):
                    url = str(data.get(field) or "").strip()
                    if url and not url.startswith("demo:"):
                        requests.append(AssetRequest(url, "logo", (22, 22)))
        for future in self._coordinator.prefetch(requests):
            try:
                future.result(timeout=5)
            except Exception:
                continue

    def close(self) -> None:
        """Stop the asset workers during backend shutdown."""

        self._coordinator.close()


def _preview_assets() -> _PreviewAssets:
    """Return one application-owned prepared asset view for public previews."""

    key = "sports_ticker.dashboard_preview_assets"
    assets = current_app.extensions.get(key)
    if isinstance(assets, _PreviewAssets):
        return assets
    directory = Path(current_app.config.get("DASHBOARD_ASSET_CACHE", "ticker_data/rewrite_assets"))
    assets = _PreviewAssets(directory)
    current_app.extensions[key] = assets
    return assets


@lru_cache(maxsize=4)
def _demo_logo(url: str, size: tuple[int, int]) -> Image.Image | None:
    """Draw a compact team mark for the fixed sports sample."""

    team = {
        "demo:nyr": ((0, 56, 168), (255, 255, 255), "NYR"),
        "demo:njd": ((206, 17, 38), (255, 255, 255), "NJD"),
    }.get(url)
    if team is None:
        return None
    width, height = size
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fill, text, label = team
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=max(2, width // 5), fill=fill, outline=text)
    box = draw.textbbox((0, 0), label)
    x = (width - (box[2] - box[0])) // 2
    y = (height - (box[3] - box[1])) // 2 - 1
    draw.text((x, y), label, fill=text)
    return image


@lru_cache(maxsize=1)
def _preview_catalog():
    from ticker_core.bootstrap import create_default_content_catalog
    return create_default_content_catalog(_preview_assets())


def _render_preview(content: dict[str, list[dict[str, object]]], mode: str) -> Image.Image:
    if mode == "airports":
        return _render_ewr_airport_demo()

    from ticker_core.context import RenderContext
    from ticker_core.rendering import ContentScene

    items = [item for records in content.values() for item in records if isinstance(item, dict)]
    if not items:
        image = Image.new("RGB", (384, 32), "black")
        ImageDraw.Draw(image).text((8, 10), f"NO {mode.upper()} DATA", fill="white")
        return image
    catalog = _preview_catalog()
    context = RenderContext(datetime.now())
    cards = [catalog.render(context, ContentScene(dict(item.get("data") or {}), mode)).image.convert("RGBA") for item in items]
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


def _render_ewr_airport_demo() -> Image.Image:
    """Render the complete fixed EWR board without renderer version coupling."""

    from ticker_core.rendering.pixels import draw_tiny_text

    image = Image.new("RGB", (384, 32), "black")
    draw = ImageDraw.Draw(image)
    blue = (80, 180, 255)
    green = (80, 255, 80)
    red = (255, 60, 60)
    white = (220, 220, 230)
    grey = (120, 120, 130)
    draw_tiny_text(draw, 3, 0, "EWR NEWARK", blue)
    draw_tiny_text(draw, 68, 0, "INBOUND", green)
    draw_tiny_text(draw, 196, 0, "OUTBOUND", red)
    draw_tiny_text(draw, 281, 0, "76F PARTLY CLOUDY", grey)
    draw.line((0, 6, 383, 6), fill=(30, 60, 100))
    draw.line((190, 8, 190, 31), fill=(30, 60, 100))
    for y, flight, airport, city in ((9, "UA188", "LAX", "LOS ANGELES"), (17, "DL402", "ATL", "ATLANTA")):
        draw_tiny_text(draw, 3, y, flight, green)
        draw_tiny_text(draw, 33, y, airport, grey)
        draw_tiny_text(draw, 53, y, city, white)
    for y, flight, airport, city in ((9, "UA205", "SFO", "SAN FRANCISCO"), (17, "B6117", "MCO", "ORLANDO")):
        draw_tiny_text(draw, 196, y, flight, red)
        draw_tiny_text(draw, 226, y, airport, grey)
        draw_tiny_text(draw, 246, y, city, white)
    return image


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
    return {"rss_mb": rss_mb, "threads": "-", "fds": fds}
