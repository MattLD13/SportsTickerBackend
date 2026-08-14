#!/usr/bin/env python3
"""Render one 384x32 rewrite frame from backend JSON without starting hardware.

Examples:
  python tools/render_rewrite.py --snapshot ticker.json --mode sports --pinned
  python tools/render_rewrite.py --url http://localhost:5000 --ticker-id TICKER_ID --mode weather
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urljoin

import requests
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ticker_core import RenderContext
from ticker_core.assets import AssetPlanner
from ticker_core.modes import DisplayMode, display_mode
from ticker_core.platform import AssetCoordinator
from ticker_core.rendering import ContentScene


PANEL_SIZE = (384, 32)
DEFAULT_BACKEND_URL = "http://127.0.0.1:5000"
MODE_FAMILIES = {
    "sports": frozenset(("sports", "golf", "racing")),
    "stock": frozenset(("stock",)),
    "weather": frozenset(("weather",)),
    "music": frozenset(("music",)),
    "flights": frozenset(("flights",)),
    "airports": frozenset(("airports",)),
}


def parse_datetime(value: str) -> datetime:
    """Parse one ISO datetime value."""
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use an ISO datetime value.") from error


def load_snapshot(
    snapshot_path: Path | None,
    url: str,
    endpoint: str,
    mode: str,
    timeout: float,
) -> dict[str, Any]:
    """Load one raw backend response from disk or HTTP."""
    if snapshot_path is not None:
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Cannot read snapshot {snapshot_path}: {error}") from error
    else:
        target = urljoin(url.rstrip('/') + '/', endpoint.lstrip('/'))
        response = requests.get(target, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    return normalize_snapshot(data, mode)


def normalize_snapshot(value: object, requested_mode: str) -> dict[str, Any]:
    """Normalize a V2 display response into a renderer snapshot."""
    if not isinstance(value, Mapping):
        raise ValueError("The backend response must be an object.")
    data = dict(value)
    if data.get("api_version") != "v2":
        raise ValueError("The backend response must use api_version v2.")
    records: list[dict[str, Any]] = []
    for values in _items_mapping(data.get("content")):
        for envelope in _items(values):
            rendered = dict(envelope.get("data") or {})
            rendered["id"] = envelope.get("id", rendered.get("id", ""))
            rendered["family"] = envelope.get("family", rendered.get("family", ""))
            rendered["kind"] = envelope.get("kind", rendered.get("kind", ""))
            rendered["is_shown"] = envelope.get("is_shown", True)
            records.append(rendered)
    return {"mode": requested_mode, "content": {"items": records}}


def _items(value: object) -> list[dict[str, Any]]:
    """Keep only JSON object content records."""
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _items_mapping(value: object) -> tuple[object, ...]:
    """Return v2 family record lists without accepting arbitrary scalar values."""

    return tuple(value.values()) if isinstance(value, Mapping) else ()


def content_items(snapshot: Mapping[str, Any], mode: str) -> list[dict[str, Any]]:
    """Return records owned by one selected display mode."""
    content = snapshot.get("content")
    if not isinstance(content, Mapping):
        return []
    families = MODE_FAMILIES.get(mode, frozenset())
    return [
        item for item in _items(content.get("items"))
        if str(item.get("family") or "").strip().lower() in families
    ]


def choose_item(items: list[dict[str, Any]], item_id: str, index: int) -> dict[str, Any] | None:
    """Choose a selected item from normalized content."""
    if item_id:
        target = item_id.strip().lower()
        selected = next((item for item in items if str(item.get("id", "")).lower() == target), None)
        if selected is None:
            raise ValueError(f"No content item has id {item_id!r}.")
        return selected
    return items[max(0, min(index, len(items) - 1))] if items else None


def panel_image(image: Image.Image) -> Image.Image:
    """Return a complete panel frame from a content image."""
    frame = Image.new("RGB", PANEL_SIZE, "black")
    frame.paste(image.convert("RGB").crop((0, 0, *PANEL_SIZE)), (0, 0))
    return frame


def render_snapshot(
    snapshot: Mapping[str, Any],
    mode: DisplayMode | str,
    *,
    item_id: str = "",
    index: int = 0,
    now: datetime | None = None,
    asset_directory: Path | str = Path("ticker_data/rewrite_assets"),
    prefetch: bool = True,
    pinned: bool = False,
) -> Image.Image:
    """Render one rewrite frame using its catalog and asset coordinator."""
    from ticker_core.bootstrap import create_default_content_catalog

    selected_mode = display_mode(mode)
    coordinator = AssetCoordinator(asset_directory)
    try:
        if prefetch:
            futures = coordinator.prefetch(AssetPlanner().plan(snapshot).requests)
            for future in futures:
                future.result()
        context = RenderContext(now or datetime.now())
        if selected_mode is DisplayMode.CLOCK:
            from ticker_core.features.clock import ClockScene
            from ticker_core.bootstrap import create_default_scene_registry

            return panel_image(create_default_scene_registry().render(context, ClockScene()))
        item = choose_item(content_items(snapshot, str(selected_mode)), item_id, index)
        if item is None:
            from ticker_core.rendering.fonts import load_default_font_set
            from ticker_core.features.utility import UtilityRenderer

            return panel_image(UtilityRenderer(load_default_font_set()).empty(context))
        item = dict(item)
        if pinned and selected_mode is DisplayMode.SPORTS:
            item["sports_presentation"] = "pinned"
        catalog = create_default_content_catalog(coordinator)
        rendered = catalog.render(context, ContentScene(item, str(selected_mode)))
        return panel_image(rendered.image)
    finally:
        coordinator.close()


def main() -> int:
    """Load a snapshot and save one rewrite PNG."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Read a backend JSON snapshot from this file.")
    parser.add_argument("--url", default=DEFAULT_BACKEND_URL, help="Backend base URL when --snapshot is absent.")
    parser.add_argument("--endpoint", default="", help="Override the V2 data endpoint.")
    parser.add_argument("--ticker-id", default="", help="Ticker id for the V2 data request.")
    parser.add_argument("--mode", choices=[str(value) for value in DisplayMode], default="sports")
    parser.add_argument("--item-id", default="", help="Render this content item id.")
    parser.add_argument("--index", type=int, default=0, help="Render this content item when --item-id is absent.")
    parser.add_argument("--datetime", type=parse_datetime, default=None, help="Use this ISO time for deterministic output.")
    parser.add_argument("--assets", type=Path, default=Path("ticker_data/rewrite_assets"), help="Store long-term assets here.")
    parser.add_argument("--no-prefetch", action="store_true", help="Do not fetch missing assets before rendering.")
    parser.add_argument("--pinned", action="store_true", help="Render the selected sports item in its full pinned layout.")
    parser.add_argument("--output", type=Path, default=Path("previews/rewrite.png"), help="Save the 384x32 PNG here.")
    arguments = parser.parse_args()
    try:
        endpoint = arguments.endpoint or f"/api/v2/tickers/{arguments.ticker_id}/data"
        if arguments.snapshot is None and not arguments.ticker_id and not arguments.endpoint:
            raise ValueError("Provide --ticker-id when loading from a backend.")
        snapshot = load_snapshot(arguments.snapshot, arguments.url, endpoint, arguments.mode, 10.0)
        image = render_snapshot(snapshot, arguments.mode, item_id=arguments.item_id, index=arguments.index, now=arguments.datetime, asset_directory=arguments.assets, prefetch=not arguments.no_prefetch, pinned=arguments.pinned)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        image.save(arguments.output)
        print(f"Saved {arguments.output} ({image.width}x{image.height})")
        return 0
    except Exception as error:
        print(f"Render failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
