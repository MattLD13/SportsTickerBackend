#!/usr/bin/env python3
"""Run six labeled scroll-motion choices against one real V2 payload.

Copy this file into the Pi experiment directory before running hardware trials.
The default schedule lasts 245 seconds, including the five-second static baseline.
Candidates 1-4 are reconstructed runnable equivalents from the recorded trial
contract. The exact rejected dither diff is archived at
``docs/research/ticker-motion-2026-08-16/source/rejected-spatial-dither.patch``.
Use ``--segment-seconds`` for local checks. The caller must run it under an
external unconditional service-restoration unit. This tool never manages systemd.
"""

from __future__ import annotations

import argparse
from base64 import b85decode
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import sys
from time import monotonic, sleep
from typing import Any

from PIL import Image, ImageChops, ImageDraw


PANEL_SIZE = (384, 32)
_RANK_TILE_SIZE = 32
_RANK_GROUPS = 64
_BLOCK_RANK_DATA = (
    '0T>$+I0GCy6b?BDAwDELG!-x?3@iyXGd2YvI|>#85HA@Q039VFKLjZwCp`uqE;lO(Dho0XF(wfj4IUFM',
    'ArCeMBr6aG7a$ok5dt_W02T>8EGZKxI}9y64iqvH2p9xCCmIVS9u+hk0UItI10n|>IwK7xH8(jhFA6a~',
    '1tBH^G9D#5FB%&y5ElU*2O|k8A}1~wBoZ_z6bdm92s{8RGamy!KNB?#FcCN$DLV@w1{OI46%IWaD-1R_',
    'JQ6AtH4r}m3oRNc0w)e6I~fKZB@r_d1sgOm3@8XM6)YeCGAl3`E)OCXIte}l4Idl|IX4z2I5q?!2OT3l',
    '2qruaIszpfG8-ur5-tl98Y=)b9~U?T4Kpt+2^<+TKOP4mHz*JWFbpIhDgz@T0X;1a7BLt$ITZyv5k3kh',
    'Co4S-83il|6E+4W4i*a+KOrOxG72C96b~sQ8$1v>FEju*A_OfF2{<znC_XVBE*KRZ2O0r8Is-5tDm5G>',
    'Bq{+F8XqeO5-B(^3M~&WGzdKfHwQKg88JT|5k3<xCp7~(BM=+_6eT({1{Mt+G8haXB0M_|1R)nD8v-aS',
    '5+gYY9V-wrJ^?8k6b3yl7a2PiF&GsGE($*+0x&cv5iAZbARY`SB?B`HDmoen4>lq<JOCdYArk~R4JI`O',
    '05TgO11&Q-B^DhS9}hGT3oHf{2rvaTArdbnHa#g31U?rH6#+3CCO-lrHzE!w3KJYB2Rl3%9x4nvD=rB*',
    'E*Co@1v&^T2^Ih_8zUGYARIk3Cj&7NDg+b{JU$9J4jB+L1|>HYEDIVxI4A)%4K^kMEgv2!BnJ~OG7KFO',
    'A`%uiJqtP!0yGy2A1V|q6B-OI7zQ{G2`?N2J}3@5B`_H^BnUGh9W4Yl6)8Lc5IG<w9tA5S8x21IF()zy',
    '7B~(S9RociF$p;cJ{u+l4=6M%6C4aFCprKkGZ7;P5-J!q1~MKuKRgW|EE)kY3N||g84Dm3Ednkt7bOrO',
    'DlZN+G8H@w2plN@CL#nQGY}6F6cIQu7#b@m4I4WKAOk-NJ~k6KCm|j+IRPaJF)Rfg79Twq0vRqk2Q3RE',
    'HY^Sp6eb-CDi=EgJ_k2F03{YEKO7?>Bsd8(3n>O68w4H_Ee|yl4KXVp0T~P$FFFt>G!-BMJOwThIS4W^',
    '2{{8X6&wI1BoiSo8#*!y3?3N=EfF;*I}a-&4jm%`DIfth8U-pS4Lvv*7A6urHv}#V7Z5)PGZZjB1~eZm',
    'B@-Vt8wWlBFAXRHIx;yT1}P944jvLGCLK2lEd?qOFbpm{7%UYaI5aT<I|x4m83ZF74>JiD6d@K1Ha#RO',
)
_BLOCK_RANK_FIELD = b85decode("".join(_BLOCK_RANK_DATA).encode("ascii"))
_MASK_TABLES = tuple(
    tuple(255 if value < threshold else 0 for value in range(256))
    for threshold in range(_RANK_GROUPS + 1)
)


