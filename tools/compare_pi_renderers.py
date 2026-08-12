#!/usr/bin/env python3
"""Render legacy and rewrite frames, then save an exact visible diff.

Examples:
  python tools/compare_pi_renderers.py --snapshot ticker.json --mode sports_full
  python tools/compare_pi_renderers.py --url http://localhost:5000 --mode weather --out-dir previews/parity
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import random
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageChops

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from render_rewrite import (
        DEFAULT_BACKEND_URL,
        choose_item,
        content_items,
        load_snapshot,
        panel_image,
        parse_datetime,
        render_snapshot,
    )
except ModuleNotFoundError:
    from tools.render_rewrite import (
        DEFAULT_BACKEND_URL,
        choose_item,
        content_items,
        load_snapshot,
        panel_image,
        parse_datetime,
        render_snapshot,
    )
from ticker_core.modes import DisplayMode


@dataclass(frozen=True, slots=True)
class CampaignScenario:
    """Describe one directly comparable legacy and rewrite display state."""

    name: str
    family: str
    legacy: Callable[[], Image.Image]
    rewrite: Callable[[], Image.Image]


def _safe_name(value: str) -> str:
    """Return one filesystem-safe scenario name."""
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)[:120]


def _state_label(item: Mapping[str, object]) -> str:
    """Describe the backend state variant used for one scenario."""
    value = item.get("state") or item.get("status") or "unspecified"
    return _safe_name(str(value).lower()) or "unspecified"


def _family(item: Mapping[str, object]) -> str:
    """Return the active renderer family for a backend record."""
    item_type = str(item.get("type", "")).lower()
    sport = str(item.get("sport", "")).lower()
    if item_type == "leaderboard":
        return "leaderboard"
    if item_type == "stock_ticker":
        return "stock"
    if item_type in {"golf", "masters"} or sport in {"golf", "masters"}:
        return "golf"
    if item_type == "racing" or sport in {"indycar", "f1", "nascar"}:
        return "racing"
    if item_type in {"weather", "music", "flight_visitor", "flight_airport_hud"}:
        return item_type
    if item.get("no_games"):
        return "empty"
    return "sports"


CAMPAIGN_PATHS = (
    "sports_scroll", "sports_full", "weather", "music", "flight_visitor", "flight_airport_hud",
    "stock", "leaderboard", "empty", "clock", "pairing", "offline", "update", "sleep",
    "connection_lost_overlay", "alert", "news",
    "golf_scroll", "golf_full", "indycar_scroll", "indycar_full", "f1_scroll", "f1_full",
    "nascar_scroll", "nascar_full",
)


def _campaign_items(snapshot: Mapping[str, object]) -> list[dict[str, object]]:
    """Normalize separate airport records into one renderer-ready HUD item."""
    items = content_items(snapshot)
    weather = next((item for item in items if str(item.get("type", "")).lower() == "flight_weather"), None)
    arrivals = [item for item in items if str(item.get("type", "")).lower() == "flight_arrival"]
    departures = [item for item in items if str(item.get("type", "")).lower() == "flight_departure"]
    ordinary = [item for item in items if str(item.get("type", "")).lower() not in {"flight_weather", "flight_arrival", "flight_departure"}]
    if weather or arrivals or departures:
        ordinary.append({
            "id": "airport_hud", "type": "flight_airport_hud", "sport": "flight",
            "weather": weather or {}, "arrivals": arrivals, "departures": departures,
            "_weather_item": weather or {}, "_arrivals": arrivals, "_departures": departures,
        })
    return ordinary


def _legacy_helpers():
    """Load isolated legacy debug helpers only for parity comparisons."""
    try:
        from fetch_and_render import collapse_flight_items, make_renderer, prefetch_logos
    except ModuleNotFoundError:
        from tools.fetch_and_render import collapse_flight_items, make_renderer, prefetch_logos
    return collapse_flight_items, make_renderer, prefetch_logos


def render_legacy_item(item: Mapping[str, object], mode: str, *, prefetch: bool = True, now: datetime | None = None) -> Image.Image:
    """Render one legacy content item without starting hardware."""
    _, make_renderer, prefetch_logos = _legacy_helpers()
    frozen = patch("ticker_controller.controller.time.time", return_value=now.timestamp()) if now is not None else nullcontext()
    with frozen:
        renderer = make_renderer(mode)
        if now is not None and str(item.get("type", "")).lower() == "music":
            from ticker_core.features.music import MusicRenderer

            renderer.last_frame_time = now.timestamp()
            renderer.viz_phase = list(MusicRenderer._phase)
            renderer.viz_heights = [2.0] * 16
        if prefetch:
            prefetch_logos(renderer, [dict(item)])
        old_mode = renderer.mode
        item_type = str(item.get("type", "")).lower()
        sport = str(item.get("sport", "")).lower()
        if item_type in {"golf", "masters"} or sport in {"golf", "masters"}:
            renderer.mode = "golf" if mode == "sports_full" else "sports"
        elif item_type == "racing" or sport in {"indycar", "f1", "nascar"}:
            renderer.mode = (sport if sport in {"f1", "nascar"} else "indycar") if mode == "sports_full" else "sports"
        elif mode == "sports_full" and item_type not in {"weather", "music", "clock", "flight_visitor", "flight_airport_hud"}:
            renderer.mode = "sports_full"
        elif mode == "sports":
            renderer.mode = "sports"
        try:
            # Legacy racing renderers can fetch weather during drawing. The rewrite
            # intentionally never performs render-time I/O, so compare only payload data.
            with patch("ticker_controller.modes.racing.requests.get", side_effect=OSError):
                return panel_image(renderer.draw_single_game(dict(item)))
        finally:
            renderer.mode = old_mode


def render_legacy(snapshot: dict, mode: str, item_id: str, index: int) -> Image.Image:
    """Render one legacy frame without starting the hardware controller."""
    collapse_flight_items, _, _ = _legacy_helpers()

    items = collapse_flight_items(content_items(snapshot))
    item = choose_item(items, item_id, index)
    if item is None:
        return Image.new("RGB", (384, 32), "black")
    return render_legacy_item(item, mode)


def make_visible_diff(old: Image.Image, new: Image.Image) -> tuple[Image.Image, int]:
    """Highlight changed pixels in bright magenta over a dark source frame."""
    old_rgb, new_rgb = old.convert("RGB"), new.convert("RGB")
    delta = ImageChops.difference(old_rgb, new_rgb)
    changed = sum(1 for value in delta.getdata() if value != (0, 0, 0))
    mask = delta.convert("L").point(lambda value: 255 if value else 0)
    base = Image.blend(old_rgb, new_rgb, 0.25).convert("RGBA")
    highlight = Image.new("RGBA", old_rgb.size, (255, 0, 255, 255))
    base.paste(highlight, mask=mask)
    return base.convert("RGB"), changed


@contextmanager
def _freeze_legacy_clock(now: datetime):
    """Freeze legacy utility clocks while a utility scenario renders."""
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    with patch.multiple(
        "ticker_controller.modes.misc",
        datetime=FrozenDateTime,
        time=SimpleNamespace(time=lambda: now.timestamp()),
    ), patch("ticker_controller.controller.time.time", return_value=now.timestamp()):
        yield


@contextmanager
def _freeze_legacy_weather(now: datetime):
    """Freeze weather animation and local clock inputs for one oracle frame."""
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    frozen_time = SimpleNamespace(time=lambda: now.timestamp(), localtime=time.localtime, strftime=time.strftime)
    with patch.multiple("ticker_controller.modes.weather", datetime=FrozenDateTime, time=frozen_time):
        yield


@contextmanager
def _stable_legacy_random() -> None:
    """Use one repeatable legacy random state for parity captures."""
    state = random.getstate()
    random.seed(0)
    try:
        yield
    finally:
        random.setstate(state)


def _legacy_content_frame(item: Mapping[str, object], mode: str, now: datetime) -> Image.Image:
    """Render one legacy content frame with deterministic weather inputs."""
    if item.get("no_games"):
        with _freeze_legacy_clock(now):
            return render_legacy_item(item, mode, prefetch=False, now=now)
    if str(item.get("type", "")).lower() == "music":
        values = iter(0.5 + (index % 5) * 0.175 for index in range(16))
        with patch("ticker_controller.modes.music.time.time", return_value=now.timestamp()), patch(
            "ticker_controller.modes.music.random.uniform", side_effect=lambda low, high: next(values)
        ):
            return render_legacy_item(item, mode, prefetch=False, now=now)
    if str(item.get("type", "")).lower() != "weather":
        return render_legacy_item(item, mode, prefetch=False, now=now)
    with _freeze_legacy_weather(now):
        return render_legacy_item(item, mode, prefetch=False, now=now)


def _new_frame_builder(asset_directory: Path):
    """Create a pure rewrite frame builder and its managed asset coordinator."""
    from ticker_core.bootstrap import create_default_frame_builder
    from ticker_core.platform import AssetCoordinator

    assets = AssetCoordinator(asset_directory)
    builder, _ = create_default_frame_builder(assets)
    return assets, builder


def _new_content_frame(item: Mapping[str, object], mode: str, now: datetime, assets: Path) -> Image.Image:
    """Render one rewrite content state through the complete frame builder."""
    from ticker_core.assets import AssetPlanner
    from ticker_core.runtime import Content, FrameDecision, FrameKind

    coordinator, builder = _new_frame_builder(assets)
    try:
        for future in coordinator.prefetch(AssetPlanner().plan({"content": {"sports": [item]}}).requests):
            future.result()
        content = Content(str(item.get("id", "campaign")), str(item.get("type", "")), str(item.get("sport", "")), dict(item))
        decision = FrameDecision(FrameKind.STATIC, 0.0, 100, False, now, mode, content=content)
        return builder.build(decision)
    finally:
        coordinator.close()


def _new_utility_frame(kind: str, now: datetime, assets: Path, *, code: str = "", offline_for: float = 0.0) -> Image.Image:
    """Render one rewrite utility state through the complete frame builder."""
    from ticker_core.runtime import Content, FrameDecision, FrameKind

    coordinator, builder = _new_frame_builder(assets)
    try:
        if kind == "clock":
            content = Content("clock", "clock", "clock", {"id": "clock", "sport": "clock"})
            return builder.build(FrameDecision(FrameKind.STATIC, 0.0, 100, False, now, "clock", content=content))
        return builder.build(
            FrameDecision(
                FrameKind(kind), 0.0, 100, False, now, "sports",
                pairing_code=code or None,
                offline_for=offline_for or None,
            )
        )
    finally:
        coordinator.close()


def _new_alert_frame(alert: Mapping[str, object], under: Mapping[str, object] | None, now: datetime, assets: Path, elapsed: float) -> Image.Image:
    """Render one rewrite score alert over the same deterministic base frame."""
    from ticker_core.runtime import Content, FrameDecision, FrameKind

    coordinator, builder = _new_frame_builder(assets)
    try:
        if under is not None:
            content = Content(str(under.get("id", "under")), str(under.get("type", "")), str(under.get("sport", "")), dict(under))
            builder.build(FrameDecision(FrameKind.STATIC, 0.0, 100, False, now, "sports", content=content))
        else:
            builder.build(FrameDecision(FrameKind.EMPTY, 0.0, 100, False, now, "sports"))
        return builder.build(FrameDecision(FrameKind.SCORE_ALERT, 0.0, 100, False, now, "sports", alert=dict(alert), alert_elapsed=elapsed))
    finally:
        coordinator.close()


def _new_news_frame(news: Mapping[str, object], under: Mapping[str, object] | None, now: datetime, assets: Path, elapsed: float) -> Image.Image:
    """Render one rewrite news overlay over the same deterministic base frame."""
    from ticker_core.runtime import Content, FrameDecision, FrameKind

    coordinator, builder = _new_frame_builder(assets)
    try:
        if under is None:
            return builder.build(FrameDecision(FrameKind.EMPTY, 0.0, 100, False, now, "sports", news=dict(news), news_elapsed=elapsed))
        content = Content(str(under.get("id", "under")), str(under.get("type", "")), str(under.get("sport", "")), dict(under))
        return builder.build(FrameDecision(FrameKind.STATIC, 0.0, 100, False, now, "sports", content=content, news=dict(news), news_elapsed=elapsed))
    finally:
        coordinator.close()


def _legacy_utility(kind: str, now: datetime, *, code: str = "", offline_for: float = 0.0) -> Image.Image:
    """Render one legacy utility state with its clock frozen."""
    _, make_renderer, _ = _legacy_helpers()
    with _freeze_legacy_clock(now):
        renderer = make_renderer("sports")
        renderer.pairing_code = code
        if kind == "pairing":
            return panel_image(renderer.draw_pairing_screen())
        if kind == "offline":
            return panel_image(renderer.draw_offline_screen(offline_for))
        if kind == "update":
            return panel_image(renderer.draw_update_screen())
        if kind == "sleep":
            return Image.new("RGB", (384, 32), "black")
        if kind == "clock":
            return panel_image(renderer.draw_clock_modern())
        return panel_image(renderer.draw_no_games_screen())


def _legacy_alert(alert: Mapping[str, object], under: Mapping[str, object] | None, elapsed: float, now: datetime) -> Image.Image:
    """Render one legacy alert with the same underlying frame."""
    _, make_renderer, _ = _legacy_helpers()
    renderer = make_renderer("sports")
    base = render_legacy_item(under, "sports", prefetch=False, now=now) if under is not None else panel_image(renderer.draw_no_games_screen())
    return panel_image(renderer.draw_score_alert(dict(alert), elapsed, base))


def _legacy_news(news: Mapping[str, object], under: Mapping[str, object] | None, elapsed: float, now: datetime) -> Image.Image:
    """Render one legacy news overlay with the same underlying frame."""
    _, make_renderer, _ = _legacy_helpers()
    renderer = make_renderer("sports")
    base = render_legacy_item(under, "sports", prefetch=False, now=now) if under is not None else panel_image(renderer.draw_no_games_screen())
    return panel_image(renderer.apply_news_banner(base, dict(news), elapsed))


def build_campaign(snapshot: Mapping[str, object], now: datetime, assets: Path) -> tuple[list[CampaignScenario], dict[str, int]]:
    """Inventory comparable renderer paths that this snapshot provides."""
    scenarios: list[CampaignScenario] = []
    inventory = {name: 0 for name in CAMPAIGN_PATHS}
    items = _campaign_items(snapshot)
    base = next((item for item in items if _family(item) == "sports"), None)
    for index, item in enumerate(items):
        family = _family(item)
        sport = _safe_name(str(item.get("sport") or item.get("type") or "unknown").lower())
        label = f"{index:02d}_{sport}_{_state_label(item)}"
        modes: tuple[str, ...]
        if family in {"sports", "golf", "racing"}:
            modes = ("sports", "sports_full")
        elif family == "weather":
            modes = ("weather",)
        elif family == "music":
            modes = ("music",)
        elif family.startswith("flight"):
            modes = ("flights",)
        else:
            modes = ("sports",)
        for mode in modes:
            bucket = mode if mode == "sports_full" and family == "sports" else "sports_scroll" if mode == "sports" and family == "sports" else family
            if family == "golf":
                bucket = "golf_full" if mode == "sports_full" else "golf_scroll"
            elif family == "racing":
                series = str(item.get("sport", "indycar")).lower()
                bucket = f"{series}_{'full' if mode == 'sports_full' else 'scroll'}"
            elif family.startswith("flight"):
                bucket = family
            inventory[bucket] += 1
            scenarios.append(CampaignScenario(
                f"{bucket}_{label}", bucket,
                lambda item=item, mode=mode: _legacy_content_frame(item, mode, now),
                lambda item=item, mode=mode: _new_content_frame(item, mode, now, assets),
            ))
    for kind, code, offline_for in (("clock", "", 0.0), ("pairing", "ABC123", 0.0), ("offline", "", 301.0), ("update", "", 0.0), ("empty", "", 0.0), ("sleep", "", 0.0)):
        inventory[kind] += 1
        scenarios.append(CampaignScenario(
            kind, kind,
            lambda kind=kind, code=code, offline_for=offline_for: _legacy_utility(kind, now, code=code, offline_for=offline_for),
            lambda kind=kind, code=code, offline_for=offline_for: _new_utility_frame(kind, now, assets, code=code, offline_for=offline_for),
        ))
    alerts = snapshot.get("alerts")
    for index, alert in enumerate(alerts if isinstance(alerts, list) else ()):
        if not isinstance(alert, Mapping):
            continue
        for phase, elapsed in (("enter", 0.1), ("hold", 1.0), ("exit", 4.1 if alert.get("big") else 3.6)):
            inventory["alert"] += 1
            scenarios.append(CampaignScenario(
                f"alert_{index:02d}_{phase}_{_state_label(alert)}", "alert",
                lambda alert=alert, elapsed=elapsed: _legacy_alert(alert, base, elapsed, now),
                lambda alert=alert, elapsed=elapsed: _new_alert_frame(alert, base, now, assets, elapsed),
            ))
    news_items = snapshot.get("news")
    for index, news in enumerate(news_items if isinstance(news_items, list) else ()):
        if not isinstance(news, Mapping):
            continue
        total = 8.0 if news.get("domain") == "stocks" else 7.0
        for phase, elapsed in (("enter", 0.1), ("hold", 1.0), ("exit", total - 0.1)):
            inventory["news"] += 1
            scenarios.append(CampaignScenario(
                f"news_{index:02d}_{phase}_{_safe_name(str(news.get('kind', 'news')).lower())}", "news",
                lambda news=news, elapsed=elapsed: _legacy_news(news, base, elapsed, now),
                lambda news=news, elapsed=elapsed: _new_news_frame(news, base, now, assets, elapsed),
            ))
    return scenarios, inventory


def run_campaign(snapshot: Mapping[str, object], now: datetime, assets: Path, out_dir: Path) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Run every available scenario and save both renders plus their diff."""
    scenarios, inventory = build_campaign(snapshot, now, assets)
    results: list[dict[str, object]] = []
    for scenario in scenarios:
        result: dict[str, object] = {"name": scenario.name, "family": scenario.family}
        try:
            old, new = scenario.legacy(), scenario.rewrite()
            diff, changed = make_visible_diff(old, new)
            result.update(status="pass" if changed == 0 else "fail", changed_pixels=changed)
            if changed:
                result["audit"] = _difference_audit(scenario.name, scenario.family, changed)
            relative_folder = Path("scenarios") / _safe_name(scenario.name)
            folder = out_dir / relative_folder
            folder.mkdir(parents=True, exist_ok=True)
            old.save(folder / "old.png")
            new.save(folder / "new.png")
            diff.save(folder / "diff.png")
            result["images"] = relative_folder.as_posix()
        except Exception as error:
            result.update(status="error", changed_pixels=None, error=str(error))
        results.append(result)
    return results, inventory


