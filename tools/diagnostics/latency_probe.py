"""Collect isolated live worker-to-frame traces without changing a deployed service or physical display."""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def worker(args):
    from backend_ops.worker import ProviderWorker, serve
    from sports_ticker.providers.espn import EspnScoreboardProvider
    from sports_ticker.providers.espn_fastcast import EspnFastcastSource, fastcast_topic
    from sports_ticker.providers.nhl_live import NhlLiveSituationSource

    urls = {league: f'https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard'
            for sport, league in [('basketball', 'nba'), ('football', 'nfl'), ('hockey', 'nhl')]}
    provider = EspnScoreboardProvider(urls, fastcast=EspnFastcastSource({league: fastcast_topic(url) for league, url in urls.items()}),
                                     nhl_situation_source=NhlLiveSituationSource())
    try:
        serve(ProviderWorker('espn', provider), args.data / 'espn.sock')
    finally:
        provider.close()


def display(args):
    from ticker_core.app.application import TickerApplication
    from ticker_core.app.poller import BackendPoller
    from ticker_core.assets import ShortTermContentCache
    from ticker_core.bootstrap import create_default_frame_builder
    from ticker_core.drivers import MemoryFrameSink
    from ticker_core.platform import AssetCoordinator, TickerPiLogger
    from ticker_core.protocol import BackendClient
    from ticker_core.runtime import FramePacer, TickerRuntime

    class DisabledCommands:
        def reboot(self):
            raise RuntimeError('Probe device commands are disabled')

        def run_update(self, *values):
            raise RuntimeError('Probe updates are disabled')

    client = BackendClient(f'http://127.0.0.1:{args.port}', device_token=(args.data / 'device_token').read_text().strip())
    assets = AssetCoordinator(args.data / 'assets')
    frames, viewport = create_default_frame_builder(assets)
    application = TickerApplication(
        client=client, poller=BackendPoller(client, 'latency-probe', telemetry=lambda: None,
                                          profile={'product_family': 'full', 'hardware': 'pi-zero-2w'}),
        cache=ShortTermContentCache(args.data / 'content.json'), assets=assets,
        runtime=TickerRuntime(monotonic=time.monotonic, wall_clock=datetime.now), viewport=viewport,
        frames=frames, pacer=FramePacer(time.monotonic), sink=MemoryFrameSink(), commands=DisabledCommands(),
        device_id='latency-probe', repository=ROOT, wall_clock=datetime.now, poll_in_process=True,
        logger=TickerPiLogger(args.data / 'logs'))
    deadline = time.monotonic() + args.seconds
    stop = False

    def stopped(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stopped)
    try:
        application.start()
        while not stop and time.monotonic() < deadline:
            application.step()
            application._stop.wait(application._pacer.next_delay(application._last_decision.interval))
        if application._last_frame is not None:
            application._last_frame.save(args.data / 'last-frame.png')
    finally:
        application.close()