CADENCE = 0.03
LEVELS = (1, 5, 8, 10)
OPTION_NAMES = {
    1: "continuous-blend",
    2: "spatial-rank-dither",
    3: "integer-floor-30ms",
    4: "adaptive-blend-crisp",
    5: "uniform-native-pixel",
    6: "aligned-dwell",
}
WARMUP_SECONDS = 2.0
MEASUREMENT_SECONDS = 8.0
BASELINE_SECONDS = 5.0
BADGE_RECT = (0, 0, 39, 10)  # left, top, right, bottom, with right and bottom exclusive
SYNC_MARKER = "SYNC_MOTION_TRIAL"


def _repo_root() -> Path:
    """Add the immutable release or local repository to the import path."""
    script_root = Path(__file__).resolve().parents[1]
    release_root = Path("/opt/sports-ticker/current")
    root = release_root if release_root.exists() else script_root
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


_repo_root()

from ticker_core.assets import AssetPlanner  # noqa: E402
from ticker_core.bootstrap import create_default_content_catalog  # noqa: E402
from ticker_core.context import RenderContext  # noqa: E402
from ticker_core.drivers import MemoryFrameSink, RgbMatrixFrameSink  # noqa: E402
from ticker_core.platform import AssetCoordinator  # noqa: E402
from ticker_core.protocol import TickerResponse  # noqa: E402
from ticker_core.rendering.fonts import load_default_font_set  # noqa: E402
from ticker_core.runtime import Content  # noqa: E402
from ticker_core.app.viewport import CardViewport  # noqa: E402


def speed_interval(level: int) -> float:
    """Return the current iOS speed interval in seconds per pixel."""
    if level not in range(1, 11):
        raise ValueError("Speed level must be between 1 and 10.")
    pixels_per_second = 10.0 + (level - 1) * (30.0 / 9.0)
    return 1.0 / pixels_per_second


