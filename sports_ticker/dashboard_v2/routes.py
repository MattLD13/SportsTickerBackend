"""Render the established public dashboard from version two data."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
import os
import hashlib
from pathlib import Path
from time import monotonic, time
from concurrent.futures import wait
from zoneinfo import ZoneInfo
from threading import Lock

from flask import abort, current_app, render_template, request, send_file
from PIL import Image

from sports_ticker.domain import DisplaySettings
from sports_ticker.projections import project_data_v2, select_display_content

from . import dashboard_v2
from .preview import PreviewRenderer, case_items, layout_case, layout_library


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
        version_hash=_version_hash(),
        demo_modes=_demo_modes(),
        panel_w=384,
        panel_h=32,
        scroll_px_s=round(1 / settings.scroll_speed) if settings and settings.scroll_speed else 33,
    )


@dashboard_v2.get("/demo/portfolio")
def demo_portfolio():
    """Render an embeddable panel demo for portfolio pages."""

    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    settings = tickers[0].display_settings if tickers else None
    return render_template(
        "demo_portfolio.html",
        version_hash=_version_hash(),
        demo_modes=_demo_modes(),
        panel_w=384,
        panel_h=32,
        scroll_px_s=round(1 / settings.scroll_speed) if settings and settings.scroll_speed else 33,
    )


@dashboard_v2.get("/demo/layouts")
def demo_layouts():
    """Show public sample layouts without reading or changing ticker state."""

    return render_template("demo_layouts.html", version_hash=_version_hash())


@dashboard_v2.get("/api/v2/demo/frame.png")
def demo_frame():
    """Render public content through the current production Pi renderer."""
    name = request.args.get("case", "")
    row = layout_case(name) if name else None
    if name and row is None:
        abort(404)
    default_presentation = "rotation" if not row or not row["main"]["full"] else "pinned"
    presentation = request.args.get("presentation", default_presentation)
    if presentation not in {"rotation", "pinned"}:
        abort(400)
    mode = row["mode"] if row else request.args.get("mode", "sports")
    if row:
        if not row["main"]["available"]:
            abort(404)
        if presentation == "rotation" and not row["main"]["pane"]:
            abort(400)
        if presentation == "pinned" and not row["main"]["full"]:
            abort(400)
        items = case_items(row, presentation)
        content = {mode: [{"data": item} for item in items]}
        now = datetime.fromisoformat(row.get("example_time", layout_library()["example_time"]))
    else:
        if mode not in {item["id"] for item in _demo_modes()}:
            abort(404)
        content = _live_sports_content() if mode == "sports" else {}
        content = content or _demo_content(mode)
        items = [dict(item["data"]) for records in content.values() for item in records if item.get("is_shown", True)]
        if mode not in {"sports", "stock"}:
            presentation = "pinned"
        timestamp = int(time() * 4) / 4
        now = datetime.fromtimestamp(timestamp, ZoneInfo("America/New_York"))
    assets = _preview_assets()
    assets.prefetch(content)
    encoded = assets.renderer.render(items, mode, presentation, now, row=row)
    response = send_file(BytesIO(encoded), mimetype="image/png", max_age=0)
    response.set_etag(hashlib.sha256(encoded).hexdigest())
    response.headers["X-Ticker-Renderer"] = _version_hash()
    return response.make_conditional(request)


_STARTED_AT = monotonic()
_SAMPLE_STARTED = time()
_PREVIEW_LOCK = Lock()


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
        {"id": "stock", "label": "Stocks", "kind": "scroll"},
        {"id": "weather", "label": "Weather", "kind": "frame"},
        {"id": "music", "label": "Music", "kind": "frame"},
        {"id": "flights", "label": "Flights", "kind": "static"},
        {"id": "airports", "label": "Airports", "kind": "static"},
        {"id": "clock", "label": "Clock", "kind": "frame"},
    ]


def _live_sports_content() -> dict[str, list[dict[str, object]]]:
    """Return the first current sports projection with ticker delay settings."""

    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    ticker_settings = tickers[0].display_settings if tickers else DisplaySettings()
    canonical_settings = DisplaySettings(
        active_sports=ticker_settings.active_sports,
        my_teams=ticker_settings.my_teams,
        mode="sports",
        sports_presentation="rotation",
        sports_filter="all",
        pinned_content_id="",
        live_delay_mode=ticker_settings.live_delay_mode,
        live_delay_seconds=ticker_settings.live_delay_seconds,
    )
    with application.snapshot_store._lock:
        snapshots = list(application.snapshot_store._snapshots.values())
    for snapshot in snapshots:
        if not snapshot.content:
            continue
        projected = project_data_v2(
            replace(snapshot, effective_settings=canonical_settings),
            application.provider_health(),
            {"stale": False},
        )
        content = select_display_content(
            projected["content"],
            _selection_settings(canonical_settings, "sports"),
        )
        items = [
            item for records in content.values() for item in records
            if isinstance(item, dict) and item.get("is_shown", True)
        ]
        if items:
            return content
    return {}


def _demo_content(mode: str) -> dict[str, list[dict[str, object]]]:
    """Select reviewed public inputs without exposing personal utility data."""
    selected = {"sports": ("FB02", "BS09", "BK03", "HK07", "SC04"), "stock": ("MD01",),
                "weather": ("MD04",), "flights": ("MD13",), "airports": ("MD18",), "clock": ("MD20",)}
    if mode == "music":
        cycle_start = _SAMPLE_STARTED + int((time() - _SAMPLE_STARTED + 112) // 303) * 303
        return {"music": [{"data": {"type": "music", "sport": "music", "name": "MR. BLUE SKY",
            "artist": "ELECTRIC LIGHT ORCHESTRA", "cover": "demo:album", "is_playing": True,
            "progress": 112, "duration": 303, "fetch_ts": cycle_start}}]}
    return {mode: [{"id": name, "data": layout_case(name)["game"]} for name in selected.get(mode, ())]}


def _display_content(application, ticker_id: str, *, mode: str | None = None) -> dict[str, list[dict[str, object]]]:
    ticker = application.get_ticker(ticker_id)
    snapshot = application.get_snapshot(ticker_id)
    if ticker is None or snapshot is None:
        return {}
    if mode is None:
        data = application.project_data(ticker_id)
        return data["content"]
    display_settings = replace(
        ticker.display_settings,
        mode=str(mode).strip().lower(),
        sports_presentation="rotation",
        sports_filter="all",
        pinned_content_id="",
    )
    projected = project_data_v2(
        replace(snapshot, effective_settings=display_settings),
        application.provider_health(),
        {"stale": False},
    )
    return select_display_content(
        projected["content"],
        _selection_settings(display_settings, str(mode).strip().lower()),
        allowed_modes=ticker.profile.capabilities.modes,
    )


def _selection_settings(settings: DisplaySettings, mode: str) -> dict[str, object]:
    """Return the selection facts required by a dashboard projection."""

    return {
        "mode": mode,
        "sports_filter": "all",
        "sports_presentation": "rotation",
        "pinned_content_id": "",
        "live_delay_mode": settings.live_delay_mode,
        "live_delay_seconds": settings.live_delay_seconds,
    }


class _PreviewAssets:
    """Read prepared team marks after a route-level prefetch completes."""

    def __init__(self, directory: Path) -> None:
        from ticker_core.platform.assets import AssetCoordinator

        self._coordinator = AssetCoordinator(directory)
        self._album = Image.open(Path(__file__).parent / "static/mr-blue-sky-cover.png").convert("RGBA")
        self.renderer = PreviewRenderer(self)

    def image(self, url: str, processor: str, size: tuple[int, int]):
        if url == "demo:album":
            return self._album.resize(size, Image.Resampling.NEAREST)
        return self._coordinator.image(url, processor, size)

    def prefetch(self, content: dict[str, list[dict[str, object]]]) -> None:
        """Prepare current sports logos before the renderer reads them."""

        from ticker_core.assets import AssetPlanner

        requests = [item for item in AssetPlanner().plan(content).requests if not item.url.startswith("demo:")]
        wait(self._coordinator.prefetch(requests), timeout=2)

    @property
    def revision(self) -> int:
        """Expose completed asset changes to the encoded frame cache."""
        return self._coordinator.revision

    def close(self) -> None:
        """Stop the asset workers during backend shutdown."""

        self.renderer.close()
        self._coordinator.close()


def _preview_assets() -> _PreviewAssets:
    """Return one application-owned prepared asset view for public previews."""

    key = "sports_ticker.dashboard_preview_assets"
    with _PREVIEW_LOCK:
        assets = current_app.extensions.get(key)
        if isinstance(assets, _PreviewAssets):
            return assets
        directory = Path(current_app.config.get("DASHBOARD_ASSET_CACHE", "ticker_data/rewrite_assets"))
        assets = _PreviewAssets(directory)
        current_app.extensions[key] = assets
        return assets


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
