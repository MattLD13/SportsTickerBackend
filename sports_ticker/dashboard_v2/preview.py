"""Render public examples with the production Pi drawing and frame services."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
import hashlib
from io import BytesIO
import json
from pathlib import Path
from threading import RLock

from ticker_core.bootstrap import create_default_content_catalog, create_default_frame_builder
from ticker_core.context import RenderContext
from ticker_core.platform.wifi import HotspotDetails, WiFiSetupState
from ticker_core.rendering import ContentScene
from ticker_core.rendering.strip import compose_pane_strip
from ticker_core.runtime import Content, FrameDecision, FrameKind


@lru_cache(maxsize=1)
def layout_library() -> dict:
    """Read reviewed sample inputs and generated Mini frames."""
    return json.loads((Path(__file__).parent / "static/layout-gallery.json").read_text(encoding="utf-8"))


def layout_case(name: str) -> dict | None:
    """Select an existing public example without accepting caller data."""
    return next((row for row in layout_library()["cases"] if row["name"] == name), None)


def main_layout(row: dict) -> dict:
    """Describe which production views exist for one reviewed example."""
    mode, game = row["mode"], row["game"]
    if mode == "message" and game["utility_kind"] not in {"empty", "offline", "checking", "downloading", "installing"}:
        return {"available": False, "pane": False, "full": False, "note": "This Mini status screen has no separate Ticker Six screen. Ticker Six retains its current display."}
    if mode == "clock" and not game.get("ready", True):
        return {"available": False, "pane": False, "full": False, "note": "The big ticker uses its system clock. This Mini time-sync screen has no matching big ticker screen."}
    return {"available": True, "pane": mode in {"sports", "stock"}, "full": mode != "stock"}


def case_items(row: dict, presentation: str) -> list[dict]:
    """Select neighboring examples for the production scrolling view."""
    if presentation == "pinned":
        return [row["game"]]
    group = [item for item in layout_library()["cases"] if item["group"] == row["group"] and item["mode"] == row["mode"] and item["main"]["pane"]]
    index = group.index(row)
    return [group[(index + offset) % len(group)]["game"] for offset in range(min(4, len(group)))]


class PreviewRenderer:
    """Keep bounded rendering state and encoded frames for public examples."""

    def __init__(self, assets) -> None:
        self._assets = assets
        self._lock = RLock()
        self._sessions: OrderedDict[str, tuple] = OrderedDict()
        self._frames: OrderedDict[tuple, bytes] = OrderedDict()
        self._bytes = 0

    def close(self) -> None:
        """Stop the frame services owned by the preview renderer."""
        with self._lock:
            for _, _, viewport in self._sessions.values():
                viewport.close()
            self._sessions.clear()
            self._frames.clear()
            self._bytes = 0

    def render(self, items: list[dict], mode: str, presentation: str, now: datetime, *, row: dict | None = None) -> bytes:
        """Draw through production renderers after asset preparation completes."""
        scene_key = json.dumps([items, mode, presentation, row and row["name"]], sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(scene_key.encode()).hexdigest()
        cache_key = (digest, now.isoformat(), self._assets.revision)
        with self._lock:
            cached = self._frames.get(cache_key)
            if cached is not None:
                self._frames.move_to_end(cache_key)
                return cached
            session = self._sessions.get(digest)
            if session is None:
                catalog = create_default_content_catalog(self._assets)
                builder, viewport = create_default_frame_builder(self._assets)
                session = (catalog, builder, viewport)
                self._sessions[digest] = session
                while len(self._sessions) > 16:
                    _, (_, _, removed) = self._sessions.popitem(last=False)
                    removed.close()
            self._sessions.move_to_end(digest)
            catalog, builder, _ = session
            context = RenderContext(now)
            if presentation == "rotation" and items:
                cards = [catalog.render(context, ContentScene(deepcopy(item), mode)).image for item in items[:60]]
                image = compose_pane_strip((card, card.width + 1) for card in cards)
            else:
                kind = FrameKind.STATIC if items else FrameKind.EMPTY
                game = deepcopy(items[0]) if items else {}
                if mode == "sports":
                    game["sports_presentation"] = "pinned"
                content = Content(str(game.get("id") or "public-demo"), str(game.get("type") or "scoreboard"), str(game.get("sport") or mode), game) if items else None
                extra = {}
                frame_mode = mode
                if row and mode == "pairing":
                    kind = FrameKind.WIFI_SETUP if game["wifi_setup"] else FrameKind.PAIRING
                    extra = {"wifi_state": WiFiSetupState(False, False, HotspotDetails("SportsTicker Setup", ""), setup_code=game["wifi_pin"])} if game["wifi_setup"] else {"pairing_code": game["app_code"]}
                elif row and mode == "message":
                    utility_kind = game["utility_kind"]
                    background = game.get("background")
                    if background:
                        frame_mode = background["mode"]
                        base_game = deepcopy(background["game"])
                        base_game["sports_presentation"] = "pinned"
                        content = Content(str(base_game.get("id") or "demo-base"), str(base_game.get("type") or "scoreboard"), str(base_game.get("sport") or "sports"), base_game)
                        builder.build(FrameDecision(FrameKind.STATIC, 1 / 30, 100, False, now, background["mode"], content=content))
                    if utility_kind == "offline":
                        kind = FrameKind.STATIC if background else FrameKind.OFFLINE
                        extra = {"connection_lost": True} if background else {"offline_for": float(game.get("age_seconds", 60))}
                    elif utility_kind == "empty":
                        kind = FrameKind.EMPTY
                    else:
                        kind = FrameKind.UPDATE
                        total = max(1, int(game.get("total", 1)))
                        extra = {"update_version": "DEMO", "update_progress": min(1.0, float(game.get("complete", 0)) / total)}
                decision = FrameDecision(kind, 1 / 30, 100, False, now, frame_mode, content=content, **extra)
                image = builder.build(decision)
            stream = BytesIO()
            image.convert("RGB").save(stream, format="PNG")
            encoded = stream.getvalue()
            self._frames[cache_key] = encoded
            self._bytes += len(encoded)
            while len(self._frames) > 64 or self._bytes > 8 * 1024 * 1024:
                _, removed = self._frames.popitem(last=False)
                self._bytes -= len(removed)
            return encoded
