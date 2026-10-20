"""Render the established public dashboard from version two data."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
import os
import hashlib
import re
from math import isfinite
from pathlib import Path
from time import monotonic, time
from concurrent.futures import wait
from zoneinfo import ZoneInfo
from threading import Lock

from flask import abort, current_app, render_template, request, send_file
from PIL import Image

from sports_ticker.domain import DISPLAY_MODES, DisplaySettings
from sports_ticker.fleet.profiles import TickerProfile
from sports_ticker.leagues import LEAGUES
from sports_ticker.markets import MARKET_GROUPS, selected_market_groups
from sports_ticker.projections import project_data_v2, select_display_content
from sports_ticker.providers.http import JsonHttpError

from . import dashboard_v2
from .preview import PreviewRenderer, case_items, layout_case, layout_library


@dashboard_v2.get("/")
def public_index():
    """Render the original landing page with current V2 fleet facts."""

    application = current_app.extensions["sports_ticker.backend_application"]
    tickers = application.list_tickers()
    ticker = tickers[0] if tickers else None
    settings = ticker.display_settings if ticker is not None else None
    snapshot = application.get_snapshot(ticker.ticker_id) if ticker is not None else None
    content = snapshot.content if snapshot is not None else ()
    active_sports = settings.active_sports if settings is not None else {}
    sports = _sports_rows(active_sports, content, _coverage_catalog(application))
    utilities = _utility_rows(content)
    effective = {item.ticker_id: application.schedule_service.effective_settings(
        item.ticker_id, item.display_settings, allowed_modes=item.profile.capabilities.modes,
    ) for item in tickers}
    fleet = _fleet_rows(tickers, effective)
    active_modes = {item["mode"] for item in fleet if item["link"] == "online" and item["mode"] in DISPLAY_MODES}
    mode_label = " / ".join(item["name"] for item in _display_modes() if item["id"] in active_modes) or "Offline"
    markets = _market_rows(tickers, fleet)
    visible = _display_content(application, ticker.ticker_id) if ticker is not None else {}
    shown = sum(len(items) for items in visible.values())
    return render_template(
        "dashboard/index.html",
        version_hash=_version_hash(),
        server_version=_version_hash(),
        uptime_str=_uptime(),
        fleet=fleet,
        fleet_online=sum(1 for item in fleet if item["link"] == "online"),
        fleet_offline=sum(1 for item in fleet if item["offline_reason"]),
        server_health=_server_health(),
        fleet_mode_label=mode_label,
        active_modes=active_modes,
        active_mode_count=len(active_modes),
        hardware_specs=_hardware_specs(tickers),
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
    data_state = "example"
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
        content, data_state = _public_mode_content(mode)
        items = _preview_items(content)
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
    response.headers["X-Ticker-Data"] = data_state
    response.headers["X-Ticker-Items"] = len(items)
    return response.make_conditional(request)


@dashboard_v2.get("/api/v2/demo/animation.png")
def demo_animation():
    """Prepare consecutive production frames for smooth browser playback."""
    mode = request.args.get("mode", "")
    if mode not in {"music", "weather"}:
        abort(400)
    current_segment = int(time() // 3)
    try:
        segment = int(request.args.get("segment", current_segment))
    except ValueError:
        abort(400)
    if not current_segment - 2 <= segment <= current_segment + 1:
        abort(400)
    content, data_state = _public_mode_content(mode, at=segment * 3)
    items = _preview_items(content)
    assets = _preview_assets()
    assets.prefetch(content)
    now = datetime.fromtimestamp(segment * 3, ZoneInfo("America/New_York"))
    encoded = assets.renderer.animation(items, mode, now)
    response = send_file(BytesIO(encoded), mimetype="image/png", max_age=0)
    response.set_etag(hashlib.sha256(encoded).hexdigest())
    response.headers["X-Ticker-Frames"] = 90
    response.headers["X-Ticker-FPS"] = 30
    response.headers["X-Ticker-Segment"] = segment
    response.headers["X-Ticker-Renderer"] = _version_hash()
    response.headers["X-Ticker-Data"] = data_state
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


def _fleet_rows(tickers, effective=None) -> list[dict[str, object]]:
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
            "mode": "pairing" if ticker.pairing is None or not ticker.pairing.paired else
                (effective or {}).get(ticker.ticker_id, ticker.display_settings).mode,
            "last_poll": "never" if age is None else f"{age}s ago",
            "uptime": _duration(metadata.get("uptime_seconds")),
            "temp": f"{temperature:.0f}C" if type(temperature) in (int, float) and isfinite(temperature) else "-",
            "build": _build_label(metadata.get("build")),
            "build_id": str(metadata.get("build") or "Not reported"),
            "offline_reason": "" if age is not None and age < 90 else "No recent heartbeat",
        })
    return rows


def _build_label(value):
    """Format existing device versions without exposing revision hashes as labels."""
    build = str(value or "").strip()
    six = re.fullmatch(r"r(\d+)(?:\+[A-Za-z0-9.-]+)?", build)
    mini = re.fullmatch(r"mini-(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)", build)
    if six:
        return f"Build {six[1]}"
    if mini:
        return f"v{mini[1]}"
    return build or "Not reported"


def _market_rows(tickers, fleet):
    """Mark stock groups green only while connected tickers use them."""
    live = set()
    for ticker, row in zip(tickers, fleet):
        if row["link"] != "online" or row["mode"] != "stock":
            continue
        live.update(group.id for group in selected_market_groups(ticker.display_settings.active_sports))
    return [{"id": group.id, "label": group.label,
             "state": "live" if group.id in live else "on"}
            for group in MARKET_GROUPS]


def _hardware_specs(tickers):
    """Keep product geometry separate and show each device's own telemetry."""
    cards = []
    for family, name in (("full", "Ticker Six"), ("mini", "Ticker Mini")):
        candidates = [ticker for ticker in tickers if ticker.profile.product_family == family]
        ticker = max(candidates, key=lambda item: item.device.last_seen_at or 0) if candidates else None
        profile = ticker.profile if ticker else TickerProfile.from_mapping({"product_family": family})
        display = profile.display
        metadata = ticker.device.metadata if ticker else {}
        speed = ticker.display_settings.scroll_speed if ticker else 0.03
        if family == "mini":
            seconds = min(10, max(1, speed * 100))
            timing = f"{seconds:g} SEC/PAGE"
        else:
            timing = f"{round(1 / speed) if speed > 0 else 33} PX/SEC"
        cards.append({
            "name": name, "resolution": f"{display.width}X{display.height}",
            "controller": "ESP32-S3 controller" if family == "mini" else "Raspberry Pi controller",
            "panels": f"{display.panel_count} X 64X32", "timing_label": "Page duration" if family == "mini" else "Scroll rate",
            "timing": timing, "modes": len(profile.capabilities.modes) if ticker else len(DISPLAY_MODES),
            "build": _build_label(metadata.get("build")),
            "build_id": str(metadata.get("build") or "Not reported"), "uptime": _duration(metadata.get("uptime_seconds")),
        })
    return cards


