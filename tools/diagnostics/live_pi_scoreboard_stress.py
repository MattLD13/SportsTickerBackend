"""Show fifteen synthetic live scoreboards on the real Pi matrix and measure rendering."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
from uuid import uuid4

import requests


PANEL_SIZE = (384, 32)
PANEL_INTERVAL = 0.03


def _ssh_command(target: str, identity: Path, command: str) -> list[str]:
    return [
        "ssh",
        "-i",
        str(identity),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        target,
        command,
    ]


def _scp_command(source: str, destination: str, identity: Path) -> list[str]:
    return [
        "scp",
        "-i",
        str(identity),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        source,
        destination,
    ]


def _ssh(target: str, identity: Path, command: str, *, timeout: int = 25) -> str:
    result = subprocess.run(
        _ssh_command(target, identity, command),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def _live_game_items(payload: dict[str, Any], count: int) -> list[dict[str, Any]]:
    source = payload.get("content", {}).get("sports", [])
    scoreboards = [
        item for item in source
        if isinstance(item, dict)
        and item.get("kind") == "scoreboard"
        and isinstance(item.get("data"), dict)
    ]
    if not scoreboards:
        raise ValueError("The backend snapshot has no scoreboard games to expand.")
    games = []
    for index in range(count):
        original = scoreboards[index % len(scoreboards)]
        item_data = deepcopy(original["data"])
        item_id = f"codex-live-game-{index + 1:02d}"
        item_data.update(
            {
                "id": item_id,
                "type": "scoreboard",
                "state": "in",
                "status": f"LIVE {index + 1:02d}",
                "away_score": str((7 + index * 3) % 50),
                "home_score": str((10 + index * 5) % 50),
            }
        )
        item_data.setdefault("sport", "nfl")
        item_data.setdefault("away_abbr", "AWY")
        item_data.setdefault("home_abbr", "HME")
        games.append(
            {
                "id": item_id,
                "family": "sports",
                "kind": "scoreboard",
                "sport": str(item_data["sport"]),
                "data": item_data,
                "source_id": str(original.get("id", "unknown")),
            }
        )
    return games


def _orchestrate(args: argparse.Namespace) -> dict[str, object]:
    backend_url = args.backend_url.rstrip("/")
    response = requests.get(
        f"{backend_url}/tickers/{args.ticker_id}/data",
        timeout=20,
    )
    response.raise_for_status()
    games = _live_game_items(response.json(), args.game_count)
    run_id = uuid4().hex[:10]
    remote_runner = f"/tmp/ticker-scoreboard-stress-{run_id}.py"
    remote_games = f"/tmp/ticker-scoreboard-games-{run_id}.json"
    remote_report = f"/tmp/ticker-scoreboard-report-{run_id}.json"
    remote_frame = f"/tmp/ticker-scoreboard-frame-{run_id}.png"
    destination = Path(args.output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    local_report = destination / f"pi-{args.game_count}-games-{run_id}.json"
    local_frame = destination / f"pi-{args.game_count}-games-{run_id}.png"
    remote_spec = {
        "release": _ssh(
            args.ssh_target,
            args.ssh_key,
            "systemctl is-active ticker-controller.service && readlink -f /opt/sports-ticker/current",
        ).splitlines()[-1],
        "games": games,
    }

    with tempfile.TemporaryDirectory(prefix="ticker-scoreboard-stress-") as temp:
        local_runner = Path(temp) / "live_pi_scoreboard_stress.py"
        local_games = Path(temp) / "games.json"
        local_runner.write_bytes(Path(__file__).read_bytes())
        local_games.write_text(json.dumps(remote_spec["games"]), encoding="utf-8")
        subprocess.run(
            _scp_command(str(local_runner), f"{args.ssh_target}:{remote_runner}", args.ssh_key),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        subprocess.run(
            _scp_command(str(local_games), f"{args.ssh_target}:{remote_games}", args.ssh_key),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    shell_script = f"""set -eu
