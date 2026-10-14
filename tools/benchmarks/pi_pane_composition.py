"""Compare current pane composition with flattened and bounded surfaces."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticker_core.app.viewport import CardViewport
from ticker_core.bootstrap import create_default_frame_builder
from ticker_core.context import RenderContext
from ticker_core.platform.assets import AssetCoordinator
from ticker_core.runtime import Content
from tools.render_rewrite import content_items, normalize_snapshot


PANEL_WIDTH = 384
PANEL_HEIGHT = 32
DIVIDER = (45, 45, 45)
SNAPSHOT = ROOT / "tests" / "rewrite" / "debug" / "v2_render_snapshot.json"


class FlattenedPanes:
    """Precompose every pane into one cyclic image, then crop each frame."""

    def __init__(self, viewport: CardViewport) -> None:
        self.strip: Image.Image | None = None
        self.tiled: Image.Image | None = None
        self.layout = None
        self.rebuild(viewport)

    def rebuild(self, viewport: CardViewport) -> float:
        started = time.perf_counter()
        layout = viewport.layout
        if layout is None:
            raise RuntimeError("Pane surfaces are not ready.")
        surfaces = dict(viewport._surfaces)
        strip = Image.new("RGB", (layout.width, PANEL_HEIGHT), "black")
        draw = ImageDraw.Draw(strip)
        x = 0
        for segment in layout.segments:
            draw.line((x, 0, x, PANEL_HEIGHT - 1), fill=DIVIDER)
            surface = surfaces.get(segment.item_id)
            if surface is not None:
                strip.paste(surface.image, (x + 1, 0), surface.image)
            x += segment.width
        tile_count = math.ceil(PANEL_WIDTH / layout.width) + 1
        tiled = Image.new("RGB", (layout.width * tile_count, PANEL_HEIGHT), "black")
        for index in range(tile_count):
            tiled.paste(strip, (index * layout.width, 0))
        self.strip = strip
        self.tiled = tiled
        self.layout = layout
        return time.perf_counter() - started

    def frame(self, offset: int) -> Image.Image:
        assert self.layout is not None and self.tiled is not None
        left = offset % self.layout.width
        return self.tiled.crop((left, 0, left + PANEL_WIDTH, PANEL_HEIGHT))


class BoundedPaneRibbon:
    """Keep one panel-sized rolling window and append one exposed column."""

    def __init__(self, viewport: CardViewport) -> None:
        self.canvas: Image.Image | None = None
        self.last_offset: int | None = None
        self.layout = None
        self.surfaces = {}
        self.reset(viewport)

    def reset(self, viewport: CardViewport, offset: int = 0) -> None:
        self.layout = viewport.layout
        if self.layout is None:
            raise RuntimeError("Pane surfaces are not ready.")
        self.surfaces = dict(viewport._surfaces)
        self.canvas = viewport.frame(offset, PANEL_WIDTH, PANEL_HEIGHT)
        self.last_offset = offset % self.layout.width

    def frame(self, offset: int, viewport: CardViewport) -> Image.Image:
        assert self.layout is not None and self.canvas is not None and self.last_offset is not None
        current = offset % self.layout.width
        if current != (self.last_offset + 1) % self.layout.width:
            self.canvas = viewport.frame(current, PANEL_WIDTH, PANEL_HEIGHT)
        else:
            shifted = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), "black")
            shifted.paste(self.canvas.crop((1, 0, PANEL_WIDTH, PANEL_HEIGHT)), (0, 0))
            column = self._column(self.last_offset + PANEL_WIDTH)
            shifted.paste(column, (PANEL_WIDTH - 1, 0))
            self.canvas = shifted
        self.last_offset = current
        return self.canvas

    def _column(self, absolute_x: int) -> Image.Image:
        assert self.layout is not None
        position = absolute_x % self.layout.width
        start = 0
        for segment in self.layout.segments:
            if start + segment.width > position:
                local_x = position - start
                column = Image.new("RGB", (1, PANEL_HEIGHT), "black")
                if local_x == 0:
                    ImageDraw.Draw(column).line((0, 0, 0, PANEL_HEIGHT - 1), fill=DIVIDER)
                else:
                    surface = self.surfaces.get(segment.item_id)
                    if surface is not None:
                        pane_column = surface.image.crop((local_x - 1, 0, local_x, PANEL_HEIGHT))
                        column.paste(pane_column, (0, 0), pane_column)
                return column
            start += segment.width
        raise AssertionError("Pane position does not map to a segment.")


def _independent_pane_frame(viewport: CardViewport, offset: int) -> Image.Image:
    """Recreate the previous per-frame pane compositor as a pixel reference."""
    with viewport._lock:
        layout = viewport._layout
        surfaces = dict(viewport._surfaces)
        order = viewport._order
    image = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), "black")
    if layout is None or not order:
        return image
    position = offset % layout.width
    start = 0
    index = 0
    for index, segment in enumerate(layout.segments):
        if start + segment.width > position:
            break
        start += segment.width
    x = start - position
    draw = ImageDraw.Draw(image)
    while x < PANEL_WIDTH:
        segment = layout.segments[index % len(layout.segments)]
        surface = surfaces.get(segment.item_id)
        draw.line((x, 0, x, PANEL_HEIGHT - 1), fill=DIVIDER)
        if surface is not None:
            image.paste(surface.image, (x + 1, 0), surface.image)
        x += segment.width
        index += 1
    return image


def _wait_ready(viewport: CardViewport, interval: float) -> float:
    started = time.perf_counter()
    deadline = started
    while True:
        viewport.install_completed()
        status = viewport.status
        if not status["pending"]:
            if status["failed"]:
                raise RuntimeError(f"Pane render failed: {status}")
            if status["ready"] != status["desired"]:
                raise RuntimeError(f"Pane surfaces did not commit: {status}")
            return time.perf_counter() - started
        if time.perf_counter() - started > 120:
            raise TimeoutError(str(status))
        deadline += interval
        time.sleep(max(0.0, deadline - time.perf_counter()))


def _timings(render, offsets: list[int]) -> dict[str, float]:
    warmup_count = min(30, max(0, len(offsets) - 1))
    for index, offset in enumerate(offsets[:warmup_count]):
        render(index, offset)
    samples: list[float] = []
    for index, offset in enumerate(offsets[warmup_count:], start=warmup_count):
        started = time.perf_counter()
        image = render(index, offset)
        samples.append(time.perf_counter() - started)
    ordered = sorted(value * 1000 for value in samples)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "frames": len(samples),
        "mean_ms": statistics.fmean(ordered),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[p95_index],
        "max_ms": ordered[-1],
        "rgb_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
    }


def _case(snapshot_path: Path, output: Path, pane_count: int, frame_count: int) -> dict[str, object]:
    raw = snapshot_path.read_bytes()
    data = json.loads(raw)
    source = content_items(normalize_snapshot(data, "sports"), "sports")
    if not source:
        raise RuntimeError("The input snapshot has no sports panes.")
    context = RenderContext(datetime.fromisoformat("2026-08-13T00:00:00+00:00"))
    interval = float(data["settings"]["scroll_speed"])
    panes = tuple(
        Content(
            f"pane-{index}-{source[index % len(source)]['id']}",
            source[index % len(source)]["kind"],
            source[index % len(source)]["sport"],
            dict(source[index % len(source)]),
        )
        for index in range(pane_count)
    )
    asset_path = output / f"assets-{pane_count}"
    assets = AssetCoordinator(asset_path, fetch=lambda url: None)
    _, viewport = create_default_frame_builder(assets)
    try:
        viewport.update(panes, context, "sports")
        ready_seconds = _wait_ready(viewport, interval)
        flat = FlattenedPanes(viewport)
        ribbon = BoundedPaneRibbon(viewport)
        offsets = [index % viewport.layout.width for index in range(frame_count)]

        check_offsets = sorted({0, 1, viewport.layout.width // 2, viewport.layout.width - 1})
        for offset in check_offsets:
            expected = _independent_pane_frame(viewport, offset)
            current_frame = viewport.frame(offset, PANEL_WIDTH, PANEL_HEIGHT)
            flat_frame = flat.frame(offset)
            ribbon.reset(viewport, offset)
            ribbon_frame = ribbon.frame((offset + 1) % viewport.layout.width, viewport)
            next_expected = _independent_pane_frame(viewport, (offset + 1) % viewport.layout.width)
            current_equal = current_frame.tobytes() == expected.tobytes()
            flat_equal = flat_frame.tobytes() == expected.tobytes()
            ribbon_equal = ribbon_frame.tobytes() == next_expected.tobytes()
            if not current_equal or not flat_equal or not ribbon_equal:
                raise AssertionError(
                    f"Pane composition changed pixels at offset {offset}: "
                    f"panes={pane_count}, current={current_equal}, "
                    f"flat={flat_equal}, ribbon={ribbon_equal}, "
                    f"ribbon_first={next(((index % PANEL_WIDTH, index // PANEL_WIDTH, left, right) for index, (left, right) in enumerate(zip(ribbon_frame.getdata(), next_expected.getdata())) if left != right), None)}."
                )

        independent = _timings(lambda index, offset: _independent_pane_frame(viewport, offset), offsets)
        current = _timings(lambda index, offset: viewport.frame(offset, PANEL_WIDTH, PANEL_HEIGHT), offsets)
        flat_timings = _timings(lambda index, offset: flat.frame(offset), offsets)
        ribbon.reset(viewport)
        ribbon_timings = _timings(
            lambda index, offset: ribbon.frame(offset, viewport), offsets
        )
        output.mkdir(parents=True, exist_ok=True)
        viewport.frame(0, PANEL_WIDTH, PANEL_HEIGHT).save(output / f"panes-{pane_count}-current-cached.png")
        flat.frame(0).save(output / f"panes-{pane_count}-flattened.png")
        ribbon.reset(viewport)
        ribbon.frame(0, viewport).save(output / f"panes-{pane_count}-bounded-ribbon.png")

        prior_generation = viewport.status["committed_generation"]
        changed = dict(panes[0].data)
        changed["away_score"] = str(int(changed["away_score"]) + 1)
        changed_panes = (Content(panes[0].id, panes[0].type, panes[0].sport, changed), *panes[1:])
        update_started = time.perf_counter()
        viewport.update(changed_panes, context, "sports")
        _wait_ready(viewport, interval)
        pane_update_seconds = time.perf_counter() - update_started
        flat_rebuild_seconds = flat.rebuild(viewport)
        ribbon_rebuild_started = time.perf_counter()
        ribbon.reset(viewport)
        ribbon_rebuild_seconds = time.perf_counter() - ribbon_rebuild_started
        updated_independent = _independent_pane_frame(viewport, 0)
        updated_current = viewport.frame(0, PANEL_WIDTH, PANEL_HEIGHT)
        updated_flat = flat.frame(0)
        updated_ribbon = ribbon.frame(0, viewport)
        if (
            updated_current.tobytes() != updated_independent.tobytes()
            or updated_current.tobytes() != updated_flat.tobytes()
            or updated_current.tobytes() != updated_ribbon.tobytes()
        ):
            raise AssertionError("Pane update changed output pixels across composition methods.")
        if viewport.status["committed_generation"] <= prior_generation:
            raise AssertionError("Pane score update did not commit.")
        updated_current.save(output / f"panes-{pane_count}-updated.png")

        surface_bytes = sum(
            surface.image.width * surface.image.height * len(surface.image.getbands())
            for surface in viewport._surfaces.values()
        )
        assert flat.strip is not None and flat.tiled is not None and ribbon.canvas is not None
        return {
            "pane_count": pane_count,
            "unique_source_records": len(source),
            "frame_count": frame_count,
            "readiness_seconds": round(ready_seconds, 6),
            "pane_update_to_ready_seconds": round(pane_update_seconds, 6),
            "flattened_rebuild_seconds": round(flat_rebuild_seconds, 6),
            "bounded_ribbon_rebuild_seconds": round(ribbon_rebuild_seconds, 6),
            "composition": {
                "previous_independent_panes": independent,
                "current_cached_flattened_strip": current,
                "flattened_strip_crop": flat_timings,
                "bounded_384px_ribbon": ribbon_timings,
            },
            "retained_rgb_bytes": {
                "pane_surfaces_rgba": surface_bytes,
                "current_tiled_pane_strip_rgb": viewport._tiled_strip.width * viewport._tiled_strip.height * 3,
                "flattened_strip_rgb": flat.strip.width * flat.strip.height * 3,
                "flattened_tiled_source_rgb": flat.tiled.width * flat.tiled.height * 3,
                "bounded_ribbon_rgb": ribbon.canvas.width * ribbon.canvas.height * 3,
            },
            "pixels_match": True,
        }
    finally:
        viewport.close()
        assets.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--output", type=Path, default=ROOT / "previews" / "benchmarks" / "pane-composition")
    parser.add_argument("--frames", type=int, default=3000)
    args = parser.parse_args()
    if args.frames < 100:
        raise ValueError("Use at least 100 frames per pane composition.")
    results = [_case(args.snapshot, args.output, count, args.frames) for count in (1, 10, 60)]
    report = {
        "host": sys.platform,
        "python": sys.version,
        "snapshot": args.snapshot.resolve().relative_to(ROOT).as_posix(),
        "snapshot_sha256": hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
        "limitations": [
            "The fixture has two sports panes. Capacity cases repeat those real pane scenes with unique IDs.",
            "The benchmark compares pane composition after asynchronous pane renders complete.",
            "Pane image generation, assets, backend time, and matrix DMA are reported separately or excluded.",
            "The bounded ribbon retains one 384x32 image and shifts one column for sequential scrolling.",
            "All three composition paths must produce identical 384x32 pixels before timing is accepted.",
        ],
        "cases": results,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "pane-composition.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