async def server(args):
    from backend_ops.worker_contract import WorkerProvider
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    from sports_ticker.application import BackendRuntime, RefreshScheduler
    from sports_ticker.asgi import BackendASGI
    from sports_ticker.bootstrap_v2 import create_backend_application
    from sports_ticker.dashboard_v2.live_demo import PublicDemoData
    from sports_ticker.domain import DisplaySettings
    from sports_ticker.fleet import PairingState
    from sports_ticker.fleet.device_credentials import device_token_hash

    worker_log = (args.data / 'worker.log').open('ab')
    display_log = (args.data / 'display.log').open('ab')
    worker_process = subprocess.Popen([sys.executable, __file__, 'worker', '--data', str(args.data)],
                                      stdout=worker_log, stderr=subprocess.STDOUT)
    display_process = None
    token_path = args.data / 'device_token'
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.call_later(args.seconds, stop.set)
    try:
        provider = WorkerProvider('espn', args.data)
        deadline = time.monotonic() + 15
        while not provider.socket.exists() and worker_process.poll() is None and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if not provider.socket.exists():
            raise RuntimeError('The isolated ESPN worker did not start.')
        flask = create_backend_application(args.data / 'probe.sqlite3', [provider])
        backend = flask.extensions['sports_ticker.backend_application']
        scheduler = RefreshScheduler(flask.extensions['sports_ticker.refresh_service'],
                                     executor=ThreadPoolExecutor(max_workers=2, thread_name_prefix='probe-provider'))
        backend.scheduler = scheduler
        flask.extensions['sports_ticker.scheduler'] = scheduler
        settings = DisplaySettings(active_sports={'nba': True, 'nfl': True, 'nhl': True},
                                   timezone='America/New_York',
                                   live_delay_mode=False, score_alerts=False)
        token = secrets.token_hex(32)
        token_path.write_text(token, encoding='ascii')
        token_path.chmod(0o600)
        if backend.repository.get_ticker('latency-probe') is None:
            backend.repository.create_ticker('latency-probe', display_settings=settings, pairing=PairingState(paired=True),
                                            credential_hash=device_token_hash(token))
        else:
            backend.repository.update_ticker('latency-probe', display_settings=settings)
            backend.repository.set_device_credential_hash('latency-probe', device_token_hash(token), now=time.time())
        scheduler.register_provider('espn', 5, provider.fetch_for_ticker, refresh_changed=provider.fetch_live_for_ticker,
                                    refresh_batch=provider.fetch_batch_for_tickers)
        scheduler.register_ticker('latency-probe', lambda _: backend.repository.get_ticker('latency-probe').display_settings)
        runtime = BackendRuntime(scheduler, backend.event_service, poll_interval=0.2)
        runtime.add_change_source('espn', provider.wait_for_changes)
        flask.extensions['sports_ticker.runtime'] = runtime
        flask.extensions['sports_ticker.public_demo_data'] = PublicDemoData({})
        app = BackendASGI(flask)
        config = Config()
        config.bind = [f'127.0.0.1:{args.port}']
        config.accesslog = None
        config.loglevel = 'warning'

        async def supervise():
            nonlocal display_process
            await asyncio.sleep(2)
            display_process = subprocess.Popen([sys.executable, __file__, 'display', '--data', str(args.data),
                                                '--port', str(args.port), '--seconds', str(args.seconds)],
                                               stdout=display_log, stderr=subprocess.STDOUT)
            while not stop.is_set():
                snapshot = backend.snapshot_store.get('latency-probe')
                content = snapshot.content if snapshot is not None else ()
                live = [item for item in content if item.data.get('state') in {'in', 'half', 'crit'}]
                upcoming = [item for item in content if item.data.get('state') == 'pre']
                selected = (live or upcoming or list(content))[:1]
                record = backend.repository.get_ticker('latency-probe')
                if selected and record.display_settings.pinned_content_id != selected[0].id:
                    backend.repository.update_ticker('latency-probe', display_settings=replace(
                        record.display_settings, sports_presentation='pinned', pinned_content_id=selected[0].id))
                state = {'checked_at': datetime.now().astimezone().isoformat(), 'live_games': len(live),
                         'game_id': selected[0].id if selected else None, 'context': 'isolated live worker and memory frame sink',
                         'worker_running': worker_process.poll() is None, 'display_running': display_process.poll() is None,
                         'runtime': runtime.status(), 'provider_error': scheduler.get_health('espn').last_error}
                (args.data / 'status.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
                if not state['worker_running'] or not state['display_running']:
                    raise RuntimeError('An isolated probe process stopped.')
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass

        supervisor = asyncio.create_task(supervise())
        supervisor.add_done_callback(lambda task: stop.set())
        try:
            await serve(app, config, shutdown_trigger=stop.wait)
            if supervisor.done():
                supervisor.result()
        finally:
            stop.set()
            await supervisor
    finally:
        for process in (display_process, worker_process):
            if process is None:
                continue
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        token_path.unlink(missing_ok=True)
        worker_log.close()
        display_log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('server', 'worker', 'display'))
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18766)
    parser.add_argument('--seconds', type=float, default=120)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 86400 or not 1024 <= args.port <= 65535:
        parser.error('Use a duration from 1 to 86400 seconds and a port from 1024 to 65535.')
    args.data = args.data.resolve()
    args.data.mkdir(parents=True, exist_ok=True)
    if args.role == 'server':
        asyncio.run(server(args))
    elif args.role == 'worker':
        worker(args)
    else:
        display(args)


if __name__ == '__main__':
    main()
