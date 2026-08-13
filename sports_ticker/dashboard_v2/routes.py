"""Render the original public dashboard from version two data."""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from flask import current_app, render_template

from . import dashboard_v2


@dashboard_v2.get("/")
@dashboard_v2.get("/dashboard")
def index():
    """Render the original landing page with the current v2 snapshot."""

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
    health = application.scheduler_health() or {}
    fleet = _fleet_rows(tickers, mode)
    shown = sum(1 for item in content if item.is_shown)
    version = _version_hash()
    return render_template(
        "dashboard/index.html",
        version_hash=version,
        server_version=f"v2 {version}",
        uptime_str=_uptime(),
        fleet=fleet,
        fleet_online=sum(1 for item in fleet if item["link"] == "online"),
        fleet_dark=0,
        server_health={"rss_mb": "—", "threads": "—", "fds": "—"},
        global_mode=mode,
        sports_leagues=sports,
        util_leagues=utilities,
        market_leagues=markets,
        live_count=shown,
        active_count=sum(1 for item in sports + utilities + markets if item["state"] != "off"),
        league_count=len(sports) + len(utilities) + len(markets),
        display_modes=_display_modes(),
        demo_modes=_demo_modes(),
        panel_w=384,
        panel_h=32,
        scroll_px_s=round(1 / settings.scroll_speed) if settings and settings.scroll_speed else 33,
        provider_health=health,
    )


_STARTED_AT = monotonic()


def _version_hash() -> str:
    """Read the deployed build identifier without starting an extra service."""

    return str(current_app.config.get("VERSION", "v2"))[:7]


def _uptime() -> str:
    """Format the current process uptime for the original status panel."""

    seconds = int(monotonic() - _STARTED_AT)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m {seconds}s"


def _fleet_rows(tickers, mode: str) -> list[dict[str, object]]:
    """Project device health into the established landing-page fleet table."""

    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for ticker in tickers:
        last_seen = ticker.device.last_seen_at
        age = None if last_seen is None else max(0, int(now - last_seen))
        link = "online" if age is not None and age < 90 else "off"
        rows.append({
            "name": ticker.name,
            "id": ticker.ticker_id[:8],
            "link": link,
            "mode": mode.replace("_", " "),
            "last_poll": "never" if age is None else f"{age}s ago",
            "uptime": "—",
            "temp": "—",
            "build": "v2",
            "dark_reason": "" if link == "online" else "No recent heartbeat",
        })
    return rows


def _league_rows(active_sports, content, family: str) -> list[dict[str, str]]:
    """Build original coverage chips from v2 settings and current content."""

    records = {item.data.get("sport", item.family) for item in content if item.family == family}
    names = sorted({str(value).lower() for value in active_sports} | {str(value).lower() for value in records})
    return [{"id": name, "label": name.replace("_", " ").upper(), "state": "live" if name in records else "on"} for name in names]


def _utility_rows(content) -> list[dict[str, str]]:
    """Build original utility chips from the published v2 families."""

    families = ("weather", "music", "flights", "airports", "golf", "racing", "clock")
    shown = {item.family for item in content}
    return [{"id": name, "label": name.replace("_", " ").upper(), "state": "live" if name in shown else "on"} for name in families]


def _display_modes() -> list[dict[str, str]]:
    """Describe only the canonical v2 display modes."""

    return [
        {"id": "sports", "name": "Sports", "desc": "Scores, golf, and racing", "group": "Sports"},
        {"id": "weather", "name": "Weather", "desc": "Current local conditions", "group": "Data"},
        {"id": "music", "name": "Music", "desc": "Connected Spotify playback", "group": "Data"},
        {"id": "flights", "name": "Flights", "desc": "Tracked visitor flight", "group": "Flight"},
        {"id": "airports", "name": "Airports", "desc": "Arrivals and departures", "group": "Flight"},
        {"id": "clock", "name": "Clock", "desc": "Full panel time and date", "group": "Data"},
    ]


def _demo_modes() -> list[dict[str, str]]:
    """Retain original page controls until v2 preview frames are added."""

    return [{"id": "clock", "label": "Clock", "kind": "canvas"}]

    return render_template("dashboard_v2/index.html")