restore_ticker() {{ sudo systemctl start ticker-controller.service >/dev/null 2>&1 || true; }}
trap restore_ticker EXIT
sudo systemctl stop ticker-controller.service
sudo env PYTHONPATH=/opt/sports-ticker/current TICKER_GPIO_SLOWDOWN=1 TICKER_CARD_CPU=3 /usr/bin/python3 {remote_runner} --device-runner --games-file {remote_games} --report-file {remote_report} --frame-file {remote_frame} --duration-seconds {args.duration_seconds}
sudo cat {remote_report}
"""
    run_result: subprocess.CompletedProcess[str] | None = None
    try:
        raw_result = subprocess.run(
            _ssh_command(args.ssh_target, args.ssh_key, "sh -s"),
            input=shell_script.encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=args.duration_seconds + 180,
        )
        run_result = subprocess.CompletedProcess(
            raw_result.args,
            raw_result.returncode,
            raw_result.stdout.decode("utf-8", errors="replace"),
            raw_result.stderr.decode("utf-8", errors="replace"),
        )
        if Path(local_report.parent).exists():
            for remote_path, local_path in ((remote_report, local_report), (remote_frame, local_frame)):
                subprocess.run(
                    _scp_command(f"{args.ssh_target}:{remote_path}", str(local_path), args.ssh_key),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
    finally:
        try:
            _ssh(args.ssh_target, args.ssh_key, "sudo systemctl start ticker-controller.service")
        finally:
            _ssh(
                args.ssh_target,
                args.ssh_key,
                f"sudo rm -f {remote_runner} {remote_games} {remote_report} {remote_frame}",
            )

    if run_result is None or run_result.returncode != 0:
        detail = "" if run_result is None else run_result.stderr.strip()
        raise RuntimeError(f"Pi scoreboard test failed. {detail}")
    if not local_report.exists():
        raise RuntimeError("Pi scoreboard test did not return a report.")
    report = json.loads(local_report.read_text(encoding="utf-8"))
    report["release"] = remote_spec["release"]
    report["report_file"] = str(local_report)
    report["frame_file"] = str(local_frame) if local_frame.exists() else None
    local_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _percentile(samples: list[float], value: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = max(0, math.ceil(len(ordered) * value) - 1)
    return round(ordered[index], 3)


def _summarize(samples: list[dict[str, float]], started: float, ended: float) -> dict[str, object]:
    if not samples:
        return {"frames": 0, "duration_s": round(ended - started, 3)}
    intervals = [sample["interval_ms"] for sample in samples if sample["interval_ms"] >= 0]
    work = [sample["work_ms"] for sample in samples]
    present = [sample["present_ms"] for sample in samples]
    return {
        "frames": len(samples),
        "duration_s": round(ended - started, 3),
        "fps": round(len(samples) / max(ended - started, 0.001), 3),
        "work_ms_p50": _percentile(work, 0.50),
        "work_ms_p95": _percentile(work, 0.95),
        "present_ms_p95": _percentile(present, 0.95),
        "interval_ms_p95": _percentile(intervals, 0.95),
        "interval_ms_p99": _percentile(intervals, 0.99),
        "interval_ms_max": round(max(intervals), 3),
        "overruns": sum(sample["work_ms"] + sample["present_ms"] > 30.0 for sample in samples),
    }


def _device_run(args: argparse.Namespace) -> dict[str, object]:
    from ticker_core.bootstrap import create_default_frame_builder
    from ticker_core.context import RenderContext
    from ticker_core.drivers import RgbMatrixFrameSink
    from ticker_core.platform import AssetCoordinator
    from ticker_core.rendering import FrameGeometry
    from ticker_core.runtime import Content

    games = json.loads(args.games_file.read_text(encoding="utf-8"))
    if len(games) != 15 or len({game["id"] for game in games}) != 15:
        raise ValueError("The physical load check needs fifteen unique game panes.")
    if not all(game.get("data", {}).get("state") == "in" for game in games):
        raise ValueError("Every physical load pane must describe a live game.")

    content = tuple(
        Content(game["id"], game["kind"], game["sport"], game["data"])
        for game in games
    )
    context = RenderContext(datetime.now(timezone.utc))
    asset_directory = Path("/home/mld/ticker/assets")
    assets = AssetCoordinator(asset_directory, fetch=lambda _url: None, workers=1)
    frames, viewport = create_default_frame_builder(
        assets,
        card_cpu=3,
        geometry=FrameGeometry(width=384, height=32),
    )
    started = time.monotonic()
    viewport.update(content, context, "sports")
    ready_deadline = started + 90
    while time.monotonic() < ready_deadline:
        viewport.install_completed()
        status = viewport.status
        if not status["pending"]:
            break
        time.sleep(0.003)
    ready_seconds = time.monotonic() - started
    status = dict(viewport.status)
    if status["pending"] or status["failed"] or status["ready"] != 15:
        viewport.close()
        assets.close()
        raise RuntimeError(f"Fifteen panes did not finish rendering: {status}")

    sink = RgbMatrixFrameSink.create()
    frame_file = args.frame_file
    phases: dict[str, dict[str, object]] = {}
    offset = 0
    previous_present: float | None = None

    def present_once(samples: list[dict[str, float]]) -> None:
        nonlocal offset, previous_present
        viewport.install_completed()
        started_at = time.perf_counter()
        image = viewport.frame(offset, PANEL_SIZE[0], PANEL_SIZE[1])
        present_started = time.perf_counter()
        if image.size != PANEL_SIZE:
            raise RuntimeError(f"Unexpected physical frame size: {image.size}")
        sink.present(image, brightness=100, inverted=False)
        finished = time.perf_counter()
        samples.append(
            {
                "work_ms": max(0.0, (present_started - started_at) * 1000),
                "present_ms": max(0.0, (finished - present_started) * 1000),
                "interval_ms": -1.0 if previous_present is None else max(0.0, (finished - previous_present) * 1000),
            }
        )
        previous_present = finished
        offset = (offset + 1) % (viewport.layout.width if viewport.layout else 1)

    def run_duration(seconds: float, bucket: list[dict[str, float]]) -> None:
        deadline = time.perf_counter()
        stop_at = deadline + seconds
        while time.perf_counter() < stop_at:
            present_once(bucket)
            deadline += PANEL_INTERVAL
            delay = deadline - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -PANEL_INTERVAL:
                deadline = time.perf_counter()

    try:
        sink.present(viewport.frame(0, *PANEL_SIZE), brightness=100, inverted=False)
        if frame_file is not None:
            viewport.frame(0, *PANEL_SIZE).save(frame_file)
        phases["steady_before_updates"] = {}
        samples: list[dict[str, float]] = []
        phase_started = time.monotonic()
        run_duration(args.duration_seconds / 3, samples)
        phases["steady_before_updates"] = _summarize(samples, phase_started, time.monotonic())

        layout = viewport.layout
        if layout is None:
            raise RuntimeError("The fifteen-game pane layout is missing.")
        changed_index = 7
        game_start = sum(segment.width for segment in layout.segments[:changed_index])
        before_frame = viewport.frame(game_start, *PANEL_SIZE)
        one_update = deepcopy(games)
        one_update[changed_index]["data"]["away_score"] = str(
            int(one_update[changed_index]["data"].get("away_score", 0)) + 1
        )
        viewport.update(
            tuple(Content(game["id"], game["kind"], game["sport"], game["data"]) for game in one_update),
            RenderContext(datetime.now(timezone.utc)),
            "sports",
        )
        one_pending = viewport.status["pending"]
        one_samples: list[dict[str, float]] = []
        update_started = time.monotonic()
        target_generation = viewport.status["staging_generation"]
        deadline = time.perf_counter()
        while time.monotonic() - update_started < 90:
            viewport.install_completed()
            status = viewport.status
            if status["committed_generation"] == target_generation and status["pending"] == 0:
                break
            present_once(one_samples)
            deadline += PANEL_INTERVAL
            delay = deadline - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -PANEL_INTERVAL:
                deadline = time.perf_counter()
        one_update_ready = time.monotonic() - update_started
        if viewport.status["committed_generation"] != target_generation:
            raise TimeoutError(f"Single-game score update did not commit: {dict(viewport.status)}")
        layout = viewport.layout
        assert layout is not None
        game_start = sum(segment.width for segment in layout.segments[:changed_index])
        after_frame = viewport.frame(game_start, *PANEL_SIZE)
        score_frame_changed = before_frame.tobytes() != after_frame.tobytes()
        sink.present(after_frame, brightness=100, inverted=False)
        run_duration(args.duration_seconds / 6, one_samples)
        phases["single_score_update"] = _summarize(one_samples, update_started, time.monotonic())

        all_updates = deepcopy(one_update)
        for index, game in enumerate(all_updates):
            game["data"]["home_score"] = str(int(game["data"].get("home_score", 0)) + 1)
        viewport.update(
            tuple(Content(game["id"], game["kind"], game["sport"], game["data"]) for game in all_updates),
            RenderContext(datetime.now(timezone.utc)),
            "sports",
        )
        all_pending = viewport.status["pending"]
        all_samples: list[dict[str, float]] = []
        all_started = time.monotonic()
        target_generation = viewport.status["staging_generation"]
        deadline = time.perf_counter()
        while time.monotonic() - all_started < 90:
            viewport.install_completed()
            status = viewport.status
            if status["committed_generation"] == target_generation and status["pending"] == 0:
                break
            present_once(all_samples)
            deadline += PANEL_INTERVAL
            delay = deadline - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -PANEL_INTERVAL:
                deadline = time.perf_counter()
        all_update_ready = time.monotonic() - all_started
        if viewport.status["committed_generation"] != target_generation:
            raise TimeoutError(f"Fifteen-game score update did not commit: {dict(viewport.status)}")
        run_duration(args.duration_seconds / 3, all_samples)
        phases["fifteen_score_update"] = _summarize(all_samples, all_started, time.monotonic())

        final_status = dict(viewport.status)
        final_layout = viewport.layout
        assert final_layout is not None
        scroll_columns = sum(int(phase["frames"]) for phase in phases.values())
        scroll_cycle_seconds = round(final_layout.width * PANEL_INTERVAL, 3)
        report = {
            "hardware": "real Pi RGB matrix",
            "panel": {"width": PANEL_SIZE[0], "height": PANEL_SIZE[1]},
            "game_panes": len(games),
            "unique_game_ids": len({game["id"] for game in games}),
            "unique_matchups": len({(game["data"].get("away_abbr"), game["data"].get("home_abbr")) for game in games}),
            "pane_strip_width_px": final_layout.width,
            "scroll_cycle_seconds": scroll_cycle_seconds,
            "scroll_columns_presented": scroll_columns,
            "full_scroll_cycles": round(scroll_columns / final_layout.width, 2),
            "cold_panes_ready_seconds": round(ready_seconds, 3),
            "one_score_update_queue_depth": one_pending,
            "one_score_update_ready_seconds": round(one_update_ready, 3),
            "one_score_update_changed_pixels": score_frame_changed,
            "fifteen_score_update_queue_depth": all_pending,
            "fifteen_score_update_ready_seconds": round(all_update_ready, 3),
            "final_viewport": final_status,
            "phases": phases,
            "temperature_c": _temperature_c(),
            "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None,
            "frame_file": str(frame_file) if frame_file else None,
            "display_budget_ok": all(
                _phase_meets_budget(phases[name])
                for name in ("steady_before_updates", "single_score_update", "fifteen_score_update")
            ),
        }
        report["passed"] = (
            final_status["desired"] == 15
            and final_status["ready"] == 15
            and final_status["failed"] == 0
            and score_frame_changed
            and report["display_budget_ok"]
            and one_pending == 1
            and all_pending == 15
            and scroll_columns >= final_layout.width
        )
        args.report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            raise RuntimeError("The physical fifteen-game load check did not pass.")
        return report
    finally:
        viewport.close()
        assets.close()


def _temperature_c() -> float | None:
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
        return round(int(raw) / 1000, 1)
    except (OSError, ValueError):
        return None


def _phase_meets_budget(phase: dict[str, object]) -> bool:
    frames = int(phase.get("frames", 0))
    if frames <= 0:
        return False
    overrun_ratio = int(phase.get("overruns", frames)) / frames
    return (
        float(phase.get("fps", 0.0)) >= 30.0
        and float(phase.get("interval_ms_p95") or float("inf")) <= 31.0
        and overrun_ratio <= 0.05
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-runner", action="store_true")
    parser.add_argument("--games-file", type=Path)
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--frame-file", type=Path)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--backend-url", default="https://ticker.mattdicks.org/api/v2")
    parser.add_argument("--ticker-id", default="722c59f4-fce3-4735-b072-faaa2f579a0a")
    parser.add_argument("--ssh-target", default="mld@ticker2.local")
    parser.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh" / "ticker2_codex")
    parser.add_argument("--game-count", type=int, default=15)
    parser.add_argument("--output-dir", type=Path, default=Path(".tmp/real-pi-scoreboard-stress"))
    args = parser.parse_args()
    if args.device_runner:
        if args.games_file is None or args.report_file is None:
            parser.error("Device mode needs --games-file and --report-file")
    else:
        if args.game_count != 15:
            parser.error("The physical stress profile currently validates fifteen games.")
        if not 30 <= args.duration_seconds <= 300:
            parser.error("--duration-seconds must be between 30 and 300")
    return args


def main() -> int:
    args = _parse_args()
    try:
        if args.device_runner:
            _device_run(args)
        else:
            print(json.dumps(_orchestrate(args), indent=2))
    except (OSError, requests.RequestException, subprocess.SubprocessError, ValueError, RuntimeError, TimeoutError) as error:
        print(f"Real Pi scoreboard stress failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