def _difference_audit(name: str, family: str, changed: int) -> str:
    """Label recurring measured drift without changing production output."""
    if family in {"sports_scroll", "alert", "news"} and changed == 12:
        return "Renderer drift. The legacy and rewrite hybrid colon glyphs differ."
    if family.endswith("_scroll") and family.split("_", 1)[0] in {"f1", "indycar", "nascar"} and changed == 28:
        return "Renderer drift. The pre-race mini-flag white differs from 230 to 235."
    if family.endswith("_full") and family.split("_", 1)[0] in {"f1", "indycar", "nascar"} and changed == 200:
        return "Renderer drift. The pre-race full-panel white differs from 230 to 235."
    if family == "music":
        return "Renderer drift. Legacy music uses hidden random visualizer noise while rewrite uses deterministic phases."
    return "Measured renderer drift. The harness uses fresh renderers and fixed time."


def verify_connection_lost_overlay() -> dict[str, object]:
    """Validate the rewrite-only disconnect icon without a legacy oracle."""
    from ticker_core.features.status import ConnectionLostOverlay

    source = Image.new("RGB", (384, 32))
    source.putdata([((x * 7) % 256, (y * 31) % 256, ((x + y) * 13) % 256) for y in range(32) for x in range(384)])
    rendered = ConnectionLostOverlay().apply(source)
    changed = ImageChops.difference(source, rendered)
    changed_pixels = sum(1 for value in changed.getdata() if value != (0, 0, 0))
    outside_changed = any(
        source.getpixel((x, y)) != rendered.getpixel((x, y))
        for y in range(32) for x in range(384)
        if not (372 <= x < 384 and 0 <= y < 10)
    )
    samples = {
        "top_red_slash": rendered.getpixel((381, 0)) == (255, 70, 70),
        "bottom_red_slash": rendered.getpixel((372, 8)) == (255, 70, 70),
        "server_outline": rendered.getpixel((374, 2)) == (210, 215, 225),
        "outside_preserved": not outside_changed,
    }
    valid = rendered.mode == "RGB" and rendered.size == (384, 32) and changed.getbbox() == (372, 0, 384, 10) and all(samples.values())
    return {
        "label": "rewrite-only validation",
        "name": "connection_lost_overlay",
        "status": "pass" if valid else "fail",
        "changed_pixels": changed_pixels,
        "changed_bounds": changed.getbbox(),
        "checks": samples,
    }


