#!/usr/bin/env python3
"""Measure observable ticker defects from an existing webcam video.

This tool never opens a camera. It accepts a video filename and a four-corner
calibration file, then streams rectified 384x32 frames into compact metrics.
The evaluator labels fine temporal judder, PWM flicker, and nausea as low
confidence below 120 FPS because unsynchronized capture aliases the display.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import math
from typing import Any

import cv2
import numpy as np


PANEL_SIZE = (384, 32)
DISPLAY_INTERVAL = 0.03
BEAT_FRAMES = 9


@dataclass(frozen=True)
class Calibration:
    source_points: np.ndarray
    matrix: np.ndarray
    reprojection_error: float


def _quad_points(value: Any) -> np.ndarray:
    """Validate four clockwise image points."""
    points = np.asarray(value, dtype=np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("Calibration points must contain four finite [x, y] pairs.")
    return points


def load_calibration(path: Path) -> Calibration:
    """Load a reusable quadrilateral and build its panel homography."""
    data = json.loads(path.read_text(encoding="utf-8"))
    points = _quad_points(data.get("points", data))
    target = np.asarray(
        [[0, 0], [PANEL_SIZE[0] - 1, 0], [PANEL_SIZE[0] - 1, PANEL_SIZE[1] - 1], [0, PANEL_SIZE[1] - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(points, target)
    projected = cv2.perspectiveTransform(points[None, :, :], matrix)[0]
    error = float(np.sqrt(np.mean(np.sum((projected - target) ** 2, axis=1))))
    return Calibration(points, matrix, error)


def rectify(frame: np.ndarray, calibration: Calibration) -> np.ndarray:
    """Warp one camera frame into the logical 384x32 panel."""
    warped = cv2.warpPerspective(frame, calibration.matrix, PANEL_SIZE, flags=cv2.INTER_AREA)
    return cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)


def _rect_mask(rect: Any) -> np.ndarray:
    """Build a logical-panel mask from an exact x, y, width, height rectangle."""
    mask = np.ones((PANEL_SIZE[1], PANEL_SIZE[0]), dtype=bool)
    if rect is None:
        return mask
    if isinstance(rect, dict):
        rect = [rect.get("x"), rect.get("y"), rect.get("width", rect.get("w")), rect.get("height", rect.get("h"))]
    values = np.asarray(rect, dtype=float)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("A metric mask rectangle must be [x, y, width, height].")
    x, y, width, height = [int(round(value)) for value in values]
    x0, x1 = max(0, x), min(PANEL_SIZE[0], x + max(0, width))
    y0, y1 = max(0, y), min(PANEL_SIZE[1], y + max(0, height))
    mask[y0:y1, x0:x1] = False
    return mask


def metric_mask(badge_rect: Any = None, marker_rect: Any = None) -> np.ndarray:
    """Mask the badge and optional sync marker from every evaluator metric."""
    mask = _rect_mask(badge_rect)
    if marker_rect is not None:
        mask &= _rect_mask(marker_rect)
    # Sobel and interpolation kernels read neighboring pixels. Guard the exact
    # masked rectangle by two pixels so badge edges cannot enter a metric.
    invalid = cv2.dilate((~mask).astype(np.uint8), np.ones((5, 5), np.uint8))
    return invalid == 0


def _marker_metrics(signal: list[float], fps: float) -> dict[str, Any]:
    """Detect declared low-power sync marker transitions from its ROI."""
    values = np.asarray(signal, dtype=np.float32)
    if len(values) < 2 or float(np.ptp(values)) < 2.0:
        return {"declared": True, "detected": False, "transitions": 0}
    threshold = float(np.median(values) + np.ptp(values) * 0.25)
    states = values >= threshold
    transitions = int(np.count_nonzero(states[1:] != states[:-1]))
    return {
        "declared": True,
        "detected": transitions > 0,
        "transitions": transitions,
        "sample_fps": round(fps, 3),
        "signal_range": round(float(np.ptp(values)), 3),
    }


def _timestamp(cap: cv2.VideoCapture, index: int, fps: float, prior: float | None) -> tuple[float, str]:
    """Read an OpenCV timestamp, falling back to the stream frame clock."""
    value = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
    if value > 0 and (prior is None or value > prior):
        return value, "opencv_pos_msec"
    return index / max(fps, 1.0), "fps_fallback"


def _profile(gray: np.ndarray, valid_mask: np.ndarray | None = None) -> np.ndarray:
    """Return a normalized horizontal edge profile."""
    gradient = np.abs(np.diff(gray.astype(np.float32), axis=1))
    if valid_mask is None:
        values = gradient.mean(axis=0)
    else:
        valid = valid_mask[:, :-1] & valid_mask[:, 1:]
        counts = valid.sum(axis=0)
        values = np.divide((gradient * valid).sum(axis=0), counts, out=np.zeros(gradient.shape[1], dtype=np.float32), where=counts > 0)
    values -= values.mean()
    norm = float(np.linalg.norm(values))
    return values / norm if norm > 1e-6 else values


def estimate_shift(previous: np.ndarray, current: np.ndarray, valid_mask: np.ndarray | None = None, radius: int = 4) -> float:
    """Estimate horizontal motion with integer correlation and parabolic refinement."""
    left = _profile(previous, valid_mask)
    right = _profile(current, valid_mask)
    scores: list[float] = []
    shifts = list(range(-radius, radius + 1))
    for shift in shifts:
        if shift < 0:
            a, b = left[:shift], right[-shift:]
        elif shift > 0:
            a, b = left[shift:], right[:-shift]
        else:
            a, b = left, right
        scores.append(float(np.dot(a, b) / max(len(a), 1)))
    winner = int(np.argmax(scores))
    refined = float(shifts[winner])
    if 0 < winner < len(scores) - 1:
        y0, y1, y2 = scores[winner - 1 : winner + 2]
        denominator = y0 - 2.0 * y1 + y2
        if abs(denominator) > 1e-9:
            refined += 0.5 * (y0 - y2) / denominator
    return refined


def _aligned(gray: np.ndarray, shift: float) -> np.ndarray:
    """Translate a current frame back toward the preceding frame."""
    matrix = np.asarray([[1.0, 0.0, shift], [0.0, 1.0, 0.0]], dtype=np.float32)
    return cv2.warpAffine(gray, matrix, PANEL_SIZE, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _edge_energy(gray: np.ndarray, valid_mask: np.ndarray | None = None) -> float:
    """Return exposure-normalized horizontal edge energy."""
    pixels = gray[valid_mask] if valid_mask is not None else gray.ravel()
    scaled = gray.astype(np.float32) / max(float(np.percentile(pixels, 99)), 1.0)
    gradient = cv2.Sobel(scaled, cv2.CV_32F, 1, 0, ksize=3)
    return float(np.mean(np.abs(gradient[valid_mask]))) if valid_mask is not None else float(np.mean(np.abs(gradient)))


def _ghost_ratio(previous: np.ndarray, current: np.ndarray, shift: float, valid_mask: np.ndarray | None = None) -> float:
    """Measure secondary edge correlation at one to three pixel offsets."""
    aligned = _aligned(previous, shift)
    prior_edge = np.abs(cv2.Sobel(aligned.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3))
    current_edge = np.abs(cv2.Sobel(current.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3))
    if valid_mask is not None:
        prior_edge = prior_edge[valid_mask]
        current_edge = current_edge[valid_mask]
    else:
        prior_edge = prior_edge.ravel()
        current_edge = current_edge.ravel()
    prior_edge -= prior_edge.mean()
    current_edge -= current_edge.mean()
    main = abs(float(np.dot(prior_edge, current_edge)))
    if main < 1e-6:
        return 0.0
    secondary = 0.0
    for offset in (-3, -2, -1, 1, 2, 3):
        if valid_mask is None:
            rolled = np.roll(prior_edge.reshape(PANEL_SIZE[1], PANEL_SIZE[0]), offset, axis=1).ravel()
            secondary = max(secondary, abs(float(np.dot(rolled, current_edge))))
        else:
            shifted = np.roll(np.abs(cv2.Sobel(aligned.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)), offset, axis=1)
            secondary = max(secondary, abs(float(np.dot(shifted[valid_mask] - shifted[valid_mask].mean(), current_edge))))
    return secondary / main


def _spray_ratio(previous: np.ndarray, current: np.ndarray, shift: float, valid_mask: np.ndarray | None = None) -> float:
    """Measure changed pixels away from the expected moving edge mask."""
    aligned = _aligned(previous, shift)
    difference = cv2.absdiff(aligned, current)
    edge = np.maximum(
        np.abs(cv2.Sobel(aligned.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)),
        np.abs(cv2.Sobel(current.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)),
    )
    edge_mask = (edge > 28).astype(np.uint8)
    edge_mask = cv2.dilate(edge_mask, np.ones((3, 5), np.uint8))
    changed = difference > 28
    outside = changed & (edge_mask == 0)
    if valid_mask is not None:
        outside &= valid_mask
        changed &= valid_mask
    return float(np.count_nonzero(outside) / max(np.count_nonzero(changed), 1))


def _phase_metrics(shifts: list[float], times: list[float], expected_velocity: float | None) -> dict[str, Any]:
    """Summarize nine-frame beat cycles without claiming frame synchronization."""
    if not shifts:
        return {"average_px_s": None, "velocity_mad_px_s": None, "zero_hold_ratio": None, "large_jump_ratio": None}
    velocities = [abs(shift) / max(times[index + 1] - times[index], 1e-6) for index, shift in enumerate(shifts)]
    cycles = []
    for start in range(0, len(shifts) - BEAT_FRAMES + 1, BEAT_FRAMES):
        elapsed = times[start + BEAT_FRAMES] - times[start]
        cycles.append(abs(sum(shifts[start : start + BEAT_FRAMES])) / max(elapsed, 1e-6))
    median = float(np.median(velocities))
    threshold = max(median * 2.0, 0.5)
    phase_bins: list[dict[str, float | int]] = []
    for phase in range(BEAT_FRAMES):
        selected = [
            abs(shift) / max(times[index + 1] - times[index], 1e-6)
            for index, shift in enumerate(shifts)
            if round((((times[index] - times[0]) / DISPLAY_INTERVAL) % 1.0) * BEAT_FRAMES) % BEAT_FRAMES == phase
        ]
        selected_shifts = [
            abs(shift)
            for index, shift in enumerate(shifts)
            if round((((times[index] - times[0]) / DISPLAY_INTERVAL) % 1.0) * BEAT_FRAMES) % BEAT_FRAMES == phase
        ]
        phase_bins.append(
            {
                "phase": phase,
                "samples": len(selected),
                "median_px_s": round(float(np.median(selected)), 6) if selected else 0.0,
                "zero_hold_ratio": round(float(np.mean(np.asarray(selected_shifts) < 0.08)), 6) if selected_shifts else 0.0,
                "large_jump_ratio": round(float(np.mean(np.asarray(selected_shifts) > threshold)), 6) if selected_shifts else 0.0,
            }
        )
    return {
        "average_px_s": float(np.median(cycles)) if cycles else float(np.median(velocities)),
        "velocity_mad_px_s": float(np.median(np.abs(np.asarray(velocities) - median))),
        "zero_hold_ratio": float(np.mean(np.abs(shifts) < 0.08)),
        "large_jump_ratio": float(np.mean(np.abs(shifts) > threshold)),
        "expected_px_s": expected_velocity,
        "beat_cycles": len(cycles),
        "phase_bins": phase_bins,
    }


def _open_frames(path: Path, calibration: Calibration, max_frames: int | None = None, start_s: float = 0.0, end_s: float | None = None):
    """Yield rectified grayscale frames and timestamps from a video file."""
    if not path.is_file():
        raise FileNotFoundError(path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = 30.0
    prior: float | None = None
    index = 0
    timestamp_sources: list[str] = []
    try:
        while max_frames is None or index < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp, source = _timestamp(cap, index, fps, prior)
            prior = timestamp
            timestamp_sources.append(source)
            if timestamp < start_s:
                index += 1
                continue
            if end_s is not None and timestamp >= end_s:
                break
            yield rectify(frame, calibration), timestamp, fps, timestamp_sources
            index += 1
    finally:
        cap.release()


def analyze_clip(
    path: Path,
    calibration: Calibration,
    expected_velocity: float | None,
    diagnostics: Path | None,
    max_frames: int | None = None,
    start_s: float = 0.0,
    end_s: float | None = None,
    valid_mask: np.ndarray | None = None,
    marker_rect: Any = None,
) -> dict[str, Any]:
    """Analyze one clip with a bounded three-frame working buffer."""
    previous: np.ndarray | None = None
    previous_time: float | None = None
    frame_buffer: deque[np.ndarray] = deque(maxlen=3)
    shifts: list[float] = []
    frame_times: list[float] = []
    exposure: list[tuple[float, float, float, float]] = []
    luminance_signal: list[float] = []
    marker_signal: list[float] = []
    drifts: list[float] = []
    spray: list[float] = []
    ghosts: list[float] = []
    edges: list[float] = []
    freeze_run = 0
    longest_freeze = 0
    first: np.ndarray | None = None
    frame_count = 0
    fps = 0.0
    timestamp_sources: list[str] = []
    if diagnostics:
        diagnostics.mkdir(parents=True, exist_ok=True)
    for gray, timestamp, fps, source_history in _open_frames(path, calibration, max_frames, start_s, end_s):
        timestamp_sources = source_history
        frame_count += 1
        frame_buffer.append(gray)
        if first is None:
            first = gray
        pixels = gray[valid_mask] if valid_mask is not None else gray.ravel()
        percentiles = np.percentile(pixels, [1, 50, 99])
        exposure.append((float(percentiles[0]), float(percentiles[1]), float(percentiles[2]), float(np.mean(pixels >= 250))))
        luminance_signal.append(float(percentiles[2]))
        if marker_rect is not None:
            marker_mask = _rect_mask(marker_rect)
            marker_signal.append(float(np.median(gray[~marker_mask])))
        edges.append(_edge_energy(gray, valid_mask))
        if previous is not None and previous_time is not None:
            shift = estimate_shift(previous, gray, valid_mask)
            shifts.append(shift)
            residual_image = cv2.absdiff(_aligned(previous, shift), gray)
            residual = float(np.median(residual_image[valid_mask])) if valid_mask is not None else float(np.median(residual_image))
            if residual < 1.5 and abs(shift) < 0.08:
                freeze_run += 1
            else:
                freeze_run = 0
            longest_freeze = max(longest_freeze, freeze_run)
            spray.append(_spray_ratio(previous, gray, shift, valid_mask))
            ghosts.append(_ghost_ratio(previous, gray, shift, valid_mask))
            top = gray[:3].astype(np.float32)
            bottom = gray[-3:].astype(np.float32)
            old_top = previous[:3].astype(np.float32)
            old_bottom = previous[-3:].astype(np.float32)
            if valid_mask is not None:
                top = np.where(valid_mask[:3], top, 0.0)
                bottom = np.where(valid_mask[-3:], bottom, 0.0)
                old_top = np.where(valid_mask[:3], old_top, 0.0)
                old_bottom = np.where(valid_mask[-3:], old_bottom, 0.0)
            try:
                dx1, dy1 = cv2.phaseCorrelate(old_top, top)[0]
                dx2, dy2 = cv2.phaseCorrelate(old_bottom, bottom)[0]
                drifts.append(float(math.hypot((dx1 + dx2) / 2.0, (dy1 + dy2) / 2.0)))
            except cv2.error:
                pass
        previous = gray
        previous_time = timestamp
        frame_times.append(timestamp)
        if diagnostics and frame_count % 60 == 0:
            cv2.imwrite(str(diagnostics / f"frame-{frame_count:06d}.png"), gray)
    if frame_count == 0:
        raise ValueError(f"Video contains no readable frames: {path}")
    # `times` contains one leading timestamp and pair timestamps. Normalize to frame PTS.
    duration = max(frame_times[-1] - frame_times[0], 0.0) if frame_times else 0.0
    exposure_array = np.asarray(exposure)
    normalized_luminance = np.asarray(luminance_signal, dtype=np.float32)
    normalized_luminance /= max(float(np.median(normalized_luminance)), 1.0)
    luminance_delta = np.diff(normalized_luminance)
    return {
        "video": str(path),
        "window_s": [round(start_s, 6), round(end_s, 6) if end_s is not None else None],
        "frames": frame_count,
        "fps": round(fps, 3),
        "duration_s": round(duration, 6),
        "timestamp_source": "opencv_pos_msec" if timestamp_sources.count("opencv_pos_msec") >= max(1, len(timestamp_sources) * 0.8) else "fps_fallback",
        "calibration_reprojection_px": round(calibration.reprojection_error, 6),
        "confidence": {
            "spatial": "high" if calibration.reprojection_error <= 0.5 else "low",
            "temporal": "high" if fps >= 120 else "low",
            "reason": "120fps+ captures support cadence and flicker metrics" if fps >= 120 else "30/60fps capture aliases 33.33fps display timing",
        },
        "metrics": {
            "exposure": {
                "p01": round(float(np.median(exposure_array[:, 0])), 3),
                "median": round(float(np.median(exposure_array[:, 1])), 3),
                "p99": round(float(np.median(exposure_array[:, 2])), 3),
                "clipped_fraction_median": round(float(np.median(exposure_array[:, 3])), 6),
                "p99_cv": round(float(np.std(exposure_array[:, 2]) / max(np.mean(exposure_array[:, 2]), 1.0)), 6),
            },
            "camera_panel_drift_px_median": round(float(np.median(drifts)), 6) if drifts else None,
            "freeze_longest_frames": longest_freeze,
            "freeze_longest_s": round(longest_freeze / max(fps, 1.0), 6),
            "motion": _phase_metrics(shifts, frame_times, expected_velocity),
            "spray_ratio_median": round(float(np.median(spray)), 6) if spray else None,
            "spray_ratio_p95": round(float(np.percentile(spray, 95)), 6) if spray else None,
            "persistent_spray_fraction": round(float(np.mean(np.asarray(spray) > 0.05)), 6) if spray else None,
            "edge_energy_median": round(float(np.median(edges)), 6) if edges else None,
            "ghost_ratio_median": round(float(np.median(ghosts)), 6) if ghosts else None,
            "ghost_ratio_p95": round(float(np.percentile(ghosts, 95)), 6) if ghosts else None,
            "persistent_ghost_fraction": round(float(np.mean(np.asarray(ghosts) > 0.2)), 6) if ghosts else None,
            "visible_flicker_index": round(float(np.std(luminance_delta)), 6) if len(luminance_delta) else None,
        },
        "sync_marker": _marker_metrics(marker_signal, fps) if marker_signal else {"declared": False, "detected": False, "transitions": 0},
        "low_confidence": {
            "judder": fps < 120,
            "jitter": fps < 120,
            "flicker_pwm": fps < 120,
            "nausea": True,
        },
    }


def speed_velocity(level: int) -> float:
    """Return the existing ten-level physical speed contract."""
    if level not in range(1, 11):
        raise ValueError("Speed level must be between 1 and 10.")
    return 10.0 + (level - 1) * (30.0 / 9.0)


def _manifest_number(data: dict[str, Any], *names: str, default: float | None = None) -> float | None:
    """Return the first finite numeric manifest field."""
    for name in names:
        value = data.get(name)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    return default


def _manifest_window(segment: dict[str, Any], offset: float) -> tuple[float, float]:
    """Convert one trial segment to capture-relative measurement bounds."""
    if "start_s" in segment and "end_s" in segment:
        return float(segment["start_s"]) + offset, float(segment["end_s"]) + offset
    start = _manifest_number(segment, "measurement_start_s")
    end = _manifest_number(segment, "measurement_end_s")
    if start is None:
        trial_start = _manifest_number(segment, "start_s", "start", default=0.0) or 0.0
        if "duration_s" in segment and not any(name in segment for name in ("warmup_seconds", "warmup_s", "measurement_seconds", "measurement_s")):
            return trial_start + offset, trial_start + offset + (_manifest_number(segment, "duration_s", default=0.0) or 0.0)
        warmup = _manifest_number(segment, "warmup_seconds", "warmup_s", default=2.0) or 0.0
        measurement = _manifest_number(segment, "measurement_seconds", "measurement_s", "duration_s", default=8.0) or 8.0
        start, end = trial_start + warmup, trial_start + warmup + measurement
    if end is None:
        end = start + (_manifest_number(segment, "measurement_seconds", "measurement_s", "duration_s", default=8.0) or 8.0)
    return start + offset, end + offset


def _resolve_manifest_path(root: Path, value: Any) -> Path:
    """Resolve a manifest path relative to the manifest directory."""
    path = Path(str(value))
    if path.is_absolute() or path.is_file():
        return path
    return root / path


def _comparison_rows(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare candidate metrics at each declared speed."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for segment in segments:
        level = segment.get("level")
        if isinstance(level, int):
            grouped.setdefault(level, []).append(segment)
    rows = []
    for level, entries in sorted(grouped.items()):
        rows.append({
            "level": level,
            "candidates": [
                {
                    "candidate": entry.get("candidate", entry.get("option", entry.get("id"))),
                    "average_px_s": entry.get("metrics", {}).get("motion", {}).get("average_px_s"),
                    "spray_p95": entry.get("metrics", {}).get("spray_ratio_p95"),
                    "ghost_p95": entry.get("metrics", {}).get("ghost_ratio_p95"),
                    "edge_ratio": entry.get("metrics", {}).get("edge_width_proxy_ratio_vs_baseline"),
                }
                for entry in entries
            ],
        })
    return rows


def _detect_declared_sync_marker(video: Path, calibration: Calibration, sync_segment: dict[str, Any], baseline_segment: dict[str, Any]) -> dict[str, Any]:
    """Find the one-frame dim corner marker against the same-video baseline."""
    sync_start = _manifest_number(sync_segment, "start_s", "measurement_start_s", default=0.0) or 0.0
    sync_end = _manifest_number(sync_segment, "end_s", "measurement_end_s", default=sync_start + 0.03) or sync_start + 0.03
    baseline_start = _manifest_number(baseline_segment, "start_s", default=0.0) or 0.0
    baseline_end = _manifest_number(baseline_segment, "end_s", default=baseline_start + 5.0) or baseline_start + 5.0
    # The first camera PTS often rounds the marker timestamp down to zero.
    early = list(_open_frames(video, calibration, max_frames=8, start_s=max(0.0, sync_start - 0.05), end_s=sync_end + 0.05))
    reference = list(_open_frames(video, calibration, max_frames=120, start_s=baseline_start, end_s=baseline_end))
    if not early or not reference:
        return {"name": sync_segment.get("marker", "SYNC_MOTION_TRIAL"), "detected": False, "reason": "marker or baseline frames unavailable"}
    baseline = np.median(np.asarray([item[0] for item in reference]), axis=0)
    corners = [(0, 0), (PANEL_SIZE[0] - 1, 0), (0, PANEL_SIZE[1] - 1), (PANEL_SIZE[0] - 1, PANEL_SIZE[1] - 1)]
    scores = []
    for x, y in corners:
        score = max(float(abs(float(item[0][y, x]) - baseline[y, x])) for item in early)
        scores.append((score, x, y))
    score, x, y = max(scores)
    # A dim marker must produce a localized camera response above normal corner noise.
    # A low score means the 60 FPS capture missed the one-frame marker.
    detected = score >= 20.0
    observed = next((item[1] for item in early if abs(float(item[0][y, x]) - baseline[y, x]) >= 20.0), early[0][1])
    declared = sync_start
    return {
        "name": sync_segment.get("marker", "SYNC_MOTION_TRIAL"),
        "visual": sync_segment.get("visual", "one_dim_corner_pixel"),
        "detected": detected,
        "score": round(score, 3),
        "rect": [x, y, 1, 1],
        "observed_capture_s": round(observed, 6),
        "declared_trial_s": round(declared, 6),
        "capture_to_trial_offset_s": round(observed - declared, 6),
        "candidates": [{"rect": [cx, cy, 1, 1], "score": round(cs, 3)} for cs, cx, cy in sorted(scores, reverse=True)],
    }


def analyze_manifest(manifest_path: Path, calibration: Calibration, video_override: Path | None, offset_override: float | None, output: Path, diagnostics: Path | None, max_frames: int | None) -> dict[str, Any]:
    """Analyze manifest measurement windows and return one aggregate report."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must contain a JSON object.")
    root = manifest_path.parent
    video_value = video_override or manifest.get("video") or manifest.get("capture")
    if not video_value:
        raise ValueError("Manifest must declare video or capture.")
    video = video_value if isinstance(video_value, Path) else _resolve_manifest_path(root, video_value)
    offset = offset_override if offset_override is not None else (_manifest_number(manifest, "capture_to_trial_offset_s", "time_offset_s", default=0.0) or 0.0)
    badge_rect = manifest.get("badge_rect") or manifest.get("badge_mask_rect") or (manifest.get("badge") or {}).get("rect")
    marker = manifest.get("sync_marker") or manifest.get("marker")
    marker_rect = marker.get("rect") if isinstance(marker, dict) else marker
    declared_segments = manifest.get("segments") or manifest.get("measurements") or []
    sync_segment = next((segment for segment in declared_segments if isinstance(segment, dict) and segment.get("kind") == "sync_marker"), None)
    baseline_segment = next((segment for segment in declared_segments if isinstance(segment, dict) and segment.get("kind") == "static_baseline"), None)
    sync_detection = None
    if marker is not None and sync_segment is not None and baseline_segment is not None and marker_rect is None:
        sync_detection = _detect_declared_sync_marker(video, calibration, sync_segment, baseline_segment)
        if sync_detection.get("detected"):
            marker_rect = sync_detection.get("rect")
            if offset_override is None:
                offset = float(sync_detection.get("capture_to_trial_offset_s", offset))
    valid_mask = metric_mask(badge_rect, marker_rect)
    baseline_result = None
    prelude = manifest.get("static_prelude") or baseline_segment
    if isinstance(prelude, dict):
        prelude_start, prelude_end = _manifest_window(prelude, offset)
        baseline_result = analyze_clip(video, calibration, None, None, max_frames, prelude_start, prelude_end, valid_mask, marker_rect)
    segments = []
    declared = declared_segments
    if not isinstance(declared, list):
        raise ValueError("Manifest segments must be an array.")
    for index, segment in enumerate(declared):
        if not isinstance(segment, dict):
            continue
        if segment.get("kind") == "sync_marker" or segment.get("kind") == "static_baseline":
            continue
        if segment.get("kind") == "motion" and segment.get("phase") != "measurement":
            continue
        start, end = _manifest_window(segment, offset)
        level_value = segment.get("level", segment.get("speed_level"))
        result = analyze_clip(video, calibration, speed_velocity(int(level_value)) if level_value is not None else None, diagnostics, max_frames, start, end, valid_mask, marker_rect)
        result["segment"] = segment.get("id", f"segment-{index + 1:02d}")
        result["candidate"] = segment.get("candidate", segment.get("option"))
        result["level"] = level_value
        if baseline_result is not None:
            base_edge = baseline_result["metrics"].get("edge_energy_median")
            edge = result["metrics"].get("edge_energy_median")
            result["metrics"]["edge_width_proxy_ratio_vs_baseline"] = round(float(base_edge / edge), 6) if base_edge and edge else None
        segments.append(result)
    aggregate = {
        "manifest": str(manifest_path),
        "video": str(video),
        "capture_to_trial_offset_s": offset,
        "badge_rect_masked": badge_rect,
        "sync_marker": sync_detection or (marker if marker is not None else {"declared": False}),
        "sync_confidence": "high" if sync_detection and sync_detection.get("detected") else ("not_declared" if marker is None else "invalid_marker_not_observed"),
        "baseline": baseline_result,
        "segments": segments,
        "comparisons": _comparison_rows(segments),
    }
    aggregate["invalid_segments"] = [
        {
            "segment": segment.get("segment"),
            "reasons": [
                reason
                for reason in (
                    "sync_marker_not_observed" if marker is not None and not (sync_detection and sync_detection.get("detected")) else None,
                    "temporal_metrics_low_confidence_below_120fps" if segment.get("fps", 0.0) < 120 else None,
                )
                if reason is not None
            ],
        }
        for segment in segments
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(aggregate, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, nargs="?", help="Existing video file. Numeric camera indexes are not accepted.")
    parser.add_argument("--calibration", type=Path, required=True, help="JSON containing four clockwise panel corner points.")
    parser.add_argument("--manifest", type=Path, help="Trial manifest containing measurement windows and candidate labels.")
    parser.add_argument("--time-offset", type=float, help="Capture-time minus trial-time offset in seconds.")
    parser.add_argument("--baseline", type=Path, help="Optional baseline video recorded with the same camera setup.")
    parser.add_argument("--level", type=int, choices=range(1, 11), help="Existing iOS speed level for expected velocity.")
    parser.add_argument("--output", type=Path, default=Path("temp/camera-analysis/evaluation.json"))
    parser.add_argument("--diagnostics", type=Path, help="Optional directory for one rectified PNG every 60 frames.")
    parser.add_argument("--max-frames", type=int)
    arguments = parser.parse_args()
    calibration = load_calibration(arguments.calibration)
    if arguments.manifest:
        if not arguments.manifest.is_file():
            parser.error("manifest must name an existing file")
        result = analyze_manifest(arguments.manifest, calibration, arguments.video, arguments.time_offset, arguments.output, arguments.diagnostics, arguments.max_frames)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if arguments.video is None or not arguments.video.is_file():
        parser.error("video must name an existing file when --manifest is absent")
    result = analyze_clip(arguments.video, calibration, speed_velocity(arguments.level) if arguments.level else None, arguments.diagnostics, arguments.max_frames)
    if arguments.baseline:
        baseline = analyze_clip(arguments.baseline, calibration, None, None, arguments.max_frames)
        result["baseline"] = {"video": baseline["video"], "edge_energy_median": baseline["metrics"]["edge_energy_median"]}
        current = result["metrics"]["edge_energy_median"]
        base = baseline["metrics"]["edge_energy_median"]
        result["metrics"]["edge_width_proxy_ratio_vs_baseline"] = round(float(base / current), 6) if current and base else None
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