def _coverage_catalog(application):
    """Use the shared catalog for league and conference names."""
    if application.catalog is not None:
        try:
            return application.catalog.leagues()
        except JsonHttpError:
            current_app.logger.warning("Conference coverage catalog is unavailable")
    return tuple({"id": league.id, "label": league.label, "type": "sport"} for league in LEAGUES)


def _sports_rows(active_sports, content, catalog) -> list[dict[str, str]]:
    """Keep sports coverage within the shared league and conference catalog."""
    records = {str(item.data.get("sport", "")).lower() for item in content if item.family == "sports"}
    entries = (
        entry for entry in catalog
        if entry["type"] == "sport" and active_sports.get(entry["id"], True)
        and active_sports.get(entry.get("conference_parent", entry["id"]), True)
    )
    return [
        {"id": entry["id"], "label": entry["label"], "state": "live" if entry["id"] in records else "on"}
        for entry in entries
    ]


def _utility_rows(content) -> list[dict[str, str]]:
    families = ("weather", "music", "flights", "airports", "golf", "racing", "clock")
    shown = {item.family for item in content}
    return [{"id": name, "label": name.replace("_", " ").upper(), "state": "live" if name in shown else "on"} for name in families]


def _display_modes() -> list[dict[str, str]]:
    return [
        {"id": "sports", "name": "Sports", "desc": "Scores, golf, and racing", "group": "Sports"},
        {"id": "stock", "name": "Stocks", "desc": "Stock prices and market changes", "group": "Data"},
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


def _demo_content(mode: str, *, at: float | None = None) -> dict[str, list[dict[str, object]]]:
    """Select reviewed public inputs without exposing personal utility data."""
    selected = {"sports": ("FB02", "BS09", "BK03", "HK07", "SC04"), "clock": ("MD20",)}
    if mode == "music":
        sample_time = time() if at is None else at
        cycle_start = _SAMPLE_STARTED + int((sample_time - _SAMPLE_STARTED + 112) // 303) * 303
        return {"music": [{"data": {"type": "music", "sport": "music", "name": "MR. BLUE SKY",
            "artist": "ELECTRIC LIGHT ORCHESTRA", "cover": "demo:album", "is_playing": True,
            "progress": 112, "duration": 303, "fetch_ts": cycle_start}}]}
    return {mode: [{"id": name, "data": layout_case(name)["game"]} for name in selected.get(mode, ())]}


def _public_mode_content(mode, *, at=None):
    """Select live public feeds without copying personal device utility state."""
    if mode in {"stock", "weather", "flights", "airports"}:
        source = current_app.extensions.get("sports_ticker.public_demo_data")
        return source.content(mode) if source is not None else ({mode: []}, "unavailable")
    if mode == "sports":
        content = _live_sports_content()
        if content:
            return content, "live"
    return _demo_content(mode, at=at), "example"


def _preview_items(content):
    """Carry explicit V2 identity and renderer kind into preview scenes."""
    items = []
    for records in content.values():
        for record in records:
            if not record.get("is_shown", True):
                continue
            game = dict(record["data"])
            for field, value in (("id", record.get("id")), ("type", record.get("kind")), ("sport", record.get("family"))):
                if value:
                    game.setdefault(field, value)
            items.append(game)
    return items


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

        requests = [item for item in AssetPlanner().plan(content).requests if not item.url.startswith("demo:")
                    and (set(content) != {"stock"} or item.size == (24, 24))]
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