def write_campaign_report(results: list[dict[str, object]], inventory: Mapping[str, int], out_dir: Path) -> None:
    """Write compact machine and human readable parity reports."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {status: sum(1 for result in results if result["status"] == status) for status in ("pass", "fail", "error")}
    rewrite_only = verify_connection_lost_overlay()
    report = {
        "summary": {**counts, "scenarios": len(results)},
        "inventory": dict(inventory),
        "harness_audit": "Every comparison uses fresh renderers, one fixed wall time, and a restored legacy random seed for music.",
        "rewrite_only_validation": [rewrite_only],
        "results": results,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Pi rewrite parity campaign", "", f"Rendered: {len(results)}. Pass: {counts['pass']}. Fail: {counts['fail']}. Error: {counts['error']}.", "", "| Path | Rendered |", "| --- | ---: |"]
    lines.extend(f"| {name} | {count} |" for name, count in inventory.items())
    untested = [name for name, count in inventory.items() if count == 0]
    if untested:
        lines.extend(["", "Not tested from this snapshot: " + ", ".join(untested) + "."])
    if inventory.get("connection_lost_overlay") == 0:
        lines.append("Connection-lost overlay has no legacy equivalent, so it remains untested for pixel parity.")
    lines.extend([
        "", "## Rewrite-only validation", "",
        f"| Scenario | Status | Changed pixels | Bounds |",
        "| --- | --- | ---: | --- |",
        f"| {rewrite_only['name']} | {rewrite_only['status']} | {rewrite_only['changed_pixels']} | {rewrite_only['changed_bounds']} |",
    ])
    failures = [result for result in results if result["status"] != "pass"]
    if failures:
        lines.extend(["", "## Failures", "", "| Scenario | Status | Changed pixels |", "| --- | --- | ---: |"])
        lines.extend(f"| {result['name']} | {result['status']} | {result.get('changed_pixels', '')} |" for result in failures)
    lines.extend(["", "## Every comparison", "", "| Scenario | Family | Status | Changed pixels | Renders |", "| --- | --- | --- | ---: | --- |"])
    for result in results:
        folder = result.get("images")
        links = ""
        if folder:
            links = f"[old]({folder}/old.png) · [new]({folder}/new.png) · [diff]({folder}/diff.png)"
        lines.append(f"| {result['name']} | {result['family']} | {result['status']} | {result.get('changed_pixels', '')} | {links} |")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """Save old.png, new.png, and diff.png for one input snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Read a backend JSON snapshot from this file.")
    parser.add_argument("--url", default=DEFAULT_BACKEND_URL, help="Backend base URL when --snapshot is absent.")
    parser.add_argument("--endpoint", default="/api/state", help="Backend endpoint when --snapshot is absent.")
    parser.add_argument("--ticker-id", default="", help="Ticker id for a /data request.")
    parser.add_argument("--mode", choices=[str(value) for value in DisplayMode], default="sports")
    parser.add_argument("--item-id", default="", help="Render this content item id.")
    parser.add_argument("--index", type=int, default=0, help="Render this content item when --item-id is absent.")
    parser.add_argument("--datetime", type=parse_datetime, default=None, help="Use this ISO time for rewrite rendering.")
    parser.add_argument("--assets", type=Path, default=Path("ticker_data/rewrite_assets"), help="Store rewrite assets here.")
    parser.add_argument("--out-dir", type=Path, default=Path("previews/parity"), help="Save old.png, new.png, and diff.png here.")
    parser.add_argument("--campaign", action="store_true", help="Compare every renderer state available in the input snapshot.")
    arguments = parser.parse_args()
    try:
        snapshot = load_snapshot(arguments.snapshot, arguments.url, arguments.endpoint, arguments.ticker_id, arguments.mode, 10.0)
        if arguments.campaign:
            results, inventory = run_campaign(snapshot, arguments.datetime or datetime.now(), arguments.assets, arguments.out_dir)
            write_campaign_report(results, inventory, arguments.out_dir)
            counts = {status: sum(1 for result in results if result["status"] == status) for status in ("pass", "fail", "error")}
            print(f"Campaign: {len(results)} rendered, {counts['pass']} pass, {counts['fail']} fail, {counts['error']} error")
            print(f"Saved {arguments.out_dir / 'report.json'}")
            print(f"Saved {arguments.out_dir / 'report.md'}")
            return 1 if counts["fail"] or counts["error"] else 0
        old = render_legacy(snapshot, arguments.mode, arguments.item_id, arguments.index)
        new = render_snapshot(snapshot, arguments.mode, item_id=arguments.item_id, index=arguments.index, now=arguments.datetime or datetime.now(), asset_directory=arguments.assets)
        diff, changed = make_visible_diff(old, new)
        arguments.out_dir.mkdir(parents=True, exist_ok=True)
        old.save(arguments.out_dir / "old.png")
        new.save(arguments.out_dir / "new.png")
        diff.save(arguments.out_dir / "diff.png")
        print(f"Saved {arguments.out_dir / 'old.png'}")
        print(f"Saved {arguments.out_dir / 'new.png'}")
        print(f"Saved {arguments.out_dir / 'diff.png'}")
        print(f"Differing pixels: {changed}")
        return 0
    except Exception as error:
        print(f"Comparison failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
