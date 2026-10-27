"""Measure controlled 150-game scrolling on a real Six or a memory display.

Use --hardware only with an external recovery handler that restores ticker-controller.service.
The tool writes isolated data and never changes a release or controller settings.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from multiprocessing import get_context
import os
from queue import Empty
from pathlib import Path
import resource
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def summarize(values):
    values = sorted(values)
    if not values:
        return None
    return {'count': len(values), 'p50_ms': statistics.median(values),
            'p95_ms': values[min(len(values)-1, int(len(values)*0.95))] if len(values) >= 20 else None,
            'max_ms': values[-1]}


class ControlledInput:
    """Decode controlled input in the normal polling process before the production queue bridge."""

    def __init__(self, commands, initial):
        self.commands, self.initial = commands, initial

    def run(self, stop, events):
        from ticker_core.app.poller import PollFailed, PollSucceeded
        from ticker_core.protocol import TickerResponse, display_delta
        previous = TickerResponse.from_payload(self.initial)
        events.put(PollSucceeded(previous))
        while not stop.is_set():
            try:
                payload, identifiers, sequence, reconnect = self.commands.get(timeout=0.1)
            except Empty:
                continue
            received, ingested = time.monotonic(), time.time()*1000
            response = TickerResponse.from_payload(payload)
            if reconnect:
                events.put(PollFailed(ConnectionError('controlled disconnect'), 0.4))
                if stop.wait(0.4):
                    return
            decoded = time.monotonic()
            traces = {identifier: {'trace_id': f'{sequence}:{identifier}', 'source': 'controlled_v2',
                                   'ingested_at_ms': ingested, 'input_boundary': 'controlled_v2_input'} for identifier in identifiers}
            timing = {'received_at_ms': ingested, 'received_mono': received, 'decoded_mono': decoded,
                      'queued_mono': time.monotonic(), 'transport': 'controlled_v2_input',
                      'active_items': [item.id for item in response.content], 'items': traces}
            events.put(PollSucceeded(response if reconnect else display_delta(previous, response), (decoded-received)*1000, None, timing))
            previous = response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=45)
    parser.add_argument('--games', type=int, default=150)
    parser.add_argument('--hardware', action='store_true')
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--card-cpu', type=int)
    parser.add_argument('--warmup-seconds', type=float, default=90)
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--scenario', choices=('scores', 'mixed', 'single'), default='scores')
    parser.add_argument('--resume-cache', action='store_true')
    parser.add_argument('--update-interval', type=float)
    args = parser.parse_args()
    if not 1 <= args.games <= 1000 or not 5 <= args.seconds <= 360 or not 1 <= args.warmup_seconds <= 120:
        parser.error('Use 1 to 1000 games and a duration from 5 to 360 seconds.')
    if not 0 <= args.start_index < args.games:
        parser.error('The start index must select one of the supplied games.')
    interval = args.update_interval if args.update_interval is not None else (3.0 if args.scenario == 'mixed' else 2.0 if args.scenario == 'single' else 5.0)
    if not 0.5 <= interval <= 30:
        parser.error('Use an update interval from 0.5 to 30 seconds.')
    from ticker_core.app.application import TickerApplication
    from ticker_core.assets import ShortTermContentCache
    from ticker_core.bootstrap import create_default_frame_builder
    from ticker_core.drivers import MemoryFrameSink, RgbMatrixFrameSink
    from ticker_core.platform import AssetCoordinator, TickerPiLogger
    from ticker_core.protocol import BackendClient
    from ticker_core.runtime import FrameKind, FramePacer, TickerRuntime

    class DisabledCommands:
        def reboot(self):
            raise RuntimeError('Stress-test device commands are disabled')

        def run_update(self, *values):
            raise RuntimeError('Stress-test updates are disabled')

    class Logger(TickerPiLogger):
        def __init__(self, directory):
            super().__init__(directory)
            self.latencies = []
            self.issues = []

        def record_latency(self, value):
            self.latencies.append(dict(value))
            super().record_latency(value)

        def record_issue(self, source, error, **details):
            self.issues.append({'source': source, 'error_type': type(error).__name__})
            super().record_issue(source, error, **details)

    args.data.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.snapshot.read_text())
    original = next(item for item in payload['content']['sports'] if item['kind'] == 'scoreboard')
    games = []
    for index in range(args.games):
        item = deepcopy(original)
        item['id'] = f'game-{index}'
        item['data']['home_score'] = str(10 + index % 30)
        item['data']['away_score'] = str(10 + (index + 7) % 30)
        games.append(item)
    payload['content'] = {'sports': games}
    payload['events'] = {'alerts': [], 'news': []}
    payload['settings'].update(mode='sports', sports_presentation='rotation', pinned_content_id='', score_alerts=False,
                               scroll_speed=0.03, live_delay_mode=False)
    if args.resume_cache:
        saved = json.loads((args.data / 'content.json').read_text(encoding='utf-8'))
        if saved['expires_at'] <= time.time():
            parser.error('The stored input cache has expired.')
        payload = saved['payload']
        games = payload['content']['sports']
        if len(games) != args.games:
            parser.error('The stored input cache has a different game count.')
    logger = Logger(args.data / 'logs')
    assets = AssetCoordinator(args.data / 'assets')
    frames, viewport = create_default_frame_builder(assets, card_cpu=args.card_cpu)
    sink = RgbMatrixFrameSink.create() if args.hardware else MemoryFrameSink()
    commands = get_context('spawn').Queue(maxsize=2)
    application = TickerApplication(client=BackendClient('http://127.0.0.1:1'), poller=ControlledInput(commands, payload),
        cache=ShortTermContentCache(args.data / 'content.json'), assets=assets,
        runtime=TickerRuntime(monotonic=time.monotonic, wall_clock=datetime.now), viewport=viewport, frames=frames,
        pacer=FramePacer(time.monotonic), sink=sink, commands=DisabledCommands(), device_id='scroll-stress',
        repository=Path(__file__).resolve().parents[2], wall_clock=datetime.now, poll_in_process=True,
        render_cpu=args.cpu, poll_cpu=2 if args.hardware else None, logger=logger)
    frames_at, work_times, cases = [], [], {}
    samples, rebuilds, previous_strip = 0, 0, None
    frame_kinds, disconnect_frames, scenario_counts = Counter(), 0, Counter()
    wraps, last_offset = 0, None

    def inject(identifiers, case, sequence):
        payload.setdefault('events', {})['alerts'] = []
        for item in games:
            if item['id'] in identifiers:
                if case == 'visible_clock':
                    item['data']['status'] = f"Q3 08:{(59-sequence % 60):02}"
                elif case == 'game_final':
                    item['data'].update(state='post', status='FINAL')
                else:
                    item['data']['home_score'] = str(10 + (int(item['data']['home_score']) - 9) % 40)
        if case == 'alert':
            payload['events']['alerts'] = [{'event_id': f'stress-{sequence}', 'kind': 'touchdown', 'payload': {
                'sport': 'nfl', 'team_abbr': 'DAL', 'home_abbr': 'DAL', 'away_abbr': 'NYG',
                'headline': 'TOUCHDOWN', 'kind': 'touchdown', 'points': 7}}]
        payload['snapshot']['revision'] = sequence + 2
        for identifier in identifiers:
            cases[f'{sequence}:{identifier}'] = case
        commands.put_nowait((deepcopy(payload), tuple(identifiers), sequence, case == 'reconnect'))
        scenario_counts[case] += 1

    def step(record=False):
        nonlocal rebuilds, previous_strip, wraps, last_offset, disconnect_frames
        started = time.monotonic()
        application.step()
        finished = time.monotonic()
        if viewport._tiled_strip is not previous_strip:
            previous_strip = viewport._tiled_strip
            rebuilds += int(previous_strip is not None)
        if record:
            frame_kinds[str(application._last_decision.kind)] += 1
            disconnect_frames += int(application._last_decision.connection_lost)
            if application._last_decision.kind is FrameKind.SCROLL:
                offset = application._last_decision.scroll_offset
                if last_offset is not None and offset < last_offset:
                    wraps += 1
                last_offset = offset
            work_times.append((finished-started)*1000)
            if application._last_present_at == finished:
                frames_at.append(finished)
            elif application._last_present_at is not None and (not frames_at or application._last_present_at > frames_at[-1]):
                frames_at.append(application._last_present_at)
        application._stop.wait(application._pacer.next_delay(application._last_decision.interval))

    def visible_complete():
        layout = viewport.layout
        decision = application._last_decision
        if layout is None or decision is None or decision.kind is not FrameKind.SCROLL:
            return set()
        offset = (decision.scroll_offset or 0) % layout.width
        start, selected = 0, set()
        for segment in layout.segments:
            for repeat in range(2):
                left = start + repeat*layout.width
                if left >= offset + 12 and left + segment.width <= offset + 372:
                    selected.add(segment.item_id)
            start += segment.width
        return selected

    def worker_cpu():
        processes = getattr(viewport._worker, '_processes', {})
        total = 0.0
        for pid in processes:
            try:
                fields = Path(f'/proc/{pid}/stat').read_text().split(')', 1)[1].split()
                total += (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
            except FileNotFoundError:
                continue
        return total

    try:
        warm_started = time.monotonic()
        deadline = warm_started + args.warmup_seconds
        first_scroll_ms = None
        while time.monotonic() < deadline:
            step()
            if first_scroll_ms is None and viewport.layout is not None:
                first_scroll_ms = (time.monotonic()-warm_started)*1000
            if viewport.layout is not None and len(viewport.layout.segments) == args.games and viewport.status['pending'] == 0:
                break
        else:
            raise RuntimeError(f'The full scrolling rotation did not warm: {dict(viewport.status)}')
        warm_ms = (time.monotonic()-warm_started)*1000
        rebuilds_at_warm = rebuilds
        status_at_warm = dict(viewport.status)
        if args.start_index:
            application.runtime._strip_offset = sum(segment.width for segment in viewport.layout.segments[:args.start_index])
            step()
        application._last_frame.save(args.data/'warm-frame.png')
        cpu_started = time.process_time()
        children_started = worker_cpu()
        started = time.monotonic()
        next_update = started + 1
        injected_visible = set()
        while time.monotonic()-started < args.seconds:
            now = time.monotonic()
            if now >= next_update:
                visible = visible_complete()
                if visible or args.scenario == 'mixed':
                    samples += 1
                    if args.scenario == 'mixed':
                        case = ('visible_game','all_games','visible_clock','game_final','alert','reconnect')[(samples-1)%6]
                    elif args.scenario == 'single':
                        case = 'visible_game'
                    else:
                        case = 'all_games' if samples % 2 == 0 else 'visible_game'
                    selected = ({item['id'] for item in games} if case == 'all_games' else set() if case == 'alert'
                                else {f'game-{(samples*7)%args.games}'} if case == 'game_final'
                                else {sorted(visible)[0] if visible else 'game-0'})
                    inject(selected, case, samples)
                    injected_visible.update(f'{samples}:{identifier}' for identifier in selected & visible)
                next_update += interval
            step(True)
        for _ in range(200):
            if viewport.status['pending'] == 0:
                break
            step(True)
        elapsed = time.monotonic()-started
        cpu = time.process_time()-cpu_started
        application._last_frame.save(args.data/'last-frame.png')
        status = dict(viewport.status)
        received = {item.id: item for item in application._last_response.content}
        for game in games:
            actual = received.get(game['id'])
            if (actual is None or actual.data.get('home_score') != game['data']['home_score']
                    or actual.data.get('status') != game['data']['status']
                    or actual.data.get('state') != game['data']['state']):
                raise RuntimeError(f"The latest controlled game data was not retained: {game['id']}")
        visible_rows = [row for row in logger.latencies if row['outcome']=='presented' and row['trace_id'] in injected_visible]
        def metrics_for(visible_at_accept):
            rows = [row for row in logger.latencies if row.get('visible_at_accept') is visible_at_accept]
            return {
                'count': len(rows),
                'outcomes': dict(Counter(row['outcome'] for row in rows)),
                **{key: summarize([row[key] for row in rows if isinstance(row.get(key), (int, float))])
                   for key in ('source_to_present_ms', 'pane_prepare_ms', 'worker_wait_ms',
                               'worker_render_ms', 'visibility_wait_ms')},
            }
        output = {'context': 'Controlled V2 input on the Pi through the normal polling process and queue bridge, production application, card process, scrolling renderer, and frame sink. No provider or network delay.',
                  'hardware': args.hardware, 'games': args.games, 'pane_count': len(viewport.layout.segments),
                  'start_index': args.start_index, 'rotation_wraps': wraps, 'last_scroll_offset': last_offset,
                  'scenario': args.scenario, 'scenario_counts': dict(scenario_counts), 'frame_kinds': dict(frame_kinds),
                  'disconnect_frames': disconnect_frames, 'resume_cache': args.resume_cache, 'issues': logger.issues,
                  'latest_game_data_matches': True,
                  'warm_ms': warm_ms, 'first_scroll_ms': first_scroll_ms, 'elapsed_seconds': elapsed, 'update_batches': samples,
                  'frames': len(frames_at), 'fps': len(frames_at)/elapsed, 'frame_work': summarize(work_times),
                  'presentation_intervals': summarize([(b-a)*1000 for a,b in zip(frames_at,frames_at[1:])]),
                  'visible_updates_expected': len(injected_visible), 'visible_updates_presented': len(visible_rows),
                  'visible_input_to_present': summarize([row['source_to_present_ms'] for row in visible_rows]),
                  'visible_by_case': {case: summarize([row['source_to_present_ms'] for row in visible_rows if cases[row['trace_id']]==case])
                                      for case in ('visible_game','all_games','visible_clock','game_final','reconnect')},
                  'visible_at_accept': metrics_for(True), 'offscreen_at_accept': metrics_for(False),
                  'visibility_unknown_at_accept': metrics_for(None),
                  'cpu_percent_main': cpu/elapsed*100, 'cpu_percent_card_worker': (worker_cpu()-children_started)/elapsed*100,
                  'peak_rss_kib_main': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'strip_rebuilds_observed': rebuilds, 'strip_rebuilds_during_updates': rebuilds-rebuilds_at_warm,
                  'viewport_at_warm': status_at_warm, 'viewport': status,
                  'outcomes': dict(Counter(row['outcome'] for row in logger.latencies)),
                  'latency_records': logger.latencies}
        (args.data/'result.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
        print(json.dumps({key:value for key,value in output.items() if key!='latency_records'},indent=2))
    finally:
        application.close()
        commands.close()
        commands.join_thread()


if __name__ == '__main__':
    main()