def load_payload(path: Path) -> Mapping[str, Any]:
    """Load a raw V2 payload from direct JSON or last-good cache JSON."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read payload {path}: {error}") from error
    if isinstance(value, Mapping) and isinstance(value.get("payload"), Mapping):
        value = value["payload"]
    if not isinstance(value, Mapping):
        raise ValueError("The stored payload must be a JSON object.")
    return value


def runtime_items(response: TickerResponse) -> tuple[Content, ...]:
    """Convert validated V2 sports content into renderer-owned runtime items."""
    items: list[Content] = []
    for item in response.content:
        if item.family not in {"sports", "golf", "racing"} or not item.is_shown:
            continue
        data = dict(item.data)
        data.setdefault("id", item.id)
        data.setdefault("type", item.kind)
        data.setdefault("sport", item.family)
        items.append(Content(item.id, item.kind, str(data.get("sport", item.family)), data))
    return tuple(items)


def _apply_badge(frame: Image.Image, label: str) -> Image.Image:
    """Add one compact trial label inside the declared half-open mask rectangle."""
    output = frame.copy().convert("RGB")
    draw = ImageDraw.Draw(output)
    left, top, right, bottom = BADGE_RECT
    draw.rectangle((left, top, right - 1, bottom - 1), fill=(0, 0, 0))
    draw.text((left + 1, top), label, font=_badge_font(), fill=(255, 255, 0))
    return output


def badge(frame: Image.Image, option: int, level: int) -> Image.Image:
    """Add a compact motion label without changing the underlying card renderer."""
    return _apply_badge(frame, f"#{option} S{level}")


def baseline_badge(frame: Image.Image) -> Image.Image:
    """Add the static reference label inside the same declared badge rectangle."""
    return _apply_badge(frame, "BASE")


@lru_cache(maxsize=1)
def _badge_font():
    """Load the trial font once instead of touching font storage per frame."""
    return load_default_font_set().tiny


@lru_cache(maxsize=8)
def _rank_plane(width: int, height: int) -> Image.Image:
    """Build the recorded 16-block rank plane for one viewport geometry."""
    source_width = width + _RANK_TILE_SIZE
    rows = []
    for y in range(height):
        row = bytes(
            _BLOCK_RANK_FIELD[
                (((y % _RANK_TILE_SIZE) // 8) * 4 + ((x % _RANK_TILE_SIZE) // 8)) * 64
                + (y % 8) * 8
                + (x % 8)
            ]
            for x in range(source_width)
        )
        rows.append(row)
    return Image.frombytes("L", (source_width, height), b"".join(rows))


@lru_cache(maxsize=128)
def _coverage_mask_base(width: int, height: int, quantum: int) -> Image.Image:
    """Cache one exact q-over-64 rank mask for one viewport geometry."""
    return _rank_plane(width, height).point(_MASK_TABLES[quantum])


def _spatial_dither_frame(viewport: CardViewport, offset: float) -> Image.Image:
    """Reproduce the rejected spatial rank-dither renderer inside the trial tool."""
    position = max(0.0, float(offset))
    column = int(position)
    phase = position - column
    current = viewport.frame(column)
    following = viewport.frame(column + 1)
    quantum = max(0, min(64, round(max(0.0, min(1.0, phase)) * 64)))
    if quantum <= 0:
        return current
    if quantum >= 64:
        return following
    mask = _coverage_mask_base(PANEL_SIZE[0], PANEL_SIZE[1], quantum)
    shifted = ImageChops.offset(mask, -(column % _RANK_TILE_SIZE), 0)
    return Image.composite(following, current, shifted.crop((0, 0, PANEL_SIZE[0], PANEL_SIZE[1])))


def motion_parameters(option: int, level: int) -> tuple[float, float, bool, bool]:
    """Return frame interval, logical step, blend flag, and dither flag for one candidate."""
    requested_interval = speed_interval(level)
    if option == 1:
        return CADENCE, CADENCE / requested_interval, True, False
    if option == 2:
        return CADENCE, CADENCE / requested_interval, False, True
    if option == 3:
        return CADENCE, CADENCE / requested_interval, False, False
    if option == 4:
        return CADENCE, CADENCE / requested_interval, level < 8, False
    if option == 5:
        return requested_interval, 1.0, False, False
    if option == 6:
        frame_interval = CADENCE if level < 8 else requested_interval
        return frame_interval, 1.0, False, False
    raise ValueError(f"Unknown trial option {option}.")


def render_motion_frame(viewport: CardViewport, option: int, offset: float, step: float) -> Image.Image:
    """Render one candidate frame without changing the production viewport."""
    if option == 2:
        return _spatial_dither_frame(viewport, offset)
    if option == 1 or (option == 4 and step < 1.0):
        return viewport.frame(offset)
    return viewport.frame(int(offset))


def make_sink(dry_run: bool):
    """Select memory output locally or the real matrix output on Pi."""
    return MemoryFrameSink(*PANEL_SIZE) if dry_run else RgbMatrixFrameSink.create()


def wait_for_layout(viewport: CardViewport, timeout: float = 30.0) -> None:
    """Wait until all normal card surfaces commit before the trial starts."""
    deadline = monotonic() + timeout
    while viewport.layout is None and monotonic() < deadline:
        viewport.install_completed()
        sleep(0.005)
    viewport.install_completed()
    if viewport.layout is None:
        raise RuntimeError("The normal card viewport did not become ready.")


def layout_spans(viewport: CardViewport) -> tuple[int, ...]:
    """Return each real card span from the committed renderer layout."""
    if viewport.layout is None:
        raise RuntimeError("The card viewport has no committed layout.")
    spans = tuple(segment.width for segment in viewport.layout.segments)
    if not spans or any(span <= 0 for span in spans):
        raise RuntimeError("The card viewport returned invalid card spans.")
    return spans


def dwell_schedule(spans: tuple[int, ...], level: int, option: int) -> tuple[float, ...]:
    """Compute one aligned dwell for each real card span."""
    requested_interval = speed_interval(level)
    if option != 6 or level >= 8:
        return tuple(0.0 for _ in spans)
    dwells = tuple(max(0.0, span * (requested_interval - CADENCE)) for span in spans)
    for span, dwell in zip(spans, dwells):
        requested_cycle = span * requested_interval
        if abs(span * CADENCE + dwell - requested_cycle) > 1e-9:
            raise RuntimeError(f"Aligned dwell failed for card span {span}.")
    return dwells


def _manifest_event(
    *,
    kind: str,
    start: float,
    end: float,
    **fields: Any,
) -> dict[str, Any]:
    """Build one trial-relative timing record."""
    if end < start:
        raise RuntimeError(f"Manifest event {kind} has a negative duration.")
    return {
        "kind": kind,
        "start_s": round(start, 6),
        "end_s": round(end, 6),
        **fields,
    }


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Require ordered, non-overlapping timing records and complete motion phases."""
    segments = manifest.get("segments")
    if not isinstance(segments, list) or not segments:
        raise RuntimeError("The motion manifest has no timing segments.")
    previous_end = -1.0
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise RuntimeError("The motion manifest contains an invalid segment.")
        start = float(segment["start_s"])
        end = float(segment["end_s"])
        if start < previous_end - 1e-6 or end < start:
            raise RuntimeError("The motion manifest contains overlapping timing segments.")
        previous_end = end
    motion = [segment for segment in segments if segment.get("kind") == "motion"]
    if len(motion) != len(LEVELS) * 6 * 2:
        raise RuntimeError("The motion manifest must contain six candidates with warmup and measurement records.")
    phases = {(segment.get("candidate"), segment.get("speed_level"), segment.get("phase")) for segment in motion}
    expected = {
        (option, level, phase)
        for option in range(1, 7)
        for level in LEVELS
        for phase in ("warmup", "measurement")
    }
    if phases != expected:
        raise RuntimeError("The motion manifest does not contain every candidate, speed, and phase.")


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Write the trial manifest as readable JSON."""
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def emit_sync_marker(
    viewport: CardViewport,
    sink: object,
    brightness: int,
    inverted: bool,
    origin: float,
    manifest: list[dict[str, Any]],
) -> None:
    """Present one dim marker frame and record it before the static baseline."""
    start = monotonic()
    frame = viewport.frame(0).convert("RGB")
    frame.putpixel((PANEL_SIZE[0] - 1, PANEL_SIZE[1] - 1), (16, 16, 16))
    sink.present(frame, brightness=brightness, inverted=inverted)
    end = monotonic()
    manifest.append(
        _manifest_event(
            kind="sync_marker",
            start=start - origin,
            end=end - origin,
            marker=SYNC_MARKER,
            visual="one_dim_corner_pixel",
            badge_mask_rect=list(BADGE_RECT),
        )
    )
    print(f"sync-marker name={SYNC_MARKER} power=16", flush=True)


def run_baseline(
    viewport: CardViewport,
    sink: object,
    brightness: int,
    inverted: bool,
    duration: float,
    origin: float,
    manifest: list[dict[str, Any]],
) -> None:
    """Hold one crisp same-content frame for the exact static reference duration."""
    start = monotonic()
    deadline = start + duration
    frame = baseline_badge(viewport.frame(0))
    if frame.size != PANEL_SIZE:
        raise RuntimeError(f"Baseline frame size is {frame.size}, not {PANEL_SIZE}.")
    sink.present(frame, brightness=brightness, inverted=inverted)
    remaining = deadline - monotonic()
    if remaining > 0:
        sleep(remaining)
    end = monotonic()
    manifest.append(
        _manifest_event(
            kind="static_baseline",
            start=start - origin,
            end=end - origin,
            requested_seconds=duration,
            card_span_px=None,
            dwell_s=None,
            candidate="BASE",
            speed_level=None,
            badge_mask_rect=list(BADGE_RECT),
            scrolling=False,
            blend=False,
            dither=False,
        )
    )
    print(f"baseline-complete seconds={end - start:.3f} frames=1 badge=BASE", flush=True)


def run_segment(
    viewport: CardViewport,
    sink: object,
    option: int,
    level: int,
    warmup_seconds: float,
    measurement_seconds: float,
    brightness: int,
    inverted: bool,
    spans: tuple[int, ...],
    origin: float,
    manifest: list[dict[str, Any]],
) -> int:
    """Run one warmup and measurement window for one isolated candidate."""
    requested_interval = speed_interval(level)
    frame_interval, position_step, blend, dither = motion_parameters(option, level)
    dwells = dwell_schedule(spans, level, option)
    aligned_boundary_proof: list[dict[str, float | int]] = []
    if option == 6 and level < 8:
        boundary = 0
        for card_index, (span, dwell) in enumerate(zip(spans, dwells)):
            boundary += span
            aligned_boundary_proof.append(
                {
                "card_index": card_index,
                    "boundary_offset_px": boundary,
                    "boundary_error_px": 0,
                    "cycle_error_s": span * CADENCE + dwell - span * requested_interval,
                }
            )
    print(
        f"transition option={option} name={OPTION_NAMES[option]} speed={level} "
        f"interval={requested_interval:.6f}s frame_interval={frame_interval:.6f}s step={position_step:.6f} "
        f"card_pixels={list(spans)} dwell={list(round(value, 6) for value in dwells)}",
        flush=True,
    )
    offset = 0
    span_index = 0
    next_boundary = spans[0]
    dwell_until: float | None = None
    total_frames = 0
    badge_checked = False
    for phase_name, duration in (("warmup", warmup_seconds), ("measurement", measurement_seconds)):
        phase_start = monotonic()
        deadline = phase_start + duration
        next_frame = phase_start
        phase_frames = 0
        phase_dwell_boundaries: list[dict[str, int]] = []
        while True:
            now = monotonic()
            if now >= deadline and phase_frames:
                break
            current = render_motion_frame(viewport, option, offset, position_step)
            if option == 3 and isinstance(sink, MemoryFrameSink):
                expected_step = CADENCE / requested_interval
                if abs(position_step - expected_step) > 1e-9:
                    raise AssertionError(
                        f"Candidate 3 speed {level} step {position_step} does not equal {expected_step}."
                    )
                expected_rate = 1.0 / requested_interval
                if abs(position_step / frame_interval - expected_rate) > 1e-9:
                    raise AssertionError(
                        f"Candidate 3 speed {level} rate {position_step / frame_interval} does not equal {expected_rate}."
                    )
                if current.tobytes() != viewport.frame(int(offset)).tobytes():
                    raise AssertionError(f"Candidate 3 speed {level} did not floor to a crisp integer frame.")
            frame = badge(current, option, level)
            if frame.size != PANEL_SIZE:
                raise RuntimeError(f"Trial frame size is {frame.size}, not {PANEL_SIZE}.")
            if not badge_checked and isinstance(sink, MemoryFrameSink):
                badge_pixels = sum(
                    red > 200 and green > 200 and blue < 80
                    for red, green, blue in frame.crop(BADGE_RECT).getdata()
                )
                if badge_pixels == 0:
                    raise RuntimeError("The trial badge did not render visible text.")
                badge_checked = True
            sink.present(frame, brightness=brightness, inverted=inverted)
            total_frames += 1
            phase_frames += 1
            if dwell_until is not None and monotonic() < dwell_until:
                sleep(min(CADENCE, max(0.0, dwell_until - monotonic())))
                continue
            if dwell_until is not None:
                dwell_until = None
                span_index = (span_index + 1) % len(spans)
                next_boundary += spans[span_index]
                next_frame = monotonic()
            offset += 1
            next_frame += frame_interval
            if option == 6 and level < 8 and offset >= next_boundary:
                if offset != next_boundary:
                    raise RuntimeError("Aligned dwell started away from an integer card boundary.")
                phase_dwell_boundaries.append(
                    {
                        "offset_px": offset,
                        "traveled_span_px": spans[span_index],
                        "boundary_error_px": offset - next_boundary,
                    }
                )
                dwell_until = monotonic() + dwells[span_index]
            wait = next_frame - monotonic()
            if wait > 0:
                sleep(wait)
            elif monotonic() >= deadline:
                break
        phase_end = monotonic()
        manifest.append(
            _manifest_event(
                kind="motion",
                start=phase_start - origin,
                end=phase_end - origin,
                candidate=option,
                candidate_name=OPTION_NAMES[option],
                speed_level=level,
                phase=phase_name,
                requested_interval_s=requested_interval,
                expected_px_per_second=1.0 / requested_interval,
                actual_px_per_second=position_step / frame_interval,
                position_step=position_step,
                frame_interval_s=frame_interval,
                card_span_px=list(spans),
                dwell_s=list(dwells),
                aligned_boundary_proof=aligned_boundary_proof,
                aligned_dwell_boundaries=phase_dwell_boundaries,
                badge_mask_rect=list(BADGE_RECT),
                frames=phase_frames,
                scrolling=True,
                blend=blend,
                dither=dither,
            )
        )
        print(f"phase-complete option={option} speed={level} phase={phase_name} frames={phase_frames} cumulative_frames={total_frames}", flush=True)
    print(f"complete option={option} speed={level} total_frames={total_frames} card_spans={list(spans)} dwell={list(round(value, 6) for value in dwells)}", flush=True)
    return total_frames


def run(arguments: argparse.Namespace) -> int:
    """Run the complete six-candidate trial with clean resource ownership."""
    trial_origin = monotonic()
    manifest: dict[str, Any] = {
        "schema": 1,
        "status": "running",
        "panel_size": list(PANEL_SIZE),
        "baseline_seconds": BASELINE_SECONDS,
        "warmup_seconds": arguments.warmup_seconds,
        "measurement_seconds": arguments.measurement_seconds,
        "levels": list(LEVELS),
        "candidates": {str(option): OPTION_NAMES[option] for option in range(1, 7)},
        "badge_mask_rect": list(BADGE_RECT),
        "sync_marker": {
            "name": SYNC_MARKER,
            "visual": "one_dim_corner_pixel",
            "power_level": 16,
        },
        "service_restoration": "Caller must run this tool under an external unconditional service-restoration unit.",
        "segments": [],
    }
    raw_payload = load_payload(arguments.payload)
    response = TickerResponse.from_payload(raw_payload)
    items = runtime_items(response)
    if not items:
        raise ValueError("The last-good payload has no shown sports, golf, or racing cards.")

    assets = AssetCoordinator(arguments.assets)
    viewport: CardViewport | None = None
    sink: object | None = None
    status = "failed"
    try:
        futures = assets.prefetch(AssetPlanner().plan(raw_payload).requests)
        for future in futures:
            future.result()
        catalog = create_default_content_catalog(assets)
        viewport = CardViewport(
            catalog,
            use_process=True,
            asset_directory=assets.directory,
            worker_cpu=arguments.card_cpu,
        )
        viewport.update(items, RenderContext(datetime.now(timezone.utc)), "sports")
        wait_for_layout(viewport)
        spans = layout_spans(viewport)
        manifest["card_spans_px"] = list(spans)
        print(f"layout card_spans={list(spans)}", flush=True)
        sink = make_sink(arguments.dry_run)
        brightness = max(0, min(100, round(response.settings.brightness)))
        trial_origin = monotonic()
        emit_sync_marker(
            viewport,
            sink,
            brightness,
            response.settings.inverted,
            trial_origin,
            manifest["segments"],
        )
        run_baseline(
            viewport,
            sink,
            brightness,
            response.settings.inverted,
            BASELINE_SECONDS,
            trial_origin,
            manifest["segments"],
        )
        total_frames = 0
        transitions = 0
        for option in range(1, 7):
            for level in LEVELS:
                transitions += 1
                total_frames += run_segment(
                    viewport,
                    sink,
                    option,
                    level,
                    arguments.warmup_seconds,
                    arguments.measurement_seconds,
                    brightness,
                    response.settings.inverted,
                    spans,
                    trial_origin,
                    manifest["segments"],
                )
        expected = BASELINE_SECONDS + (arguments.warmup_seconds + arguments.measurement_seconds) * len(LEVELS) * 6
        if transitions != 24 or total_frames < transitions or expected <= 0:
            raise RuntimeError("The trial did not complete its 24 scheduled transitions.")
        manifest["scheduled_seconds"] = expected
        manifest["status"] = "complete"
        validate_manifest(manifest)
        status = "complete"
        print(f"trial-complete transitions={transitions} frames={total_frames} scheduled_seconds={expected:.3f}", flush=True)
        return 0
    finally:
        if sink is not None and callable(getattr(sink, "clear", None)):
            sink.clear()
        if viewport is not None:
            viewport.close()
        assets.close()
        manifest["status"] = status
        manifest["trial_end_s"] = monotonic() - trial_origin
        if "scheduled_seconds" not in manifest:
            manifest["scheduled_seconds"] = BASELINE_SECONDS + (
                arguments.warmup_seconds + arguments.measurement_seconds
            ) * len(LEVELS) * 6
        try:
            if status == "complete":
                validate_manifest(manifest)
            write_manifest(arguments.manifest, manifest)
            print(f"manifest-written path={arguments.manifest} events={len(manifest['segments'])}", flush=True)
        except Exception as manifest_error:
            print(f"manifest-failed: {manifest_error}", file=sys.stderr, flush=True)
            if status == "complete":
                raise


def main() -> int:
    """Parse trial options and return a process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True, help="Path to a stored V2 payload or last-good JSON.")
    parser.add_argument("--assets", type=Path, required=True, help="Path to the durable asset cache.")
    parser.add_argument("--segment-seconds", type=float, default=None, help="Set warmup plus measurement seconds for fast local checks.")
    parser.add_argument("--warmup-seconds", type=float, default=WARMUP_SECONDS)
    parser.add_argument("--measurement-seconds", type=float, default=MEASUREMENT_SECONDS)
    parser.add_argument("--manifest", type=Path, default=Path("ticker_motion_trial_manifest.json"))
    parser.add_argument("--card-cpu", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    if arguments.segment_seconds is not None:
        if arguments.segment_seconds <= 0:
            parser.error("--segment-seconds must be positive.")
        arguments.warmup_seconds = arguments.segment_seconds / 5.0
        arguments.measurement_seconds = arguments.segment_seconds * 4.0 / 5.0
    if arguments.warmup_seconds <= 0 or arguments.measurement_seconds <= 0:
        parser.error("Warmup and measurement durations must be positive.")
    try:
        return run(arguments)
    except Exception as error:
        print(f"trial-failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
